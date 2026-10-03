"""The repair worker's write guard -- the authority boundary (RX-07).

This is the most security-sensitive unit in the package. RX-07 states that the
repair worker cannot modify contracts, reference outputs, approval records or
verifier code. That is only true if *every* write the worker performs passes
through one guard that cannot be talked out of a refusal, so the guard is a
small, explicit, deny-by-default decision with its rules in module-level data.

How a decision is made
----------------------
1. **Nothing is writable until a scratch directory is explicitly granted.**
   The default answer is no. A guard whose default is "yes unless matched"
   fails open the moment a new protected area is added and nobody remembers to
   list it.
2. **The path is resolved before it is judged.** ``..`` segments and symlinks
   are collapsed with :meth:`pathlib.Path.resolve`, which resolves existing
   ancestors and appends the rest, so a path that does not exist yet is still
   judged on where it would really land. Judging the *spelling* is the classic
   bypass: ``scratch/link/x`` where ``link`` points into ``packages/contracts``
   looks local and is not.
3. **Protected areas are matched two ways** -- by textual prefix on the
   repository-relative spelling, and by containment of the resolved real path.
   Either match refuses. The textual check catches a declared protected path
   before any filesystem state is consulted; the realpath check catches the
   symlink and ``..`` routes to the same place.
4. **Reference outputs are matched by directory name anywhere in the path**,
   because reference outputs are the scientific baseline and they are not
   confined to one location in a workspace.
5. **The approval ledger file is refused by identity**, not by prefix: it is a
   single file whose location is configuration.
6. Only then is the write permitted, and only if the resolved path is inside a
   granted scratch directory.

:data:`PROTECTED_PREFIXES` is a module-level tuple so a test can assert each
prefix individually -- a guard "proved" only in aggregate can lose one entry
without any test noticing -- and so that adding a protected area is a one-line
change.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final

from .errors import AuthorityRule, WriteRefused

__all__ = [
    "PROTECTED_PREFIXES",
    "REFERENCE_DIRECTORY_NAMES",
    "RepairAuthority",
]

PROTECTED_PREFIXES: Final[tuple[str, ...]] = (
    "packages/contracts/",
    "services/verifier/",
    "specs/schemas/",
    "tests/contracts/",
    "tests/governance/",
    "docs/evidence/",
)
"""Repository-relative prefixes the repair worker may never write (RX-07).

* ``packages/contracts/`` -- the scientific declaration layer and its digests.
* ``services/verifier/`` -- the independent judge (RX-09).
* ``specs/schemas/`` -- the published schemas a bundle validates against.
* ``tests/contracts/`` and ``tests/governance/`` -- the acceptance tests and
  the attribution control. A worker that can edit the tests that judge it is
  not under test.
* ``docs/evidence/`` -- the evidence record, including this build's precheck.
"""

REFERENCE_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {"references", "reference_outputs"}
)
"""Directory names that mark reference outputs, refused wherever they appear (RX-07)."""


class RepairAuthority:
    """Deny-by-default write guard for the repair worker (RX-07).

    Parameters
    ----------
    repo_root:
        Root the protected prefixes are relative to.
    scratch_dirs:
        Candidate scratch directories to grant at construction. Each goes
        through :meth:`grant_scratch`, so granting one inside a protected tree
        is refused here rather than discovered later.
    ledger_path:
        The approval ledger file, refused by identity when given.
    actor:
        Identity recorded on every refusal, so a log line says *who* was
        refused.
    protected_prefixes / reference_directory_names:
        Overridable for tests that need to prove the mechanism on a temporary
        tree. Defaults are the module-level data above.
    """

    def __init__(
        self,
        *,
        repo_root: Path | str,
        scratch_dirs: Iterable[Path | str] = (),
        ledger_path: Path | str | None = None,
        actor: str = "repair-worker",
        protected_prefixes: Iterable[str] = PROTECTED_PREFIXES,
        reference_directory_names: Iterable[str] = REFERENCE_DIRECTORY_NAMES,
    ) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._actor = actor
        self._protected_prefixes = tuple(protected_prefixes)
        self._reference_names = frozenset(reference_directory_names)
        self._ledger_path = Path(ledger_path).resolve() if ledger_path is not None else None
        self._protected_roots = tuple(
            (self._repo_root / prefix.rstrip("/")).resolve() for prefix in self._protected_prefixes
        )
        self._scratch: list[Path] = []
        for candidate in scratch_dirs:
            self.grant_scratch(candidate)

    # -- introspection ---------------------------------------------------

    @property
    def actor(self) -> str:
        """Identity this guard refuses on behalf of."""
        return self._actor

    @property
    def repo_root(self) -> Path:
        """Resolved repository root the protected prefixes hang off."""
        return self._repo_root

    @property
    def protected_prefixes(self) -> tuple[str, ...]:
        """The protected prefixes in force for this instance (RX-07)."""
        return self._protected_prefixes

    @property
    def granted_scratch_dirs(self) -> tuple[Path, ...]:
        """The resolved scratch directories currently granted."""
        return tuple(self._scratch)

    # -- granting --------------------------------------------------------

    def grant_scratch(self, path: Path | str) -> Path:
        """Grant writes inside ``path`` and return its resolved form (RX-07).

        A grant is itself checked: a scratch directory that resolves inside a
        protected tree, or whose path contains a reference-output directory
        name, is refused. Otherwise the guard could be disarmed by granting the
        very area it protects -- the simplest possible bypass.

        Raises
        ------
        WriteRefused:
            With the rule that refused the grant.
        """
        resolved = self._resolve(path)
        refusal = self._protected_rule(resolved, declared=str(path))
        if refusal is not None:
            rule, prefix = refusal
            raise WriteRefused(
                f"refusing to grant a scratch directory inside a protected area: {resolved}",
                rule=rule,
                target=str(path),
                actor=self._actor,
                resolved_target=str(resolved),
                protected_prefix=prefix,
            )
        if resolved not in self._scratch:
            self._scratch.append(resolved)
        return resolved

    # -- the decision ----------------------------------------------------

    def assert_writable(self, path: Path | str) -> Path:
        """Return the resolved path if the worker may write it; else raise (RX-07).

        Raises
        ------
        WriteRefused:
            A :class:`~retrace_contracts.exceptions.VerifierAuthorityError`
            subclass whose :attr:`~retrace_domain.errors.WriteRefused.rule`
            names the rule that refused, and whose ``resolved_target`` shows
            the path the decision was actually made on.
        """
        declared = str(path)
        if not declared.strip():
            raise WriteRefused(
                "empty path", rule=AuthorityRule.UNSAFE_PATH, target=declared, actor=self._actor
            )
        if "\x00" in declared:
            raise WriteRefused(
                "path contains a NUL byte",
                rule=AuthorityRule.UNSAFE_PATH,
                target=declared,
                actor=self._actor,
            )
        if not self._scratch:
            raise WriteRefused(
                "no scratch directory has been granted; the repair worker has no writable area",
                rule=AuthorityRule.NO_SCRATCH_GRANTED,
                target=declared,
                actor=self._actor,
            )

        resolved = self._resolve(path)

        refusal = self._protected_rule(resolved, declared=declared)
        if refusal is not None:
            rule, prefix = refusal
            raise WriteRefused(
                rule=rule,
                target=declared,
                actor=self._actor,
                resolved_target=str(resolved),
                protected_prefix=prefix,
            )

        if self._ledger_path is not None and resolved == self._ledger_path:
            raise WriteRefused(
                "the approval ledger is append-only through ApprovalLedger, never a direct write",
                rule=AuthorityRule.APPROVAL_LEDGER,
                target=declared,
                actor=self._actor,
                resolved_target=str(resolved),
            )

        if not any(self._contained_by(resolved, scratch) for scratch in self._scratch):
            raise WriteRefused(
                "writes are permitted only inside a granted candidate scratch directory",
                rule=AuthorityRule.OUTSIDE_GRANTED_SCRATCH,
                target=declared,
                actor=self._actor,
                resolved_target=str(resolved),
            )
        return resolved

    def is_writable(self, path: Path | str) -> bool:
        """Return whether :meth:`assert_writable` would permit ``path`` (RX-07)."""
        try:
            self.assert_writable(path)
        except WriteRefused:
            return False
        return True

    # -- internals -------------------------------------------------------

    def _protected_rule(
        self, resolved: Path, *, declared: str
    ) -> tuple[AuthorityRule, str | None] | None:
        """Return the protected-area rule that refuses this path, if any (RX-07).

        Both matching routes are applied. ``declared`` is tested as a textual
        repository-relative prefix; ``resolved`` is tested by containment of
        the real path. A path is refused if *either* matches, so neither a
        symlink nor a ``..`` chain nor a plain declaration gets through.
        """
        declared_relative = self._repo_relative(Path(declared))
        resolved_relative = self._repo_relative(resolved)
        for prefix, root in zip(self._protected_prefixes, self._protected_roots, strict=True):
            for relative in (declared_relative, resolved_relative):
                if relative is not None and (
                    relative == prefix.rstrip("/") or relative.startswith(prefix)
                ):
                    return AuthorityRule.PROTECTED_PREFIX, prefix
            if self._contained_by(resolved, root):
                return AuthorityRule.PROTECTED_PREFIX, prefix

        if self._reference_segments(resolved, declared_relative, Path(declared)):
            return AuthorityRule.REFERENCE_OUTPUT_DIRECTORY, None
        return None

    def _reference_segments(
        self, resolved: Path, declared_relative: str | None, declared: Path
    ) -> bool:
        """Return whether a reference-output directory name appears in the path (RX-07).

        Only the part of the path *below* the repository root or a granted
        scratch directory is examined. Scanning every absolute segment would
        mean a repository checked out beneath a directory that happens to be
        called ``references`` refused every write -- a guard that fails closed
        on everything is a guard that gets deleted. A path inside no known
        scope is judged on all of its segments, since it is about to be refused
        as ungranted anyway.
        """
        segments: set[str] = set()
        for scope in (self._repo_root, *self._scratch):
            try:
                segments |= set(resolved.relative_to(scope).parts)
            except ValueError:
                continue
        if not segments:
            segments |= set(resolved.parts)
        if declared_relative is not None:
            segments |= set(declared_relative.split("/"))
        if not declared.is_absolute():
            segments |= set(declared.parts)
        return bool(segments & self._reference_names)

    def _resolve(self, path: Path | str) -> Path:
        """Resolve ``path`` deterministically, collapsing symlinks and ``..`` (RX-07).

        A *relative* path is resolved against :attr:`repo_root`, never against
        the process working directory. That is deliberate: the protected
        prefixes are repository-relative, and a guard whose verdict depended on
        where the worker happened to be invoked from would be a guard that
        changes its mind between two identical calls.

        ``Path.resolve()`` is non-strict, so a path that does not exist yet --
        the normal case for a new candidate file -- is still judged on where it
        would really land.
        """
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self._repo_root / candidate
        return candidate.resolve()

    def _repo_relative(self, path: Path) -> str | None:
        """Return ``path`` as a repository-relative POSIX string, or ``None``.

        A relative input is interpreted as repository-relative, which is how
        the protected prefixes are written. An absolute path outside the
        repository has no repository-relative form and returns ``None``.
        """
        if not path.is_absolute():
            text = path.as_posix()
            while text.startswith("./"):
                text = text[2:]
            return text or None
        try:
            return path.relative_to(self._repo_root).as_posix()
        except ValueError:
            return None

    @staticmethod
    def _contained_by(candidate: Path, root: Path) -> bool:
        """Return whether ``candidate`` is ``root`` or lies beneath it.

        Uses :meth:`Path.relative_to` rather than string prefixing so that
        ``/a/bc`` is not mistaken for a child of ``/a/b``.
        """
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return True

"""The confined execution profile a run would use, and the half that keeps it shut.

Serves RX-08, RX-09 and RX-47, and closes the third open item of threat T2:
``DEFAULT_LIMITS.filesystem_confinement`` is ``NONE`` and no caller in the
repository requested confinement, which ``docs/security/THREAT_MODEL.md`` calls
a release blocker for any execution endpoint. This module is the caller that
requests it.

WHY A DECLARATION AND NOT A DEFAULT.

``FilesystemConfinement.KERNEL_MOUNT_NAMESPACE`` is *declared-deny*: it protects
the paths the caller names and nothing else, so the declaration is part of the
control rather than a detail of it. ``ExecutionLimits`` refuses the mode with an
empty declaration - a confinement that confines nothing - so the profile cannot
be switched on without someone writing down what is authoritative. That is
deliberate, and it is why this module exists as a reviewed enumeration with a
test asserting each expected member rather than as a flag.

WHERE EACH PATH COMES FROM, AND WHY NONE OF THEM IS A LITERAL.

An absolute path hardcoded in source is wrong in every deployment but the one it
was written on, and - worse - it is wrong *silently*: the mount would fail, or
would protect an empty directory that happens to exist. So:

* the approval ledger, the content-addressed store, the object indexes and the
  evidence area are derived from the configured storage root and the authorised
  tenant, which is the same construction
  :class:`~retrace_api.web.workspace.TenantWorkspace` uses, so the profile
  cannot protect a different directory from the one the service writes;
* the contracts and verifier package directories are resolved from the imported
  modules, so they are correct wherever the packages are installed - including
  inside a wheel's site-packages, where a repository-relative guess would not
  resolve at all;
* ``specs/schemas`` and the credential directory are deployment facts with no
  derivable location, so they come from configuration and their absence is
  reported as ``NEEDS_CONFIGURATION`` rather than guessed.

WHAT THIS MODULE DOES NOT ESTABLISH.

:class:`IdentitySeparation` measures CONFIGURATION: whether distinct restricted
database URLs are configured for the runner and the verifier, and whether a
distinct OS account is named for the runner's child. Configuration presence is
necessary and **not** sufficient - nothing here proves the account can actually
be assumed, that its credentials are genuinely restricted, or that the host
permits the switch. The threat model records that no distinct OS identity is
achievable on this host at all. So a satisfied :class:`IdentitySeparation` would
mean "the deployment claims the separation exists"; an *achievability probe*
is owed before that claim may be relied on, and
:attr:`IdentitySeparation.caveat` says so in the refusal body rather than only
in this docstring.
"""

from __future__ import annotations

import os
import pwd
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import retrace_contracts
import retrace_verifier
from retrace_api.web.config import ApiConfig
from retrace_api.web.errors import ExecutionProfileNotConfigured
from retrace_api.web.workspace import StorageNotConfigured
from retrace_runner import ExecutionLimits, FilesystemConfinement, NetworkIsolation

__all__ = [
    "PROTECTED_PATH_KINDS",
    "DeclaredPaths",
    "ExecutionProfile",
    "IdentitySeparation",
    "execution_profile",
    "identity_separation",
]

#: The authoritative artefact kinds a run must not be able to write. Enumerated
#: as a closed tuple so the test can assert the declaration covers every one of
#: them BY NAME: a declaration that silently lost a member would otherwise still
#: be a non-empty declaration and would still satisfy the policy validator.
PROTECTED_PATH_KINDS: Final[tuple[str, ...]] = (
    "approval-ledger",
    "reference-outputs",
    "object-index",
    "evidence",
    "contracts-package",
    "verifier-package",
    "schemas",
)

#: The one secret kind this build has anywhere to point at.
_SECRET_PATH_KINDS: Final[tuple[str, ...]] = ("credentials",)


def _package_directory(module: object) -> Path:
    """The installed directory of an imported package.

    Resolved from the module rather than from the repository layout, so it is
    right in a wheel as well as in a checkout.
    """
    file = getattr(module, "__file__", None)
    if not file:  # pragma: no cover - a namespace package has no __file__
        raise ExecutionProfileNotConfigured(
            f"{module!r} has no __file__, so its directory cannot be declared protected",
            remedy="install the package as a regular (non-namespace) package",
            missing=("package-directory",),
        )
    return Path(file).resolve().parent


@dataclass(frozen=True)
class DeclaredPaths:
    """The reviewed confinement declaration for one tenant's run (RX-08).

    ``protected`` and ``secret`` are what reach :class:`ExecutionLimits`.
    ``by_kind`` keeps the mapping from the artefact kind to the path chosen for
    it, so a review reads as "this is where the approval ledger is" rather than
    as an unlabelled path list.
    """

    by_kind: dict[str, str]
    secret_by_kind: dict[str, str]

    @property
    def protected(self) -> tuple[str, ...]:
        return tuple(sorted(self.by_kind.values()))

    @property
    def secret(self) -> tuple[str, ...]:
        return tuple(sorted(self.secret_by_kind.values()))

    def absent(self) -> tuple[str, ...]:
        """Declared paths that do not exist on this host yet.

        Reported, not tolerated silently: the mount namespace binds declared
        paths, so a declared path that is absent at mount time is a run that
        would be REFUSED rather than a protection that is quietly skipped. The
        approval ledger is legitimately absent until a workspace's first
        approval, which is exactly why this is a diagnostic rather than a
        construction error.
        """
        every = {**self.by_kind, **self.secret_by_kind}
        return tuple(f"{kind}={path}" for kind, path in sorted(every.items())
                     if not Path(path).exists())


@dataclass(frozen=True)
class IdentitySeparation:
    """Whether T2's identity half is configured as separated (RX-09).

    Three distinct requirements, measured separately so the refusal can say
    which one is missing instead of reporting one undifferentiated "not ready".
    """

    api_database_url: str | None
    runner_database_url: str | None
    verifier_database_url: str | None
    runner_os_user: str | None
    process_os_user: str

    #: Stated in the refusal body, not only here: see the module docstring.
    caveat: str = (
        "these are CONFIGURATION checks. A satisfied result means the deployment "
        "declares the separation; it does not prove the OS account can be assumed "
        "or that the database roles are genuinely restricted. An achievability "
        "probe is owed before the separation may be relied on."
    )

    @property
    def distinct_database_identities(self) -> bool:
        """Runner and verifier each have a URL, and the three differ (RX-09)."""
        urls = (self.api_database_url, self.runner_database_url, self.verifier_database_url)
        if not self.runner_database_url or not self.verifier_database_url:
            return False
        present = [url for url in urls if url]
        return len(set(present)) == len(present)

    @property
    def distinct_os_identity(self) -> bool:
        """A runner account is named and it is not the account this process uses."""
        if not self.runner_os_user:
            return False
        return self.runner_os_user != self.process_os_user

    @property
    def satisfied(self) -> bool:
        return self.distinct_database_identities and self.distinct_os_identity

    def unmet(self) -> tuple[str, ...]:
        """The specific reasons the identity half is still open."""
        reasons: list[str] = []
        if not self.runner_os_user:
            reasons.append(
                "no distinct OS execution identity is configured (RETRACE_RUNNER_OS_USER "
                f"is unset, so a confined child would run as {self.process_os_user!r}, the "
                "same account as this process)"
            )
        elif self.runner_os_user == self.process_os_user:
            reasons.append(
                f"RETRACE_RUNNER_OS_USER is {self.runner_os_user!r}, which is the account "
                "this process already runs as; that is not a separation"
            )
        if not self.runner_database_url:
            reasons.append(
                "the runner holds no distinct restricted database credential "
                "(RETRACE_RUNNER_DATABASE_URL is unset)"
            )
        if not self.verifier_database_url:
            reasons.append(
                "the verifier holds no distinct restricted database credential "
                "(RETRACE_VERIFIER_DATABASE_URL is unset)"
            )
        if (
            self.runner_database_url
            and self.verifier_database_url
            and not self.distinct_database_identities
        ):
            reasons.append(
                "the configured database identities are not all distinct; the runner and "
                "the verifier must not share a credential with each other or with the API"
            )
        return tuple(reasons)


def identity_separation(config: ApiConfig) -> IdentitySeparation:
    """Measure T2's identity half from configuration and the current account."""
    return IdentitySeparation(
        api_database_url=config.database_url,
        runner_database_url=config.runner_database_url,
        verifier_database_url=config.verifier_database_url,
        runner_os_user=config.runner_os_user,
        process_os_user=_process_os_user(),
    )


def _process_os_user() -> str:
    """The account this process runs as, by effective uid.

    Read from the password database rather than from ``$USER``: an environment
    variable is request-adjacent configuration and would let a deployment appear
    to have a separation it does not have.
    """
    uid = os.geteuid()
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:  # pragma: no cover - a uid with no passwd entry
        return f"uid:{uid}"


@dataclass(frozen=True)
class ExecutionProfile:
    """The limits a run would execute under, plus the declaration behind them."""

    limits: ExecutionLimits
    declaration: DeclaredPaths
    separation: IdentitySeparation

    @property
    def confinement_and_identity_met(self) -> bool:
        """Whether both halves of T2 are satisfied for this profile.

        NOT a permission to execute, and deliberately not named as one. Even
        when this is true the run endpoint still refuses, because no route in
        this service invokes the runner - see
        :data:`retrace_api.web.execution.EXECUTION_NOT_IMPLEMENTED`. A property
        a handler could branch on to produce a success would be a gate that
        opens onto nothing, and the response would describe work that nothing
        performed.
        """
        return (
            self.limits.filesystem_confinement is FilesystemConfinement.KERNEL_MOUNT_NAMESPACE
            and self.separation.satisfied
        )

    def summary(self) -> dict[str, object]:
        """What the refusal reports about the profile it would have used."""
        return {
            "confinement_and_identity_met": self.confinement_and_identity_met,
            "filesystem_confinement": self.limits.filesystem_confinement.value,
            "network": self.limits.network.value,
            "write_confinement": self.limits.write_confinement.value,
            "policy_digest": self.limits.policy_digest,
            "protected_paths": list(self.limits.protected_paths),
            "secret_paths": list(self.limits.secret_paths),
            "protected_kinds": sorted(self.declaration.by_kind),
            "declared_paths_absent_on_this_host": list(self.declaration.absent()),
        }


def declared_paths(config: ApiConfig, *, tenant_id: str) -> DeclaredPaths:
    """Build the reviewed declaration for ``tenant_id`` (RX-08).

    Raises :class:`~retrace_api.web.errors.ExecutionProfileNotConfigured` naming
    every setting that is absent. It raises rather than omitting the path,
    because an omitted member of :data:`PROTECTED_PATH_KINDS` would leave an
    authoritative artefact writable inside a profile that still looked confined.
    """
    storage_root = config.storage_root
    schema_root = config.schema_root
    secret_root = config.secret_root
    if storage_root is None:
        raise StorageNotConfigured
    missing = tuple(
        name
        for name, value in (
            ("RETRACE_SCHEMA_ROOT", schema_root),
            ("RETRACE_SECRET_ROOT", secret_root),
        )
        if value is None
    )
    if missing or schema_root is None or secret_root is None:
        raise ExecutionProfileNotConfigured(
            "the confinement declaration a run requires is incomplete, so no execution "
            "profile can be assembled; the missing paths are deployment facts and are "
            "not guessed",
            remedy="configure the named settings, then review the resulting declaration",
            missing=missing,
        )
    tenant_root = (storage_root / tenant_id).resolve()
    by_kind = {
        # The same construction TenantWorkspace uses, so the profile protects the
        # directory the service actually writes rather than a similar one.
        "approval-ledger": str(tenant_root / "approvals.jsonl"),
        "reference-outputs": str(tenant_root / "objects"),
        "object-index": str(tenant_root / "index"),
        "evidence": str(tenant_root / "evidence"),
        "contracts-package": str(_package_directory(retrace_contracts)),
        "verifier-package": str(_package_directory(retrace_verifier)),
        "schemas": str(schema_root.resolve()),
    }
    secret_by_kind = {"credentials": str(secret_root.resolve())}
    unknown = (set(by_kind) ^ set(PROTECTED_PATH_KINDS)) | (
        set(secret_by_kind) ^ set(_SECRET_PATH_KINDS)
    )
    if unknown:  # pragma: no cover - a guard against editing one list only
        raise ExecutionProfileNotConfigured(
            f"the declaration and the declared kinds disagree about {sorted(unknown)}",
            remedy="update both together; the enumeration is what the test asserts against",
            missing=tuple(sorted(unknown)),
        )
    return DeclaredPaths(by_kind=by_kind, secret_by_kind=secret_by_kind)


def execution_profile(config: ApiConfig, *, tenant_id: str) -> ExecutionProfile:
    """The confined profile a run for ``tenant_id`` would execute under (RX-08).

    Requests ``KERNEL_MOUNT_NAMESPACE`` and ``KERNEL_NAMESPACE`` egress denial.
    Neither is downgraded if unavailable: ``run_notebook`` refuses the run, which
    is why asking for them here is a decision about what a result would be worth
    rather than a performance hint.
    """
    declaration = declared_paths(config, tenant_id=tenant_id)
    limits = ExecutionLimits(
        network=NetworkIsolation.KERNEL_NAMESPACE,
        filesystem_confinement=FilesystemConfinement.KERNEL_MOUNT_NAMESPACE,
        protected_paths=declaration.protected,
        secret_paths=declaration.secret,
    )
    return ExecutionProfile(
        limits=limits,
        declaration=declaration,
        separation=identity_separation(config),
    )

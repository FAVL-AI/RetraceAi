"""Immutable snapshots of an imported source tree (RX-01, RX-02).

A snapshot is the scientific baseline: everything downstream -- the diagnosis,
the proposal, the run, the verification -- is stated *against a named
snapshot*, so the snapshot has to be reproducible and tamper-evident before any
of that means anything.

Two properties are load-bearing:

**The digest is a function of content alone.** ``manifest_digest`` is taken over
the sorted ``(relative path, sha256)`` pairs, so snapshotting the same tree
twice gives the same digest regardless of walk order, inode order, timestamps
or permissions, and changing one byte of one file changes it.

**The source tree is untrusted.** An imported tree may come from an upload, an
archive or a repository clone, so every path is validated before it is admitted
(RX-42's posture applied to the filesystem): absolute paths, traversal
segments, non-regular files, broken symlinks, directory symlinks and symlinks
whose real path escapes the root are each refused by a *named* rule rather than
skipped. Skipping would produce a manifest that claims completeness it does not
have.

The same validation runs again on materialise, because a manifest that arrives
with an imported evidence bundle is untrusted input too.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from types import MappingProxyType
from typing import Final

from retrace_contracts import canonical_digest, validate_relative_path

from .errors import PathRefusalRule, UnsafeSourcePath
from .store import ContentAddressedStore, is_sha256_hex

__all__ = [
    "MANIFEST_TYPE_TAG",
    "SnapshotManifest",
    "SnapshotReader",
    "snapshot_create",
    "snapshot_materialise",
    "store_reader",
]

MANIFEST_TYPE_TAG: Final[str] = "retrace.SnapshotManifest"
"""Domain-separation tag for the manifest digest (RX-01)."""

MATERIALISED_FILE_MODE: Final[int] = 0o644
"""Mode for a materialised working copy.

Deliberately writable: the snapshot is immutable in the *store*, and a working
copy a researcher cannot edit is not a working copy. Immutability is a property
of the preserved bytes, not of every derived file.
"""

SnapshotReader = Callable[[str], bytes]
"""Reads one snapshot-relative path and returns verified bytes (RX-02).

A reader never exposes the store's filesystem layout, so a consumer -- notably
a repair provider -- can only address content the manifest actually declares.
"""


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """The content map of one snapshot: sorted ``(path, sha256)`` pairs (RX-01).

    Entries are held as a sorted tuple rather than a dict so that the record is
    hashable, ordered canonically and cheap to compare. ``__post_init__``
    re-validates every path and digest and re-checks the ordering, which means
    a manifest deserialised from an untrusted bundle cannot carry a traversal
    path or a malformed digest into the materialise step.
    """

    entries: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        seen: set[str] = set()
        previous: str | None = None
        for path, digest in self.entries:
            try:
                validated = validate_relative_path(path, field="SnapshotManifest.path")
            except ValueError as error:
                # A manifest can arrive with an imported evidence bundle, so it is
                # untrusted input. Traversal is named separately from the other
                # malformed-path cases because it is the one an attacker chooses.
                if path.startswith("/"):
                    rule = PathRefusalRule.ABSOLUTE_PATH
                elif ".." in path.split("/"):
                    rule = PathRefusalRule.TRAVERSAL
                else:
                    rule = PathRefusalRule.UNSAFE_RELATIVE_PATH
                raise UnsafeSourcePath(str(error), rule=rule, path=path) from error
            if validated != path:
                raise UnsafeSourcePath(
                    "manifest path is not in normalised form",
                    rule=PathRefusalRule.UNSAFE_RELATIVE_PATH,
                    path=path,
                )
            if not is_sha256_hex(digest):
                raise ValueError(f"manifest digest for {path!r} is not a lowercase hex SHA-256")
            if path in seen:
                raise ValueError(f"manifest lists {path!r} more than once")
            if previous is not None and path <= previous:
                raise ValueError(
                    "manifest entries must be sorted by path so that the digest is "
                    f"a function of content alone; {path!r} follows {previous!r}"
                )
            seen.add(path)
            previous = path

    @classmethod
    def from_mapping(cls, files: Mapping[str, str]) -> SnapshotManifest:
        """Build a manifest from a ``{relative path -> sha256}`` mapping (RX-01)."""
        return cls(entries=tuple(sorted(files.items())))

    @property
    def files(self) -> Mapping[str, str]:
        """Read-only ``{relative path -> sha256}`` view of this manifest."""
        return MappingProxyType(dict(self.entries))

    @property
    def manifest_digest(self) -> str:
        """SHA-256 over the sorted ``(path, digest)`` pairs (RX-01).

        Computed through the contracts layer's canonical form so that a
        manifest digest and a contract digest are produced by one specified
        serialisation rather than two similar ones.
        """
        return canonical_digest(
            {"entries": [list(entry) for entry in self.entries]},
            type_tag=MANIFEST_TYPE_TAG,
        )

    @property
    def paths(self) -> tuple[str, ...]:
        """The snapshot-relative paths, sorted."""
        return tuple(path for path, _ in self.entries)

    def digest_for(self, path: str) -> str:
        """Return the stored digest of ``path``.

        Raises
        ------
        KeyError:
            If the manifest does not declare ``path``.
        """
        for candidate, digest in self.entries:
            if candidate == path:
                return digest
        raise KeyError(f"snapshot does not contain {path!r}")

    def paths_with_basename(self, basename: str) -> tuple[str, ...]:
        """Return every declared path whose final segment equals ``basename``.

        Used by the deterministic repair provider to decide whether a wrong
        relative path has exactly one plausible target in the snapshot (RX-06).
        """
        return tuple(path for path in self.paths if path.rsplit("/", 1)[-1] == basename)

    def to_json_dict(self) -> dict[str, object]:
        """Return a JSON-ready mapping of this manifest plus its digest."""
        return {
            "manifest_digest": self.manifest_digest,
            "files": dict(self.entries),
        }

    def __contains__(self, path: object) -> bool:
        return isinstance(path, str) and path in set(self.paths)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self) -> Iterator[tuple[str, str]]:
        return iter(self.entries)


def _is_excluded(relative_path: str, exclude: Iterable[str]) -> bool:
    """Return whether ``relative_path`` matches any exclusion pattern.

    A pattern matches when it equals or :func:`fnmatch.fnmatch`-matches either
    the whole relative path or any single path segment. The rule is documented
    here because an exclusion that behaves differently from the reviewer's
    expectation silently changes what a snapshot contains.
    """
    parts = relative_path.split("/")
    for pattern in exclude:
        if fnmatch(relative_path, pattern):
            return True
        if any(fnmatch(part, pattern) for part in parts):
            return True
    return False


def _refuse(rule: PathRefusalRule, path: Path, root: Path) -> UnsafeSourcePath:
    return UnsafeSourcePath(rule=rule, path=str(path), root=str(root))


def _admit_file(candidate: Path, root: Path) -> None:
    """Refuse ``candidate`` unless it is a regular file contained by ``root`` (RX-01).

    Resolution happens *before* the decision: ``..`` segments and symlinks are
    collapsed first, so containment is judged on the real path rather than on
    the spelling.
    """
    if candidate.is_symlink():
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise _refuse(PathRefusalRule.SYMLINK_BROKEN, candidate, root) from error
        if resolved.is_dir():
            raise _refuse(PathRefusalRule.SYMLINK_DIRECTORY, candidate, root)
        if not _contained_by(resolved, root):
            raise _refuse(PathRefusalRule.SYMLINK_ESCAPE, candidate, root)
        if not resolved.is_file():
            raise _refuse(PathRefusalRule.NON_REGULAR_FILE, candidate, root)
        return
    if not candidate.is_file():
        raise _refuse(PathRefusalRule.NON_REGULAR_FILE, candidate, root)


def _contained_by(candidate: Path, root: Path) -> bool:
    """Return whether ``candidate`` is ``root`` or lies beneath it.

    Both arguments must already be resolved. Uses :meth:`Path.relative_to`
    rather than string prefixing so that ``/a/bc`` is not treated as living
    inside ``/a/b``.
    """
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def snapshot_create(
    store: ContentAddressedStore,
    source_dir: Path | str,
    *,
    exclude: Iterable[str] = (),
) -> SnapshotManifest:
    """Store every file under ``source_dir`` and return its manifest (RX-01).

    Parameters
    ----------
    store:
        The content-addressed store that receives the bytes.
    source_dir:
        Root of the tree to snapshot. Treated as untrusted input.
    exclude:
        Patterns matched by :func:`_is_excluded`. Excluded directories are
        pruned, so their contents are never read or stored.

    Returns
    -------
    SnapshotManifest:
        Sorted ``(path, sha256)`` pairs with a ``manifest_digest`` that is a
        function of content alone.

    Raises
    ------
    UnsafeSourcePath:
        For an unsafe relative path, a non-regular file, a broken symlink, a
        directory symlink, or a symlink whose real path escapes the root. Each
        refusal names its :class:`~retrace_domain.errors.PathRefusalRule`.
    NotADirectoryError:
        If ``source_dir`` is not a directory.
    """
    root = Path(source_dir).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"snapshot source must be a directory: {root}")
    patterns = tuple(exclude)
    files: dict[str, str] = {}

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        kept: list[str] = []
        for name in sorted(dirnames):
            child = here / name
            relative = child.relative_to(root).as_posix()
            if _is_excluded(relative, patterns):
                continue
            if child.is_symlink():
                raise _refuse(PathRefusalRule.SYMLINK_DIRECTORY, child, root)
            kept.append(name)
        dirnames[:] = kept

        for name in sorted(filenames):
            child = here / name
            relative = child.relative_to(root).as_posix()
            if _is_excluded(relative, patterns):
                continue
            try:
                validated = validate_relative_path(relative, field="snapshot path")
            except ValueError as error:
                raise _refuse(PathRefusalRule.UNSAFE_RELATIVE_PATH, child, root) from error
            _admit_file(child, root)
            files[validated] = store.put_file(child)

    return SnapshotManifest.from_mapping(files)


def snapshot_materialise(
    store: ContentAddressedStore,
    manifest: SnapshotManifest,
    dest: Path | str,
) -> tuple[Path, ...]:
    """Write ``manifest`` back to ``dest``, verifying each blob as it goes (RX-01, RX-02).

    Every read goes through :meth:`ContentAddressedStore.get_bytes`, which
    re-hashes, so materialising a snapshot whose store has been tampered with
    raises :class:`~retrace_contracts.exceptions.SnapshotIntegrityError` at the
    first corrupt file instead of writing out silently wrong science.

    Not atomic, and deliberately not pretending to be: files are written in
    manifest order, so a refusal or an integrity failure part-way through
    leaves the files already written in place. The caller is told by the
    exception and should discard the destination rather than treat a partial
    tree as a snapshot. Making this transactional needs a staging directory and
    a rename, which is a change to make deliberately, not silently.

    Returns
    -------
    tuple of Path:
        The files written, in manifest order.

    Raises
    ------
    UnsafeSourcePath:
        If a manifest entry would write outside ``dest`` after resolution, or
        if the destination file already exists (an existing file is never
        clobbered -- the caller is told instead).
    SnapshotIntegrityError:
        If any stored blob no longer matches its recorded digest (RX-02).
    KeyError:
        If the store does not hold a digest the manifest names.
    """
    destination = Path(dest).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for path, digest in manifest.entries:
        target = destination / path
        resolved_parent = _resolve_lenient(target.parent)
        if not _contained_by(resolved_parent, destination):
            raise UnsafeSourcePath(
                rule=PathRefusalRule.DESTINATION_ESCAPE,
                path=path,
                root=str(destination),
            )
        if target.exists() or target.is_symlink():
            raise UnsafeSourcePath(
                rule=PathRefusalRule.DESTINATION_OCCUPIED,
                path=path,
                root=str(destination),
            )
        payload = store.get_bytes(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        os.chmod(target, MATERIALISED_FILE_MODE)
        written.append(target)

    return tuple(written)


def _resolve_lenient(path: Path) -> Path:
    """Resolve symlinks and ``..`` without requiring the path to exist.

    ``Path.resolve()`` is non-strict by default on Python 3.6+, so existing
    ancestors are resolved and the remainder is appended. This is the form the
    authority and destination checks need, because they decide about paths that
    are *about* to be created.
    """
    return Path(path).resolve()


def store_reader(store: ContentAddressedStore, manifest: SnapshotManifest) -> SnapshotReader:
    """Return a :data:`SnapshotReader` over ``manifest`` backed by ``store`` (RX-02).

    The returned callable validates the requested path, looks its digest up in
    the manifest and returns verified bytes. It raises ``KeyError`` for a path
    the manifest does not declare, so a consumer cannot read content the
    snapshot does not contain.
    """

    def read(relative_path: str) -> bytes:
        validate_relative_path(relative_path, field="snapshot read path")
        return store.get_bytes(manifest.digest_for(relative_path))

    return read

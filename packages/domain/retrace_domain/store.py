"""Content-addressed immutable blob store (RX-01, RX-02).

The store is the preservation primitive the rest of RETRACE stands on. Its
whole job is that *the bytes you read back are the bytes that were stored*, and
that the claim is checkable rather than asserted.

Design decisions and the reason for each
----------------------------------------
**Identity is the content digest, never the path.** A blob lives at a sharded
path derived from its SHA-256, so two independent imports of identical bytes
converge on one object and a path cannot carry meaning the content does not.

**Reads re-hash.** :meth:`ContentAddressedStore.get_bytes` recomputes the
digest of the stored bytes on every read and raises
:class:`~retrace_contracts.exceptions.SnapshotIntegrityError` on a mismatch
(RX-02). Nothing in the read path consults ``mtime``, size or filename, so a
tamper that preserves metadata is still detected and a metadata change that
preserves content is still a successful read.

**Writes are atomic and then read-only.** Bytes are written to a temporary file
in the store, flushed, ``fsync``-ed, chmod-ed to ``0o444`` and moved into place
with :func:`os.replace`. A reader therefore never observes a partially written
blob, and ordinary tooling cannot edit one in place by accident.

**An existing digest is never overwritten with different bytes.** Re-putting
identical bytes is a no-op that returns the same digest. If the bytes already
stored under a digest do *not* match the incoming bytes, the store is already
corrupt: the put raises rather than "repairing" it, because silently rewriting
a blob would destroy the only evidence that corruption occurred.

Known limits (honest, and not defended here)
--------------------------------------------
* The store protects against corruption and accident, not against an attacker
  with write access to its directory who recomputes everything consistently.
  Detecting that requires an external anchor for the digests -- the approval
  ledger and evidence bundle are where that anchoring belongs.
* ``0o444`` is advisory: the owning user can always ``chmod`` it back. The
  tamper-evidence property comes from re-hashing on read, not from the mode
  bits.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from retrace_contracts import SnapshotIntegrityError, sha256_hex

__all__ = ["BLOB_MODE", "ContentAddressedStore", "hash_file", "is_sha256_hex"]

BLOB_MODE: Final[int] = 0o444
"""Mode applied to a stored blob: read-only for everyone (RX-01)."""

_BLOBS_DIRNAME: Final[str] = "blobs"
_TMP_DIRNAME: Final[str] = "incoming"
_CHUNK_BYTES: Final[int] = 1 << 20
_DIGEST_LENGTH: Final[int] = 64
_HEX_DIGITS: Final[frozenset[str]] = frozenset("0123456789abcdef")


def is_sha256_hex(value: str) -> bool:
    """Return whether ``value`` is a lowercase 64-character hex SHA-256 digest.

    Used to refuse a crafted digest before it is turned into a filesystem path
    (RX-01): a digest is the only thing that selects a blob, so it is validated
    as data rather than trusted as a filename.
    """
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(character in _HEX_DIGITS for character in value)
    )


def hash_file(path: Path) -> tuple[str, int]:
    """Return ``(sha256_hex, byte_count)`` for ``path``, read in chunks (RX-01).

    Streams the file so that a large input is never fully resident in memory,
    and returns the byte count alongside the digest so a caller can record size
    without a second ``stat`` that might see a different file.
    """
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


class ContentAddressedStore:
    """An immutable, tamper-evident local blob store (RX-01, RX-02).

    Parameters
    ----------
    root:
        Directory the store owns. Created if absent. Two subdirectories are
        used: ``blobs/`` for sharded content and ``incoming/`` for the
        temporary files of in-flight writes.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).resolve()
        self._blobs = self._root / _BLOBS_DIRNAME
        self._tmp = self._root / _TMP_DIRNAME
        self._blobs.mkdir(parents=True, exist_ok=True)
        self._tmp.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """The resolved directory this store owns."""
        return self._root

    @property
    def blobs_root(self) -> Path:
        """The directory holding sharded blob content."""
        return self._blobs

    # -- addressing ------------------------------------------------------

    def path_for(self, digest: str) -> Path:
        """Return the sharded path a blob with ``digest`` occupies (RX-01).

        Two levels of two hex characters keep any one directory small without
        making the layout depend on anything but the digest itself.

        Raises
        ------
        ValueError:
            If ``digest`` is not a lowercase hex SHA-256. A digest is untrusted
            input until checked, because it is interpolated into a path.
        """
        self._require_digest(digest)
        return self._blobs / digest[0:2] / digest[2:4] / digest

    def has(self, digest: str) -> bool:
        """Return whether a blob file exists for ``digest`` (no verification)."""
        return self.path_for(digest).is_file()

    def digests(self) -> Iterator[str]:
        """Yield every digest the store holds, in sorted order (RX-02).

        Sorted so that :meth:`verify_all` reports the *same* first failure on
        every run; an integrity sweep whose order varies is hard to reason about.
        """
        if not self._blobs.is_dir():  # pragma: no cover - mkdir in __init__
            return
        for path in sorted(self._blobs.rglob("*")):
            if path.is_file() and is_sha256_hex(path.name):
                yield path.name

    # -- writing ---------------------------------------------------------

    def put_bytes(self, data: bytes) -> str:
        """Store ``data`` and return its SHA-256 digest (RX-01).

        Re-putting identical bytes is a no-op and returns the same digest.

        Raises
        ------
        SnapshotIntegrityError:
            If a blob already exists for the computed digest but its stored
            bytes differ from ``data``. The store is corrupt at that point and
            refuses to overwrite the evidence.
        TypeError:
            If ``data`` is not ``bytes``/``bytearray``. Accepting ``str`` would
            make the digest depend on an implicit encoding.
        """
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("put_bytes requires bytes; encode text explicitly before storing")
        payload = bytes(data)
        digest = sha256_hex(payload)
        target = self.path_for(digest)
        if target.is_file():
            self._require_stored_matches_digest(target, digest)
            return digest
        self._write_atomic(target, payload)
        return digest

    def put_file(self, path: Path | str) -> str:
        """Store the contents of ``path`` and return its SHA-256 digest (RX-01).

        The file is hashed in chunks, then copied in chunks, so a large input is
        never fully resident in memory. The refusal rules match
        :meth:`put_bytes`.

        Raises
        ------
        SnapshotIntegrityError:
            If the digest already exists with different stored bytes.
        FileNotFoundError / IsADirectoryError:
            Propagated from the filesystem; a missing input is not silently
            treated as empty content.
        """
        source = Path(path)
        if source.is_dir():
            raise IsADirectoryError(f"put_file requires a file, not a directory: {source}")
        digest, _ = hash_file(source)
        target = self.path_for(digest)
        if target.is_file():
            self._require_stored_matches_digest(target, digest)
            return digest
        self._copy_atomic(source, target)
        return digest

    # -- reading and verification ----------------------------------------

    def get_bytes(self, digest: str) -> bytes:
        """Return the bytes stored under ``digest``, re-hashing them first (RX-02).

        There is deliberately no ``verify=False`` variant. A read path that can
        skip verification is a read path that will skip verification, and the
        only property this store offers is that it does not.

        Raises
        ------
        KeyError:
            If no blob exists for ``digest``.
        SnapshotIntegrityError:
            If the stored bytes do not hash to ``digest`` (RX-02).
        """
        target = self.path_for(digest)
        if not target.is_file():
            raise KeyError(f"no blob stored for digest {digest}")
        payload = target.read_bytes()
        observed = sha256_hex(payload)
        if observed != digest:
            raise SnapshotIntegrityError(
                path=str(target), expected_sha256=digest, observed_sha256=observed
            )
        return payload

    def verify(self, digest: str) -> str:
        """Re-read and re-hash one blob, returning ``digest`` on success (RX-02).

        Raises
        ------
        KeyError:
            If no blob exists for ``digest``.
        SnapshotIntegrityError:
            If the stored bytes no longer hash to ``digest``.
        """
        target = self.path_for(digest)
        if not target.is_file():
            raise KeyError(f"no blob stored for digest {digest}")
        observed, _ = hash_file(target)
        if observed != digest:
            raise SnapshotIntegrityError(
                path=str(target), expected_sha256=digest, observed_sha256=observed
            )
        return digest

    def verify_all(self) -> tuple[str, ...]:
        """Verify every blob in the store and return the digests checked (RX-02).

        Raises on the first mismatch rather than collecting failures: a store
        with one corrupt blob is a store whose contents are in question, and
        continuing would invite a caller to treat the remaining passes as
        reassurance.
        """
        checked: list[str] = []
        for digest in self.digests():
            self.verify(digest)
            checked.append(digest)
        return tuple(checked)

    # -- internals -------------------------------------------------------

    @staticmethod
    def _require_digest(digest: str) -> None:
        if not is_sha256_hex(digest):
            raise ValueError(
                "digest must be a lowercase hex SHA-256 (64 chars); "
                f"refusing to build a path from {digest!r}"
            )

    @staticmethod
    def _require_stored_matches_digest(target: Path, digest: str) -> None:
        """Refuse a put whose digest is already stored with non-matching bytes (RX-02).

        The incoming payload hashed to ``digest``, so comparing the *stored*
        bytes' digest to ``digest`` is exactly the "same digest, different
        bytes" test, and it streams instead of holding two copies in memory.
        """
        stored_digest, _ = hash_file(target)
        if stored_digest != digest:
            raise SnapshotIntegrityError(
                "refusing to overwrite an existing blob with different bytes: "
                f"digest {digest} is already stored and its content does not match. "
                "The store is corrupt; investigate before overwriting the evidence.",
                path=str(target),
                expected_sha256=digest,
                observed_sha256=stored_digest,
            )

    def _write_atomic(self, target: Path, payload: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=self._tmp, delete=False)
        temporary = Path(handle.name)
        try:
            with handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, BLOB_MODE)
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def _copy_atomic(self, source: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=self._tmp, delete=False)
        temporary = Path(handle.name)
        try:
            with handle, source.open("rb") as reader:
                while True:
                    chunk = reader.read(_CHUNK_BYTES)
                    if not chunk:
                        break
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, BLOB_MODE)
            os.replace(temporary, target)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

"""The verifier's read-only reference interface, and the domain seam (RX-07, RX-09).

RX-09 requires the verifier to run with a separate identity and **read-only**
access to reference outputs. That is expressed here as a type, not as a
convention: :class:`ReadOnlyReferenceReader` declares the write-shaped methods a
caller might reach for and makes every one of them raise
:class:`~retrace_contracts.VerifierAuthorityError`. A write attempted through a
reference reader therefore fails with a *named authority refusal* rather than an
``AttributeError``, which would read as "this object just does not do that" when
the truth is "this actor is not permitted to do that".

``packages/domain`` owns the real reference store. This service does not import
it. :class:`ReferenceReader` is the narrow protocol the integrator wires the
real store into; :class:`FilesystemReferenceReader` is a working implementation
used by this package's tests and by a local evidence bundle re-run (RX-16).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from retrace_contracts import VerifierAuthorityError, validate_relative_path

from .errors import ReferenceUnavailable

__all__ = [
    "VERIFIER_IDENTITY_NOTE",
    "FilesystemReferenceReader",
    "ReadOnlyReferenceReader",
    "ReferenceReader",
]

VERIFIER_IDENTITY_NOTE: str = (
    "RX-09 requires the verifier's identity to differ from the runner's. This "
    "package enforces the read-only half of that in code: every write-shaped "
    "method on a reference reader raises VerifierAuthorityError. It cannot "
    "enforce the identity half, which is a deployment property -- the two "
    "services must be granted different credentials by the platform, and this "
    "library has no way to verify that it was."
)


@runtime_checkable
class ReferenceReader(Protocol):
    """Read-only access to the reference evidence a contract pins (RX-09).

    Deliberately three methods. Anything wider would let the verifier do more
    than read, and anything narrower would force it to compute digests from
    bytes it had to hold in memory.
    """

    def exists(self, path: str) -> bool:
        """Return whether reference ``path`` is present."""
        raise NotImplementedError

    def read_bytes(self, path: str) -> bytes:
        """Return the exact bytes at reference ``path``.

        Raises :class:`~retrace_verifier.errors.ReferenceUnavailable` when the
        reference is absent or unreadable -- never returns empty bytes for a
        missing file, because an empty reference and an absent reference are
        different evidence states.
        """
        raise NotImplementedError

    def digest(self, path: str) -> str:
        """Return the lowercase hex SHA-256 of the bytes at reference ``path``."""
        raise NotImplementedError


class ReadOnlyReferenceReader:
    """Base class that refuses every write by name (RX-07, RX-09).

    Subclasses implement :meth:`exists`, :meth:`read_bytes` and :meth:`digest`.
    The write-shaped methods below exist *so that they can refuse*: a caller
    that reaches for one gets a :class:`~retrace_contracts.VerifierAuthorityError`
    naming the actor, the action and the target.

    ``open`` is included because it is the most likely accidental write path:
    ``reader.open(path, "w")`` looks harmless and is exactly the authority
    breach RX-09 forbids.
    """

    actor: str = "verifier"

    def _refuse(self, action: str, target: str) -> None:
        """Raise the named authority refusal for ``action`` on ``target`` (RX-09)."""
        raise VerifierAuthorityError(
            actor=self.actor,
            action=action,
            target=target,
        )

    def open(self, path: str, mode: str = "rb") -> Any:
        """Open a reference for reading only; any write mode is refused (RX-09)."""
        if any(character in mode for character in "wax+"):
            self._refuse(f"open(mode={mode!r})", path)
        return self._open_for_read(path)

    def _open_for_read(self, path: str) -> Any:
        """Return a readable binary handle for ``path``. Implemented by subclasses."""
        raise NotImplementedError

    def write_bytes(self, path: str, data: bytes) -> None:
        """Refused (RX-09)."""
        self._refuse("write_bytes", path)

    def write_text(self, path: str, text: str) -> None:
        """Refused (RX-09)."""
        self._refuse("write_text", path)

    def delete(self, path: str) -> None:
        """Refused (RX-09)."""
        self._refuse("delete", path)

    def replace(self, path: str, data: bytes) -> None:
        """Refused (RX-09)."""
        self._refuse("replace", path)

    def mkdir(self, path: str) -> None:
        """Refused (RX-09)."""
        self._refuse("mkdir", path)

    def __setitem__(self, path: str, data: bytes) -> None:
        """Refused (RX-09)."""
        self._refuse("__setitem__", path)


class FilesystemReferenceReader(ReadOnlyReferenceReader):
    """A reference reader confined to one directory (RX-09, RX-42).

    Path admission, applied before any filesystem call:

    * the path must pass
      :func:`retrace_contracts.validate_relative_path` -- no absolute paths, no
      ``..`` segments, no backslashes, no control characters;
    * the resolved path must still lie inside ``root`` after symlinks are
      followed, so a symlink inside the reference store cannot be used to read
      outside it.

    An absent or unreadable reference raises
    :class:`~retrace_verifier.errors.ReferenceUnavailable`.
    """

    def __init__(self, root: Path | str, *, actor: str = "verifier") -> None:
        self.root = Path(root).resolve()
        self.actor = actor

    def _resolve(self, path: str) -> Path:
        """Admit ``path`` and return the resolved absolute location (RX-42)."""
        try:
            relative = validate_relative_path(path, field="reference path")
        except ValueError as error:
            raise ReferenceUnavailable(
                path=path, reason=f"path refused: {error}"
            ) from error
        candidate = (self.root / relative).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ReferenceUnavailable(
                path=path,
                reason=f"resolved path escapes the reference root {self.root}",
            )
        return candidate

    def exists(self, path: str) -> bool:
        """Return whether the admitted reference exists and is a regular file."""
        try:
            return self._resolve(path).is_file()
        except ReferenceUnavailable:
            return False

    def read_bytes(self, path: str) -> bytes:
        """Return the reference bytes, or raise ``ReferenceUnavailable`` (RX-17)."""
        location = self._resolve(path)
        try:
            return location.read_bytes()
        except OSError as error:
            raise ReferenceUnavailable(path=path, reason=repr(error)) from error

    def digest(self, path: str) -> str:
        """Return the SHA-256 of the reference bytes (RX-01)."""
        return hashlib.sha256(self.read_bytes(path)).hexdigest()

    def _open_for_read(self, path: str) -> Any:
        """Return a read-only binary handle to the admitted reference."""
        location = self._resolve(path)
        try:
            return location.open("rb")
        except OSError as error:
            raise ReferenceUnavailable(path=path, reason=repr(error)) from error

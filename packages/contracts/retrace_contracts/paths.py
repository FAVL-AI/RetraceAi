"""Path safety for declared, snapshot-relative paths (RX-06, RX-42).

Every path that appears in a contract, proposal or bundle manifest is relative
to a content-addressed snapshot root. A path that can escape that root turns a
reviewable patch into an arbitrary filesystem write, so the escape forms are
refused at parse time rather than checked at apply time.

"""

from __future__ import annotations

import re
from typing import Final

__all__ = ["MAX_PATH_LENGTH", "is_safe_relative_path", "validate_relative_path"]

MAX_PATH_LENGTH: Final[int] = 1024

_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def validate_relative_path(value: str, *, field: str = "path") -> str:
    """Return ``value`` if it is a safe snapshot-relative POSIX path (RX-06).

    Refused, each with a named reason:

    * empty or whitespace-only
    * longer than :data:`MAX_PATH_LENGTH`
    * containing a control character or NUL byte
    * absolute (``/etc/passwd``) or a Windows drive path (``C:\\x``)
    * containing a backslash (ambiguous separator)
    * containing an empty, ``.`` or ``..`` segment (traversal)
    * a trailing separator (a directory, not a file)

    Raises
    ------
    ValueError:
        With a message naming ``field`` and the specific rule broken. Pydantic
        turns this into a ``ValidationError`` at model construction.
    """
    if not isinstance(value, str):  # pragma: no cover - pydantic enforces the type
        raise ValueError(f"{field} must be a string")
    candidate = value.strip()
    if not candidate:
        raise ValueError(f"{field} must not be empty or whitespace-only")
    if len(candidate) > MAX_PATH_LENGTH:
        raise ValueError(f"{field} exceeds {MAX_PATH_LENGTH} characters")
    if _CONTROL_CHARS.search(candidate):
        raise ValueError(f"{field} contains a control character")
    if "\\" in candidate:
        raise ValueError(f"{field} must use POSIX separators; backslash is not allowed")
    if candidate.startswith("/"):
        raise ValueError(f"{field} must be snapshot-relative, not absolute")
    if _WINDOWS_DRIVE.match(candidate):
        raise ValueError(f"{field} must be snapshot-relative, not a drive path")
    if candidate.endswith("/"):
        raise ValueError(f"{field} must name a file, not a directory")
    for segment in candidate.split("/"):
        if segment == "":
            raise ValueError(f"{field} contains an empty path segment")
        if segment in (".", ".."):
            raise ValueError(f"{field} contains a traversal segment {segment!r}")
    return candidate


def is_safe_relative_path(value: str) -> bool:
    """Return whether ``value`` passes :func:`validate_relative_path` (RX-06)."""
    try:
        validate_relative_path(value)
    except ValueError:
        return False
    return True

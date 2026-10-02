"""Canonical serialisation and content digests (RX-03).

RX-03 requires a ``contract_hash`` such that *semantically equal contracts hash
equal* and *any field change changes the hash*. That is a statement about a
canonical form, not about ``json.dumps`` defaults, so the canonical form is
specified here explicitly and tested directly.

Canonical form, version 1
-------------------------
The digested document is::

    {"@canonical_form": 1, "@type": "<type tag>", "payload": <canonical value>}

serialised with ``sort_keys=True``, ``separators=(",", ":")``,
``ensure_ascii=True`` and ``allow_nan=False``. Consequences:

* **Key order is not semantic.** Mappings are sorted, so two contracts built
  with their ``units`` entries in a different order hash equal.
* **Sequence order is semantic.** Lists keep their order, because the order of
  ``reference_inputs`` or ``known_limits`` is authored information.
* **Set order is not semantic.** ``set``/``frozenset`` members are sorted by
  their own canonical serialisation.
* **Null is explicit.** A field whose value is ``None`` is serialised as
  ``null`` and is *not* dropped, so "field absent" and "field explicitly null"
  cannot produce two different digests for the same contract.
* **Whitespace cannot vary.** The compact separators remove every formatting
  degree of freedom.
* **The type tag provides domain separation.** Two different record types with
  coincidentally identical payloads do not collide.
* **Non-finite floats and naive datetimes have no canonical form.** They raise
  :class:`~retrace_contracts.exceptions.CanonicalisationError` rather than
  producing a digest over an unportable or ambiguous serialisation.

Known limits of this canonical form are recorded in the module-level
:data:`CANONICAL_FORM_LIMITS` so that callers and reviewers can read them
without reading the implementation.

"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence, Set
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Final

from .exceptions import CanonicalisationError

__all__ = [
    "CANONICAL_FORM_LIMITS",
    "CANONICAL_FORM_VERSION",
    "canonical_digest",
    "canonical_json",
    "canonical_timestamp",
    "canonicalise",
    "sha256_hex",
]

CANONICAL_FORM_VERSION: Final[int] = 1
"""Version of the canonical form. Bumping it changes every digest by design."""

_FORM_KEY: Final[str] = "@canonical_form"
_TYPE_KEY: Final[str] = "@type"
_PAYLOAD_KEY: Final[str] = "payload"

CANONICAL_FORM_LIMITS: Final[tuple[str, ...]] = (
    "Float digests depend on Python's shortest round-trip repr; a non-Python "
    "re-implementation must reproduce that exact repr to recompute a digest.",
    "Unicode strings are hashed as written. No NFC/NFKC normalisation is "
    "applied, so two visually identical but differently composed strings hash "
    "differently.",
    "Datetimes are normalised to UTC with microsecond precision; precision "
    "finer than one microsecond is not representable and is not silently "
    "rounded by this module (it cannot reach it).",
    "The digest covers declared content only. It is not a signature and "
    "carries no authorship or authority claim.",
)


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 of ``data`` (RX-01, RX-03)."""
    return hashlib.sha256(data).hexdigest()


def canonical_timestamp(value: datetime) -> str:
    """Render ``value`` as a canonical UTC timestamp string (RX-03, RX-31).

    The datetime must be timezone-aware. RETRACE stores instants in UTC and
    displays them locally (RX-31); a naive datetime has no determinate instant,
    so it cannot be digested and is refused rather than assumed to be UTC.

    Two aware datetimes denoting the same instant in different zones render
    identically, which is required for "semantically equal records hash equal".
    """
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise CanonicalisationError(
            "timezone-naive datetime has no canonical form; "
            "supply an aware datetime (RETRACE stores UTC)"
        )
    moment = value.astimezone(UTC)
    return (
        f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
        f"T{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d}"
        f".{moment.microsecond:06d}Z"
    )


def canonicalise(value: Any, *, path: str = "$") -> Any:
    """Convert ``value`` into JSON-canonicalisable primitives (RX-03).

    Supported inputs: ``None``, ``bool``, ``int``, finite ``float``, ``str``,
    ``Decimal``, ``Enum``, aware ``datetime``, ``date``, mappings with string
    keys, sequences, sets, and objects exposing a pydantic ``model_dump``.

    Anything else raises :class:`CanonicalisationError` naming the path, so an
    unsupported type surfaces as an explicit refusal instead of as a digest
    computed over ``repr()``.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, Enum):
        return canonicalise(value.value, path=path)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalisationError(
                f"non-finite float {value!r} has no canonical form", path=path
            )
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise CanonicalisationError(
                f"non-finite Decimal {value!r} has no canonical form", path=path
            )
        # Decimals are digested as strings: 1.10 and 1.1 are different
        # declarations of precision and must not be collapsed.
        return str(value)
    if isinstance(value, datetime):
        return canonical_timestamp(value)
    if isinstance(value, date):
        return f"{value.year:04d}-{value.month:02d}-{value.day:02d}"
    if isinstance(value, (bytes, bytearray)):
        raise CanonicalisationError(
            "raw bytes have no canonical form; digest them and store the hex digest",
            path=path,
        )
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalisationError(
                    f"mapping key {key!r} is not a string; "
                    "non-string keys have no canonical JSON form",
                    path=path,
                )
            out[key] = canonicalise(item, path=f"{path}.{key}")
        return out
    if isinstance(value, (Set, frozenset)):
        members = [canonicalise(item, path=f"{path}[]") for item in value]
        # Set membership carries no order, so order is removed deterministically.
        return sorted(
            members,
            key=lambda member: json.dumps(
                member, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ),
        )
    if isinstance(value, Sequence):
        return [canonicalise(item, path=f"{path}[{index}]") for index, item in enumerate(value)]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return canonicalise(model_dump(mode="python"), path=path)
    raise CanonicalisationError(
        f"unsupported type {type(value).__name__} has no canonical form", path=path
    )


def canonical_json(payload: Mapping[str, Any], *, type_tag: str) -> str:
    """Return the canonical JSON document for ``payload`` under ``type_tag``.

    This is the exact string that :func:`canonical_digest` hashes, exposed so
    that a digest disagreement can be diffed by a human instead of guessed at
    (RX-03).
    """
    if not type_tag:
        raise CanonicalisationError("a canonical document requires a non-empty type tag")
    document = {
        _FORM_KEY: CANONICAL_FORM_VERSION,
        _TYPE_KEY: type_tag,
        _PAYLOAD_KEY: canonicalise(dict(payload)),
    }
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def canonical_digest(payload: Mapping[str, Any], *, type_tag: str) -> str:
    """Return the lowercase hex SHA-256 of the canonical document (RX-03).

    Stability contract: for a fixed ``CANONICAL_FORM_VERSION`` and ``type_tag``,
    equal canonical payloads always produce equal digests, and any change to any
    digested field produces a different digest.
    """
    return sha256_hex(canonical_json(payload, type_tag=type_tag).encode("utf-8"))

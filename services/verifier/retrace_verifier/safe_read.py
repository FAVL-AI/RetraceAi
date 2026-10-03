"""Defensive reading of run outputs and reference payloads (RX-10, RX-42).

RX-10: the verifier parses run output defensively -- no ``pickle``, no ``eval``,
no arbitrary deserialisation. This module is the only place in
:mod:`retrace_verifier` that touches untrusted bytes, and it is built so that a
hostile payload is **refused before anything deserialises it**:

#. **Extension allowlist.** Only :data:`ALLOWED_SUFFIXES` are considered at all.
   A ``.pkl``/``.pickle``/``.joblib``/``.npy``/``.yaml`` path is refused by
   name, without being opened.
#. **Size cap, checked by ``stat`` first.** A file larger than
   :attr:`ParseLimits.max_bytes` is refused without being read into memory.
#. **Magic-byte refusal.** The leading bytes are matched against
   :data:`REFUSED_MAGIC` -- pickle opcode streams at every protocol level, NumPy
   ``.npy``, zip, gzip, bzip2, xz, zstd, SQLite and HDF5 -- and any NUL byte in
   the inspected prefix. A pickle payload saved as ``outputs.json`` is refused
   here even though its extension is allowed, and a JSON payload saved as
   ``outputs.pkl`` is refused at step 1 even though its content is harmless.
   Both directions have negative controls in ``tests/exec/test_verifier_parsing.py``.
#. **Structural pre-scan.** Nesting depth, key count and container count are
   measured by scanning the raw text with
   :func:`scan_json_shape` *before* ``json.loads`` is called, so an
   over-deep or over-wide document never reaches the parser and can never
   exhaust the C recursion limit.
#. **Non-finite refusal.** ``json.loads`` is called with a ``parse_constant``
   that raises, so the ``NaN``, ``Infinity`` and ``-Infinity`` tokens the JSON
   specification does not contain are refused rather than silently producing a
   float that no tolerance comparison can be honest about.

This module uses ``json`` and ``csv`` from the standard library and nothing
else. There is no ``eval``, ``exec``, ``compile``, ``pickle``, ``marshal``,
``shelve`` or ``yaml`` anywhere in this package, which
``tests/exec/test_verifier_surface.py`` asserts over the AST of every module.
"""

from __future__ import annotations

import csv
import io
import json
import math
from pathlib import Path
from typing import Any, ClassVar, Final

from pydantic import Field
from retrace_contracts import FrozenRecord

from .errors import OutputParseRefused

__all__ = [
    "ALLOWED_SUFFIXES",
    "DEFAULT_PARSE_LIMITS",
    "MAGIC_INSPECTION_BYTES",
    "REFUSED_MAGIC",
    "REFUSED_SUFFIXES",
    "ParseLimits",
    "load_csv_document",
    "load_json_document",
    "read_payload",
    "read_payload_bytes",
    "refuse_by_magic",
    "refuse_by_suffix",
    "scan_json_shape",
]

ALLOWED_SUFFIXES: Final[tuple[str, ...]] = (".json", ".csv")
"""The only payload formats the verifier will read (RX-10)."""

REFUSED_SUFFIXES: Final[tuple[str, ...]] = (
    ".pkl",
    ".pickle",
    ".p",
    ".joblib",
    ".npy",
    ".npz",
    ".pt",
    ".pth",
    ".h5",
    ".hdf5",
    ".yaml",
    ".yml",
    ".dill",
    ".marshal",
    ".db",
    ".sqlite",
    ".so",
    ".exe",
)
"""Extensions named explicitly so the refusal message says *why*, not just "no"."""

REFUSED_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (b"\x80\x01", "pickle protocol 1 opcode stream"),
    (b"\x80\x02", "pickle protocol 2 opcode stream"),
    (b"\x80\x03", "pickle protocol 3 opcode stream"),
    (b"\x80\x04", "pickle protocol 4 opcode stream"),
    (b"\x80\x05", "pickle protocol 5 opcode stream"),
    (b"(lp", "pickle protocol 0 list opcode stream"),
    (b"(dp", "pickle protocol 0 dict opcode stream"),
    (b"}q", "pickle protocol 1 dict opcode stream"),
    (b"]q", "pickle protocol 1 list opcode stream"),
    (b"ccopy_reg\n", "pickle global opcode stream"),
    (b"cos\n", "pickle global opcode stream naming os"),
    (b"c__builtin__\n", "pickle global opcode stream naming builtins"),
    (b"c__main__\n", "pickle global opcode stream naming __main__"),
    (b"\x93NUMPY", "NumPy .npy array"),
    (b"PK\x03\x04", "zip archive"),
    (b"PK\x05\x06", "empty zip archive"),
    (b"\x1f\x8b", "gzip stream"),
    (b"BZh", "bzip2 stream"),
    (b"\xfd7zXZ", "xz stream"),
    (b"\x28\xb5\x2f\xfd", "zstd stream"),
    (b"SQLite format 3\x00", "SQLite database"),
    (b"\x89HDF\r\n\x1a\n", "HDF5 container"),
    (b"\xd0\xcf\x11\xe0", "OLE compound document (macro-bearing office file)"),
)
"""Byte signatures refused outright. Pickle is covered at every protocol level."""

MAGIC_INSPECTION_BYTES: Final[int] = 4096
"""How much of the prefix is inspected for signatures and NUL bytes."""


class ParseLimits(FrozenRecord):
    """Ceilings applied to every untrusted payload (RX-10).

    Each ceiling has a reason, not a round number for its own sake:

    ``max_bytes``
        An outputs document is a summary, not a dataset. Anything larger is
        either the wrong artefact or an attempt to exhaust the verifier.
    ``max_depth``
        Deep nesting is the standard way to make a JSON parser recurse until the
        interpreter dies. Measured before parsing.
    ``max_keys`` / ``max_containers``
        Width equivalents of ``max_depth``.
    ``max_string_length``
        A single enormous string is as effective as many small ones.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ParseLimits"

    max_bytes: int = Field(default=8 * 1024 * 1024, gt=0, description="Payload size ceiling.")
    max_depth: int = Field(default=32, gt=0, description="JSON nesting ceiling.")
    max_keys: int = Field(default=10_000, gt=0, description="JSON key-count ceiling.")
    max_containers: int = Field(
        default=50_000, gt=0, description="JSON object/array-count ceiling."
    )
    max_string_length: int = Field(
        default=65_536, gt=0, description="Ceiling on any single string value."
    )
    max_csv_rows: int = Field(default=100_000, gt=0, description="CSV row ceiling.")
    max_csv_columns: int = Field(default=64, gt=0, description="CSV column ceiling.")


DEFAULT_PARSE_LIMITS: Final[ParseLimits] = ParseLimits()
"""The default ceilings. Tests tighten them to exercise each refusal."""


def refuse_by_suffix(path: Path | str) -> str:
    """Return the admitted lowercase suffix of ``path``, or refuse it (RX-10).

    A refused extension is never opened. The refusal names the suffix so a
    reviewer can see that the *artefact* was wrong, not the verifier.
    """
    suffix = Path(path).suffix.lower()
    if suffix in REFUSED_SUFFIXES:
        raise OutputParseRefused(
            reason="refused-extension",
            path=str(path),
            detail=f"{suffix!r} is a serialised-object or archive format; the verifier "
            "reads JSON and CSV only and will not deserialise objects",
        )
    if suffix not in ALLOWED_SUFFIXES:
        raise OutputParseRefused(
            reason="extension-not-allowlisted",
            path=str(path),
            detail=f"{suffix!r} is not one of {ALLOWED_SUFFIXES}",
        )
    return suffix


def refuse_by_magic(data: bytes, *, path: str | None = None) -> None:
    """Refuse ``data`` if its prefix matches a non-text signature (RX-10).

    Checked for every payload regardless of extension, because the extension is
    attacker-controlled: this is what refuses a pickle stream saved as
    ``outputs.json``. A NUL byte anywhere in the inspected prefix is also
    refused -- a JSON or CSV document never contains one, so its presence means
    the payload is not what it claims to be.
    """
    prefix = data[:MAGIC_INSPECTION_BYTES]
    for signature, label in REFUSED_MAGIC:
        if prefix.startswith(signature):
            raise OutputParseRefused(
                reason="refused-magic-bytes",
                path=path,
                detail=f"payload begins with a {label}; it was not deserialised",
            )
    if b"\x00" in prefix:
        raise OutputParseRefused(
            reason="binary-payload",
            path=path,
            detail="a NUL byte appears in the first "
            f"{MAGIC_INSPECTION_BYTES} bytes; JSON and CSV contain none",
        )


def scan_json_shape(text: str, limits: ParseLimits, *, path: str | None = None) -> dict[str, int]:
    """Measure nesting, keys and containers *before* parsing, or refuse (RX-10).

    A single pass over the raw characters, string-aware so that brackets and
    colons inside string literals do not count. Returns the measured shape.

    This runs before ``json.loads`` on purpose: a 100 000-deep document refused
    here never reaches the C scanner, whereas checking the depth of an
    already-parsed object would require having survived parsing it.
    """
    depth = 0
    max_depth = 0
    keys = 0
    containers = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            depth += 1
            containers += 1
            max_depth = max(max_depth, depth)
            if max_depth > limits.max_depth:
                raise OutputParseRefused(
                    reason="json-too-deep",
                    path=path,
                    detail=f"nesting exceeds max_depth={limits.max_depth}",
                )
            if containers > limits.max_containers:
                raise OutputParseRefused(
                    reason="json-too-many-containers",
                    path=path,
                    detail=f"container count exceeds max_containers={limits.max_containers}",
                )
        elif character in "}]":
            depth -= 1
            if depth < 0:
                raise OutputParseRefused(
                    reason="json-unbalanced",
                    path=path,
                    detail="a closing bracket appears with no matching opening bracket",
                )
        elif character == ":":
            keys += 1
            if keys > limits.max_keys:
                raise OutputParseRefused(
                    reason="json-too-many-keys",
                    path=path,
                    detail=f"key count exceeds max_keys={limits.max_keys}",
                )
    if in_string or depth != 0:
        raise OutputParseRefused(
            reason="json-unbalanced",
            path=path,
            detail="unterminated string or unbalanced brackets",
        )
    return {"depth": max_depth, "keys": keys, "containers": containers}


def _refuse_constant(token: str) -> Any:
    """Refuse the non-finite JSON extension tokens (RX-10).

    ``NaN``, ``Infinity`` and ``-Infinity`` are not JSON. Accepting them would
    put a value into a tolerance comparison for which no comparison is
    meaningful: every tolerance test against ``NaN`` is false, which would read
    as a numeric disagreement rather than as a refused payload.
    """
    raise OutputParseRefused(
        reason="non-finite-token",
        detail=f"the token {token!r} is not valid JSON and has no admissible comparison",
    )


def _refuse_non_finite_float(token: str) -> float:
    """Parse a JSON float and refuse any non-finite result (RX-10)."""
    value = float(token)
    if not math.isfinite(value):
        raise OutputParseRefused(
            reason="non-finite-number",
            detail=f"the literal {token!r} is not a finite number",
        )
    return value


def _check_strings(value: Any, limits: ParseLimits, *, path: str | None = None) -> None:
    """Refuse any string in the parsed document longer than the ceiling (RX-10)."""
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            if len(current) > limits.max_string_length:
                raise OutputParseRefused(
                    reason="string-too-long",
                    path=path,
                    detail=f"a string value exceeds max_string_length="
                    f"{limits.max_string_length}",
                )
        elif isinstance(current, dict):
            stack.extend(current.keys())
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def load_json_document(
    data: bytes, *, limits: ParseLimits = DEFAULT_PARSE_LIMITS, path: str | None = None
) -> dict[str, Any]:
    """Parse ``data`` as a JSON object under every ceiling, or refuse (RX-10).

    The top level must be an object. A top-level array or scalar is refused
    rather than coerced, because an outputs document is a named mapping and
    guessing at a shape is how a verifier ends up comparing the wrong thing.
    """
    if len(data) > limits.max_bytes:
        raise OutputParseRefused(
            reason="payload-too-large",
            path=path,
            detail=f"{len(data)} bytes exceeds max_bytes={limits.max_bytes}",
        )
    refuse_by_magic(data, path=path)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OutputParseRefused(
            reason="not-utf8", path=path, detail=repr(error)
        ) from error
    scan_json_shape(text, limits, path=path)
    try:
        parsed = json.loads(
            text, parse_constant=_refuse_constant, parse_float=_refuse_non_finite_float
        )
    except OutputParseRefused:
        raise
    except ValueError as error:
        raise OutputParseRefused(
            reason="malformed-json", path=path, detail=str(error)
        ) from error
    if not isinstance(parsed, dict):
        raise OutputParseRefused(
            reason="json-not-an-object",
            path=path,
            detail=f"top level is {type(parsed).__name__}, not an object",
        )
    _check_strings(parsed, limits, path=path)
    return parsed


def load_csv_document(
    data: bytes, *, limits: ParseLimits = DEFAULT_PARSE_LIMITS, path: str | None = None
) -> dict[str, Any]:
    """Parse ``data`` as a ``name,value[,unit]`` CSV into an outputs mapping (RX-10).

    CSV carries scalars only; there is no CSV encoding of a vector or a nested
    methodology declaration in this build. A contract output that needs one must
    be reported in JSON, and a required check for an output that CSV cannot
    express is reported ``SKIPPED`` rather than guessed at.
    """
    if len(data) > limits.max_bytes:
        raise OutputParseRefused(
            reason="payload-too-large",
            path=path,
            detail=f"{len(data)} bytes exceeds max_bytes={limits.max_bytes}",
        )
    refuse_by_magic(data, path=path)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OutputParseRefused(reason="not-utf8", path=path, detail=repr(error)) from error
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration as error:
        raise OutputParseRefused(
            reason="csv-empty", path=path, detail="no header row"
        ) from error
    if len(header) > limits.max_csv_columns:
        raise OutputParseRefused(
            reason="csv-too-wide",
            path=path,
            detail=f"{len(header)} columns exceeds max_csv_columns={limits.max_csv_columns}",
        )
    columns = [cell.strip().lower() for cell in header]
    if columns[:2] != ["name", "value"]:
        raise OutputParseRefused(
            reason="csv-unexpected-header",
            path=path,
            detail=f"expected a header beginning 'name,value'; got {columns!r}",
        )
    unit_index = columns.index("unit") if "unit" in columns else None
    outputs: dict[str, Any] = {}
    for row_number, row in enumerate(reader, start=2):
        if row_number - 1 > limits.max_csv_rows:
            raise OutputParseRefused(
                reason="csv-too-many-rows",
                path=path,
                detail=f"row count exceeds max_csv_rows={limits.max_csv_rows}",
            )
        if not row or all(not cell.strip() for cell in row):
            continue
        if len(row) < 2:
            raise OutputParseRefused(
                reason="csv-short-row",
                path=path,
                detail=f"row {row_number} has {len(row)} cells; name and value are required",
            )
        name = row[0].strip()
        if not name:
            raise OutputParseRefused(
                reason="csv-unnamed-output", path=path, detail=f"row {row_number} has no name"
            )
        if name in outputs:
            raise OutputParseRefused(
                reason="csv-duplicate-output",
                path=path,
                detail=f"output {name!r} appears more than once",
            )
        raw_value = row[1].strip()
        try:
            value: Any = _refuse_non_finite_float(raw_value)
        except OutputParseRefused:
            raise
        except ValueError:
            value = raw_value
        entry: dict[str, Any] = {"value": value}
        if unit_index is not None and len(row) > unit_index:
            unit = row[unit_index].strip()
            if unit:
                entry["unit"] = unit
        outputs[name] = entry
    return {"outputs": outputs}


def read_payload_bytes(
    data: bytes,
    *,
    suffix: str,
    limits: ParseLimits = DEFAULT_PARSE_LIMITS,
    path: str | None = None,
) -> dict[str, Any]:
    """Parse in-memory ``data`` of the given admitted ``suffix`` (RX-10)."""
    if suffix == ".json":
        return load_json_document(data, limits=limits, path=path)
    if suffix == ".csv":
        return load_csv_document(data, limits=limits, path=path)
    raise OutputParseRefused(
        reason="extension-not-allowlisted",
        path=path,
        detail=f"{suffix!r} is not one of {ALLOWED_SUFFIXES}",
    )


def read_payload(
    path: Path | str, *, limits: ParseLimits = DEFAULT_PARSE_LIMITS
) -> dict[str, Any]:
    """Read and parse a payload from disk under every ceiling (RX-10).

    Order: extension first (so a refused format is never opened), then ``stat``
    (so an oversized file is never read), then magic bytes, then the structural
    pre-scan, then the parser.
    """
    location = Path(path)
    suffix = refuse_by_suffix(location)
    try:
        size = location.stat().st_size
    except OSError as error:
        raise OutputParseRefused(
            reason="payload-unreadable", path=str(location), detail=repr(error)
        ) from error
    if size > limits.max_bytes:
        raise OutputParseRefused(
            reason="payload-too-large",
            path=str(location),
            detail=f"{size} bytes on disk exceeds max_bytes={limits.max_bytes}",
        )
    try:
        data = location.read_bytes()
    except OSError as error:
        raise OutputParseRefused(
            reason="payload-unreadable", path=str(location), detail=repr(error)
        ) from error
    return read_payload_bytes(data, suffix=suffix, limits=limits, path=str(location))

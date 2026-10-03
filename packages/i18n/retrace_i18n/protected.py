"""Protected spans - text a translation pass must never touch (RX-29).

A translated interface is a rewriting machine pointed at scientific text. Most of
what it rewrites is prose and should be rewritten. Some of it is EVIDENCE, and
rewriting it destroys the thing the reader needs:

* a quoted sentence from a source - a translated quotation is no longer a quotation;
* a code identifier (``run_00001``, ``ResultContract``, a column name);
* a DOI or other resolvable reference;
* a unit (``ms``, ``MiB``, ``mmol/L``) - a translated or reflowed unit changes a
  measurement;
* a dataset name and a digest - a single altered hex character silently breaks
  the link between a bundle and the bytes it describes.

So protection here is EXPLICIT and in-band: the span is marked in the message
value itself, by the person writing the message, rather than guessed by a
heuristic at translation time. A heuristic that must decide whether ``run_00001``
is an identifier or a word will eventually be wrong, and when it is wrong it is
wrong silently.

MARKER CHOICE
    ``❲`` / ``❳`` (LIGHT LEFT/RIGHT TORTOISE SHELL BRACKET ORNAMENT).
    Chosen because they are single code points, printable, trivially greppable,
    and effectively absent from scientific prose - unlike ``[[``, ``{{`` or
    ``<``, each of which occurs in real source text and in code. They are
    markers only: they are stripped before display and never shown to a user.

NESTING IS REFUSED, not supported. A nested span has no unambiguous meaning for
a byte-identity check, so :func:`validate` rejects it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

__all__ = [
    "CLOSE",
    "OPEN",
    "ProtectedSpanError",
    "Segment",
    "placeholders",
    "protect",
    "protected_spans",
    "segments",
    "span_violations",
    "translate_preserving",
    "unprotect",
    "validate",
]

OPEN: Final[str] = "❲"
CLOSE: Final[str] = "❳"

_SPAN = re.compile(f"{OPEN}([^{OPEN}{CLOSE}]*){CLOSE}")
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ProtectedSpanError(ValueError):
    """A protected span is malformed, nested, or would be altered (RX-29)."""


@dataclass(frozen=True, slots=True)
class Segment:
    """One stretch of a message value (RX-29).

    ``protected`` segments carry the payload WITHOUT its markers and must be
    re-emitted byte-identically.
    """

    text: str
    protected: bool


def validate(value: str, *, field: str = "value") -> str:
    """Return ``value`` if its protected markers are well formed (RX-29).

    Refused with a named reason: an unmatched open or close marker, a nested
    span, and a close marker that precedes its open marker.
    """
    depth = 0
    for position, char in enumerate(value):
        if char == OPEN:
            if depth:
                raise ProtectedSpanError(
                    f"{field}: nested protected span at offset {position}; nesting has no "
                    "defined byte-identity semantics and is refused"
                )
            depth += 1
        elif char == CLOSE:
            if not depth:
                raise ProtectedSpanError(
                    f"{field}: close marker without a matching open marker at offset {position}"
                )
            depth -= 1
    if depth:
        raise ProtectedSpanError(f"{field}: unterminated protected span")
    return value


def protect(payload: str) -> str:
    """Wrap ``payload`` as a single protected span (RX-29).

    Raises
    ------
    ProtectedSpanError:
        If ``payload`` already contains a marker. Re-wrapping protected text
        would produce a nested span, which :func:`validate` refuses.
    """
    if OPEN in payload or CLOSE in payload:
        raise ProtectedSpanError("payload already contains a protected-span marker")
    return f"{OPEN}{payload}{CLOSE}"


def unprotect(value: str) -> str:
    """Strip the markers, keeping the payload - the display form (RX-29)."""
    validate(value)
    return value.replace(OPEN, "").replace(CLOSE, "")


def protected_spans(value: str) -> tuple[str, ...]:
    """Return every protected payload, in order, without markers (RX-29)."""
    validate(value)
    return tuple(match.group(1) for match in _SPAN.finditer(value))


def segments(value: str) -> tuple[Segment, ...]:
    """Split ``value`` into alternating literal and protected segments (RX-29)."""
    validate(value)
    out: list[Segment] = []
    cursor = 0
    for match in _SPAN.finditer(value):
        if match.start() > cursor:
            out.append(Segment(value[cursor : match.start()], protected=False))
        out.append(Segment(match.group(1), protected=True))
        cursor = match.end()
    if cursor < len(value):
        out.append(Segment(value[cursor:], protected=False))
    return tuple(out)


def translate_preserving(value: str, translate: Callable[[str], str]) -> str:
    """Apply ``translate`` to the translatable parts of ``value`` only (RX-29).

    Protected payloads are re-emitted byte-identically, markers included, so the
    result is still a valid protected-span string and can be checked again. This
    is the ONLY function in the package that a translation pass should go
    through; anything that calls ``translate(whole_value)`` is the defect RX-29
    exists to prevent.
    """
    parts: list[str] = []
    for segment in segments(value):
        if segment.protected:
            parts.append(f"{OPEN}{segment.text}{CLOSE}")
        else:
            parts.append(translate(segment.text))
    return "".join(parts)


def span_violations(before: str, after: str, *, label: str = "") -> tuple[str, ...]:
    """Return human-readable reasons ``after`` altered ``before``'s spans (RX-29).

    Empty tuple means every protected payload survived byte-identically, in the
    same order and the same number. This is the comparator the catalogue-wide
    translation-pass test asserts on, and the thing the negative control proves
    can fail: a pass that translates whole values must produce a non-empty
    result here.
    """
    prefix = f"{label}: " if label else ""
    try:
        source = protected_spans(before)
    except ProtectedSpanError as exc:  # pragma: no cover - guarded by catalogue tests
        return (f"{prefix}source value is malformed: {exc}",)
    try:
        result = protected_spans(after)
    except ProtectedSpanError as exc:
        return (f"{prefix}translated value is malformed: {exc}",)

    problems: list[str] = []
    if len(source) != len(result):
        problems.append(
            f"{prefix}protected span count changed: {len(source)} -> {len(result)}"
        )
    for index, (want, got) in enumerate(zip(source, result, strict=False)):
        if want != got:
            problems.append(f"{prefix}protected span {index} changed: {want!r} -> {got!r}")
    return tuple(problems)


def placeholders(value: str) -> frozenset[str]:
    """Return the ``{name}`` placeholders in ``value`` (RX-26).

    Collected across the whole string, protected payloads included, because a
    placeholder dropped by a translator breaks the message just as surely as an
    altered digest. Checked for parity between the source value and every
    non-null translation.
    """
    return frozenset(_PLACEHOLDER.findall(value))


def all_protected_spans(values: Iterable[str]) -> tuple[str, ...]:
    """Flatten the protected payloads of many values, in order (RX-29)."""
    out: list[str] = []
    for value in values:
        out.extend(protected_spans(value))
    return tuple(out)

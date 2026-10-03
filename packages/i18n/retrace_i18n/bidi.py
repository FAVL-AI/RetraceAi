"""Bidirectional text: keeping scientific identifiers in logical order (RX-28).

THE FAILURE THIS PREVENTS
    A run identifier, a comparison operator and a digest are left-to-right runs
    embedded in right-to-left prose. The Unicode Bidirectional Algorithm resolves
    neutral characters at the edges of such a run from the SURROUNDING paragraph
    direction, so inside an Arabic, Hebrew, Persian or Urdu sentence:

    * ``p < 0.05`` can display as ``0.05 > p`` - the operator appears reversed
      and the claim is inverted;
    * a trailing ``.`` or ``:`` after ``run_00001`` jumps to the wrong end;
    * a digest split across a line can reorder its neutral separators.

    The stored bytes are unchanged, which is what makes this dangerous: the
    string is right and the reader is wrong.

WHY ISOLATES AND NOT EMBEDDINGS
    ``U+2066 LEFT-TO-RIGHT ISOLATE`` .. ``U+2069 POP DIRECTIONAL ISOLATE`` make
    the enclosed run neutral with respect to its surroundings in BOTH
    directions. The deprecated embedding controls (``U+202A``/``U+202B``) do not
    isolate, so a digit at the boundary still interacts with the outer text.
    Isolates are the current Unicode recommendation and the only form used here.

    HTML ``dir``/``<bdi>`` is the right tool in a browser. This module is for
    plain text - notifications, email bodies, export chrome, accessibility
    strings - where no markup is available.

SCOPE AND LIMITS, stated
    * This inserts isolate characters. It does NOT implement the bidirectional
      algorithm and does not predict the final visual order; a renderer does
      that. The test asserts the isolates are present and the payload bytes and
      logical order are unchanged, which is what this unit can actually
      establish.
    * Protected spans (RX-29) are the unit of isolation: what must not be
      translated is exactly what must not be reordered, so one marker serves
      both. Text with no protected span gets no isolates.
"""

from __future__ import annotations

from typing import Final

from .protected import protected_spans, segments, unprotect, validate
from .registry import LocaleRegistry, resolve_direction

__all__ = [
    "FSI",
    "ISOLATE_CHARS",
    "LRI",
    "PDI",
    "RLI",
    "isolate",
    "render_for_direction",
    "render_message",
    "strip_isolates",
]

LRI: Final[str] = "⁦"
RLI: Final[str] = "⁧"
FSI: Final[str] = "⁨"
PDI: Final[str] = "⁩"

ISOLATE_CHARS: Final[frozenset[str]] = frozenset({LRI, RLI, FSI, PDI})


def isolate(text: str, *, direction: str = "ltr") -> str:
    """Wrap ``text`` in a directional isolate (RX-28).

    ``direction`` is the direction OF ``text``: ``"ltr"`` for a scientific
    identifier, ``"rtl"`` for an RTL run inside LTR prose, ``"auto"`` to let the
    renderer infer it from the first strong character.
    """
    opener = {"ltr": LRI, "rtl": RLI, "auto": FSI}.get(direction)
    if opener is None:
        raise ValueError(f"direction must be 'ltr', 'rtl' or 'auto', not {direction!r}")
    return f"{opener}{text}{PDI}"


def strip_isolates(text: str) -> str:
    """Remove every isolate character, recovering the logical-order string (RX-28).

    The inverse of :func:`render_for_direction` for comparison purposes: the
    test asserts ``strip_isolates(rendered) == unprotect(source)``, which is how
    "the isolates changed presentation and nothing else" is actually checked.
    """
    return "".join(char for char in text if char not in ISOLATE_CHARS)


def render_for_direction(value: str, direction: str) -> str:
    """Render ``value`` for display in ``direction``, isolating protected runs (RX-28).

    Protected-span markers are stripped - they are an authoring device, never
    shown. In an RTL paragraph each protected payload is wrapped in
    ``LRI .. PDI``; in an LTR paragraph nothing is inserted, because there is
    nothing for the algorithm to get wrong and inserting controls that do no
    work would only pollute copy-paste and string comparison.

    The payload itself is passed through byte-identically in both cases.
    """
    validate(value)
    if direction not in ("ltr", "rtl"):
        raise ValueError(f"direction must be 'ltr' or 'rtl', not {direction!r}")
    if direction == "ltr":
        return unprotect(value)
    parts: list[str] = []
    for segment in segments(value):
        parts.append(isolate(segment.text) if segment.protected else segment.text)
    return "".join(parts)


def render_message(
    code: str,
    value: str,
    *,
    source: LocaleRegistry | None = None,
) -> str:
    """Render ``value`` for locale ``code`` (RX-28).

    Direction comes from the registry, never from a list in this module, so the
    four RTL locales the spec declares - including ``ur``, which the upstream
    prose omitted - are handled by construction rather than by remembering to
    add them here.
    """
    return render_for_direction(value, resolve_direction(code, source=source))


def isolation_violations(code: str, value: str, rendered: str) -> tuple[str, ...]:
    """Return reasons ``rendered`` fails the RX-28 obligations for ``value``.

    Empty tuple means: every protected payload is present byte-identically,
    each is immediately enclosed by ``LRI .. PDI`` when the locale is RTL, and
    stripping the isolates reproduces the display text exactly. This is the
    comparator the RTL tests assert on and the one the negative control (a
    renderer that inserts no isolates) must fail.
    """
    problems: list[str] = []
    payloads = protected_spans(value)
    if strip_isolates(rendered) != unprotect(value):
        problems.append(f"{code}: stripping isolates does not reproduce the display text")
    for payload in payloads:
        if payload not in rendered:
            problems.append(f"{code}: protected payload {payload!r} is missing or altered")
            continue
        if f"{LRI}{payload}{PDI}" not in rendered:
            problems.append(f"{code}: protected payload {payload!r} is not isolated")
    return tuple(problems)

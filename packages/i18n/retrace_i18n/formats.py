"""A deliberately narrow locale-aware integer formatter (RX-27).

WHAT THIS IS NOT
    This is not a replacement for CLDR number formatting and must not be
    presented as one. ``babel`` is not installed in this environment and no
    CLDR data is bundled, so the only honest options were: guess separators per
    locale in code, or require each catalogue to DECLARE them and refuse to
    format when it has not. This module does the second.

    A locale whose catalogue has no ``formats.number`` block raises
    :class:`FormatUnavailable`. That is the point: a wrong group separator in a
    tolerance, a digest length or a budget is a silent misreading of a number,
    and a caller that gets an exception will render the untranslated form or the
    ``NEEDS_CONFIGURATION`` label instead of a plausible wrong number.

WHAT IS COVERED
    Integer grouping and the decimal separator for the locales whose catalogues
    declare them. ``grouping`` is a list of group sizes from the least
    significant end, so the Indic 3-then-2 pattern (``12,34,567``) is expressible
    rather than approximated.

WHAT IS NOT COVERED, and is owed
    Date and time formatting (RX-31 - a different unit owns it; no date pattern
    is hardcoded here or anywhere in this package), currency, percent, compact
    decimals, non-ASCII digit shaping (Arabic-Indic digits), significant-digit
    rounding, and negative-number patterns beyond a leading minus sign. Locales
    whose numbering needs digit shaping are left undeclared rather than
    approximated with ASCII digits.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ["FormatUnavailable", "NumberFormat", "format_integer"]


class FormatUnavailable(LookupError):
    """No verified number format is declared for this locale (RX-27)."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(
            f"locale {code!r} declares no formats.number block. Formatting is refused rather "
            "than guessed: render the source-locale form or the NEEDS_CONFIGURATION label."
        )


@dataclass(frozen=True, slots=True)
class NumberFormat:
    """Declared integer-grouping facts for one locale (RX-27)."""

    group: str
    decimal: str
    grouping: tuple[int, ...] = (3,)
    minus: str = "-"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, code: str) -> NumberFormat:
        """Build from a catalogue ``formats.number`` block (RX-27)."""
        group = data.get("group")
        decimal = data.get("decimal")
        if not isinstance(group, str) or not isinstance(decimal, str):
            raise FormatUnavailable(code)
        raw = data.get("grouping", [3])
        if not isinstance(raw, Sequence) or isinstance(raw, str | bytes) or not raw:
            raise FormatUnavailable(code)
        sizes = tuple(int(size) for size in raw)
        if any(size < 1 for size in sizes):
            raise FormatUnavailable(code)
        return cls(
            group=group,
            decimal=decimal,
            grouping=sizes,
            minus=str(data.get("minus", "-")),
        )

    def apply(self, value: int) -> str:
        """Group ``value``'s digits per the declared pattern (RX-27)."""
        digits = str(abs(int(value)))
        chunks: list[str] = []
        index = 0
        remaining = digits
        while remaining:
            size = self.grouping[min(index, len(self.grouping) - 1)]
            chunks.append(remaining[-size:])
            remaining = remaining[:-size]
            index += 1
        body = self.group.join(reversed(chunks))
        return f"{self.minus}{body}" if value < 0 else body


def format_integer(code: str, value: int, number_format: NumberFormat | None) -> str:
    """Format ``value`` for ``code``, or refuse (RX-27).

    ``number_format`` comes from the locale's catalogue. ``None`` means the
    catalogue declares none, which raises :class:`FormatUnavailable`.
    """
    if number_format is None:
        raise FormatUnavailable(code)
    return number_format.apply(value)

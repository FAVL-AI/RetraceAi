"""The narrow number formatter refuses to guess (RX-27)."""

from __future__ import annotations

import pytest
from retrace_i18n.catalogue import Catalogue
from retrace_i18n.formats import FormatUnavailable, NumberFormat, format_integer
from retrace_i18n.registry import LocaleRegistry


def test_source_locale_declares_a_number_format(catalogues: dict[str, Catalogue]) -> None:
    fmt = catalogues["en"].number_format
    assert fmt is not None
    assert format_integer("en", 1234567, fmt) == "1,234,567"


@pytest.mark.parametrize(
    ("code", "value", "expected"),
    [
        ("en", 1234567, "1,234,567"),
        ("de", 1234567, "1.234.567"),
        ("nl", 1234567, "1.234.567"),
        ("fr", 1234567, "1 234 567"),
        ("sv", 1234567, "1 234 567"),
        ("hi", 1234567, "12,34,567"),
        ("ja", 1234567, "1,234,567"),
        ("en", -1234, "-1,234"),
        ("en", 0, "0"),
        ("en", 999, "999"),
    ],
)
def test_declared_formats_group_as_declared(
    code: str, value: int, expected: str, catalogues: dict[str, Catalogue]
) -> None:
    """Grouping follows the catalogue's declaration, including Indic 3-then-2 (RX-27)."""
    fmt = catalogues[code].number_format
    assert fmt is not None, f"{code} declares no number format"
    assert format_integer(code, value, fmt) == expected


def test_some_locales_deliberately_declare_no_format(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """Undeclared is the honest state where digit shaping is needed (RX-27).

    Arabic and Persian use Arabic-Indic digits and their own separators. No
    verified data for them is bundled, so no format is declared and formatting
    is refused rather than rendered with ASCII digits and a guessed separator.
    """
    undeclared = [c for c in reg.codes if catalogues[c].number_format is None]
    assert "ar" in undeclared
    assert "fa" in undeclared
    declared = [c for c in reg.codes if catalogues[c].number_format is not None]
    assert len(declared) >= 15, "the formatter would be near-vacuous with so few declarations"


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def test_negative_control_an_undeclared_locale_raises(
    catalogues: dict[str, Catalogue],
) -> None:
    """MANDATORY negative control: no declaration means refusal, not a guess (RX-27).

    A plausible wrong separator is a silently misread number. The caller gets an
    exception so it can render the source form or NEEDS_CONFIGURATION instead.
    """
    assert catalogues["ar"].number_format is None
    with pytest.raises(FormatUnavailable) as excinfo:
        format_integer("ar", 1234, catalogues["ar"].number_format)
    assert "refused rather than guessed" in str(excinfo.value)


@pytest.mark.parametrize(
    "bad",
    [
        {"decimal": "."},
        {"group": ","},
        {"group": ",", "decimal": ".", "grouping": []},
        {"group": ",", "decimal": ".", "grouping": [0]},
        {"group": ",", "decimal": ".", "grouping": "3"},
    ],
)
def test_negative_control_malformed_format_blocks_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(FormatUnavailable):
        NumberFormat.from_mapping(bad, code="xx")


def test_no_date_pattern_is_declared_anywhere(catalogues: dict[str, Catalogue]) -> None:
    """RX-27 forbids a hardcoded date format; this package declares none at all.

    Date and time rendering belongs to the unit that owns RX-31. Asserting the
    absence here keeps a well-meant "temporary" pattern from appearing in a
    catalogue and becoming the de facto format.
    """
    for code, catalogue in catalogues.items():
        for key, message in catalogue.entries.items():
            for text in message.strings():
                for token in ("%Y", "YYYY", "dd/MM", "MM/dd", "HH:mm:ss"):
                    assert token not in text, f"{code}/{key} carries a date pattern {token!r}"

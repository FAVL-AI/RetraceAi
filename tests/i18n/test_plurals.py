"""CLDR cardinal plural selection (RX-27).

PROVENANCE OF THE EXPECTED VALUES IN THIS FILE
    They were written from knowledge of the CLDR cardinal rules, like the
    implementation they test, and were NOT read from a pinned CLDR release. That
    means this file demonstrates INTERNAL CONSISTENCY between the rules and the
    expectations, and the spec agreement that both declare - it does NOT
    establish agreement with CLDR. A real oracle test (export
    ``supplemental/plurals.xml`` from a pinned release, sweep every locale) is
    owed and absent. Treated as DERIVED, not VERIFIED.

    This is stated here rather than in a commit message so that a reader of the
    passing suite cannot mistake it for CLDR conformance.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from i18n_support import synthetic_registry
from retrace_i18n.plurals import (
    Operands,
    PluralCategoryMismatch,
    UnsupportedPluralLocale,
    compute_plural_category,
    plural_rule_name,
    select_plural,
)
from retrace_i18n.registry import LocaleRegistry


def test_every_locale_resolves_a_category_for_a_sweep_of_counts(reg: LocaleRegistry) -> None:
    """No declared locale may raise for an ordinary integer count (RX-27).

    This is the broad gate: every one of the 36 locales, swept over the integers
    that distinguish the CLDR families, must produce a category it declares.
    """
    counts = [0, 1, 2, 3, 5, 11, 12, 14, 19, 21, 22, 25, 100, 101, 102, 111, 1_000_000]
    for locale in reg:
        for count in counts:
            category = select_plural(locale.code, count, source=reg)
            assert category in locale.plural_categories, (locale.code, count, category)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("en", "en"), ("nl", "nl"), ("de", "de"), ("sv", "sv"), ("fi", "fi"), ("ur", "ur"),
        ("da", "da"), ("fr", "fr"), ("es", "es"), ("it", "it"), ("pt", "pt"),
        ("pl", "pl"), ("ru", "ru"), ("uk", "uk"), ("cs", "cs"), ("sk", "sk"),
        ("ro", "ro"), ("he", "he"), ("ar", "ar"),
        ("zh-Hans", "zh"), ("ja", "ja"), ("ko", "ko"), ("vi", "vi"), ("th", "th"), ("id", "id"),
        ("ak", "ak"), ("hi", "hi"), ("bn", "bn"), ("fa", "fa"), ("sw", "sw"),
        ("el", "el"), ("hu", "hu"), ("tr", "tr"), ("nb", "nb"), ("ta", "ta"), ("te", "te"),
    ],
)
def test_each_locale_uses_an_implemented_rule_not_an_inference(
    code: str, expected: str, reg: LocaleRegistry
) -> None:
    """All 36 locales hit a named rule; none falls through to an inference (RX-27)."""
    name = plural_rule_name(code, source=reg)
    assert name == expected
    assert not name.startswith("inferred:"), f"{code} fell back to a guessed rule"


@pytest.mark.parametrize(
    ("code", "cases"),
    [
        # one / other, 'one' requires i = 1 and v = 0
        ("en", {0: "other", 1: "one", 2: "other", 21: "other", "1.0": "other"}),
        ("de", {1: "one", 0: "other", 2: "other"}),
        ("nl", {1: "one", 2: "other"}),
        ("ur", {1: "one", 2: "other", 0: "other"}),
        # one: n = 1
        ("tr", {1: "one", 0: "other", 2: "other"}),
        ("el", {1: "one", 2: "other"}),
        # one: i = 0 or n = 1
        ("hi", {0: "one", 1: "one", 2: "other", "0.5": "one"}),
        ("fa", {0: "one", 1: "one", 2: "other"}),
        # one: n = 0..1
        ("ak", {0: "one", 1: "one", 2: "other"}),
        # single category
        ("zh-Hans", {0: "other", 1: "other", 5: "other", 1_000_000: "other"}),
        ("ja", {1: "other"}),
        ("ko", {1: "other"}),
        ("vi", {1: "other"}),
        ("th", {1: "other"}),
        ("id", {1: "other"}),
        # Romance: 'many' is the compact-decimal million category
        ("fr", {0: "one", 1: "one", 2: "other", 1_000_000: "many", 2_000_000: "many"}),
        ("pt", {0: "one", 1: "one", 2: "other", 1_000_000: "many"}),
        ("es", {0: "other", 1: "one", 2: "other", 1_000_000: "many"}),
        ("it", {0: "other", 1: "one", 2: "other", 1_000_000: "many"}),
        # Slavic few/many
        ("pl", {1: "one", 2: "few", 3: "few", 4: "few", 5: "many", 12: "many", 14: "many",
                22: "few", 25: "many", 111: "many", "1.5": "other"}),
        ("ru", {1: "one", 21: "one", 2: "few", 22: "few", 5: "many", 11: "many", 14: "many",
                100: "many", "1.5": "other"}),
        ("uk", {1: "one", 21: "one", 3: "few", 5: "many", 11: "many"}),
        ("cs", {1: "one", 2: "few", 4: "few", 5: "other", 0: "other", "1.5": "many"}),
        ("sk", {1: "one", 3: "few", 7: "other", "0.5": "many"}),
        # Romanian 'few' for 0 and the 1..19 band of n % 100
        ("ro", {1: "one", 0: "few", 2: "few", 19: "few", 20: "other", 101: "few",
                120: "other", "1.5": "few"}),
        # Hebrew two and the tens 'many'
        ("he", {1: "one", 2: "two", 3: "other", 10: "other", 20: "many", 30: "many",
                11: "other", 0: "other"}),
        # Arabic six categories
        ("ar", {0: "zero", 1: "one", 2: "two", 3: "few", 10: "few", 11: "many", 99: "many",
                100: "other", 101: "other", 103: "few", 111: "many"}),
    ],
)
def test_rule_tables(code: str, cases: dict[object, str], reg: LocaleRegistry) -> None:
    """The family rules return the declared categories for the deciding counts (RX-27)."""
    for value, expected in cases.items():
        assert select_plural(code, value, source=reg) == expected, (code, value)


def test_operands_distinguish_visible_fraction_digits() -> None:
    """``1`` and ``"1.0"`` are different CLDR inputs and stay different (RX-27)."""
    assert Operands.of(1) == Operands(n=Decimal(1), i=1, v=0, f=0, t=0)
    one_point_zero = Operands.of("1.0")
    assert (one_point_zero.i, one_point_zero.v, one_point_zero.f, one_point_zero.t) == (1, 1, 0, 0)
    assert select_plural("en", 1) == "one"
    assert select_plural("en", "1.0") == "other"


def test_operands_reject_values_that_are_not_counts() -> None:
    for bad in (True, "not a number", float("nan"), float("inf")):
        with pytest.raises(TypeError):
            Operands.of(bad)  # type: ignore[arg-type]


def test_negative_counts_use_the_absolute_value() -> None:
    """CLDR operands are defined on the absolute value (RX-27)."""
    assert select_plural("en", -1) == "one"
    assert select_plural("ar", -2) == "two"


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def test_negative_control_category_not_declared_for_the_locale_raises(
    reg: LocaleRegistry,
) -> None:
    """MANDATORY negative control: a computed category outside the declared set raises.

    Russian is given a spec that declares only ``one``/``other``. Asking for 2 -
    which the East Slavic rule resolves to ``few`` - must raise rather than be
    coerced to ``other``, because coercion would render a wrong grammatical form
    and hide the spec/rule disagreement (RX-27).
    """
    trimmed = synthetic_registry(reg, ru={"plural_categories": ["one", "other"]})
    assert select_plural("ru", 1, source=trimmed) == "one"
    with pytest.raises(PluralCategoryMismatch) as excinfo:
        select_plural("ru", 2, source=trimmed)
    message = str(excinfo.value)
    assert "few" in message
    assert "specs/locales.json" in message
    # The raw rule still computes the right category: the mismatch is a contract
    # failure between rule and spec, not a rule failure.
    assert compute_plural_category("ru", 2, source=trimmed) == "few"


def test_negative_control_arabic_trimmed_to_two_categories_raises(reg: LocaleRegistry) -> None:
    """The same control on a six-category locale (RX-27)."""
    trimmed = synthetic_registry(reg, ar={"plural_categories": ["one", "other"]})
    with pytest.raises(PluralCategoryMismatch):
        select_plural("ar", 0, source=trimmed)


def test_negative_control_unimplemented_rule_refuses_to_guess(reg: LocaleRegistry) -> None:
    """A rich category set with no implemented rule raises instead of guessing (RX-27).

    Swahili is re-declared with a Slavic-shaped category set. There is no
    implemented ``sw`` four-category rule and none can be inferred from the
    shape, so the only honest answer is a refusal: guessing produces output that
    looks right and is wrong.
    """
    # Re-tagged to a language the rule table does not know, so the lookup cannot
    # fall back to the real Swahili rule.
    renamed = synthetic_registry(
        reg, sw={"code": "qq", "plural_categories": ["one", "few", "many", "other"]}
    )
    assert "qq" in renamed.codes and "sw" not in renamed.codes
    with pytest.raises(UnsupportedPluralLocale) as excinfo:
        select_plural("qq", 2, source=renamed)
    assert "pinned CLDR release" in str(excinfo.value)

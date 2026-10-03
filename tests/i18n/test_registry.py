"""The locale registry is the only locale list (RX-26, RX-28)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from retrace_i18n.registry import (
    CLDR_PLURAL_CATEGORIES,
    LocaleRegistry,
    RegistrySpecError,
    SpecNotFoundError,
    UnknownLocaleError,
    get_locale,
    load_registry,
    locale_codes,
    plural_categories,
    resolve_direction,
    spec_path,
)

#: The declared total. Asserted as a literal ON PURPOSE: the point of this test
#: is that a locale silently dropped from specs/locales.json fails the build.
#: Everything else in the package derives its locale list from the spec.
EXPECTED_LOCALE_COUNT = 36

#: The four right-to-left locales. ``ur`` is included because the registry marks
#: Urdu rtl; the upstream prose named only Arabic, Hebrew and Persian, and that
#: omission is a recorded deviation, not a reason to drop Urdu here (RX-28).
EXPECTED_RTL = {"ar", "he", "fa", "ur"}


def test_registry_declares_exactly_thirty_six_locales(reg: LocaleRegistry) -> None:
    """A dropped or added locale must not pass silently (RX-26)."""
    assert len(reg) == EXPECTED_LOCALE_COUNT
    assert len(locale_codes(source=reg)) == EXPECTED_LOCALE_COUNT
    assert len(set(reg.codes)) == EXPECTED_LOCALE_COUNT, "duplicate locale code"


def test_spec_declared_count_matches_the_list(reg: LocaleRegistry) -> None:
    """The spec's own ``count`` field agrees with its list (RX-26)."""
    data = json.loads(Path(spec_path()).read_text(encoding="utf-8"))
    assert data["count"] == len(reg) == len(data["locales"])


def test_source_locale_is_english_and_present(reg: LocaleRegistry) -> None:
    assert reg.source_locale == "en"
    assert reg.source.code == "en"


def test_every_locale_has_usable_facts(reg: LocaleRegistry) -> None:
    """Direction, script, endonym and plural categories are all present (RX-26)."""
    for locale in reg:
        assert locale.direction in ("ltr", "rtl"), locale.code
        assert locale.endonym.strip(), locale.code
        assert locale.plural_categories, locale.code
        assert set(locale.plural_categories) <= CLDR_PLURAL_CATEGORIES, locale.code
        assert "other" in locale.plural_categories, (
            f"{locale.code}: CLDR requires every locale to have 'other'"
        )


def test_direction_resolves_rtl_for_the_four_rtl_locales(reg: LocaleRegistry) -> None:
    """ar, he, fa AND ur resolve rtl (RX-28)."""
    for code in sorted(EXPECTED_RTL):
        assert resolve_direction(code, source=reg) == "rtl", code
    assert set(reg.rtl_codes) == EXPECTED_RTL


@pytest.mark.parametrize("code", ["en", "nl", "de", "ja", "zh-Hans", "hi", "sw", "ak", "el", "th"])
def test_direction_resolves_ltr_for_a_sample_of_others(code: str, reg: LocaleRegistry) -> None:
    """A sample across scripts resolves ltr (RX-28) - the negative side of the pair."""
    assert resolve_direction(code, source=reg) == "ltr"
    assert code not in EXPECTED_RTL


def test_tag_reconciliation_resolves_region_qualified_tags(reg: LocaleRegistry) -> None:
    """``ur-PK`` resolves to the ``ur`` entry while the tag scheme is reconciled (RX-26).

    The upstream spec writes region-qualified tags where this one writes bare
    language tags. A caller must not have to know which spelling is current.
    """
    assert get_locale("ur-PK", source=reg).code == "ur"
    assert get_locale("ur_PK", source=reg).code == "ur"
    assert get_locale("PT", source=reg).code == "pt"
    assert get_locale("zh-hans", source=reg).code == "zh-Hans"


def test_unknown_locale_raises_rather_than_falling_back(reg: LocaleRegistry) -> None:
    """An unknown code is an error, never a silent default (RX-26)."""
    with pytest.raises(UnknownLocaleError) as excinfo:
        get_locale("xx-YY", source=reg)
    assert "xx-YY" in str(excinfo.value)
    assert "specs/locales.json" in str(excinfo.value)


def test_no_locale_carries_a_review_record(reg: LocaleRegistry) -> None:
    """Reviewed coverage is 0 of 36 because no review has happened (RX-30)."""
    assert reg.reviewed_codes == ()
    for locale in reg:
        assert locale.reviewer is None, locale.code
        assert locale.reviewed_at is None, locale.code
        assert not locale.is_reviewed, locale.code


def test_registry_is_cached_and_immutable(reg: LocaleRegistry) -> None:
    """The spec is parsed once per path (RX-26)."""
    assert load_registry() is load_registry()
    with pytest.raises((AttributeError, TypeError)):
        reg.entries = ()  # type: ignore[misc]


def test_language_subtag_is_stable_across_tag_schemes(reg: LocaleRegistry) -> None:
    """Plural and direction families key on the subtag, not the full tag (RX-27)."""
    assert get_locale("zh-Hans", source=reg).language_subtag == "zh"
    assert get_locale("ur", source=reg).language_subtag == "ur"


def test_plural_categories_come_from_the_spec(reg: LocaleRegistry) -> None:
    """The declared categories are read, never inferred (RX-27)."""
    assert plural_categories("ar", source=reg) == ("zero", "one", "two", "few", "many", "other")
    assert plural_categories("pl", source=reg) == ("one", "few", "many", "other")
    assert plural_categories("ja", source=reg) == ("other",)


# ---------------------------------------------------------------------------
# Negative controls. Each proves the validator REJECTS a specific malformed
# spec, so a passing build is evidence the check works rather than evidence it
# never fired.
# ---------------------------------------------------------------------------

_MINIMAL: dict[str, Any] = {
    "source_locale": "en",
    "count": 1,
    "locales": [
        {
            "code": "en",
            "name": "English",
            "endonym": "English",
            "script": "Latn",
            "direction": "ltr",
            "plural_categories": ["one", "other"],
            "review_status": "source",
            "reviewer": None,
            "reviewed_at": None,
        }
    ],
}


def _spec(**changes: Any) -> dict[str, Any]:
    out = json.loads(json.dumps(_MINIMAL))
    out.update(changes)
    return out


def test_negative_control_count_disagreeing_with_the_list_is_refused() -> None:
    """A dropped locale shows up as a count mismatch and is refused (RX-26)."""
    with pytest.raises(RegistrySpecError, match="count=2"):
        LocaleRegistry.from_spec(_spec(count=2))


def test_negative_control_duplicate_code_is_refused() -> None:
    bad = _spec()
    bad["locales"] = [bad["locales"][0], json.loads(json.dumps(bad["locales"][0]))]
    bad["count"] = 2
    with pytest.raises(RegistrySpecError, match="duplicate"):
        LocaleRegistry.from_spec(bad)


def test_negative_control_bad_direction_is_refused() -> None:
    bad = _spec()
    bad["locales"][0]["direction"] = "sideways"
    with pytest.raises(RegistrySpecError, match="direction"):
        LocaleRegistry.from_spec(bad)


def test_negative_control_non_cldr_plural_category_is_refused() -> None:
    bad = _spec()
    bad["locales"][0]["plural_categories"] = ["one", "plenty"]
    with pytest.raises(RegistrySpecError, match="non-CLDR"):
        LocaleRegistry.from_spec(bad)


def test_negative_control_empty_plural_categories_is_refused() -> None:
    bad = _spec()
    bad["locales"][0]["plural_categories"] = []
    with pytest.raises(RegistrySpecError, match="no plural categories"):
        LocaleRegistry.from_spec(bad)


def test_negative_control_source_locale_outside_the_list_is_refused() -> None:
    with pytest.raises(RegistrySpecError, match="source_locale"):
        LocaleRegistry.from_spec(_spec(source_locale="fr"))


def test_negative_control_empty_locale_list_is_refused() -> None:
    with pytest.raises(RegistrySpecError, match="non-empty"):
        LocaleRegistry.from_spec({"source_locale": "en", "locales": []})


def test_negative_control_missing_spec_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pointer to a non-existent spec is an error, not a built-in fallback (RX-26)."""
    monkeypatch.setenv("RETRACE_LOCALES_SPEC", "/nonexistent/locales.json")
    with pytest.raises(SpecNotFoundError):
        spec_path()

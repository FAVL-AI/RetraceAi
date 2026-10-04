"""Catalogue structure, resolution and the honesty of 'pending' (RX-26, RX-30)."""

from __future__ import annotations

import pytest
from i18n_support import catalogue_from, entry, plural_entry
from retrace_i18n.catalogue import (
    FLAG_BETA,
    FLAG_FALLBACK,
    FLAG_MACHINE_TRANSLATED,
    FLAG_MISSING_KEY,
    FLAG_PENDING,
    STATUS_PENDING,
    Catalogue,
    CatalogueError,
    MissingKeyError,
    Translator,
)
from retrace_i18n.plurals import select_plural
from retrace_i18n.registry import LocaleRegistry

EXPECTED_KEY_COUNT = 86

#: Every surface RX-26 mandates, as a namespace prefix and the minimum count.
#: A catalogue that quietly loses a whole surface fails here rather than
#: averaging out across the other 80 keys.
MANDATED_SURFACES = {
    "nav.": 13,
    "outcome.": 5,
    "truth.": 9,
    "field.": 9,
    "validation.": 7,
    "error.": 6,
    "notify.": 5,
    "help.": 4,
    "consent.": 3,
    "invite.": 3,
    "email.": 4,
    "a11y.": 6,
    "export.": 5,
    "state.": 4,
    "count.": 3,
}


def test_one_catalogue_per_declared_locale(catalogues: dict[str, Catalogue],
                                           reg: LocaleRegistry) -> None:
    """36 locales, 36 catalogues - a spec locale with no file is a missing deliverable."""
    assert set(catalogues) == set(reg.codes)
    assert len(catalogues) == 36


def test_source_catalogue_key_count(catalogues: dict[str, Catalogue]) -> None:
    """The source key set is the measuring stick and is asserted literally (RX-26)."""
    assert len(catalogues["en"].entries) == EXPECTED_KEY_COUNT


def test_every_mandated_surface_is_covered(catalogues: dict[str, Catalogue]) -> None:
    """RX-26 names the surfaces; each is present with its full complement."""
    keys = catalogues["en"].keys
    for prefix, count in MANDATED_SURFACES.items():
        present = [k for k in keys if k.startswith(prefix)]
        assert len(present) == count, f"{prefix}: expected {count}, found {len(present)}"
    assert sum(MANDATED_SURFACES.values()) == EXPECTED_KEY_COUNT


def test_the_thirteen_navigation_routes_are_the_documented_ones(
    catalogues: dict[str, Catalogue],
) -> None:
    """The nav namespace matches the 13 routes RX-20 lists, exactly (RX-26)."""
    expected = {
        "workspaces", "projects", "sources", "studio", "lineage", "repairs", "contracts",
        "runs", "evidence", "wiki", "connectors", "calendar", "settings",
    }
    found = {k.removeprefix("nav.") for k in catalogues["en"].keys if k.startswith("nav.")}
    assert found == expected


def test_structural_coverage_is_complete_for_every_locale(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """Zero missing and zero extra keys in all 36 catalogues (RX-26)."""
    for code in reg.codes:
        translator = Translator(
            code,
            catalogue=catalogues[code],
            source_catalogue=catalogues["en"],
            registry_source=reg,
        )
        assert translator.missing_keys() == (), code
        assert translator.extra_keys() == (), code


def test_every_source_entry_has_a_translator_description(
    catalogues: dict[str, Catalogue],
) -> None:
    """A string with no description is a string a translator must guess at (RX-26)."""
    for key, message in catalogues["en"].entries.items():
        assert len(message.description) >= 10, f"{key}: description too thin"


def test_descriptions_are_carried_into_every_catalogue(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """The translator sees the description next to the string, in every locale."""
    source = catalogues["en"]
    for code in reg.codes:
        if code == "en":
            continue
        for key, message in catalogues[code].entries.items():
            assert message.description == source.entries[key].description, (code, key)


def test_every_non_source_entry_is_marked_machine_generated(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """RX-30: machine provenance is recorded per entry, not just per file."""
    for code in reg.codes:
        if code == "en":
            continue
        for key, message in catalogues[code].entries.items():
            assert message.machine_generated is True, (code, key)
            assert message.status in ("translated", "pending"), (code, key, message.status)
    for key, message in catalogues["en"].entries.items():
        assert message.machine_generated is False, key


def test_every_catalogue_is_beta_with_no_reviewer(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """RX-30: review_status 'beta', reviewer null, so nothing is reviewed."""
    for code in reg.codes:
        catalogue = catalogues[code]
        expected = "source" if code == "en" else "beta"
        assert catalogue.review_status == expected, code
        assert catalogue.reviewer is None, code
        assert catalogue.reviewed_at is None, code
        assert not catalogue.is_reviewed, code


def test_pending_entries_hold_null_not_an_empty_string(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """A pending key is ``null``: an empty string would render as blank chrome (RX-30)."""
    for code in reg.codes:
        for key, message in catalogues[code].entries.items():
            if message.status != STATUS_PENDING:
                continue
            if message.is_plural:
                assert all(v is None for v in (message.forms or {}).values()), (code, key)
            else:
                assert message.value is None, (code, key)


def test_plural_entries_declare_exactly_the_locales_categories(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """A plural entry's form keys match the spec's declared categories (RX-27)."""
    for locale in reg:
        for key, message in catalogues[locale.code].entries.items():
            if not message.is_plural:
                continue
            if locale.code == "en":
                assert set(message.forms or {}) == {"one", "other"}, key
            else:
                assert set(message.forms or {}) == set(locale.plural_categories), (
                    locale.code, key,
                )


def test_source_locale_resolution_carries_no_flags(reg: LocaleRegistry) -> None:
    """English is the source: no beta, no machine-translated, no fallback (RX-30)."""
    translator = Translator("en", registry_source=reg)
    text, flags = translator.text("nav.projects")
    assert text == "Projects"
    assert flags == ()


def test_an_unreviewed_locale_renders_the_beta_label(reg: LocaleRegistry) -> None:
    """MANDATORY: a locale without a review record renders ``beta`` (RX-30)."""
    for code in ("nl", "de", "ja", "ar", "ur", "ak"):
        translator = Translator(code, registry_source=reg)
        _, flags = translator.text("nav.projects")
        assert FLAG_BETA in flags, code
        assert FLAG_MACHINE_TRANSLATED in flags, code


def test_a_translated_value_is_still_flagged(reg: LocaleRegistry) -> None:
    """A real translation is still machine output until a human reviews it (RX-30)."""
    translator = Translator("nl", registry_source=reg)
    text, flags = translator.text("nav.projects")
    assert text == "Projecten"
    assert set(flags) == {FLAG_MACHINE_TRANSLATED, FLAG_BETA}


def test_a_pending_value_falls_back_and_says_so(reg: LocaleRegistry) -> None:
    """A null translation falls back to English WITH the pending flag (RX-30)."""
    resolution = Translator("ak", registry_source=reg).resolve("nav.projects")
    assert resolution.value == "Projects"
    assert resolution.used_locale == "en"
    assert resolution.is_pending
    assert resolution.is_source_fallback
    assert not resolution.is_missing_key
    assert FLAG_PENDING in resolution.flags


def test_outcome_labels_are_pending_in_every_non_source_locale(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """A deliberate, recorded decision, not an oversight (RX-25, RX-30).

    The five outcome labels are conformance statements; whether a rendering
    keeps the 'within contract' qualifier inseparable from the label is a
    linguistic judgement (docs/security/T10_REVIEW.md control 1). No machine
    value is written for them, so the interface falls back to the English label
    with the beta and pending chips rather than showing a plausible translation
    nobody has checked.
    """
    for code in reg.codes:
        if code == "en":
            continue
        for key in (k for k in catalogues[code].keys if k.startswith("outcome.")):
            assert catalogues[code].entries[key].value is None, (code, key)
            resolution = Translator(
                code, catalogue=catalogues[code], source_catalogue=catalogues["en"],
                registry_source=reg,
            ).resolve(key)
            assert resolution.used_locale == "en"
            assert FLAG_PENDING in resolution.flags


def test_plural_selection_drives_the_form(reg: LocaleRegistry) -> None:
    """The plural category chooses the form, per locale (RX-27)."""
    nl = Translator("nl", registry_source=reg)
    assert nl.plural("count.runs", 1)[0] == "1 uitvoering"
    assert nl.plural("count.runs", 3)[0] == "3 uitvoeringen"
    pl = Translator("pl", registry_source=reg)
    assert pl.plural("count.runs", 1)[0] == "1 uruchomienie"
    assert pl.plural("count.runs", 3)[0] == "3 uruchomienia"
    assert pl.plural("count.runs", 5)[0] == "5 uruchomień"
    ja = Translator("ja", registry_source=reg)
    # Japanese declares a single plural category, so 1 and 7 must select the SAME
    # FORM - but the rendered strings still differ, because the count itself is
    # interpolated: the count appears inside the rendered string. Comparing text
    # therefore tested the interpolation, not the pluralisation. Compare the
    # selected category, and assert separately that the only difference in the
    # output is the number.
    assert select_plural("ja", 1) == select_plural("ja", 7)
    ja_one, ja_seven = ja.plural("count.runs", 1)[0], ja.plural("count.runs", 7)[0]
    assert ja_one != ja_seven, "the count is not interpolated at all"
    assert ja_one.replace("1", "#", 1) == ja_seven.replace("7", "#", 1), (
        f"ja singular/plural differ by more than the number: {ja_one!r} vs {ja_seven!r}"
    )


def test_a_plural_key_with_no_forms_falls_back_flagged(reg: LocaleRegistry) -> None:
    """Arabic has no plural forms yet; it falls back to English and says so (RX-27, RX-30)."""
    resolution = Translator("ar", registry_source=reg).resolve("count.runs", count=3)
    assert resolution.used_locale == "en"
    assert FLAG_PENDING in resolution.flags
    assert resolution.value == "{n} runs"


def test_placeholder_substitution_refuses_missing_values(reg: LocaleRegistry) -> None:
    translator = Translator("en", registry_source=reg)
    assert translator.text("validation.required", field="Project name")[0] == (
        "Project name is required."
    )
    with pytest.raises(KeyError, match="missing placeholder"):
        translator.text("validation.required")


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def test_negative_control_missing_key_is_detected_and_reported(reg: LocaleRegistry) -> None:
    """MANDATORY negative control: a missing key is DETECTED, not silently English.

    A catalogue short one key must (a) list it in ``missing_keys``, (b) flag the
    resolution ``missing-key`` and ``fallback-to-source``, and (c) raise under
    ``strict``. Silent unflagged fallback is the exact defect: the interface
    would look finished while a key had been lost in the build.
    """
    source = catalogue_from(
        "en",
        {"a.present": entry("Present"), "a.absent": entry("Absent")},
        review_status="source",
    )
    short = catalogue_from("nl", {"a.present": entry("Aanwezig")})
    translator = Translator(
        "nl", catalogue=short, source_catalogue=source, registry_source=reg
    )

    assert translator.missing_keys() == ("a.absent",)

    resolution = translator.resolve("a.absent")
    assert resolution.value == "Absent"
    assert resolution.used_locale == "en"
    assert resolution.is_missing_key
    assert resolution.is_source_fallback
    assert FLAG_MISSING_KEY in resolution.flags

    with pytest.raises(MissingKeyError):
        translator.resolve("a.absent", strict=True)

    # Discrimination: a key that IS present is not flagged missing.
    present = translator.resolve("a.present")
    assert not present.is_missing_key
    assert present.value == "Aanwezig"


def test_negative_control_key_absent_from_the_source_always_raises(
    reg: LocaleRegistry,
) -> None:
    """An unknown key is a programming error, never an empty string (RX-26)."""
    translator = Translator("nl", registry_source=reg)
    with pytest.raises(MissingKeyError):
        translator.resolve("nav.does_not_exist")


def test_negative_control_a_reviewed_catalogue_drops_the_beta_flag(
    reg: LocaleRegistry,
) -> None:
    """Discrimination for the beta gate: it is driven by data, not hardcoded (RX-30).

    A SYNTHETIC catalogue carrying a reviewer and a timestamp renders without
    ``beta``. Nothing in the repository has such a record - this proves the flag
    would disappear if one existed, so its presence on all 36 real catalogues is
    a measurement rather than a constant.
    """
    source = catalogue_from("en", {"a.key": entry("Value")}, review_status="source")
    reviewed = catalogue_from(
        "nl",
        {"a.key": entry("Waarde")},
        review_status="reviewed",
        reviewer="a named linguist",
        reviewed_at="2026-01-01T00:00:00Z",
    )
    translator = Translator(
        "nl", catalogue=reviewed, source_catalogue=source, registry_source=reg
    )
    _, flags = translator.text("a.key")
    assert FLAG_BETA not in flags
    assert FLAG_MACHINE_TRANSLATED in flags, (
        "machine provenance survives review of the string; only 'beta' lifts"
    )


def test_negative_control_review_status_label_alone_is_not_review(
    reg: LocaleRegistry,
) -> None:
    """A catalogue CLAIMING review without a reviewer is still unreviewed (RX-30)."""
    source = catalogue_from("en", {"a.key": entry("Value")}, review_status="source")
    claiming = catalogue_from(
        "nl", {"a.key": entry("Waarde")}, review_status="reviewed", reviewer=None
    )
    assert not claiming.is_reviewed
    translator = Translator(
        "nl", catalogue=claiming, source_catalogue=source, registry_source=reg
    )
    assert FLAG_BETA in translator.text("a.key")[1]


def test_negative_control_structurally_invalid_catalogues_are_refused() -> None:
    with pytest.raises(CatalogueError, match="locale"):
        Catalogue.from_mapping({"messages": {"a": {"value": "x"}}})
    with pytest.raises(CatalogueError, match="non-empty"):
        Catalogue.from_mapping({"locale": "nl", "messages": {}})
    with pytest.raises(CatalogueError, match="must be an object"):
        Catalogue.from_mapping({"locale": "nl", "messages": {"a": "just a string"}})
    with pytest.raises(CatalogueError, match="neither"):
        catalogue_from("nl", {"a.key": {"description": "no value and no forms"}})


def test_negative_control_plural_message_without_a_count_raises(reg: LocaleRegistry) -> None:
    translator = Translator("en", registry_source=reg)
    with pytest.raises(ValueError, match="needs a count"):
        translator.resolve("count.runs")


def test_negative_control_partial_plural_forms_are_reported_pending(
    reg: LocaleRegistry,
) -> None:
    """A Polish entry missing ``many`` is pending, not 'translated' (RX-27, RX-30)."""
    source = catalogue_from(
        "en", {"count.x": plural_entry({"one": "{n} x", "other": "{n} xs"})},
        review_status="source",
    )
    partial = catalogue_from(
        "pl",
        {"count.x": plural_entry({"one": "{n} x", "few": "{n} xy", "many": None,
                                  "other": "{n} xy"})},
    )
    translator = Translator(
        "pl", catalogue=partial, source_catalogue=source, registry_source=reg
    )
    assert translator.pending_keys() == ("count.x",)
    resolution = translator.resolve("count.x", count=5)
    assert resolution.used_locale == "en"
    assert FLAG_PENDING in resolution.flags and FLAG_FALLBACK in resolution.flags

"""The coverage report must be honest, and must be able to be unflattering (RX-26, RX-30)."""

from __future__ import annotations

import json
from pathlib import Path

from helpers import catalogue_from, entry
from retrace_i18n.catalogue import Catalogue
from retrace_i18n.coverage import build_report, locale_coverage, report_path, write_report
from retrace_i18n.registry import LocaleRegistry

REPORT = Path(__file__).resolve().parents[2] / "packages" / "i18n" / "COVERAGE.json"


def test_report_file_exists_and_parses() -> None:
    assert REPORT.is_file(), f"{REPORT} is not written; run tools/write_coverage.py"
    json.loads(REPORT.read_text(encoding="utf-8"))


def test_report_path_points_into_the_package() -> None:
    assert report_path() == REPORT


def test_committed_report_matches_a_fresh_measurement(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """A stale COVERAGE.json is worse than none: it reports yesterday's truth."""
    on_disk = json.loads(REPORT.read_text(encoding="utf-8"))
    fresh = build_report(source=reg, catalogues=catalogues)
    for field in ("source_locale", "source_key_count", "locale_count",
                  "reviewed_locale_count", "complete_locale_count", "totals"):
        assert on_disk[field] == fresh[field], field
    assert on_disk["locales"] == fresh["locales"]


def test_zero_of_thirty_six_locales_are_reviewed(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """MANDATORY: reviewed coverage is 0 of 36 because no review has happened (RX-30)."""
    report = build_report(source=reg, catalogues=catalogues)
    assert report["locale_count"] == 36
    assert report["reviewed_locale_count"] == 0
    assert report["reviewed_locales"] == []
    assert report["totals"]["reviewed_keys"] == 0
    for code, row in report["locales"].items():
        assert row["reviewed"] is False, code
        assert row["reviewed_keys"] == 0, code
        assert row["reviewed_coverage"] == 0.0, code


def test_no_locale_is_reported_complete(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """MANDATORY: nothing may be complete while review has not happened (RX-30).

    English included: it is the source, but it carries no review record either,
    so calling it complete would overstate the same thing.
    """
    report = build_report(source=reg, catalogues=catalogues)
    assert report["complete_locale_count"] == 0
    assert report["complete_locales"] == []
    for code, row in report["locales"].items():
        assert row["complete"] is False, code


def test_structural_and_translated_coverage_are_reported_separately(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """Full keys with null values must not read as coverage (RX-26, RX-30)."""
    report = build_report(source=reg, catalogues=catalogues)
    for code, row in report["locales"].items():
        assert row["structural_coverage"] == 1.0, code
        assert row["keys_missing"] == 0, code
        assert row["translated_keys"] + row["pending_keys"] == row["source_key_count"], code
        if code != "en":
            assert row["translated_coverage"] < 1.0, (
                f"{code} claims full translated coverage; no locale should today"
            )


def test_pending_keys_are_listed_not_just_counted(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """A reviewer needs to know WHICH keys are absent, not how many (RX-30)."""
    report = build_report(source=reg, catalogues=catalogues)
    for code, row in report["locales"].items():
        assert len(row["pending_key_list"]) == row["pending_keys"], code
        if code != "en":
            assert "outcome.reproduced_within_contract" in row["pending_key_list"], code


def test_the_mostly_pending_locales_are_reported_as_such(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """The deliberately untranslated locales show 0 translated keys, not a padded number."""
    report = build_report(source=reg, catalogues=catalogues)
    for code in ("ak", "ta", "te", "ur"):
        row = report["locales"][code]
        assert row["translated_keys"] == 0, code
        assert row["pending_keys"] == row["source_key_count"], code
        assert row["structural_coverage"] == 1.0, code


def test_report_records_the_spec_digest(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """The report pins which locale spec it measured against (RX-26)."""
    report = build_report(source=reg, catalogues=catalogues)
    assert report["spec"]["declared_locale_count"] == 36
    assert len(report["spec"]["sha256"]) == 64


def test_write_report_is_idempotent(tmp_path: Path, catalogues: dict[str, Catalogue],
                                    reg: LocaleRegistry) -> None:
    """Writing twice differs only in the timestamp (RX-26)."""
    first = json.loads(
        write_report(tmp_path / "a.json", source=reg, catalogues=catalogues)
        .read_text(encoding="utf-8")
    )
    second = json.loads(
        write_report(tmp_path / "b.json", source=reg, catalogues=catalogues)
        .read_text(encoding="utf-8")
    )
    first.pop("generated_at")
    second.pop("generated_at")
    assert first == second


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def test_negative_control_complete_can_be_true_for_a_synthetic_reviewed_locale(
    reg: LocaleRegistry,
) -> None:
    """MANDATORY discrimination control: ``complete`` is computed, not hardcoded False.

    A SYNTHETIC locale with every key translated AND a real review record is
    reported complete. Nothing in the repository looks like this. Without this
    control, ``complete: false`` on all 36 real locales could equally be produced
    by a checker that always returns False - which would be a check that cannot
    fail and therefore no evidence at all.
    """
    source = catalogue_from(
        "en", {"a.one": entry("One"), "a.two": entry("Two")}, review_status="source"
    )
    perfect = catalogue_from(
        "nl",
        {"a.one": entry("Een"), "a.two": entry("Twee")},
        review_status="reviewed",
        reviewer="a named linguist",
        reviewed_at="2026-01-01T00:00:00Z",
    )
    # `reviewed` is `catalogue.is_reviewed AND locale.is_reviewed`, and a Locale is
    # reviewed only when it names BOTH a reviewer and a timestamp. Passing the real
    # registry made the True branch unreachable, so this control could never fire -
    # which is precisely the failure mode it exists to rule out. Synthesise the
    # registry as well, so the branch is genuinely exercised.
    reviewed_registry = LocaleRegistry.from_spec(
        {
            "source_locale": "en",
            "locales": [
                {"code": "en", "name": "English", "endonym": "English", "script": "Latn",
                 "direction": "ltr", "plural_categories": ["one", "other"],
                 "review_status": "source", "reviewer": None, "reviewed_at": None},
                {"code": "nl", "name": "Dutch", "endonym": "Nederlands", "script": "Latn",
                 "direction": "ltr", "plural_categories": ["one", "other"],
                 "review_status": "reviewed", "reviewer": "a named linguist",
                 "reviewed_at": "2026-01-01T00:00:00Z"},
            ],
        }
    )
    row = locale_coverage(
        "nl",
        catalogues={"en": source, "nl": perfect},
        source=reviewed_registry,
    )
    assert row["reviewed"] is True
    assert row["translated_keys"] == 2
    assert row["pending_keys"] == 0
    assert row["structural_coverage"] == 1.0
    assert row["reviewed_coverage"] == 1.0
    assert row["complete"] is True


def test_negative_control_full_keys_without_review_is_not_complete(
    reg: LocaleRegistry,
) -> None:
    """Translated everything, reviewed nothing: still not complete (RX-30)."""
    source = catalogue_from("en", {"a.one": entry("One")}, review_status="source")
    translated = catalogue_from("nl", {"a.one": entry("Een")})
    row = locale_coverage("nl", catalogues={"en": source, "nl": translated}, source=reg)
    assert row["translated_coverage"] == 1.0
    assert row["reviewed"] is False
    assert row["complete"] is False


def test_negative_control_a_missing_key_shows_in_structural_coverage(
    reg: LocaleRegistry,
) -> None:
    """A dropped key lowers structural coverage and is named (RX-26)."""
    source = catalogue_from(
        "en", {"a.one": entry("One"), "a.two": entry("Two")}, review_status="source"
    )
    short = catalogue_from("nl", {"a.one": entry("Een")})
    row = locale_coverage("nl", catalogues={"en": source, "nl": short}, source=reg)
    assert row["keys_missing"] == 1
    assert row["missing_keys"] == ["a.two"]
    assert row["structural_coverage"] == 0.5
    assert row["complete"] is False


def test_negative_control_an_empty_string_counts_as_pending(reg: LocaleRegistry) -> None:
    """Padding coverage with an empty string does not work (RX-30)."""
    source = catalogue_from("en", {"a.one": entry("One")}, review_status="source")
    padded = catalogue_from("nl", {"a.one": entry("", status="translated")})
    row = locale_coverage("nl", catalogues={"en": source, "nl": padded}, source=reg)
    assert row["pending_keys"] == 1
    assert row["translated_keys"] == 0

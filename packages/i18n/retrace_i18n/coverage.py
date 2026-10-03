"""Coverage report - the file whose value is that it is unflattering (RX-26, RX-30).

Writes ``packages/i18n/COVERAGE.json``. Three numbers per locale, deliberately
kept apart because conflating them is how localisation gets reported as done:

1. STRUCTURAL coverage - does the catalogue have every key the source has? A
   missing key is a build defect; it is listed, not averaged away.
2. TRANSLATED coverage - how many of those keys carry a real string rather than
   ``null`` + ``pending``. Nulls are the honest record of absent confidence and
   are counted as absent, never padded.
3. REVIEWED coverage - how many keys have passed HUMAN LINGUISTIC REVIEW. This
   is 0 for every locale, because no review has happened. It is reported
   separately precisely so that high translated coverage cannot be read as
   review (RX-30).

``complete`` requires structural coverage of 1.0, zero pending keys AND a review
record. Nothing is complete today and the report says so. The computation is not
hardcoded to ``False``: the negative control in ``tests/i18n`` feeds it a
synthetic fully-translated, reviewed locale and asserts it reports ``True``, so a
``complete: false`` here is a measurement rather than a constant.

Run it with
``env -u PYTHONPATH ./.venv/bin/python packages/i18n/tools/write_coverage.py``
(a thin runner, because PYTHONPATH must stay cleared on this workstation).
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .catalogue import Catalogue, Translator, catalogue_dir, load_catalogues
from .registry import LocaleRegistry, registry

__all__ = [
    "REPORT_FILENAME",
    "build_report",
    "locale_coverage",
    "main",
    "report_path",
    "write_report",
]

REPORT_FILENAME = "COVERAGE.json"

_COMPLETENESS_RULE = (
    "complete = (structural_coverage == 1.0) AND (pending_keys == 0) AND reviewed. "
    "'reviewed' requires a named reviewer AND a review timestamp in the catalogue, not a "
    "review_status label. No locale satisfies this today (RX-30)."
)


def report_path() -> Path:
    """Where the report is written (RX-26)."""
    return catalogue_dir().parent / REPORT_FILENAME


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def locale_coverage(
    code: str,
    *,
    catalogues: Mapping[str, Catalogue],
    source: LocaleRegistry,
) -> dict[str, Any]:
    """Measure one locale against the source catalogue (RX-26, RX-30)."""
    translator = Translator(
        code,
        catalogue=catalogues[code],
        source_catalogue=catalogues[source.source_locale],
        registry_source=source,
    )
    locale = translator.locale
    catalogue = translator.catalogue
    source_keys = translator.source.keys
    total = len(source_keys)
    missing = translator.missing_keys()
    extra = translator.extra_keys()
    pending = translator.pending_keys()
    present = total - len(missing)
    translated = present - len(pending)
    reviewed = catalogue.is_reviewed and locale.is_reviewed
    reviewed_keys = translated if reviewed else 0
    return {
        "name": locale.name,
        "endonym": locale.endonym,
        "script": locale.script,
        "direction": locale.direction,
        "plural_categories": list(locale.plural_categories),
        "is_source": code == source.source_locale,
        "source_key_count": total,
        "keys_present": present,
        "keys_missing": len(missing),
        "missing_keys": list(missing),
        "extra_keys": list(extra),
        "translated_keys": translated,
        "pending_keys": len(pending),
        "pending_key_list": list(pending),
        "structural_coverage": round(present / total, 4) if total else 0.0,
        "translated_coverage": round(translated / total, 4) if total else 0.0,
        "reviewed_keys": reviewed_keys,
        "reviewed_coverage": round(reviewed_keys / total, 4) if total else 0.0,
        "review_status": catalogue.review_status,
        "reviewer": catalogue.reviewer,
        "reviewed_at": catalogue.reviewed_at,
        "reviewed": reviewed,
        "number_format_declared": catalogue.number_format is not None,
        "complete": bool(
            not missing and not pending and reviewed and total > 0
        ),
    }


def build_report(
    *,
    source: LocaleRegistry | None = None,
    catalogues: Mapping[str, Catalogue] | None = None,
) -> dict[str, Any]:
    """Build the whole coverage report (RX-26, RX-30)."""
    reg = source or registry()
    loaded = dict(catalogues) if catalogues is not None else load_catalogues(source=reg)
    per_locale = {
        code: locale_coverage(code, catalogues=loaded, source=reg) for code in reg.codes
    }
    reviewed = [code for code, row in per_locale.items() if row["reviewed"]]
    complete = [code for code, row in per_locale.items() if row["complete"]]
    source_row = per_locale[reg.source_locale]
    spec = reg.spec_path
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "spec": {
            "path": "specs/locales.json",
            "sha256": _sha256(spec) if spec and spec.is_file() else None,
            "declared_locale_count": len(reg),
        },
        "source_locale": reg.source_locale,
        "source_key_count": source_row["source_key_count"],
        "locale_count": len(reg),
        "reviewed_locale_count": len(reviewed),
        "reviewed_locales": reviewed,
        "complete_locale_count": len(complete),
        "complete_locales": complete,
        "completeness_rule": _COMPLETENESS_RULE,
        "totals": {
            "translated_keys": sum(r["translated_keys"] for r in per_locale.values()),
            "pending_keys": sum(r["pending_keys"] for r in per_locale.values()),
            "missing_keys": sum(r["keys_missing"] for r in per_locale.values()),
            "reviewed_keys": sum(r["reviewed_keys"] for r in per_locale.values()),
        },
        "locales": per_locale,
    }


def write_report(path: Path | None = None, **kwargs: Any) -> Path:
    """Write the report as formatted JSON and return its path (RX-26)."""
    target = path or report_path()
    report = build_report(**kwargs)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    """Write the report and print the headline numbers (RX-26, RX-30)."""
    del argv
    target = write_report()
    report = json.loads(target.read_text(encoding="utf-8"))
    total = report["locale_count"]
    print(f"wrote {target}")
    print(f"locales: {total}  keys in source: {report['source_key_count']}")
    print(f"reviewed: {report['reviewed_locale_count']}/{total}")
    print(f"complete: {report['complete_locale_count']}/{total}")
    print(f"pending values across all locales: {report['totals']['pending_keys']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Scaffold and re-merge the non-source catalogues (RX-26, RX-30).

The JSON catalogues are the record. This tool exists so that adding a key to
``en.json`` cannot silently leave 35 catalogues structurally short: it walks the
registry, and for each non-source locale

* adds any key the source has and the catalogue lacks, as ``value: null`` with
  ``status: "pending"`` and ``machine_generated: true``;
* adds any plural category the locale DECLARES and the entry lacks, as ``null``;
* copies the translator ``description`` from the source so the translator sees it
  next to the string;
* removes keys the source no longer has;
* NEVER overwrites, invents, machine-fills or "improves" an existing non-null
  string, and never sets ``reviewer`` or ``reviewed_at``. Lifting ``beta``
  requires a human linguist (RX-30), which no tool can stand in for.

Run: ``env -u PYTHONPATH ./.venv/bin/python packages/i18n/tools/build_catalogues.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from retrace_i18n.registry import registry  # noqa: E402

CATALOGUES = PACKAGE_ROOT / "catalogues"

_NOTES = (
    "MACHINE-GENERATED, UNREVIEWED (RX-30). review_status is 'beta' and reviewer is null: no "
    "human linguistic review has happened, so every string here renders the beta and "
    "machine-translated truthfulness chips. A null value with status 'pending' is the honest "
    "record that no confident translation exists for that key; it is counted as absent by "
    "packages/i18n/COVERAGE.json and must not be filled with a plausible-looking guess. Text "
    "between the U+2772 and U+2773 markers is a PROTECTED SPAN (RX-29) and must be re-emitted "
    "byte-identically - do not translate, transliterate, case-fold or reorder it."
)


def _entry_skeleton(source_entry: dict[str, Any], categories: tuple[str, ...]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    if "forms" in source_entry:
        entry["forms"] = dict.fromkeys(categories)
    else:
        entry["value"] = None
    entry["description"] = source_entry.get("description", "")
    entry["machine_generated"] = True
    entry["status"] = "pending"
    return entry


def merge(code: str, source_messages: dict[str, Any], categories: tuple[str, ...]) -> bool:
    """Scaffold or re-merge one catalogue. Returns whether the file changed."""
    path = CATALOGUES / f"{code}.json"
    existing: dict[str, Any] = {}
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
    messages: dict[str, Any] = dict(existing.get("messages", {}))

    merged: dict[str, Any] = {}
    for key, source_entry in source_messages.items():
        current = messages.get(key)
        skeleton = _entry_skeleton(source_entry, categories)
        if not isinstance(current, dict):
            merged[key] = skeleton
            continue
        entry = dict(skeleton)
        if "forms" in skeleton:
            forms = dict(skeleton["forms"])
            for category in categories:
                value = (current.get("forms") or {}).get(category)
                if isinstance(value, str) and value:
                    forms[category] = value
            entry["forms"] = forms
            entry["status"] = (
                "translated" if any(isinstance(v, str) and v for v in forms.values()) else "pending"
            )
        else:
            value = current.get("value")
            if isinstance(value, str) and value:
                entry["value"] = value
                entry["status"] = "translated"
        merged[key] = entry

    document = {
        "locale": code,
        "review_status": "beta",
        "reviewer": None,
        "reviewed_at": None,
        "notes": _NOTES,
        **({"formats": existing["formats"]} if "formats" in existing else {}),
        "messages": merged,
    }
    rendered = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == rendered:
        return False
    path.write_text(rendered, encoding="utf-8")
    return True


def main() -> int:
    reg = registry()
    source = json.loads((CATALOGUES / f"{reg.source_locale}.json").read_text(encoding="utf-8"))
    source_messages = source["messages"]
    changed = 0
    for locale in reg:
        if locale.code == reg.source_locale:
            continue
        if merge(locale.code, source_messages, locale.plural_categories):
            changed += 1
    print(f"source keys: {len(source_messages)}")
    print(f"catalogues written or updated: {changed} of {len(reg) - 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

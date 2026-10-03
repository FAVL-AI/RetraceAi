"""Synthetic-data builders for the localisation negative controls (RX-26 .. RX-30).

Kept in a named module rather than in ``conftest.py`` so that every call site
reads as ``helpers.synthetic_registry(...)`` - making it obvious in the test
body that the data is fabricated for a control and is not repository state.

Nothing here edits a real file. ``specs/locales.json`` and the catalogues are
read-only to this worker; these builders copy parsed data in memory.
"""

from __future__ import annotations

import json
from typing import Any

from retrace_i18n.catalogue import Catalogue
from retrace_i18n.registry import LocaleRegistry


def synthetic_registry(reg: LocaleRegistry, **overrides: dict[str, Any]) -> LocaleRegistry:
    """A registry built from the real spec with named per-locale overrides.

    Used by controls that need a locale declaring the WRONG plural categories,
    or re-tagged, without touching the spec file.
    """
    assert reg.spec_path is not None, "the real registry must know its spec path"
    spec = json.loads(reg.spec_path.read_text(encoding="utf-8"))
    for entry in spec["locales"]:
        patch = overrides.get(entry["code"])
        if patch:
            entry.update(patch)
    return LocaleRegistry.from_spec(spec)


def catalogue_from(code: str, messages: dict[str, Any], **kwargs: Any) -> Catalogue:
    """Build an in-memory catalogue for a negative control (RX-26)."""
    document: dict[str, Any] = {
        "locale": code,
        "review_status": kwargs.pop("review_status", "beta"),
        "reviewer": kwargs.pop("reviewer", None),
        "reviewed_at": kwargs.pop("reviewed_at", None),
        "messages": messages,
        **kwargs,
    }
    return Catalogue.from_mapping(document)


def entry(value: str | None, *, status: str | None = None) -> dict[str, Any]:
    """A singular catalogue entry, defaulting ``status`` from ``value`` (RX-30)."""
    return {
        "value": value,
        "description": "synthetic fixture",
        "machine_generated": True,
        "status": status or ("translated" if value else "pending"),
    }


def plural_entry(forms: dict[str, str | None], *, status: str = "translated") -> dict[str, Any]:
    """A plural catalogue entry for a control (RX-27)."""
    return {
        "forms": forms,
        "description": "synthetic fixture",
        "machine_generated": True,
        "status": status,
    }

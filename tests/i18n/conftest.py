"""Shared fixtures for the localisation suite (RX-26 .. RX-31).

Every fixture reads real repository state. Nothing here fabricates a catalogue
or a locale list. Synthetic and hostile data for the negative controls lives in
``tests/i18n/helpers.py`` instead, so a fabricated fixture is always visible as
``helpers.<builder>`` at the call site.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from retrace_i18n.catalogue import Catalogue, load_catalogues
from retrace_i18n.registry import LocaleRegistry, registry

REPO = Path(__file__).resolve().parents[2]
CATALOGUE_DIR = REPO / "packages" / "i18n" / "catalogues"
UX_DOC = REPO / "docs" / "UX.md"

#: docs/UX.md verification-state table row: | `MEMBER` | `--token` | `#hex` | "Label" |
_UX_OUTCOME_ROW = re.compile(r"^\|\s*`([A-Z_]+)`\s*\|[^|]*\|[^|]*\|\s*\"([^\"]+)\"\s*\|\s*$")


@pytest.fixture(scope="session")
def reg() -> LocaleRegistry:
    """The real locale registry from specs/locales.json (RX-26)."""
    return registry()


@pytest.fixture(scope="session")
def catalogues(reg: LocaleRegistry) -> dict[str, Catalogue]:
    """Every catalogue the registry declares (RX-26)."""
    return load_catalogues(source=reg)


@pytest.fixture(scope="session")
def raw_catalogues(reg: LocaleRegistry) -> dict[str, dict[str, Any]]:
    """Unparsed catalogue JSON, for assertions about the files themselves."""
    return {
        code: json.loads((CATALOGUE_DIR / f"{code}.json").read_text(encoding="utf-8"))
        for code in reg.codes
    }


@pytest.fixture(scope="session")
def ux_outcome_labels() -> dict[str, str]:
    """The five outcome labels parsed from docs/UX.md - the authority (RX-25).

    Parsed rather than copied: a copy in the test would drift from the document
    and the test would then prove only that two copies agree.
    """
    labels: dict[str, str] = {}
    for line in UX_DOC.read_text(encoding="utf-8").splitlines():
        match = _UX_OUTCOME_ROW.match(line)
        if match:
            labels[match.group(1)] = match.group(2)
    assert len(labels) == 5, (
        f"expected 5 outcome rows in {UX_DOC}, parsed {sorted(labels)}. The parser, not the "
        "expectation, is what to fix if the table changed shape."
    )
    return labels

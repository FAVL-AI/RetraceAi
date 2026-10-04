"""Shared fixtures for the domain test suite.

Import path: ``pyproject.toml`` already lists ``packages/domain`` in
``tool.pytest.ini_options.pythonpath``, so ``retrace_domain`` and
``retrace_contracts`` both import normally. Nothing here touches ``sys.path``.

Fixture content is SYNTHETIC and authored in this repository. It is not
derived from, and establishes nothing about, any published dataset. Every
fault in a fixture is an *injected* fault (RX-56): it is labelled as such in
the fixture text, so no third-party software is implied to be defective.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from retrace_contracts import Approval
from retrace_domain import ContentAddressedStore, SnapshotManifest, snapshot_create, store_reader

APPROVER = "Frank Asante Van Laarhoven"

T0 = datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 2, 9, 5, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 2, 9, 10, 0, tzinfo=UTC)


def digest(seed: str) -> str:
    """Return a real lowercase hex SHA-256 for ``seed``.

    Fixtures use genuine digests rather than ``'a' * 64`` so that every hash in
    a test is a value something could actually have produced.
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# SYNTHETIC analysis fixtures. Each injected fault is declared in the source
# itself (RX-56); none of them describes a defect in any real package.
# ---------------------------------------------------------------------------

SEMICOLON_CSV = (
    "specimen_id;mass_g;flipper_mm;site\n"
    "S-001;3750;181;site-a\n"
    "S-002;3800;186;site-a\n"
    "S-003;3250;195;site-b\n"
    "S-004;3300;193;site-b\n"
)

COMMA_CSV = (
    "specimen_id,mass_g,flipper_mm,site\n"
    "S-001,3750,181,site-a\n"
    "S-002,3800,186,site-a\n"
    "S-003,3250,195,site-b\n"
    "S-004,3300,193,site-b\n"
)

WRONG_PATH_SOURCE = '''"""SYNTHETIC fixture. Injected fault: the input path is wrong.

injected: true -- the real file lives at inputs/data/measurements.csv.
"""
import pandas as pd


def load():
    return pd.read_csv("data/measurements.csv", sep=";")


def mean_mass(frame):
    return float(frame["mass_g"].mean())
'''

WRONG_DELIMITER_SOURCE = '''"""SYNTHETIC fixture. Injected fault: the declared delimiter is wrong.

injected: true -- the stored file is semicolon-delimited.
"""
import pandas as pd


def load():
    return pd.read_csv("inputs/data/measurements.csv", sep=",")


def mean_mass(frame):
    return float(frame["mass_g"].mean())
'''

NO_DELIMITER_SOURCE = '''"""SYNTHETIC fixture. Injected fault: no delimiter is declared at all.

injected: true -- the stored file is semicolon-delimited.
"""
import pandas as pd


def load():
    return pd.read_csv("inputs/data/measurements.csv")


def mean_mass(frame):
    return float(frame["mass_g"].mean())
'''


def write_tree(root: Path, files: Mapping[str, str]) -> Path:
    """Write ``{relative path -> text}`` under ``root`` and return ``root``."""
    for relative, text in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def corrupt_blob(store: ContentAddressedStore, target_digest: str, payload: bytes) -> Path:
    """Overwrite a stored blob's bytes in place, defeating its read-only mode.

    This is the hostile act the store must detect (RX-02). It is written here,
    once, so that every tamper test performs the *same* tamper and a test that
    "passes" because it failed to corrupt anything is not possible.
    """
    path = store.path_for(target_digest)
    os.chmod(path, 0o644)
    path.write_bytes(payload)
    assert path.read_bytes() == payload, "the tamper itself failed; the test would be vacuous"
    return path


@pytest.fixture
def store(tmp_path: Path) -> ContentAddressedStore:
    """A fresh content-addressed store under the test's temporary directory."""
    return ContentAddressedStore(tmp_path / "store")


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    """A SYNTHETIC source tree carrying the wrong-input-path injected fault."""
    return write_tree(
        tmp_path / "source",
        {
            "analysis/load.py": WRONG_PATH_SOURCE,
            "inputs/data/measurements.csv": SEMICOLON_CSV,
            "notes/README.md": "SYNTHETIC fixture tree.\n",
        },
    )


@pytest.fixture
def snapshot(
    store: ContentAddressedStore, source_tree: Path
) -> tuple[SnapshotManifest, Callable[[str], bytes]]:
    """A manifest of :func:`source_tree` plus a verifying reader over it."""
    manifest = snapshot_create(store, source_tree)
    return manifest, store_reader(store, manifest)


def build_approval(**overrides: Any) -> Approval:
    """Build an Approval binding the five required fields (RX-05)."""
    fields: dict[str, Any] = {
        "approval_id": "ap-0001",
        "contract_hash": digest("contract"),
        "candidate_hash": digest("candidate"),
        "input_snapshot_id": "snap-0001",
        "environment_policy_digest": digest("env-policy"),
        "action_digest": digest("action-accept-candidate"),
        "approved_by": APPROVER,
        "approved_at": T0,
    }
    fields.update(overrides)
    return Approval(**fields)


@pytest.fixture
def approval_factory() -> Callable[..., Approval]:
    """Factory for approval records."""
    return build_approval

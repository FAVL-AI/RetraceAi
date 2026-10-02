"""Shared fixtures for the contracts test suite.

Import path note
----------------
``pyproject.toml`` sets ``pythonpath = ["packages", "services"]``, which does not
cover ``packages/contracts`` where this package lives. ``pyproject.toml`` is
outside this worker's ownership, so the path is bridged here instead. The
integrator should add ``packages/contracts`` to ``tool.pytest.ini_options
.pythonpath`` (and to the setuptools package discovery roots) so that other
packages can import ``retrace_contracts`` without their own bridge.

"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CONTRACTS_ROOT = Path(__file__).resolve().parents[2] / "packages" / "contracts"
if str(_CONTRACTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS_ROOT))

import pytest  # noqa: E402
from retrace_contracts import (  # noqa: E402
    Approval,
    Attestation,
    CheckResult,
    CheckStatus,
    ComparisonSpec,
    EnvironmentManifest,
    EvidenceBundleManifest,
    ExclusionRule,
    ExecutionStatus,
    OutputDefinition,
    OutputKind,
    Population,
    ReferenceInput,
    RepairProposal,
    ResourceRef,
    ResultContract,
    RunRecord,
    SplitSpec,
    Tolerance,
    UIAllowlists,
    UIComponent,
    UIPlan,
    VerificationOutcome,
    VerificationReport,
)

AUTHOR = "Frank Asante Van Laarhoven"
T0 = datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 2, 9, 5, 0, tzinfo=UTC)
T2 = datetime(2026, 10, 2, 9, 10, 0, tzinfo=UTC)

VALID_DIFF = """--- a/analysis/clean.py
+++ b/analysis/clean.py
@@ -10,7 +10,7 @@ def clean(frame):
-    frame = frame.dropna()
+    frame = frame.dropna(subset=["mass_g"])
"""


def digest(seed: str) -> str:
    """Return a real lowercase hex SHA-256 for ``seed``.

    Tests use genuine digests rather than ``'a' * 64`` so that a digest in a
    fixture is a value something could actually have produced.
    """
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_contract(**overrides: Any) -> ResultContract:
    """Build a minimal but complete, internally consistent ResultContract (RX-03)."""
    fields: dict[str, Any] = {
        "reference_inputs": (
            ReferenceInput(
                path="data/penguins_synthetic.csv",
                sha256=digest("reference-input"),
                role="raw-measurements",
            ),
        ),
        "output_definitions": (
            OutputDefinition(
                name="mean_body_mass", kind=OutputKind.SCALAR, unit="g", dtype="float64"
            ),
            OutputDefinition(name="summary_note", kind=OutputKind.TEXT),
        ),
        "population": Population(
            expected_count=333, selection_rule="rows with no missing measurement column"
        ),
        "units": {"mean_body_mass": "g"},
        "exclusions": (
            ExclusionRule(
                rule_id="excl.incomplete-rows",
                description="rows missing any measurement column are excluded",
                expression="notna(all_measurement_columns)",
            ),
        ),
        "seed": 20261002,
        "split": SplitSpec(strategy="stratified-by-species", train_fraction=0.8, seed=20261002),
        "comparison": ComparisonSpec(
            algorithm="elementwise-abs-rel",
            tolerances={"mean_body_mass": Tolerance(abs_tol=1e-6, rel_tol=1e-9)},
        ),
        "required_checks": ("chk.population-count", "chk.mean-body-mass"),
        "known_limits": (
            "SYNTHETIC fixture data; establishes nothing about any published dataset.",
            "Single-machine execution; no cross-platform numerical agreement claimed.",
        ),
        "contract_version": 1,
        "created_by": AUTHOR,
    }
    fields.update(overrides)
    return ResultContract(**fields)


def build_approval(contract_hash: str | None = None, **overrides: Any) -> Approval:
    """Build an Approval binding the five required fields (RX-05)."""
    fields: dict[str, Any] = {
        "approval_id": "ap-0001",
        "contract_hash": contract_hash or digest("contract"),
        "candidate_hash": digest("candidate"),
        "input_snapshot_id": "snap-0001",
        "environment_policy_digest": digest("env-policy"),
        "action_digest": digest("action-accept-candidate"),
        "approved_by": AUTHOR,
        "approved_at": T0,
    }
    fields.update(overrides)
    return Approval(**fields)


def build_run_record(**overrides: Any) -> RunRecord:
    """Build a RunRecord with no model used (RX-33 all-None pinning)."""
    fields: dict[str, Any] = {
        "run_id": "run-0001",
        "snapshot_id": "snap-0001",
        "runner_identity": "retrace-runner",
        "environment_policy_digest": digest("env-policy"),
        "execution_status": ExecutionStatus.SUCCEEDED,
        "started_at": T0,
        "finished_at": T1,
        "exit_code": 0,
        "wall_clock_seconds": 300.0,
        "peak_memory_bytes": 268_435_456,
    }
    fields.update(overrides)
    return RunRecord(**fields)


def build_check(**overrides: Any) -> CheckResult:
    """Build a PASSED CheckResult."""
    fields: dict[str, Any] = {
        "check_id": "chk.mean-body-mass",
        "status": CheckStatus.PASSED,
        "summary": "mean body mass within declared tolerance",
        "output_name": "mean_body_mass",
        "expected": "4207.057057",
        "observed": "4207.057057",
        "abs_diff": 0.0,
        "rel_diff": 0.0,
        "unit_expected": "g",
        "unit_observed": "g",
    }
    fields.update(overrides)
    return CheckResult(**fields)


def build_report(**overrides: Any) -> VerificationReport:
    """Build a REPRODUCED_WITHIN_CONTRACT report that satisfies every invariant."""
    fields: dict[str, Any] = {
        "report_id": "rep-0001",
        "contract_hash": digest("contract"),
        "outcome": VerificationOutcome.REPRODUCED_WITHIN_CONTRACT,
        "reason": "all declared checks passed within tolerance; no methodology delta",
        "checks": (build_check(),),
        "run_record": build_run_record(),
        "verifier_identity": "retrace-verifier",
        "verified_at": T2,
        "independently_recomputed": True,
    }
    fields.update(overrides)
    return VerificationReport(**fields)


def build_proposal(**overrides: Any) -> RepairProposal:
    """Build a RepairProposal carrying a unified diff (RX-06)."""
    fields: dict[str, Any] = {
        "proposal_id": "prop-0001",
        "snapshot_id": "snap-0001",
        "target_path": "analysis/clean.py",
        "unified_diff": VALID_DIFF,
        "candidate_hash": digest("candidate"),
        "rationale": "restore the declared exclusion rule dropped by the regression",
        "provider": "deterministic-local",
    }
    fields.update(overrides)
    return RepairProposal(**fields)


def build_bundle(**overrides: Any) -> EvidenceBundleManifest:
    """Build an EvidenceBundleManifest with a non-empty limitations section (RX-15)."""
    fields: dict[str, Any] = {
        "bundle_id": "bundle-0001",
        "created_at": T2,
        "created_by": AUTHOR,
        "contract_hash": digest("contract"),
        "snapshot_ref": ResourceRef(
            ref_id="snapshot",
            path="snapshot/manifest.json",
            sha256=digest("snapshot"),
            role="snapshot",
            media_type="application/json",
            bytes_count=2048,
        ),
        "patch_ref": ResourceRef(
            ref_id="patch",
            path="patch/0001-restore-exclusion.diff",
            sha256=digest("patch"),
            role="patch",
            media_type="text/x-diff",
        ),
        "environment_manifest": EnvironmentManifest(
            python_version="3.11.9",
            platform="Linux-6.8.0-x86_64",
            packages={"pydantic": "2.9.2"},
            policy_digest=digest("env-policy"),
            captured_at=T0,
        ),
        "logs_refs": (
            ResourceRef(
                ref_id="runner-log",
                path="logs/runner.jsonl",
                sha256=digest("runner-log"),
                role="runner-log",
            ),
        ),
        "check_results": (build_check(),),
        "outcome": VerificationOutcome.REPRODUCED_WITHIN_CONTRACT,
        "limitations": (
            "SYNTHETIC fixture data; no claim about any published dataset.",
            "Attestation is an unsigned declaration, not a certification.",
        ),
        "attestation": Attestation(
            attested_by=AUTHOR,
            attested_at=T2,
            statement="the recorded checks were executed and recomputed by the verifier",
            non_certification_statement=(
                "This bundle is readiness evidence. It is not a certification, "
                "accreditation or third-party audit."
            ),
        ),
    }
    fields.update(overrides)
    return EvidenceBundleManifest(**fields)


def build_component(**overrides: Any) -> UIComponent:
    """Build an allowlisted UIComponent."""
    fields: dict[str, Any] = {
        "component_id": "cmp-table",
        "component_type": "evidence-table",
        "region_id": "main",
        "query_id": "q.run-checks",
        "title": "Declared checks",
    }
    fields.update(overrides)
    return UIComponent(**fields)


def protected_components() -> tuple[UIComponent, ...]:
    """Return one visible component per protected region (RX-23)."""
    return (
        UIComponent(
            component_id="cmp-security",
            component_type="security-banner",
            region_id="security-context",
            title="Tenant and scope",
        ),
        UIComponent(
            component_id="cmp-approval",
            component_type="approval-panel",
            region_id="approval-controls",
            title="Approval",
            action_id="a.request-approval",
        ),
        UIComponent(
            component_id="cmp-truth",
            component_type="truthfulness-label",
            region_id="truthfulness-labels",
            title="Evidence state",
        ),
    )


def build_plan(**overrides: Any) -> UIPlan:
    """Build a UIPlan that renders every protected region (RX-22, RX-23)."""
    fields: dict[str, Any] = {
        "plan_id": "plan-0001",
        "title": "Run review workspace",
        "created_by": AUTHOR,
        "components": (build_component(), *protected_components()),
        "source_prompt": "show the declared checks beside the approval controls",
    }
    fields.update(overrides)
    return UIPlan(**fields)


ALLOWLISTS = UIAllowlists(
    components=frozenset(
        {
            "evidence-table",
            "security-banner",
            "approval-panel",
            "truthfulness-label",
            "panel",
            "lineage-graph",
        }
    ),
    query_ids=frozenset({"q.run-checks", "q.lineage"}),
    action_ids=frozenset({"a.request-approval", "a.export-bundle"}),
)


@pytest.fixture
def contract_factory() -> Callable[..., ResultContract]:
    """Factory for internally consistent result contracts."""
    return build_contract


@pytest.fixture
def approval_factory() -> Callable[..., Approval]:
    """Factory for approval records."""
    return build_approval


@pytest.fixture
def allowlists() -> UIAllowlists:
    """The server-side UI policy used across the UI plan tests."""
    return ALLOWLISTS

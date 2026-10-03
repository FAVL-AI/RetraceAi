"""The scientific triad, end to end (RX-01..RX-18, RX-52, RX-56, RX-57).

Three outcomes must be reachable and must be reached for the right reasons:

1. a legitimate repair reproduces **within the approved contract**;
2. a result-changing repair does **not** receive reproduced status;
3. missing evidence stays **blocked**, never inferred into a pass.

Plus the authority properties that make those outcomes trustworthy: the repair
worker cannot reach the contract, the references, the approval ledger or the
verifier, and changing an approved candidate invalidates its approval.

Every fault here is INJECTED BY THIS FILE and labelled as such (RX-56). Nothing
is attributed to any third party's software, and the fixtures are SYNTHETIC -
they establish that the mechanism works, not anything about real data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from retrace_contracts import (
    Approval,
    ApprovalInvalidated,
    ContractNotApproved,
    ExecutionStatus,
    ReferenceKind,
    RunRecord,
    VerificationOutcome,
)
from retrace_domain import (
    PROTECTED_PREFIXES,
    AbstentionReason,
    ApprovalLedger,
    ContentAddressedStore,
    DeterministicRepairProvider,
    Diagnosis,
    FaultClass,
    RepairAuthority,
    WriteRefused,
    snapshot_create,
    snapshot_materialise,
    store_reader,
)
from retrace_runner import ExecutionLimits, run_notebook
from retrace_verifier import FilesystemReferenceReader, verify

if TYPE_CHECKING:  # pragma: no cover - annotation only
    from .conftest import ReferenceStore

#: A fixed, timezone-aware instant. Nothing here reads the clock, so every
#: digest and record in this file is reproducible. Defined locally rather than
#: imported, because tests/exec is not a package and a runtime relative import
#: of conftest fails (while a bare `from conftest import ...` would collide
#: with the other suites' conftest basenames under pytest's prepend mode).
#: `make_contract` is reached through the `contract_factory` fixture instead.
FIXED_MOMENT = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

# --------------------------------------------------------------------------- #
# The synthetic analysis. Three masses in grams; the mean is exactly 3800.0 g,
# so a correct run lands inside any sane tolerance and a changed method does not.
# --------------------------------------------------------------------------- #
MASSES = (3700.0, 3800.0, 3900.0)
EXPECTED_MEAN = 3800.0
CSV_BODY = "id,mass_g\n" + "".join(f"{i},{m}\n" for i, m in enumerate(MASSES, start=1))

#: The INJECTED fault: the notebook reads a path that does not exist in the
#: snapshot, while the real file sits at ``inputs/measurements.csv``.
WRONG_PATH = "data/measurements.csv"
REAL_PATH = "inputs/measurements.csv"

#: Must match the contract the fixture approves, or the run is a reanalysis.
SEED = 20260301
RULE = "complete cases only"

NOTEBOOK_NAME = "analysis.ipynb"

nbformat = pytest.importorskip("nbformat", reason="the runner needs real notebooks")


def notebook_json(source: str) -> str:
    """Serialise one code cell as a real ``.ipynb`` document.

    The repair provider patches this TEXT, which is the honest test: a real
    notebook is JSON, so a provider that can only patch bare Python would not
    help anybody. nbformat writes each source line as its own array element, so
    the wrong path sits on a line of its own and the diff stays reviewable.
    """
    return nbformat.writes(
        nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(source)])
    )


#: A generous wall clock: these tests are about the scientific outcome, not timing.
RUN_LIMITS = ExecutionLimits(wall_clock_seconds=180.0)

NOTEBOOK_SOURCE = f"""\
import csv, json, statistics
# INJECTED FAULT (injected: true): this path is wrong on purpose.
with open({WRONG_PATH!r}, newline="") as handle:
    rows = list(csv.DictReader(handle))
mean = statistics.fmean(float(r["mass_g"]) for r in rows)
json.dump(
    {{
        "outputs": {{"mean_mass": {{"value": mean, "unit": "g"}}}},
        # The analysis DECLARES how it produced the number. Without this the
        # verifier abstains rather than inferring a pass: it will not call a
        # result reproduced when it cannot see the method that produced it.
        "methodology": {{
            "exclusions": [],
            "seed": {SEED},
            "population": {{"count": len(rows), "selection_rule": {RULE!r}}},
        }},
    }},
    open("outputs.json", "w"),
)
"""

#: The notebook with the INJECTED fault still in place (injected: true).
FAULTY_NOTEBOOK_JSON = notebook_json(NOTEBOOK_SOURCE)


def apply_unified_diff(original: str, diff: str) -> str:
    """Apply a ``difflib`` unified diff and return the patched text.

    Deliberately strict: a context or removal line that does not match the
    original raises. The point is to prove the provider emitted a diff that
    applies cleanly to the exact bytes it claims to patch - a patch that only
    *looks* plausible is the failure mode worth catching.
    """
    out: list[str] = []
    src = original.splitlines(keepends=True)
    i = 0
    lines = diff.splitlines(keepends=True)
    k = 0
    while k < len(lines):
        line = lines[k]
        if line.startswith(("---", "+++")):
            k += 1
            continue
        if line.startswith("@@"):
            header = line.split("@@")[1].strip()
            old_part = header.split()[0]              # e.g. -12,7
            start = int(old_part[1:].split(",")[0]) - 1
            out.extend(src[i:start])
            i = start
            k += 1
            while k < len(lines) and not lines[k].startswith("@@"):
                body = lines[k]
                if body.startswith("+"):
                    out.append(body[1:])
                elif body.startswith("-"):
                    assert src[i] == body[1:], f"removal does not match source at {i}: {body!r}"
                    i += 1
                elif body.startswith(" "):
                    assert src[i] == body[1:], f"context does not match source at {i}: {body!r}"
                    out.append(src[i])
                    i += 1
                elif body.startswith(("---", "+++")):
                    pass
                k += 1
            continue
        k += 1
    out.extend(src[i:])
    return "".join(out)


@pytest.fixture
def faulty_source(tmp_path: Path) -> Path:
    """A source tree whose notebook reads the wrong path (fault INJECTED here)."""
    root = tmp_path / "source"
    (root / "inputs").mkdir(parents=True)
    (root / REAL_PATH).write_text(CSV_BODY, encoding="utf-8")
    (root / NOTEBOOK_NAME).write_text(FAULTY_NOTEBOOK_JSON, encoding="utf-8")
    return root


@pytest.fixture
def approved(tmp_path: Path, references: ReferenceStore, contract_factory):
    """A snapshot, a reference, and a contract approved in the ledger (RX-04)."""
    store = ContentAddressedStore(tmp_path / "blobs")
    ledger = ApprovalLedger(tmp_path / "ledger.jsonl")
    reference = references.write_json(
        "outputs.json", {"outputs": {"mean_mass": {"value": EXPECTED_MEAN, "unit": "g"}}}
    )
    contract = contract_factory(inputs=(reference,), population_count=len(MASSES))
    ledger.record_contract_approval(
        approval=Approval(
            approval_id="ap-contract-1",
            contract_hash=contract.contract_hash,
            candidate_hash="0" * 64,          # no candidate yet; the contract is what is approved
            input_snapshot_id="snap-pending",
            environment_policy_digest="e" * 64,
            action_digest="a" * 64,
            approved_by="favl",
            approved_at=FIXED_MOMENT,
        ),
        recorded_at=FIXED_MOMENT,
    )
    return store, ledger, contract


# ========================================================================== #
# CASE 1 - a legitimate repair reproduces WITHIN the approved contract
# ========================================================================== #
def test_case1_legitimate_repair_reproduces_within_contract(
    faulty_source: Path, approved, references: ReferenceStore, tmp_path: Path
) -> None:
    store, ledger, contract = approved
    ledger.require_approved_contract(contract.contract_hash)

    manifest = snapshot_create(store, faulty_source)
    before = manifest.manifest_digest

    # RX-07: a provider cannot write ANYWHERE without an authority guard - it
    # refuses an unguarded write outright, which is why the guard is constructed
    # here and the scratch directory is explicitly granted rather than assumed.
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    authority = RepairAuthority(repo_root=tmp_path, scratch_dirs=(scratch,))
    proposal = DeterministicRepairProvider(authority=authority).propose(
        Diagnosis(
            diagnosis_id="d1",
            snapshot_id=manifest.manifest_digest,
            target_path=NOTEBOOK_NAME,
            fault_class=FaultClass.MISSING_INPUT_PATH,
            detail="injected: the notebook reads a path absent from the snapshot",
            missing_path=WRONG_PATH,
        ),
        manifest,
        store_reader(store, manifest),
        scratch,
    )
    assert proposal is not None, "the provider abstained on a mechanically repairable fault"
    assert WRONG_PATH in proposal.unified_diff and REAL_PATH in proposal.unified_diff

    # RX-01: proposing must not mutate the snapshot. One digest covers the whole
    # tree, so this also catches a change to any file the provider did not target.
    assert snapshot_create(store, faulty_source).manifest_digest == before

    # The diff must apply cleanly to the exact bytes it claims to patch.
    patched = apply_unified_diff(FAULTY_NOTEBOOK_JSON, proposal.unified_diff)
    assert REAL_PATH in patched and WRONG_PATH not in patched

    # Execute THROUGH THE RUNNER, inside its isolation boundary. The recovered
    # project invariants require that imported code runs only in the approved
    # sandbox and never on the developer host, so this must not be a bare
    # subprocess even for a synthetic fixture: the triad has to exercise the
    # same execution path a real analysis would take (RX-08).
    repaired_tree = tmp_path / "repaired"
    repaired_tree.mkdir()
    (repaired_tree / NOTEBOOK_NAME).write_text(patched, encoding="utf-8")

    # Materialise the snapshot into the runner's scratch root BEFORE the run.
    # This is the integrator's wiring: the runner creates an empty scratch dir
    # and declares a materialiser seam, so the inputs the notebook reads are the
    # SNAPSHOTTED bytes, digest-verified as they are written (RX-01, RX-02) -
    # not a second copy the test happened to produce.
    run_dir = tmp_path / "run"
    scratch = run_dir / "scratch"
    scratch.mkdir(parents=True)
    snapshot_materialise(store, manifest, scratch)
    assert (scratch / REAL_PATH).read_text(encoding="utf-8") == CSV_BODY

    result = run_notebook(
        repaired_tree / NOTEBOOK_NAME,
        run_dir,
        RUN_LIMITS,
        run_id="triad-case-1",
        source_root=repaired_tree,
    )
    assert result.status is ExecutionStatus.SUCCEEDED, result.stderr[-2000:]
    assert result.isolation.guard_receipt_verified is True, "ran without a verified guard"
    outputs = Path(result.scratch_dir) / "outputs.json"
    assert outputs.is_file(), "the run produced no outputs document"

    report = verify(
        outputs,
        contract,
        FilesystemReferenceReader(references.root),
        run_record=RunRecord(
            run_id="run-triad-1",
            snapshot_id=manifest.manifest_digest,
            runner_identity="retrace-runner",
            environment_policy_digest=RUN_LIMITS.policy_digest,
            execution_status=result.status,
            started_at=FIXED_MOMENT,
            finished_at=FIXED_MOMENT,
            exit_code=result.exit_code,
        ),
        verified_at=FIXED_MOMENT,
    )
    assert report.outcome is VerificationOutcome.REPRODUCED_WITHIN_CONTRACT, report.reason
    assert report.independently_recomputed, "reproduced without independent recomputation"


def test_case1_control_without_the_repair_the_same_run_fails(
    faulty_source: Path, approved, references: ReferenceStore, tmp_path: Path
) -> None:
    """DISCRIMINATION CONTROL for case 1.

    Case 1 asserts that a repaired analysis reproduces. On its own that could be
    true for an unrelated reason - a contract so loose that anything satisfies
    it, or an output file left behind by something else. So run the SAME tree
    with the injected fault still in place and nothing else changed: it must
    fail to execute, and must not yield a reproduced verdict. If this control
    ever passes, case 1 proves nothing.
    """
    _, _, contract = approved
    tree = tmp_path / "unrepaired"
    tree.mkdir()
    (tree / NOTEBOOK_NAME).write_text(FAULTY_NOTEBOOK_JSON, encoding="utf-8")  # fault intact

    # Same materialised inputs as case 1: the ONLY difference is the unrepaired
    # notebook. If the data were missing instead, this control would pass for the
    # wrong reason and prove nothing about the repair.
    store = ContentAddressedStore(tmp_path / "blobs-control")
    manifest = snapshot_create(store, faulty_source)
    run_dir = tmp_path / "run"
    scratch = run_dir / "scratch"
    scratch.mkdir(parents=True)
    snapshot_materialise(store, manifest, scratch)
    assert (scratch / REAL_PATH).is_file(), "the control did not materialise the inputs"

    result = run_notebook(
        tree / NOTEBOOK_NAME,
        run_dir,
        RUN_LIMITS,
        run_id="triad-case-1-control",
        source_root=tree,
    )
    assert result.status is not ExecutionStatus.SUCCEEDED, (
        "the injected fault did not break the run; case 1 would prove nothing"
    )
    # The traceback lands in cell_error, not stderr: stderr carries only kernel
    # chatter, so asserting on it would have missed the actual failure reason.
    assert result.cell_error is not None, "failed without recording a cell error"
    assert "FileNotFoundError" in str(result.cell_error), result.cell_error
    assert WRONG_PATH in str(result.cell_error), "failed for a different reason than the fault"
    missing = Path(result.scratch_dir) / "outputs.json"
    assert not missing.exists(), "a failed run still produced an outputs document"

    # And the verifier must not manufacture a verdict from an absent output file.
    report = verify(
        missing,
        contract,
        FilesystemReferenceReader(references.root),
        verified_at=FIXED_MOMENT,
    )
    assert report.outcome is not VerificationOutcome.REPRODUCED_WITHIN_CONTRACT
    assert report.outcome in {
        VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
        VerificationOutcome.FAILED_EXECUTION,
    }, report.outcome


# ========================================================================== #
# CASE 2 - a result-changing repair must NOT receive reproduced status
# ========================================================================== #
def test_case2_result_changing_candidate_is_not_reproduced(
    approved, references: ReferenceStore, tmp_path: Path
) -> None:
    """RX-14: the numbers agree EXACTLY and it still must not pass.

    This is the single most important assertion in the suite. The candidate
    declares a different exclusion rule from the approved contract while
    producing the identical value, so only a methodology comparison can catch
    it. Numeric agreement must never override a changed method.
    """
    _, _, contract = approved
    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps(
            {
                "outputs": {"mean_mass": {"value": EXPECTED_MEAN, "unit": "g"}},
                "methodology": {"exclusions": ["dropped.outliers"], "seed": 20260301},
            }
        ),
        encoding="utf-8",
    )
    report = verify(
        outputs, contract, FilesystemReferenceReader(references.root), verified_at=FIXED_MOMENT
    )
    assert report.outcome is not VerificationOutcome.REPRODUCED_WITHIN_CONTRACT, (
        "a candidate that changed the method was accepted as reproduced"
    )
    assert report.outcome is VerificationOutcome.CHANGED_RESULT, report.reason
    assert report.methodology_delta, "CHANGED_RESULT with no recorded methodology delta"


def test_case2b_a_changed_unit_is_not_a_silent_conversion(
    approved, references: ReferenceStore, tmp_path: Path
) -> None:
    """RX-13: grams declared, kilograms supplied. Never convert, always refuse."""
    _, _, contract = approved
    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps({"outputs": {"mean_mass": {"value": EXPECTED_MEAN / 1000.0, "unit": "kg"}}}),
        encoding="utf-8",
    )
    report = verify(
        outputs, contract, FilesystemReferenceReader(references.root), verified_at=FIXED_MOMENT
    )
    assert report.outcome is not VerificationOutcome.REPRODUCED_WITHIN_CONTRACT
    assert report.outcome is VerificationOutcome.CHANGED_RESULT, report.reason


# ========================================================================== #
# CASE 3 - missing evidence stays blocked
# ========================================================================== #
def test_case3_missing_reference_stays_blocked(
    references: ReferenceStore, tmp_path: Path, contract_factory
) -> None:
    """RX-17: abstain. A reference that is declared but absent is not a pass."""
    declared = references.declare_without_writing(
        "outputs.json", json.dumps({"outputs": {}}).encode("utf-8")
    )
    contract = contract_factory(inputs=(declared,), population_count=len(MASSES))
    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps({"outputs": {"mean_mass": {"value": EXPECTED_MEAN, "unit": "g"}}}),
        encoding="utf-8",
    )
    report = verify(
        outputs, contract, FilesystemReferenceReader(references.root), verified_at=FIXED_MOMENT
    )
    assert report.outcome is VerificationOutcome.BLOCKED_MISSING_EVIDENCE, report.reason


# ========================================================================== #
# Authority - what makes the three outcomes above worth anything
# ========================================================================== #
@pytest.mark.parametrize("protected", PROTECTED_PREFIXES)
def test_repair_worker_cannot_write_any_protected_prefix(
    protected: str, tmp_path: Path
) -> None:
    """RX-07: each protected prefix refused individually, by name."""
    guard = RepairAuthority(
        repo_root=tmp_path, scratch_dirs=(tmp_path / "scratch",), ledger_path=tmp_path / "led.jsonl"
    )
    target = tmp_path / protected / "x.py"
    with pytest.raises(WriteRefused) as caught:
        guard.assert_writable(target)
    assert caught.value.rule is not None


def test_repair_worker_cannot_write_the_approval_ledger(tmp_path: Path) -> None:
    guard = RepairAuthority(
        repo_root=tmp_path, scratch_dirs=(tmp_path / "scratch",), ledger_path=tmp_path / "led.jsonl"
    )
    with pytest.raises(WriteRefused):
        guard.assert_writable(tmp_path / "led.jsonl")


def test_changing_the_approved_candidate_invalidates_the_approval(approved) -> None:
    """RX-05: approval binds the exact candidate; a swap must not survive it."""
    _, ledger, contract = approved
    bound = {
        "contract_hash": contract.contract_hash,
        "candidate_hash": "b" * 64,
        "input_snapshot_id": "snap-1",
        "environment_policy_digest": "c" * 64,
        "action_digest": "d" * 64,
    }
    ledger.record_candidate_approval(
        approval=Approval(
            approval_id="ap-candidate-1", approved_by="favl", approved_at=FIXED_MOMENT, **bound
        ),
        recorded_at=FIXED_MOMENT,
    )
    ledger.require_approved_candidate(**bound)
    # Changing the candidate must make the approval stop applying. The ledger
    # looks approvals up BY the bound pair, so an altered candidate matches no
    # entry and is refused as ContractNotApproved rather than ApprovalInvalidated.
    # Both are refusals; asserting one name would be testing the spelling rather
    # than the property, so assert the refusal and then pin the record-level
    # guarantee separately.
    swapped = dict(bound, candidate_hash="0" * 64)
    with pytest.raises((ApprovalInvalidated, ContractNotApproved)):
        ledger.require_approved_candidate(**swapped)

    # RX-05 at the record level: the stored approval itself refuses the altered
    # binding and names the field that moved.
    stored = Approval(
        approval_id="ap-candidate-1", approved_by="favl", approved_at=FIXED_MOMENT, **bound
    )
    with pytest.raises(ApprovalInvalidated) as caught:
        stored.validate_binding(**swapped)
    assert "candidate_hash" in str(caught.value)


def test_provider_abstains_rather_than_change_scientific_meaning(
    faulty_source: Path, tmp_path: Path
) -> None:
    """RX-14: abstention is a SUCCESS. The provider must not buy a pass by
    editing an exclusion rule, a seed, a split or a unit conversion."""
    store = ContentAddressedStore(tmp_path / "blobs")
    manifest = snapshot_create(store, faulty_source)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    provider = DeterministicRepairProvider(
        authority=RepairAuthority(repo_root=tmp_path, scratch_dirs=(scratch,))
    )
    proposal = provider.propose(
        Diagnosis(
            diagnosis_id="d2",
            snapshot_id=manifest.manifest_digest,
            target_path=NOTEBOOK_NAME,
            fault_class=FaultClass.EXCLUSION_RULE_CHANGED,
            detail="injected: a meaning-changing fault the provider must refuse",
        ),
        manifest,
        store_reader(store, manifest),
        scratch,
    )
    assert proposal is None, "the provider proposed a patch for a meaning-changing fault"
    assert provider.abstention_log, "abstained without recording a reason"
    assert provider.abstention_log[-1].reason in set(AbstentionReason)


# ========================================================================== #
# CASE 4 - reference_kind governs what may be CLAIMED
# ========================================================================== #
@pytest.mark.parametrize(
    ("kind", "permitted"),
    [
        (ReferenceKind.HISTORICAL_REFERENCE, True),
        (ReferenceKind.NEW_TEACHING_REFERENCE, True),
        (ReferenceKind.NO_REFERENCE, False),
    ],
    ids=["historical", "new-teaching", "none"],
)
def test_case4_no_reference_can_never_be_reported_as_reproduced(
    references: ReferenceStore, tmp_path: Path, contract_factory, kind, permitted
) -> None:
    """A NO_REFERENCE contract must never yield REPRODUCED_WITHIN_CONTRACT.

    This was a LIVE DEFECT: the contracts layer exposed
    `permits_reproduced_outcome` but the verifier did not consult it, so a
    contract declaring it had no reference still reported a reproduction when the
    numbers happened to agree. Fixed in `_select_outcome`.

    The parametrisation is the discrimination control. Two of the three kinds DO
    reach REPRODUCED from identical inputs, so a clamp that simply refused
    everything - or a fixture too weak to reach a pass at all - would fail here
    rather than look like success.
    """
    reference = references.write_json(
        "outputs.json", {"outputs": {"mean_mass": {"value": EXPECTED_MEAN, "unit": "g"}}}
    )
    contract = contract_factory(
        inputs=(reference,), population_count=len(MASSES), reference_kind=kind
    )
    assert contract.permits_reproduced_outcome is permitted

    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps(
            {
                "outputs": {"mean_mass": {"value": EXPECTED_MEAN, "unit": "g"}},
                "methodology": {
                    "exclusions": [],
                    "seed": SEED,
                    "population": {"count": len(MASSES), "selection_rule": RULE},
                },
            }
        ),
        encoding="utf-8",
    )
    report = verify(
        outputs,
        contract,
        FilesystemReferenceReader(references.root),
        run_record=RunRecord(
            run_id=f"case4-{kind.value}",
            snapshot_id="s" * 64,
            runner_identity="retrace-runner",
            environment_policy_digest="e" * 64,
            execution_status=ExecutionStatus.SUCCEEDED,
            started_at=FIXED_MOMENT,
            finished_at=FIXED_MOMENT,
            exit_code=0,
        ),
        verified_at=FIXED_MOMENT,
    )
    if permitted:
        assert report.outcome is VerificationOutcome.REPRODUCED_WITHIN_CONTRACT, report.reason
    else:
        assert report.outcome is not VerificationOutcome.REPRODUCED_WITHIN_CONTRACT, (
            "a contract declaring NO_REFERENCE was reported as reproduced"
        )
        assert report.outcome is VerificationOutcome.EXECUTED_NOT_VERIFIED, report.reason
        assert "NO_REFERENCE" in report.reason

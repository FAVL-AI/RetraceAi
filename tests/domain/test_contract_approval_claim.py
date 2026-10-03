"""The ledger checks a contract's own approval claim (RX-04, RX-05).

RESTORES A GUARD THE SCHEMA RECONCILIATION REMOVED. `approval_ref` used to be an
embedded `Approval`, and the contracts layer refused one whose hash disagreed
with the contract it sat inside. Reconciling to the recovered original made it a
bare string, and the contracts layer does no I/O, so it can no longer tell
whether the reference points at an approval for *this* declaration or for
different material. The check moved to the ledger, which is where the authority
lives; these tests are the evidence it actually moved rather than evaporated.

The case that matters is the last one: a contract can carry `status = APPROVED`
and a well-formed `approval_ref`, and still not be approved.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from retrace_contracts import (
    Approval,
    ApprovalInvalidated,
    ComparisonSpec,
    ContractNotApproved,
    ContractStatus,
    OutputDefinition,
    OutputKind,
    Population,
    ReferenceInput,
    ReferenceKind,
    ResultContract,
    Tolerance,
)
from retrace_domain import ApprovalLedger

T0 = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC)
TENANT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


def build(**overrides: object) -> ResultContract:
    fields: dict[str, object] = {
        "contract_id": "contract-1",
        "tenant_id": TENANT,
        "project_id": "project-1",
        "version": 1,
        "status": ContractStatus.DRAFT,
        "reference_kind": ReferenceKind.NEW_TEACHING_REFERENCE,
        "inputs": (ReferenceInput(id="inputs/m.csv", sha256="a" * 64, role="input"),),
        "output_definitions": (
            OutputDefinition(name="m", kind=OutputKind.SCALAR, unit="g"),
        ),
        "population": Population(expected_count=3, selection_rule="all"),
        "comparison": ComparisonSpec(
            algorithm="elementwise-abs-rel", tolerances={"m": Tolerance(abs_tol=0.01)}
        ),
        "required_checks": ("numeric:m",),
        "limitations": ("SYNTHETIC fixture.",),
        "created_by": "test-operator",
    }
    fields.update(overrides)
    return ResultContract(**fields)  # type: ignore[arg-type]


@pytest.fixture
def ledger_with_approval(tmp_path: Path) -> tuple[ApprovalLedger, ResultContract]:
    """A ledger holding one active approval for the DRAFT declaration."""
    ledger = ApprovalLedger(tmp_path / "approvals.jsonl")
    draft = build()
    ledger.record_contract_approval(
        approval=Approval(
            approval_id="ap-1",
            contract_hash=draft.declaration_digest,
            candidate_hash="0" * 64,
            input_snapshot_id="snap-1",
            environment_policy_digest="e" * 64,
            action_digest="d" * 64,
            approved_by="favl",
            approved_at=T0,
        ),
        recorded_at=T0,
    )
    return ledger, draft


def test_an_approved_contract_with_a_correct_reference_is_accepted(
    ledger_with_approval: tuple[ApprovalLedger, ResultContract],
) -> None:
    """POSITIVE CONTROL. Without this the refusals below could all be vacuous."""
    ledger, _ = ledger_with_approval
    entry = ledger.verify_contract_approval(
        build(status=ContractStatus.APPROVED, approval_ref="ap-1")
    )
    assert entry.approval_id == "ap-1"


def test_a_draft_contract_is_not_approved(
    ledger_with_approval: tuple[ApprovalLedger, ResultContract],
) -> None:
    ledger, draft = ledger_with_approval
    with pytest.raises(ContractNotApproved, match="not APPROVED"):
        ledger.verify_contract_approval(draft)


def test_a_reference_that_resolves_to_nothing_is_not_approval(
    ledger_with_approval: tuple[ApprovalLedger, ResultContract],
) -> None:
    ledger, _ = ledger_with_approval
    with pytest.raises(ContractNotApproved, match="resolves to no active"):
        ledger.verify_contract_approval(
            build(status=ContractStatus.APPROVED, approval_ref="ap-does-not-exist")
        )


def test_a_superseded_approval_is_not_an_approval(
    ledger_with_approval: tuple[ApprovalLedger, ResultContract],
) -> None:
    """RX-52: withdrawing authority must actually withdraw it."""
    ledger, _ = ledger_with_approval
    approved = build(status=ContractStatus.APPROVED, approval_ref="ap-1")
    ledger.verify_contract_approval(approved)  # accepted before supersession
    ledger.supersede(
        ledger.entries()[0].entry_id, "withdrawn for cause", recorded_at=T0
    )
    with pytest.raises(ContractNotApproved, match="resolves to no active"):
        ledger.verify_contract_approval(approved)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 99),
        ("created_by", "someone-else"),
        ("limitations", ("a different limit",)),
        ("reference_kind", ReferenceKind.NO_REFERENCE),
    ],
)
def test_a_reference_to_an_approval_for_different_material_is_refused(
    ledger_with_approval: tuple[ApprovalLedger, ResultContract],
    field: str,
    value: object,
) -> None:
    """THE RESTORED GUARD, and the case that matters.

    The contract says APPROVED and names a reference that really does resolve to
    a real, active approval - but that approval was granted against a different
    declaration. A client-supplied status and a well-formed reference establish
    nothing; the ledger is the authority, and this is where the claim meets it.

    Parametrised over four unrelated declaration fields so the guard cannot pass
    by noticing one particular edit.
    """
    ledger, _ = ledger_with_approval
    tampered = build(status=ContractStatus.APPROVED, approval_ref="ap-1", **{field: value})
    with pytest.raises(ApprovalInvalidated, match="approved material has changed"):
        ledger.verify_contract_approval(tampered)


def test_the_guard_is_not_fooled_by_contract_hash_instead_of_declaration_digest(
    ledger_with_approval: tuple[ApprovalLedger, ResultContract],
) -> None:
    """An approval recorded against `contract_hash` must NOT satisfy the claim.

    Approvals bind `declaration_digest`. If someone records one against the
    lifecycle-sensitive `contract_hash` instead, the reference resolves and the
    digests disagree, so it is refused rather than quietly accepted - which is
    what would make the whole distinction pointless.
    """
    ledger, draft = ledger_with_approval
    ledger.record_contract_approval(
        approval=Approval(
            approval_id="ap-wrong-digest",
            contract_hash=draft.contract_hash,  # the WRONG digest for an approval
            candidate_hash="0" * 64,
            input_snapshot_id="snap-1",
            environment_policy_digest="e" * 64,
            action_digest="d" * 64,
            approved_by="favl",
            approved_at=T0,
        ),
        recorded_at=T0,
    )
    with pytest.raises(ApprovalInvalidated):
        ledger.verify_contract_approval(
            build(status=ContractStatus.APPROVED, approval_ref="ap-wrong-digest")
        )

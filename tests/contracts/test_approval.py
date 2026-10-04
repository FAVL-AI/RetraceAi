"""The five-field approval binding (RX-05).

"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from contracts_support import AUTHOR, T0, build_approval, digest
from pydantic import ValidationError
from retrace_contracts import Approval, ApprovalInvalidated, ContractImmutable

# A replacement value for each bound field, used to alter exactly one at a time.
ALTERED: dict[str, str] = {
    "contract_hash": digest("other-contract"),
    "candidate_hash": digest("other-candidate"),
    "input_snapshot_id": "snap-9999",
    "environment_policy_digest": digest("other-env-policy"),
    "action_digest": digest("other-action"),
}


def test_bound_fields_are_exactly_the_five_specified() -> None:
    """RX-05: the binding covers five fields, named and ordered."""
    assert Approval.BOUND_FIELDS == (
        "contract_hash",
        "candidate_hash",
        "input_snapshot_id",
        "environment_policy_digest",
        "action_digest",
    )
    assert set(ALTERED) == set(Approval.BOUND_FIELDS)


def test_validate_binding_accepts_the_approved_combination() -> None:
    """RX-05 positive control: the exact approved combination is accepted."""
    approval = build_approval()
    assert approval.validate_binding(**approval.bound_values) is None


@pytest.mark.parametrize("field", sorted(ALTERED))
def test_altering_any_bound_field_invalidates_the_approval(field: str) -> None:
    """RX-05: altering any one bound field raises ApprovalInvalidated by name."""
    approval = build_approval()
    observed = dict(approval.bound_values)
    observed[field] = ALTERED[field]
    with pytest.raises(ApprovalInvalidated) as caught:
        approval.validate_binding(**observed)
    assert caught.value.field == field
    assert caught.value.fields == (field,)
    assert field in str(caught.value)
    assert caught.value.expected[field] == approval.bound_values[field]
    assert caught.value.observed[field] == ALTERED[field]
    assert caught.value.approval_id == approval.approval_id


def test_multiple_altered_fields_are_all_named() -> None:
    """RX-05: a reviewer is told every field that moved, not just the first."""
    approval = build_approval()
    observed = dict(approval.bound_values)
    observed["candidate_hash"] = ALTERED["candidate_hash"]
    observed["action_digest"] = ALTERED["action_digest"]
    with pytest.raises(ApprovalInvalidated) as caught:
        approval.validate_binding(**observed)
    assert caught.value.fields == ("candidate_hash", "action_digest")
    assert caught.value.field == "candidate_hash"


@pytest.mark.parametrize("omitted", sorted(ALTERED))
def test_a_partial_binding_check_is_refused(omitted: str) -> None:
    """RX-05 negative control: a check that skips a field cannot be used.

    Silently ignoring an absent field would make the binding check unable to
    detect a change in that field -- a gate that cannot fail.
    """
    approval = build_approval()
    observed = dict(approval.bound_values)
    del observed[omitted]
    with pytest.raises(ValueError, match="requires every bound field") as caught:
        approval.validate_binding(**observed)
    assert omitted in str(caught.value)
    assert not isinstance(caught.value, ApprovalInvalidated)


def test_unknown_binding_field_is_refused() -> None:
    """RX-05 negative control: a misspelled field name is not silently ignored."""
    approval = build_approval()
    observed = dict(approval.bound_values)
    observed["contract_hashh"] = digest("typo")
    with pytest.raises(ValueError, match="unknown field"):
        approval.validate_binding(**observed)


def test_binding_digest_is_stable_for_the_same_binding() -> None:
    """RX-05: the binding digest is a pure function of the five bound fields."""
    first = build_approval()
    second = build_approval(approval_id="ap-0002")
    assert first.binding_digest == second.binding_digest


@pytest.mark.parametrize("field", sorted(ALTERED))
def test_binding_digest_changes_when_a_bound_field_changes(field: str) -> None:
    """RX-05: each bound field participates in the binding digest."""
    baseline = build_approval()
    mutated = build_approval(**{field: ALTERED[field]})
    assert mutated.binding_digest != baseline.binding_digest


def test_binding_digest_ignores_who_approved_and_when() -> None:
    """RX-05: the binding answers 'what was approved', not 'by whom and when'.

    The full-record digest does cover those fields, which is asserted here so
    the narrower scope of binding_digest is visibly deliberate.
    """
    baseline = build_approval()
    later = build_approval(approved_at=T0 + timedelta(hours=1), approved_by="A. Reviewer")
    assert later.binding_digest == baseline.binding_digest
    assert later.content_digest() != baseline.content_digest()


def test_equal_instants_in_different_zones_produce_equal_record_digests() -> None:
    """RX-03/RX-31: the approval digest depends on the instant, not the offset."""
    utc = build_approval(approved_at=datetime(2026, 10, 2, 9, 0, tzinfo=UTC))
    shifted = build_approval(
        approved_at=datetime(2026, 10, 2, 11, 0, tzinfo=timezone(timedelta(hours=2)))
    )
    assert utc.content_digest() == shifted.content_digest()


def test_naive_approved_at_is_refused() -> None:
    """RX-31 negative control: an approval timestamp without a zone is refused."""
    with pytest.raises(ValidationError):
        build_approval(approved_at=datetime(2026, 10, 2, 9, 0))


def test_approval_does_not_read_the_clock() -> None:
    """RX-05: approved_at is required, so no record can stamp itself."""
    assert Approval.model_fields["approved_at"].is_required()


@pytest.mark.parametrize("field", ["contract_hash", "candidate_hash", "action_digest"])
def test_malformed_digests_are_refused(field: str) -> None:
    """RX-05 negative control: a bound digest must be a real sha256 hex string."""
    with pytest.raises(ValidationError):
        build_approval(**{field: "not-a-digest"})


def test_approval_is_immutable() -> None:
    """RX-05: an editable audit record cannot be audited."""
    approval = build_approval()
    with pytest.raises(ContractImmutable):
        approval.candidate_hash = ALTERED["candidate_hash"]


def test_approved_by_must_be_present() -> None:
    """RX-05 negative control: an unattributed approval is refused."""
    with pytest.raises(ValidationError):
        build_approval(approved_by="   ")
    assert build_approval(approved_by=AUTHOR).approved_by == AUTHOR

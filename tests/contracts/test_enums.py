"""Closure and separation of the verification vocabularies (RX-11, RX-12).

"""

from __future__ import annotations

import pytest
from retrace_contracts import (
    CheckStatus,
    ContractStatus,
    ExecutionStatus,
    OutputKind,
    ReferenceKind,
    VerificationOutcome,
)

EXPECTED_OUTCOMES = {
    "REPRODUCED_WITHIN_CONTRACT",
    "EXECUTED_NOT_VERIFIED",
    "CHANGED_RESULT",
    "BLOCKED_MISSING_EVIDENCE",
    "FAILED_EXECUTION",
}


def test_verification_outcome_has_exactly_five_members() -> None:
    """RX-12: exactly five outcomes, with exactly these names and values."""
    assert len(VerificationOutcome) == 5
    assert set(VerificationOutcome.__members__) == EXPECTED_OUTCOMES
    assert {member.value for member in VerificationOutcome} == EXPECTED_OUTCOMES


def test_no_sixth_outcome_is_representable_by_subclassing() -> None:
    """RX-12 negative control: the enum cannot be extended with a sixth value."""
    with pytest.raises(TypeError):

        class SneakyOutcome(VerificationOutcome):  # type: ignore[misc]
            PROBABLY_FINE = "PROBABLY_FINE"


def test_no_sixth_outcome_is_representable_by_lookup() -> None:
    """RX-12 negative control: an unlisted value does not resolve to a member."""
    with pytest.raises(ValueError):
        VerificationOutcome("REPRODUCED")
    with pytest.raises(ValueError):
        VerificationOutcome("PASS")


def test_execution_status_is_a_separate_type_from_verification_outcome() -> None:
    """RX-11: the two vocabularies are different types and share no value."""
    assert ExecutionStatus is not VerificationOutcome
    assert not issubclass(ExecutionStatus, VerificationOutcome)
    assert not issubclass(VerificationOutcome, ExecutionStatus)
    assert not isinstance(ExecutionStatus.SUCCEEDED, VerificationOutcome)
    outcome_values = {member.value for member in VerificationOutcome}
    status_values = {member.value for member in ExecutionStatus}
    assert outcome_values.isdisjoint(status_values)


def test_execution_status_members() -> None:
    """RX-11: the four process-termination states, and no 'reproduced'."""
    assert set(ExecutionStatus.__members__) == {"SUCCEEDED", "FAILED", "TIMEOUT", "KILLED"}
    assert "REPRODUCED_WITHIN_CONTRACT" not in ExecutionStatus.__members__


def test_check_status_distinguishes_blocked_from_failed() -> None:
    """RX-17: an unevaluable check is BLOCKED, which is neither a pass nor a fail."""
    assert CheckStatus.BLOCKED is not CheckStatus.FAILED
    assert CheckStatus.BLOCKED is not CheckStatus.PASSED
    assert set(CheckStatus.__members__) == {
        "PASSED",
        "FAILED",
        "ERRORED",
        "SKIPPED",
        "BLOCKED",
    }


@pytest.mark.parametrize(
    ("kind", "numeric"),
    [
        (OutputKind.SCALAR, True),
        (OutputKind.VECTOR, True),
        (OutputKind.ARRAY, True),
        (OutputKind.TABLE, True),
        (OutputKind.TEXT, False),
        (OutputKind.FIGURE, False),
        (OutputKind.ARTEFACT, False),
    ],
)
def test_output_kind_numeric_classification(kind: OutputKind, numeric: bool) -> None:
    """RX-13: only numeric kinds carry tolerance semantics."""
    assert kind.is_numeric is numeric


# --------------------------------------------------------------------------- #
# The vocabularies added by the spec reconciliation (closure sections 2 and 4)
# --------------------------------------------------------------------------- #
def test_contract_status_is_closed_to_a_fourth_value() -> None:
    """RX-04 negative control: a lifecycle status outside the three is unusable."""
    assert set(ContractStatus.__members__) == {"DRAFT", "APPROVED", "SUPERSEDED"}
    with pytest.raises(ValueError):
        ContractStatus("APPROVED_BY_CLIENT")
    with pytest.raises(TypeError):

        class SneakyStatus(ContractStatus):  # type: ignore[misc]
            PROVISIONALLY_FINE = "PROVISIONALLY_FINE"


def test_reference_kind_is_closed_to_a_fourth_value() -> None:
    """Closure section 4 negative control: SYNTHETIC is not admitted here."""
    assert set(ReferenceKind.__members__) == {
        "HISTORICAL_REFERENCE",
        "NEW_TEACHING_REFERENCE",
        "NO_REFERENCE",
    }
    with pytest.raises(ValueError):
        ReferenceKind("SYNTHETIC")
    with pytest.raises(TypeError):

        class SneakyKind(ReferenceKind):  # type: ignore[misc]
            SYNTHETIC = "SYNTHETIC"


def test_no_reference_is_the_only_kind_that_forbids_a_pass() -> None:
    """RX-12/RX-17: the admissibility rule lives in one place and is exhaustive."""
    forbidding = {kind for kind in ReferenceKind if not kind.permits_reproduced_outcome}
    assert forbidding == {ReferenceKind.NO_REFERENCE}


def test_the_new_vocabularies_share_no_value_with_the_judgement_vocabularies() -> None:
    """RX-11/RX-12: a lifecycle or reference value cannot be read as a judgement.

    The sharp case the reconciliation introduced is ``ContractStatus.APPROVED``:
    a contract's lifecycle status now carries the word APPROVED, and it must not
    be confusable with a check having PASSED or a result having been
    REPRODUCED_WITHIN_CONTRACT. Disjoint value sets make that a lookup failure
    rather than a reading error.

    Scope note: this does NOT assert global disjointness across all five
    vocabularies. ``CheckStatus.FAILED`` and ``ExecutionStatus.FAILED``
    deliberately share a value -- a check that failed and a process that failed
    are both "failed" -- and that predates this reconciliation. The pair that
    must stay disjoint (execution vs verification) is asserted above.
    """
    judgement_values = (
        {member.value for member in VerificationOutcome}
        | {member.value for member in CheckStatus}
        | {member.value for member in ExecutionStatus}
    )
    for enum_type in (ContractStatus, ReferenceKind):
        values = {member.value for member in enum_type}
        assert values.isdisjoint(judgement_values), (
            f"{enum_type.__name__} reuses "
            f"{sorted(values & judgement_values)} from a judgement vocabulary"
        )

    assert {member.value for member in ContractStatus}.isdisjoint(
        {member.value for member in ReferenceKind}
    )

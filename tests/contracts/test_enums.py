"""Closure and separation of the verification vocabularies (RX-11, RX-12).

"""

from __future__ import annotations

import pytest
from retrace_contracts import CheckStatus, ExecutionStatus, OutputKind, VerificationOutcome

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

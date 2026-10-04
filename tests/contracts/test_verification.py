"""Run records and verification reports (RX-11, RX-12, RX-14, RX-18, RX-33).

The tests that matter most here are the negative controls on
``REPRODUCED_WITHIN_CONTRACT``: each one proves the record type refuses to carry
a reproduction claim that its own contents do not support.

"""

from __future__ import annotations

import pytest
from contracts_support import T0, T2, build_check, build_report, build_run_record, digest
from pydantic import ValidationError
from retrace_contracts import (
    CheckResult,
    CheckStatus,
    ExecutionStatus,
    MethodologyAspect,
    MethodologyDelta,
    RunRecord,
    VerificationOutcome,
    VerificationReport,
)

MODEL_PINNING = {
    "model_id": "test-model-v1",
    "provider_id": "test-provider",
    "model_catalogue_timestamp": T0,
}

FAILED_CHECK = build_check(
    status=CheckStatus.FAILED,
    summary="mean body mass differs beyond declared tolerance",
    observed="4290.113113",
    abs_diff=83.056056,
    rel_diff=0.019742,
)
BLOCKED_CHECK = build_check(
    check_id="chk.population-count",
    status=CheckStatus.BLOCKED,
    summary="reference output absent; cannot evaluate",
    expected=None,
    observed=None,
    abs_diff=None,
    rel_diff=None,
    unit_expected=None,
    unit_observed=None,
)
SPLIT_DELTA = MethodologyDelta(
    aspect=MethodologyAspect.SPLIT,
    expected="stratified-by-species train_fraction=0.8",
    observed="random train_fraction=0.7",
    description="the split strategy and fraction both differ from the contract",
)


# --- RunRecord --------------------------------------------------------------


def test_run_record_is_valid_with_no_model_used() -> None:
    """RX-33: all three model-pinning fields None is a valid record."""
    record = build_run_record()
    assert record.used_a_model is False
    assert record.model_id is None


def test_run_record_pins_model_provider_and_catalogue_timestamp_together() -> None:
    """RX-33: a model-using run pins all three fields."""
    record = build_run_record(**MODEL_PINNING)
    assert record.used_a_model is True
    assert record.provider_id == "test-provider"
    assert record.model_catalogue_timestamp == T0


@pytest.mark.parametrize("supplied", sorted(MODEL_PINNING))
def test_partial_model_pinning_is_refused(supplied: str) -> None:
    """RX-33 negative control: one pinned field without the others is refused.

    A model id with no catalogue timestamp records a model choice that cannot be
    traced to the catalogue entry that authorised it.
    """
    with pytest.raises(ValidationError, match="pin model_id, provider_id"):
        build_run_record(**{supplied: MODEL_PINNING[supplied]})


@pytest.mark.parametrize("omitted", sorted(MODEL_PINNING))
def test_two_of_three_pinned_fields_is_refused(omitted: str) -> None:
    """RX-33 negative control: two out of three is still partial pinning."""
    partial = {k: v for k, v in MODEL_PINNING.items() if k != omitted}
    with pytest.raises(ValidationError, match="pin model_id, provider_id"):
        build_run_record(**partial)


def test_run_record_refuses_reversed_timestamps() -> None:
    """RX-08 negative control: a run cannot finish before it started."""
    with pytest.raises(ValidationError, match="precedes"):
        build_run_record(started_at=T2, finished_at=T0)


def test_succeeded_status_contradicting_a_nonzero_exit_code_is_refused() -> None:
    """RX-11 negative control: 'succeeded' and exit 3 cannot both be true."""
    with pytest.raises(ValidationError, match="SUCCEEDED contradicts"):
        build_run_record(execution_status=ExecutionStatus.SUCCEEDED, exit_code=3)


def test_failed_status_contradicting_exit_zero_is_refused() -> None:
    """RX-11 negative control: 'failed' and exit 0 cannot both be true."""
    with pytest.raises(ValidationError, match="FAILED contradicts"):
        build_run_record(execution_status=ExecutionStatus.FAILED, exit_code=0)


def test_run_record_carries_execution_status_not_a_verification_outcome() -> None:
    """RX-11: the run record cannot be given a verification outcome."""
    with pytest.raises(ValidationError):
        build_run_record(
            execution_status=VerificationOutcome.REPRODUCED_WITHIN_CONTRACT.value
        )


def test_run_record_requires_timezone_aware_timestamps() -> None:
    """RX-31 negative control: a naive run timestamp is refused."""
    from datetime import datetime

    with pytest.raises(ValidationError):
        build_run_record(started_at=datetime(2026, 10, 2, 9, 0))


def test_run_record_has_no_field_for_a_verification_verdict() -> None:
    """RX-11: there is nowhere in the run record to record a pass."""
    forbidden = {"outcome", "verified", "reproduced", "verification_outcome", "passed"}
    assert forbidden.isdisjoint(RunRecord.model_fields)


# --- CheckResult ------------------------------------------------------------


def test_unit_mismatch_is_reported_not_converted() -> None:
    """RX-13: differing units are surfaced as a mismatch."""
    check = build_check(unit_expected="g", unit_observed="kg")
    assert check.unit_mismatch is True
    assert build_check().unit_mismatch is False


def test_unit_mismatch_is_false_when_a_unit_is_unknown() -> None:
    """RX-13: an absent unit is not evidence of agreement or disagreement."""
    assert build_check(unit_observed=None).unit_mismatch is False


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_differences_are_refused(value: float) -> None:
    """RX-13 negative control: NaN is not a measured difference."""
    with pytest.raises(ValidationError):
        build_check(abs_diff=value)


def test_check_result_requires_a_summary() -> None:
    """RX-12 negative control: an unexplained check result is refused."""
    with pytest.raises(ValidationError):
        CheckResult(check_id="chk.x", status=CheckStatus.PASSED, summary="  ")


# --- VerificationReport: REPRODUCED invariants ------------------------------


def test_reproduced_report_is_valid_when_fully_supported() -> None:
    """RX-12 positive control: the one outcome that may be read as a pass."""
    report = build_report()
    assert report.is_reproduced is True
    assert report.outcome is VerificationOutcome.REPRODUCED_WITHIN_CONTRACT


def test_reproduced_is_refused_when_a_check_failed() -> None:
    """RX-11 negative control: exit 0 plus a failed check is never REPRODUCED."""
    with pytest.raises(ValidationError, match="requires every check to pass"):
        build_report(checks=(build_check(check_id="chk.population-count"), FAILED_CHECK))


@pytest.mark.parametrize(
    "status", [CheckStatus.FAILED, CheckStatus.ERRORED, CheckStatus.SKIPPED, CheckStatus.BLOCKED]
)
def test_reproduced_is_refused_for_any_non_passing_check(status: CheckStatus) -> None:
    """RX-11 negative control: skipped and blocked checks do not count as passes."""
    with pytest.raises(ValidationError, match="requires every check to pass"):
        build_report(checks=(build_check(status=status),))


def test_reproduced_is_refused_when_methodology_changed() -> None:
    """RX-14 negative control: plausible numbers plus a changed split is reanalysis."""
    with pytest.raises(ValidationError, match="methodology changed"):
        build_report(methodology_delta=(SPLIT_DELTA,))


def test_reproduced_is_refused_without_any_checks() -> None:
    """RX-12 negative control: a reproduction claim needs evidence."""
    with pytest.raises(ValidationError, match="at least one check"):
        build_report(checks=())


def test_reproduced_is_refused_without_a_run_record() -> None:
    """RX-11 negative control: nothing executed, so nothing reproduced."""
    with pytest.raises(ValidationError, match="requires a run_record"):
        build_report(run_record=None)


@pytest.mark.parametrize(
    "status", [ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT, ExecutionStatus.KILLED]
)
def test_reproduced_is_refused_when_execution_did_not_succeed(
    status: ExecutionStatus,
) -> None:
    """RX-11 negative control: a killed run cannot have reproduced anything."""
    with pytest.raises(ValidationError, match="requires execution_status=SUCCEEDED"):
        build_report(run_record=build_run_record(execution_status=status, exit_code=None))


def test_reproduced_is_refused_when_values_were_not_recomputed() -> None:
    """RX-18 negative control: notebook-reported outputs cannot produce a pass."""
    with pytest.raises(ValidationError, match="independently_recomputed=True"):
        build_report(independently_recomputed=False)


def test_independently_recomputed_defaults_to_false() -> None:
    """RX-18: a pass cannot be claimed by omitting the recomputation flag."""
    assert VerificationReport.model_fields["independently_recomputed"].default is False


def test_notebook_claims_are_recorded_without_influencing_the_outcome() -> None:
    """RX-18: a notebook printing 'PASS' is context, not evidence."""
    report = build_report(
        outcome=VerificationOutcome.CHANGED_RESULT,
        reason="recomputed mean differs beyond tolerance",
        checks=(FAILED_CHECK,),
        independently_recomputed=True,
        notebook_reported_claims=("All checks PASS",),
    )
    assert report.notebook_reported_claims == ("All checks PASS",)
    assert report.outcome is VerificationOutcome.CHANGED_RESULT


# --- VerificationReport: other outcome invariants ---------------------------


def test_changed_result_is_valid_with_a_failed_check() -> None:
    """RX-12 positive control: a numeric disagreement supports CHANGED_RESULT."""
    report = build_report(
        outcome=VerificationOutcome.CHANGED_RESULT,
        reason="recomputed mean differs beyond declared tolerance",
        checks=(FAILED_CHECK,),
    )
    assert report.failed_checks == (FAILED_CHECK,)


def test_changed_result_is_valid_with_only_a_methodology_delta() -> None:
    """RX-14 positive control: changed methodology alone is a changed result."""
    report = build_report(
        outcome=VerificationOutcome.CHANGED_RESULT,
        reason="the split differs from the contract; this is a reanalysis",
        methodology_delta=(SPLIT_DELTA,),
    )
    assert report.methodology_delta[0].aspect is MethodologyAspect.SPLIT


def test_changed_result_without_evidence_is_refused() -> None:
    """RX-12 negative control: a changed result must point at the change."""
    with pytest.raises(ValidationError, match="requires at least one FAILED check"):
        build_report(
            outcome=VerificationOutcome.CHANGED_RESULT,
            reason="something changed",
            checks=(build_check(),),
        )


def test_failed_execution_requires_a_run_that_did_not_succeed() -> None:
    """RX-11 positive and negative control for FAILED_EXECUTION."""
    report = build_report(
        outcome=VerificationOutcome.FAILED_EXECUTION,
        reason="the run exceeded its wall-clock budget",
        checks=(),
        run_record=build_run_record(
            execution_status=ExecutionStatus.TIMEOUT, exit_code=None
        ),
        independently_recomputed=False,
    )
    assert report.is_reproduced is False
    with pytest.raises(ValidationError, match="contradicts execution_status=SUCCEEDED"):
        build_report(
            outcome=VerificationOutcome.FAILED_EXECUTION,
            reason="claimed failure over a successful run",
            checks=(),
        )


def test_failed_execution_without_a_run_record_is_refused() -> None:
    """RX-11 negative control: a failed execution needs the execution."""
    with pytest.raises(ValidationError, match="FAILED_EXECUTION requires a run_record"):
        build_report(
            outcome=VerificationOutcome.FAILED_EXECUTION,
            reason="no run recorded",
            checks=(),
            run_record=None,
        )


def test_executed_not_verified_requires_a_successful_run() -> None:
    """RX-11: 'it ran but we cannot conclude' presupposes that it ran."""
    report = build_report(
        outcome=VerificationOutcome.EXECUTED_NOT_VERIFIED,
        reason="one declared check could not be evaluated",
        checks=(build_check(status=CheckStatus.SKIPPED),),
        independently_recomputed=False,
    )
    assert report.outcome is VerificationOutcome.EXECUTED_NOT_VERIFIED
    with pytest.raises(ValidationError, match="EXECUTED_NOT_VERIFIED requires"):
        build_report(
            outcome=VerificationOutcome.EXECUTED_NOT_VERIFIED,
            reason="nothing ran",
            checks=(),
            run_record=None,
        )


def test_executed_not_verified_is_refused_for_a_killed_run() -> None:
    """RX-11 negative control: a killed run is FAILED_EXECUTION."""
    with pytest.raises(ValidationError, match="use FAILED_EXECUTION"):
        build_report(
            outcome=VerificationOutcome.EXECUTED_NOT_VERIFIED,
            reason="killed",
            checks=(),
            run_record=build_run_record(
                execution_status=ExecutionStatus.KILLED, exit_code=None
            ),
        )


def test_blocked_missing_evidence_is_valid_with_a_blocked_check() -> None:
    """RX-17 positive control: absent reference evidence yields abstention."""
    report = build_report(
        outcome=VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
        reason="the declared reference output is absent from the snapshot",
        checks=(BLOCKED_CHECK,),
        independently_recomputed=False,
    )
    assert report.blocked_checks == (BLOCKED_CHECK,)
    assert report.is_reproduced is False


def test_blocked_missing_evidence_is_valid_with_no_checks_at_all() -> None:
    """RX-17 positive control: blocked before any check could run."""
    report = build_report(
        outcome=VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
        reason="no reference inputs were resolvable; nothing was evaluated",
        checks=(),
        run_record=None,
        independently_recomputed=False,
    )
    assert report.checks == ()


def test_blocked_missing_evidence_is_refused_when_a_check_failed() -> None:
    """RX-17 negative control: disagreeing evidence is not missing evidence."""
    with pytest.raises(ValidationError, match="not disagreeing"):
        build_report(
            outcome=VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
            reason="claimed abstention over a failed check",
            checks=(FAILED_CHECK,),
            independently_recomputed=False,
        )


def test_blocked_missing_evidence_is_refused_when_every_check_ran() -> None:
    """RX-17 negative control: abstention needs something actually blocked."""
    with pytest.raises(ValidationError, match="at least one BLOCKED check"):
        build_report(
            outcome=VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
            reason="claimed abstention over completed checks",
            checks=(build_check(),),
            independently_recomputed=False,
        )


def test_duplicate_check_ids_are_refused() -> None:
    """RX-12 negative control: a repeated check id double-counts evidence."""
    with pytest.raises(ValidationError, match="duplicate check_id"):
        build_report(checks=(build_check(), build_check()))


def test_report_outcome_rejects_an_execution_status_value() -> None:
    """RX-11: the outcome field cannot be given an execution status."""
    with pytest.raises(ValidationError):
        build_report(outcome=ExecutionStatus.SUCCEEDED.value)


def test_report_requires_a_reason() -> None:
    """RX-12 negative control: an outcome without a stated reason is refused."""
    with pytest.raises(ValidationError):
        build_report(reason="   ")


def test_report_pins_the_contract_hash_it_judged_against() -> None:
    """RX-03: a report is meaningless without the contract it was judged against."""
    assert build_report(contract_hash=digest("contract")).contract_hash == digest("contract")
    with pytest.raises(ValidationError):
        build_report(contract_hash="contract-1")


def test_report_digest_changes_with_the_outcome() -> None:
    """RX-12: the report digest follows its content."""
    reproduced = build_report()
    changed = build_report(
        outcome=VerificationOutcome.CHANGED_RESULT,
        reason="recomputed mean differs beyond declared tolerance",
        checks=(FAILED_CHECK,),
    )
    assert reproduced.content_digest() != changed.content_digest()


def test_verifier_and_runner_identities_are_separate_fields() -> None:
    """RX-09: the verifier identity is recorded separately from the runner's."""
    report = build_report()
    assert report.verifier_identity == "retrace-verifier"
    assert report.run_record is not None
    assert report.run_record.runner_identity == "retrace-runner"
    assert report.verifier_identity != report.run_record.runner_identity

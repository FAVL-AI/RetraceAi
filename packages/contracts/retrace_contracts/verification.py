"""The verifier's output shapes (RX-11, RX-12, RX-13, RX-14, RX-18, RX-33).

This module encodes the distinction the whole product exists to protect: a run
that finished is not a result that reproduced. :class:`RunRecord` describes what
the process did; :class:`VerificationReport` describes what the evidence shows;
the two carry different enums and neither can be substituted for the other.

:class:`VerificationReport` enforces the outcome invariants at construction, so
a verifier bug that would have reported ``REPRODUCED_WITHIN_CONTRACT`` over a
failed check cannot produce a valid report at all. The invariants are listed on
the class and each has a negative control in
``tests/contracts/test_verification.py``.

"""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import AwareDatetime, Field, model_validator

from .base import FrozenRecord, Identifier, NonEmptyStr, Sha256Hex
from .enums import CheckStatus, ExecutionStatus, MethodologyAspect, VerificationOutcome

__all__ = ["CheckResult", "MethodologyDelta", "RunRecord", "VerificationReport"]

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
NonNegativeFiniteFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class CheckResult(FrozenRecord):
    """The result of one declared check (RX-12, RX-13, RX-17).

    ``expected`` and ``observed`` are strings on purpose: a check result is an
    evidence record, and rendering the compared values as text keeps the record
    readable and diffable without committing the verifier to one numeric
    representation. The numeric difference, when one exists, is carried
    separately in ``abs_diff`` / ``rel_diff``.

    ``unit_expected`` / ``unit_observed`` exist so a unit disagreement is
    reported as a unit disagreement (RX-13) rather than silently converted or
    buried in a value string.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.CheckResult"

    check_id: Identifier = Field(description="Id of the check, matching a contract required_check.")
    status: CheckStatus = Field(description="Outcome of this check. BLOCKED is not FAILED.")
    summary: NonEmptyStr = Field(description="One-line human-readable result.")
    output_name: Identifier | None = Field(
        default=None, description="Contract output this check concerns, when applicable."
    )
    expected: str | None = Field(default=None, description="Reference value as text.")
    observed: str | None = Field(default=None, description="Recomputed value as text.")
    abs_diff: FiniteFloat | None = Field(
        default=None, description="Absolute difference, when numerically comparable."
    )
    rel_diff: FiniteFloat | None = Field(
        default=None, description="Relative difference, when numerically comparable."
    )
    unit_expected: NonEmptyStr | None = Field(default=None, description="Reference unit (RX-13).")
    unit_observed: NonEmptyStr | None = Field(default=None, description="Observed unit (RX-13).")
    details: dict[str, str] = Field(
        default_factory=dict, description="Additional diagnostic key/value detail."
    )

    @property
    def unit_mismatch(self) -> bool:
        """Whether the two units disagree (RX-13).

        A mismatch is a failure condition for the caller to act on; this layer
        never converts between units.
        """
        return (
            self.unit_expected is not None
            and self.unit_observed is not None
            and self.unit_expected != self.unit_observed
        )


class MethodologyDelta(FrozenRecord):
    """A named change of methodology between contract and run (RX-14).

    A changed exclusion, split, population or seed makes the work a reanalysis
    even when the numbers look plausible. Recording the delta as a structured
    finding -- naming the contract surface that moved -- is what stops a
    reanalysis from being reported as a reproduction.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.MethodologyDelta"

    aspect: MethodologyAspect = Field(description="Which contract surface changed.")
    expected: NonEmptyStr = Field(description="What the contract declared, as text.")
    observed: NonEmptyStr = Field(description="What the run actually did, as text.")
    description: NonEmptyStr = Field(description="Why this difference is a methodology change.")


class RunRecord(FrozenRecord):
    """What one isolated execution did (RX-08, RX-11, RX-33).

    Carries :class:`~retrace_contracts.enums.ExecutionStatus`, never a
    verification outcome.

    Model pinning (RX-33): ``model_id``, ``provider_id`` and
    ``model_catalogue_timestamp`` are *all three* set when a model was used and
    *all three* ``None`` when none was. A partially pinned record -- a model id
    with no catalogue timestamp, say -- is refused, because it records a model
    choice that cannot be traced back to the catalogue entry that authorised it.

    Timestamps must be timezone-aware; this record never reads the clock.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.RunRecord"

    MODEL_PINNING_FIELDS: ClassVar[tuple[str, ...]] = (
        "model_id",
        "provider_id",
        "model_catalogue_timestamp",
    )

    run_id: Identifier = Field(description="Stable id of this run.")
    snapshot_id: Identifier = Field(description="Snapshot the run executed against (RX-01).")
    runner_identity: NonEmptyStr = Field(
        description="Identity the runner executed as; distinct from the verifier (RX-09)."
    )
    environment_policy_digest: Sha256Hex = Field(
        description="Digest of the execution policy actually applied (RX-08)."
    )
    execution_status: ExecutionStatus = Field(
        description="How the process terminated. Not a statement about the science (RX-11)."
    )
    started_at: AwareDatetime = Field(description="Run start, timezone-aware.")
    finished_at: AwareDatetime = Field(description="Run end, timezone-aware.")
    exit_code: int | None = Field(default=None, description="Process exit code, when one exists.")
    wall_clock_seconds: NonNegativeFiniteFloat | None = Field(
        default=None, description="Measured wall-clock duration, when measured."
    )
    peak_memory_bytes: int | None = Field(
        default=None, ge=0, description="Measured peak RSS, when measured."
    )
    model_id: NonEmptyStr | None = Field(
        default=None, description="Resolved model id, pinned per run (RX-33)."
    )
    provider_id: NonEmptyStr | None = Field(
        default=None, description="Resolved provider id, pinned per run (RX-33)."
    )
    model_catalogue_timestamp: AwareDatetime | None = Field(
        default=None,
        description=(
            "Timestamp of the capability catalogue entry that authorised the model (RX-33)."
        ),
    )

    @model_validator(mode="after")
    def _check_run_consistency(self) -> RunRecord:
        """Enforce ordering, exit-code agreement and all-or-nothing model pinning."""
        if self.finished_at < self.started_at:
            raise ValueError("finished_at precedes started_at")

        pinned = [getattr(self, name) is not None for name in type(self).MODEL_PINNING_FIELDS]
        if any(pinned) and not all(pinned):
            missing = [
                name
                for name in type(self).MODEL_PINNING_FIELDS
                if getattr(self, name) is None
            ]
            raise ValueError(
                "a run that used a model must pin model_id, provider_id and "
                f"model_catalogue_timestamp together; missing: {', '.join(missing)} (RX-33)"
            )

        if self.exit_code is not None:
            if self.execution_status is ExecutionStatus.SUCCEEDED and self.exit_code != 0:
                raise ValueError(
                    f"execution_status=SUCCEEDED contradicts exit_code={self.exit_code}"
                )
            if self.execution_status is ExecutionStatus.FAILED and self.exit_code == 0:
                raise ValueError("execution_status=FAILED contradicts exit_code=0")
        return self

    @property
    def used_a_model(self) -> bool:
        """Whether this run used a model, by the all-or-nothing pinning rule (RX-33)."""
        return self.model_id is not None


class VerificationReport(FrozenRecord):
    """The verifier's judgement about one run (RX-11, RX-12, RX-14, RX-18).

    Outcome invariants, enforced at construction:

    ``REPRODUCED_WITHIN_CONTRACT``
        requires at least one check, every check ``PASSED``, an empty
        ``methodology_delta``, a ``run_record`` whose ``execution_status`` is
        ``SUCCEEDED``, and ``independently_recomputed`` true. A notebook that
        printed "PASS" cannot produce this outcome, because the report must
        declare that the values were recomputed independently (RX-18).
    ``CHANGED_RESULT``
        requires at least one ``FAILED`` check or at least one methodology
        delta. A changed result must point at the evidence of the change.
    ``FAILED_EXECUTION``
        requires a ``run_record`` whose ``execution_status`` is not
        ``SUCCEEDED``.
    ``EXECUTED_NOT_VERIFIED``
        requires a ``run_record`` whose ``execution_status`` is ``SUCCEEDED`` --
        something must actually have executed.
    ``BLOCKED_MISSING_EVIDENCE``
        requires no ``FAILED`` check and either no checks at all or at least one
        ``BLOCKED`` check. Abstention is for absent evidence, not for
        disagreeing evidence (RX-17).

    ``notebook_reported_claims`` records what the notebook *said* so a reviewer
    can see it, explicitly separated from the checks that decided the outcome
    (RX-18).
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.VerificationReport"

    report_id: Identifier = Field(description="Stable id of this report.")
    contract_hash: Sha256Hex = Field(
        description="Hash of the contract this run was judged against (RX-03)."
    )
    outcome: VerificationOutcome = Field(
        description="Exactly one of the five verification outcomes (RX-12)."
    )
    reason: NonEmptyStr = Field(
        description="Human-readable reason for the outcome, in the verifier's words."
    )
    checks: tuple[CheckResult, ...] = Field(
        default=(), description="Per-check results. Check ids are unique."
    )
    methodology_delta: tuple[MethodologyDelta, ...] = Field(
        default=(), description="Changed-methodology findings (RX-14)."
    )
    run_record: RunRecord | None = Field(
        default=None, description="The run judged, or None when nothing executed."
    )
    verifier_identity: NonEmptyStr = Field(
        description="Identity the verifier ran as; distinct from the runner (RX-09)."
    )
    verified_at: AwareDatetime = Field(description="When the judgement was made, timezone-aware.")
    independently_recomputed: bool = Field(
        default=False,
        description=(
            "True only when the compared values were recomputed by the verifier rather "
            "than read from run output (RX-18). Defaults False so a pass cannot be "
            "claimed by omission."
        ),
    )
    notebook_reported_claims: tuple[str, ...] = Field(
        default=(),
        description=(
            "Claims the executed notebook printed about itself. Recorded as untrusted "
            "context; never used to decide the outcome (RX-18)."
        ),
    )

    @property
    def failed_checks(self) -> tuple[CheckResult, ...]:
        """Checks whose status is ``FAILED``."""
        return tuple(check for check in self.checks if check.status is CheckStatus.FAILED)

    @property
    def blocked_checks(self) -> tuple[CheckResult, ...]:
        """Checks whose status is ``BLOCKED`` (missing evidence, RX-17)."""
        return tuple(check for check in self.checks if check.status is CheckStatus.BLOCKED)

    @property
    def is_reproduced(self) -> bool:
        """Whether this report may be read as a pass -- one outcome only (RX-12)."""
        return self.outcome is VerificationOutcome.REPRODUCED_WITHIN_CONTRACT

    @model_validator(mode="after")
    def _check_outcome_invariants(self) -> VerificationReport:
        """Refuse a report whose outcome is not supported by its own contents."""
        check_ids = [check.check_id for check in self.checks]
        duplicates = sorted({cid for cid in check_ids if check_ids.count(cid) > 1})
        if duplicates:
            raise ValueError(f"duplicate check_id(s): {', '.join(duplicates)}")

        failed = [check for check in self.checks if check.status is CheckStatus.FAILED]
        blocked = [check for check in self.checks if check.status is CheckStatus.BLOCKED]
        all_passed = bool(self.checks) and all(
            check.status is CheckStatus.PASSED for check in self.checks
        )
        outcome = self.outcome

        if outcome is VerificationOutcome.REPRODUCED_WITHIN_CONTRACT:
            if not self.checks:
                raise ValueError(
                    "REPRODUCED_WITHIN_CONTRACT requires at least one check result; "
                    "a reproduction claim with no checks is unsupported"
                )
            if not all_passed:
                offending = sorted(
                    f"{check.check_id}={check.status.value}"
                    for check in self.checks
                    if check.status is not CheckStatus.PASSED
                )
                raise ValueError(
                    "REPRODUCED_WITHIN_CONTRACT requires every check to pass; "
                    f"offending checks: {', '.join(offending)} (RX-11)"
                )
            if self.methodology_delta:
                aspects = ", ".join(delta.aspect.value for delta in self.methodology_delta)
                raise ValueError(
                    "REPRODUCED_WITHIN_CONTRACT is not available when methodology changed; "
                    f"deltas: {aspects}. A changed methodology is a reanalysis (RX-14)"
                )
            if self.run_record is None:
                raise ValueError("REPRODUCED_WITHIN_CONTRACT requires a run_record")
            if self.run_record.execution_status is not ExecutionStatus.SUCCEEDED:
                raise ValueError(
                    "REPRODUCED_WITHIN_CONTRACT requires execution_status=SUCCEEDED, got "
                    f"{self.run_record.execution_status.value} (RX-11)"
                )
            if not self.independently_recomputed:
                raise ValueError(
                    "REPRODUCED_WITHIN_CONTRACT requires independently_recomputed=True; "
                    "notebook-reported outputs are untrusted until recomputed (RX-18)"
                )

        elif outcome is VerificationOutcome.CHANGED_RESULT:
            if not failed and not self.methodology_delta:
                raise ValueError(
                    "CHANGED_RESULT requires at least one FAILED check or one "
                    "methodology delta as evidence of the change"
                )

        elif outcome is VerificationOutcome.FAILED_EXECUTION:
            if self.run_record is None:
                raise ValueError("FAILED_EXECUTION requires a run_record")
            if self.run_record.execution_status is ExecutionStatus.SUCCEEDED:
                raise ValueError(
                    "FAILED_EXECUTION contradicts execution_status=SUCCEEDED; "
                    "a run that completed but failed its checks is EXECUTED_NOT_VERIFIED "
                    "or CHANGED_RESULT (RX-11)"
                )

        elif outcome is VerificationOutcome.EXECUTED_NOT_VERIFIED:
            if self.run_record is None:
                raise ValueError(
                    "EXECUTED_NOT_VERIFIED requires a run_record; nothing executed otherwise"
                )
            if self.run_record.execution_status is not ExecutionStatus.SUCCEEDED:
                raise ValueError(
                    "EXECUTED_NOT_VERIFIED requires execution_status=SUCCEEDED, got "
                    f"{self.run_record.execution_status.value}; use FAILED_EXECUTION"
                )

        elif outcome is VerificationOutcome.BLOCKED_MISSING_EVIDENCE:
            if failed:
                raise ValueError(
                    "BLOCKED_MISSING_EVIDENCE is for absent evidence, not disagreeing "
                    f"evidence; {len(failed)} check(s) FAILED -- use CHANGED_RESULT (RX-17)"
                )
            if self.checks and not blocked:
                raise ValueError(
                    "BLOCKED_MISSING_EVIDENCE requires at least one BLOCKED check when "
                    "checks were run"
                )
        return self

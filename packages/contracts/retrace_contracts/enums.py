"""Closed enumerations for the RETRACE scientific authority layer.

The central design rule here is that **execution status and verification status
are different types** (RX-11). A process that exits ``0`` has only told us that
it exited ``0``; it has told us nothing about whether the scientific result was
reproduced. Keeping the two vocabularies in separate, closed enums makes the
confusion a type error rather than a judgement call.

Requirement coverage:

* :class:`VerificationOutcome` -- RX-12 (exactly five outcomes, no sixth value
  representable).
* :class:`ExecutionStatus` -- RX-11 (execution status is a separate type).
* :class:`CheckStatus` -- RX-12, RX-17 (a check can be blocked for missing
  evidence; blocked is not failed and is never a pass).
* :class:`MethodologyAspect` -- RX-14 (a changed methodology is reported as a
  named delta, not folded into a numeric difference).
* :class:`UIPlanRejectionReason` -- RX-22, RX-23 (a refused plan carries a
  specific, machine-readable reason).

"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "CheckStatus",
    "ExecutionStatus",
    "MethodologyAspect",
    "OutputKind",
    "UIPlanRejectionReason",
    "VerificationOutcome",
]


class VerificationOutcome(str, Enum):
    """The complete, closed set of verification outcomes (RX-12).

    Exactly five members. ``Enum`` forbids subclassing a type that already has
    members, so a sixth value is not representable without editing this file --
    which is the property RX-12 asks for and which
    ``tests/contracts/test_enums.py`` asserts directly.

    Members
    -------
    REPRODUCED_WITHIN_CONTRACT:
        Independently recomputed and inside every declared tolerance, with no
        methodology delta. The only outcome that may be read as a pass.
    EXECUTED_NOT_VERIFIED:
        The run completed but verification could not be concluded -- checks were
        skipped or errored, or the evidence recomputed was insufficient.
    CHANGED_RESULT:
        The run completed and the result differs from the reference, either
        numerically beyond tolerance, by unit mismatch (RX-13), or by changed
        methodology (RX-14).
    BLOCKED_MISSING_EVIDENCE:
        Required evidence was absent, so the verifier abstains (RX-17). Never
        an inferred pass.
    FAILED_EXECUTION:
        The run itself did not complete (non-zero exit, timeout, or kill).
    """

    REPRODUCED_WITHIN_CONTRACT = "REPRODUCED_WITHIN_CONTRACT"
    EXECUTED_NOT_VERIFIED = "EXECUTED_NOT_VERIFIED"
    CHANGED_RESULT = "CHANGED_RESULT"
    BLOCKED_MISSING_EVIDENCE = "BLOCKED_MISSING_EVIDENCE"
    FAILED_EXECUTION = "FAILED_EXECUTION"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ExecutionStatus(str, Enum):
    """How a run process terminated -- never a statement about science (RX-11).

    Deliberately disjoint from :class:`VerificationOutcome`: no string value is
    shared between the two enums, so a value of one type cannot validate as the
    other.

    Members
    -------
    SUCCEEDED:
        The process ran to completion within its resource envelope. This is an
        operational fact only.
    FAILED:
        The process terminated abnormally (non-zero exit or unhandled error).
    TIMEOUT:
        The process exceeded its bounded wall-clock budget (RX-08).
    KILLED:
        The process was terminated by the runner, e.g. on a memory or
        egress-policy violation (RX-08).
    """

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    KILLED = "KILLED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class CheckStatus(str, Enum):
    """Outcome of a single declared check (RX-12, RX-17).

    ``BLOCKED`` is distinct from ``FAILED``: a check whose reference evidence is
    absent has not failed, it could not be evaluated, and it must not be
    reported as either a pass or a numeric disagreement.
    """

    PASSED = "PASSED"
    FAILED = "FAILED"
    ERRORED = "ERRORED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class OutputKind(str, Enum):
    """What kind of thing a declared contract output is (RX-03, RX-13).

    The kind decides which comparison is admissible. ``SCALAR``, ``VECTOR``,
    ``ARRAY`` and ``TABLE`` are numeric and therefore require a declared
    tolerance; ``TEXT``, ``FIGURE`` and ``ARTEFACT`` are not numerically
    comparable and are compared by exact content digest instead.

    ``ARTEFACT`` is the deliberate escape hatch for an opaque output. It is
    closed-set-safe because an artefact carries no tolerance semantics: the
    verifier can only say "identical bytes" or "different bytes", never
    "close enough".
    """

    SCALAR = "SCALAR"
    VECTOR = "VECTOR"
    ARRAY = "ARRAY"
    TABLE = "TABLE"
    TEXT = "TEXT"
    FIGURE = "FIGURE"
    ARTEFACT = "ARTEFACT"

    @property
    def is_numeric(self) -> bool:
        """Whether a numeric tolerance is meaningful for this kind (RX-13)."""
        return self in _NUMERIC_OUTPUT_KINDS

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


_NUMERIC_OUTPUT_KINDS = frozenset(
    {OutputKind.SCALAR, OutputKind.VECTOR, OutputKind.ARRAY, OutputKind.TABLE}
)


class MethodologyAspect(str, Enum):
    """The contract surfaces whose change makes a result a reanalysis (RX-14).

    The member set is closed over the methodology-bearing fields of
    :class:`retrace_contracts.result_contract.ResultContract`, so a declared
    delta always names a field a reviewer can go and read.
    """

    REFERENCE_INPUTS = "REFERENCE_INPUTS"
    OUTPUT_DEFINITIONS = "OUTPUT_DEFINITIONS"
    POPULATION = "POPULATION"
    UNITS = "UNITS"
    EXCLUSIONS = "EXCLUSIONS"
    SEED = "SEED"
    SPLIT = "SPLIT"
    COMPARISON = "COMPARISON"
    REQUIRED_CHECKS = "REQUIRED_CHECKS"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class UIPlanRejectionReason(str, Enum):
    """Machine-readable reasons a generated UI plan is refused (RX-22, RX-23).

    A rejection reason is part of the product's truthfulness surface: the
    reviewer is told which rule refused the plan, not merely that something was
    wrong.
    """

    COMPONENT_NOT_ALLOWLISTED = "COMPONENT_NOT_ALLOWLISTED"
    QUERY_NOT_AUTHORISED = "QUERY_NOT_AUTHORISED"
    ACTION_NOT_REGISTERED = "ACTION_NOT_REGISTERED"
    SCRIPT_INJECTION = "SCRIPT_INJECTION"
    SQL_INJECTION = "SQL_INJECTION"
    CONTROL_CHARACTERS = "CONTROL_CHARACTERS"
    FIELD_TOO_LONG = "FIELD_TOO_LONG"
    PROTECTED_REGION_HIDDEN = "PROTECTED_REGION_HIDDEN"
    PROTECTED_REGION_MISSING = "PROTECTED_REGION_MISSING"
    DUPLICATE_COMPONENT_ID = "DUPLICATE_COMPONENT_ID"
    PLAN_TOO_LARGE = "PLAN_TOO_LARGE"
    PLAN_TOO_DEEP = "PLAN_TOO_DEEP"
    EMPTY_PLAN = "EMPTY_PLAN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

"""Independent verification of one run against an approved contract (RX-09..RX-18).

:func:`verify` is the verifier's whole public surface. It reads the run's output
artefact and the contract's pinned reference evidence, recomputes every
comparison itself, detects methodology change, and returns a frozen
:class:`~retrace_contracts.VerificationReport`.

TRUST DOMAIN
============
This module imports neither the runner nor any repair provider, and it never
will: ``tests/exec/test_verifier_surface.py`` walks the import graph of every
module in this package and fails on a forbidden import. The verifier therefore
cannot start a run, cannot propose a patch, and cannot ask a model anything. Its
only inputs are bytes it is given and bytes it reads through a read-only
reference reader (RX-09).

WHAT THE NOTEBOOK SAID IS IGNORED (RX-18)
=========================================
A run may print "VERIFICATION PASSED". That string reaches
:attr:`~retrace_contracts.VerificationReport.notebook_reported_claims` and
nothing else. No branch in this module reads ``reported_claims``, and
``tests/exec/test_verifier_outcomes.py`` includes a run whose stdout claims a
pass while its outputs disagree with the reference; the outcome is
``CHANGED_RESULT``.

OUTCOME PRECEDENCE
==================
See :data:`OUTCOME_PRECEDENCE`. One ordering decision deserves to be called out
rather than buried, because it is a deliberate deviation from the plainest
reading of the requirement matrix:

RX-17 says missing evidence yields abstention, and the task framing orders
"missing evidence" ahead of "disagreement". The frozen
:class:`~retrace_contracts.VerificationReport` refuses
``BLOCKED_MISSING_EVIDENCE`` when any check ``FAILED``, on the stated grounds
that abstention is for *absent* evidence and not for *disagreeing* evidence.
Where both occur -- one output missing and another output outside tolerance --
the contracts layer wins and the outcome is ``CHANGED_RESULT``, with the
``BLOCKED`` check still present in the report so the missing evidence is visible.
Both readings refuse to call it a reproduction, which is the property that
matters; this build resolves the tie toward the more specific finding.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from retrace_contracts import (
    CheckResult,
    CheckStatus,
    ExecutionStatus,
    MethodologyDelta,
    ResultContract,
    RunRecord,
    VerificationOutcome,
    VerificationReport,
    sha256_hex,
)

from .comparison import compare_output, output_name_from_check_id
from .document import CandidateMethodology, OutputDocument, OutputValue, parse_output_document
from .errors import OutputParseRefused, ReferenceUnavailable
from .methodology import detect_methodology_deltas, methodology_declaration_check
from .safe_read import DEFAULT_PARSE_LIMITS, ParseLimits, read_payload, read_payload_bytes
from .seams import ReferenceReader

__all__ = [
    "DEFAULT_VERIFIER_IDENTITY",
    "INDEPENDENT_RECOMPUTATION_SCOPE",
    "OUTCOME_PRECEDENCE",
    "REFERENCE_OUTPUT_ROLE",
    "VERIFICATION_LIMITS",
    "verify",
]

DEFAULT_VERIFIER_IDENTITY: Final[str] = "retrace-verifier"
"""Identity recorded in the report. The platform must grant it separately from the runner's."""

REFERENCE_OUTPUT_ROLE: Final[str] = "reference-output"
"""The ``ReferenceInput.role`` that marks a reference as carrying expected values."""

OUTCOME_PRECEDENCE: Final[tuple[str, ...]] = (
    "1. the run did not complete -> FAILED_EXECUTION",
    "2. any check FAILED -> CHANGED_RESULT (disagreement is a specific finding)",
    "3. any methodology delta -> CHANGED_RESULT, even if every number agreed (RX-14)",
    "4. any check BLOCKED, or no checks at all -> BLOCKED_MISSING_EVIDENCE (abstain)",
    "5. any required check SKIPPED or ERRORED -> EXECUTED_NOT_VERIFIED",
    "6. every check PASSED, no delta, run SUCCEEDED, values recomputed here"
    " -> REPRODUCED_WITHIN_CONTRACT",
    "7. anything else -> EXECUTED_NOT_VERIFIED; there is no fall-through to a pass",
)

INDEPENDENT_RECOMPUTATION_SCOPE: Final[str] = (
    "independently_recomputed=True in a report from this verifier means exactly "
    "this: every compared value was parsed by this package from a primary "
    "artefact -- the run's output file and the contract's digest-verified "
    "reference bytes -- and every tolerance decision, difference and verdict was "
    "computed here. It does NOT mean the verifier re-executed the computation. "
    "The run produces the values; the verifier owes you an independent judgement "
    "about them, not an independent derivation of them. A report that read a "
    "verdict out of run output instead of computing one would be false "
    "verification, and this package has no code path that does it."
)

VERIFICATION_LIMITS: Final[tuple[str, ...]] = (
    "The verifier judges the artefact it is given. It cannot establish that the "
    "artefact came from the run it is attributed to; that binding is the "
    "snapshot store's and the approval ledger's job (RX-01, RX-05).",
    "Reference integrity is checked against the digest the contract declares. If "
    "the contract itself pinned the wrong bytes, this check cannot detect it.",
    "Comparators exist for scalars, flat numeric vectors and exact text. ARRAY "
    "and TABLE outputs are reported SKIPPED, which drives the outcome to "
    "EXECUTED_NOT_VERIFIED rather than to a pass.",
    "A methodology delta is detected from the run's own declaration. A run that "
    "misreports what it did is not detectable here.",
    "The verifier's separate identity (RX-09) is a deployment property. This "
    "library enforces read-only reference access but cannot verify that it was "
    "granted a different credential from the runner's.",
)

_OUTPUTS_PRESENT_CHECK: Final[str] = "outputs:present"
_OUTPUTS_READABLE_CHECK: Final[str] = "outputs:readable"
_REFERENCE_DECLARED_CHECK: Final[str] = "reference:declared"
_RUN_RECORD_CHECK: Final[str] = "run:record-present"
_MAX_REPORTED_CLAIMS: Final[int] = 500


def _blocked(check_id: str, summary: str, **details: str) -> CheckResult:
    """Build a ``BLOCKED`` check -- evidence absent, nothing concluded (RX-17)."""
    return CheckResult(
        check_id=check_id, status=CheckStatus.BLOCKED, summary=summary, details=details
    )


def _report_id_for(contract: ResultContract, fingerprint: str) -> str:
    """Return a deterministic report id, so two identical verifications agree.

    Derived from the contract hash and a fingerprint of the artefact rather than
    from a clock or a counter: an id that changed between two identical
    verifications would make the two reports look like different events.
    """
    return "verify-" + sha256_hex(f"{contract.contract_hash}:{fingerprint}".encode())[:32]


def _read_reference_values(
    contract: ResultContract,
    reader: ReferenceReader,
    *,
    role: str,
    limits: ParseLimits,
) -> tuple[dict[str, OutputValue], list[CheckResult], bool]:
    """Read and digest-verify the contract's reference outputs (RX-01, RX-09, RX-17).

    Returns ``(values, blocking_checks, integrity_verified)``. Every failure mode
    produces a ``BLOCKED`` check rather than an exception, because absent or
    unusable reference evidence is a reason to abstain, not a crash. A digest
    mismatch is treated as *unusable* evidence: the verifier will not compare
    against bytes that are not the bytes the contract pinned.
    """
    references = [item for item in contract.reference_inputs if item.role == role]
    if not references:
        return (
            {},
            [
                _blocked(
                    _REFERENCE_DECLARED_CHECK,
                    f"the contract declares no reference input with role {role!r}, so there "
                    "is nothing to verify against; verification abstains",
                    reason="no-reference-output-declared",
                )
            ],
            False,
        )
    values: dict[str, OutputValue] = {}
    blocking: list[CheckResult] = []
    verified = True
    for reference in references:
        check_id = f"reference:{reference.path}"
        if not reader.exists(reference.path):
            blocking.append(
                _blocked(
                    check_id,
                    f"reference {reference.path!r} is absent from the reference store; "
                    "verification abstains (RX-17)",
                    reason="reference-absent",
                )
            )
            verified = False
            continue
        try:
            data = reader.read_bytes(reference.path)
        except ReferenceUnavailable as error:
            blocking.append(
                _blocked(
                    check_id,
                    f"reference {reference.path!r} could not be read: {error}",
                    reason="reference-unreadable",
                )
            )
            verified = False
            continue
        observed_digest = sha256_hex(data)
        if observed_digest != reference.sha256:
            blocking.append(
                CheckResult(
                    check_id=check_id,
                    status=CheckStatus.BLOCKED,
                    summary=(
                        f"reference {reference.path!r} does not match the digest the contract "
                        "pins, so it is not the evidence the contract declared; verification "
                        "abstains rather than comparing against unpinned bytes"
                    ),
                    expected=reference.sha256,
                    observed=observed_digest,
                    details={"reason": "reference-digest-mismatch"},
                )
            )
            verified = False
            continue
        suffix = Path(reference.path).suffix.lower()
        try:
            payload = read_payload_bytes(
                data, suffix=suffix, limits=limits, path=reference.path
            )
            document = parse_output_document(payload, path=reference.path)
        except OutputParseRefused as error:
            blocking.append(
                _blocked(
                    check_id,
                    f"reference {reference.path!r} was refused by the defensive parser "
                    f"({error.reason}) and was not deserialised; verification abstains",
                    reason=str(error.reason or "payload-refused"),
                )
            )
            verified = False
            continue
        for name, value in document.values.items():
            if name in values:
                blocking.append(
                    _blocked(
                        f"reference:conflict:{name}",
                        f"output {name!r} is declared by more than one reference input with "
                        "role "
                        f"{role!r}; the reference evidence is ambiguous, so verification "
                        "abstains",
                        reason="reference-output-conflict",
                    )
                )
                verified = False
                continue
            values[name] = value
    return values, blocking, verified


def _read_candidate(
    outputs_path: Path, *, limits: ParseLimits
) -> tuple[OutputDocument | None, CheckResult | None]:
    """Read the run's output artefact, or return the check that blocks on it (RX-10)."""
    if not outputs_path.exists():
        return None, _blocked(
            _OUTPUTS_PRESENT_CHECK,
            f"the run produced no output artefact at {outputs_path}; verification "
            "abstains rather than inferring a result (RX-17)",
            reason="outputs-absent",
        )
    try:
        payload = read_payload(outputs_path, limits=limits)
        return parse_output_document(payload, path=str(outputs_path)), None
    except OutputParseRefused as error:
        return None, _blocked(
            _OUTPUTS_READABLE_CHECK,
            f"the run's output artefact was refused by the defensive parser "
            f"({error.reason}) and was not deserialised: {error.detail}",
            reason=str(error.reason or "payload-refused"),
        )


def _declared_unit(contract: ResultContract, name: str) -> str | None:
    """Return the unit the contract declares for ``name``, if any (RX-13)."""
    if name in contract.units:
        return contract.units[name]
    for definition in contract.output_definitions:
        if definition.name == name:
            return definition.unit
    return None


def _select_outcome(
    checks: Sequence[CheckResult],
    deltas: Sequence[MethodologyDelta],
    run_record: RunRecord | None,
    *,
    recomputed: bool,
) -> tuple[VerificationOutcome, str]:
    """Choose the outcome by :data:`OUTCOME_PRECEDENCE` and say why (RX-11, RX-12)."""
    if run_record is not None and run_record.execution_status is not ExecutionStatus.SUCCEEDED:
        return (
            VerificationOutcome.FAILED_EXECUTION,
            f"the run did not complete (execution_status="
            f"{run_record.execution_status.value}); no scientific conclusion is available",
        )
    failed = [check for check in checks if check.status is CheckStatus.FAILED]
    blocked = [check for check in checks if check.status is CheckStatus.BLOCKED]
    unevaluated = [
        check
        for check in checks
        if check.status in (CheckStatus.SKIPPED, CheckStatus.ERRORED)
    ]
    if failed:
        return (
            VerificationOutcome.CHANGED_RESULT,
            f"{len(failed)} check(s) disagree with the contract's reference evidence: "
            + "; ".join(check.check_id for check in failed[:5]),
        )
    if deltas:
        return (
            VerificationOutcome.CHANGED_RESULT,
            "every compared number agreed, but the run's declared methodology differs from "
            "the contract on "
            + ", ".join(sorted({delta.aspect.value for delta in deltas}))
            + ". A changed methodology is a reanalysis, not a reproduction (RX-14)",
        )
    if blocked:
        named = "; ".join(check.check_id for check in blocked[:5])
        return (
            VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
            f"required evidence is missing or unusable ({named}); the verifier abstains "
            "rather than inferring a pass (RX-17)",
        )
    if not checks:
        return (
            VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
            "no check could be evaluated, so there is nothing to conclude from (RX-17)",
        )
    if unevaluated:
        return (
            VerificationOutcome.EXECUTED_NOT_VERIFIED,
            f"the run completed but {len(unevaluated)} required check(s) could not be "
            "evaluated: "
            + "; ".join(f"{check.check_id} [{check.status.value}]" for check in unevaluated[:5]),
        )
    if (
        run_record is not None
        and run_record.execution_status is ExecutionStatus.SUCCEEDED
        and recomputed
    ):
        return (
            VerificationOutcome.REPRODUCED_WITHIN_CONTRACT,
            f"all {len(checks)} declared check(s) were recomputed here from primary "
            "artefacts and are within the contract's declared tolerances, with no "
            "methodology delta",
        )
    return (
        VerificationOutcome.EXECUTED_NOT_VERIFIED,
        "the run completed and no check disagreed, but the conditions for a reproduction "
        "claim were not all met (a run record and independent recomputation are both "
        "required); this is deliberately not reported as a pass",
    )


def _merge_claims(*sources: Sequence[str]) -> tuple[str, ...]:
    """Merge the run's self-reported claims from every source, deduplicated (RX-18).

    Order-preserving and capped. These strings are evidence of what the run
    *said*; no branch anywhere in this package reads them, which is the property
    RX-18 asks for.
    """
    seen: dict[str, None] = {}
    for source in sources:
        for line in source:
            text = str(line).strip()
            if text and text not in seen and len(seen) < _MAX_REPORTED_CLAIMS:
                seen[text] = None
    return tuple(seen)


def verify(
    outputs_path: Path | str,
    contract: ResultContract,
    references_reader: ReferenceReader,
    *,
    run_record: RunRecord | None = None,
    candidate_methodology: CandidateMethodology | None = None,
    report_id: str | None = None,
    verifier_identity: str = DEFAULT_VERIFIER_IDENTITY,
    verified_at: datetime | None = None,
    limits: ParseLimits = DEFAULT_PARSE_LIMITS,
    reference_output_role: str = REFERENCE_OUTPUT_ROLE,
    notebook_reported_claims: Sequence[str] = (),
) -> VerificationReport:
    """Verify one run's outputs against ``contract`` and report (RX-09..RX-18).

    Parameters
    ----------
    outputs_path:
        The run's output artefact. Read defensively: JSON or CSV only, under
        every ceiling in ``limits`` (RX-10). A refused payload becomes a
        ``BLOCKED`` check and an abstention; it is never deserialised.
    contract:
        The approved :class:`~retrace_contracts.ResultContract`. Its
        ``reference_inputs`` with role ``reference_output_role`` carry the
        expected values, pinned by digest.
    references_reader:
        A read-only reference reader (RX-09). Any write attempted through it
        raises :class:`~retrace_contracts.VerifierAuthorityError`.
    run_record:
        What the runner reported. ``None`` is treated as *missing evidence about
        execution*, which blocks a reproduction claim rather than waiving the
        requirement for one.
    candidate_methodology:
        Overrides the methodology the output document declares. Supplied by an
        integrator that has a more authoritative record of what the run did.
    notebook_reported_claims:
        Lines the run printed about its own success, typically from the runner's
        captured output. Recorded in the report and **read by nothing** (RX-18).
    verified_at:
        Timestamp for the report. Defaults to now, because a judgement happens
        at a time; pass it explicitly for a byte-reproducible report.

    Returns
    -------
    VerificationReport:
        Exactly one of the five outcomes (RX-12), with the evidence that
        produced it. Never raises on hostile or missing evidence -- those are
        verification outcomes, not errors.
    """
    moment = verified_at or datetime.now(UTC)
    path = Path(outputs_path)
    checks: list[CheckResult] = []

    candidate, candidate_block = _read_candidate(path, limits=limits)
    if candidate_block is not None:
        checks.append(candidate_block)
    reference_values, reference_blocks, reference_verified = _read_reference_values(
        contract, references_reader, role=reference_output_role, limits=limits
    )
    checks.extend(reference_blocks)

    methodology = candidate_methodology or (
        candidate.methodology if candidate is not None else None
    )
    checks.append(methodology_declaration_check(methodology))
    deltas = detect_methodology_deltas(contract, methodology)

    if run_record is None:
        checks.append(
            _blocked(
                _RUN_RECORD_CHECK,
                "no run record was supplied, so it cannot be established that the artefact "
                "came from a run that completed; a reproduction claim is unavailable (RX-11)",
                reason="run-record-absent",
            )
        )

    produced = candidate.values if candidate is not None else {}
    for definition in contract.output_definitions:
        checks.append(
            compare_output(
                name=definition.name,
                kind=definition.kind,
                declared_unit=_declared_unit(contract, definition.name),
                tolerance=contract.comparison.tolerances.get(definition.name),
                expected=reference_values.get(definition.name),
                observed=produced.get(definition.name),
            )
        )

    produced_ids = {check.check_id for check in checks}
    for required in contract.required_checks:
        if required in produced_ids:
            continue
        name = output_name_from_check_id(required)
        if name is not None and any(
            definition.name == name for definition in contract.output_definitions
        ):
            # Already covered by the generated check for that output.
            continue
        checks.append(
            CheckResult(
                check_id=required,
                status=CheckStatus.SKIPPED,
                summary=(
                    f"required check {required!r} has no evaluator in this build, so it was "
                    "not evaluated; it is reported rather than dropped (RX-12)"
                ),
                details={"reason": "no-evaluator-registered"},
            )
        )
        produced_ids.add(required)

    recomputed = (
        candidate is not None
        and reference_verified
        and bool(reference_values)
        and all(
            check.status is CheckStatus.PASSED
            for check in checks
            if check.check_id.startswith("output:")
        )
    )
    outcome, reason = _select_outcome(checks, deltas, run_record, recomputed=recomputed)
    fingerprint = sha256_hex(
        "|".join(
            f"{check.check_id}={check.status.value}" for check in sorted(
                checks, key=lambda item: item.check_id
            )
        ).encode()
    )
    claims = _merge_claims(
        notebook_reported_claims,
        candidate.reported_claims if candidate is not None else (),
    )
    return VerificationReport(
        report_id=report_id or _report_id_for(contract, fingerprint),
        contract_hash=contract.contract_hash,
        outcome=outcome,
        reason=reason,
        checks=tuple(sorted(checks, key=lambda item: item.check_id)),
        methodology_delta=deltas,
        run_record=run_record,
        verifier_identity=verifier_identity,
        verified_at=moment,
        independently_recomputed=(
            recomputed and outcome is VerificationOutcome.REPRODUCED_WITHIN_CONTRACT
        ),
        notebook_reported_claims=claims,
    )

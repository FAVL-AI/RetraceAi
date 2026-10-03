"""Numerical comparison against declared tolerances and units (RX-13).

Two rules shape every function here.

**A unit disagreement is a failure, never a conversion (RX-13).** If the
contract declares grams and the run declares kilograms, this module reports a
``FAILED`` check carrying both units in
:attr:`~retrace_contracts.CheckResult.unit_expected` and
:attr:`~retrace_contracts.CheckResult.unit_observed`. It does not multiply by a
thousand. A conversion would make the verifier assert a physical equivalence
that nobody declared, and a verifier that silently converts is a verifier that
can silently convert *wrongly*.

**A comparison with no declared tolerance is not performed.** The contracts
layer already refuses a numeric output with no tolerance (RX-03), so by the time
a value reaches this module a tolerance exists. Where one is somehow absent the
check is ``ERRORED``, never defaulted: inventing ``1e-9`` would be the verifier
choosing the threshold the contract was supposed to declare.

Comparators implemented in this build: scalar and flat numeric vector against
``abs_tol``/``rel_tol``, and exact-text equality for non-numeric kinds. ``ARRAY``
and ``TABLE`` have **no comparator here**; a required check over one is reported
``SKIPPED`` with that reason, which drives the outcome to
``EXECUTED_NOT_VERIFIED`` rather than to a pass.
"""

from __future__ import annotations

import math
from typing import Final

from retrace_contracts import CheckResult, CheckStatus, OutputKind, Tolerance

from .document import OutputValue

__all__ = [
    "CHECK_ID_PREFIX",
    "UNCOMPARABLE_KINDS",
    "check_id_for_output",
    "compare_output",
    "output_name_from_check_id",
    "within_tolerance",
]

CHECK_ID_PREFIX: Final[str] = "output:"
"""Deterministic check-id convention: ``output:<declared output name>``."""

UNCOMPARABLE_KINDS: Final[frozenset[OutputKind]] = frozenset(
    {OutputKind.ARRAY, OutputKind.TABLE}
)
"""Kinds this build declares no comparator for. Reported SKIPPED, never passed."""

_VECTOR_PREVIEW = 8


def check_id_for_output(name: str) -> str:
    """Return the check id this verifier uses for contract output ``name``."""
    return f"{CHECK_ID_PREFIX}{name}"


def output_name_from_check_id(check_id: str) -> str | None:
    """Return the output a check id names, or ``None`` if it names none.

    A required check whose id this function cannot resolve has no evaluator in
    this build; the verifier reports it ``SKIPPED`` rather than quietly dropping
    it from the report (RX-12).
    """
    if check_id.startswith(CHECK_ID_PREFIX):
        suffix = check_id[len(CHECK_ID_PREFIX) :]
        return suffix or None
    return None


def within_tolerance(
    expected: float, observed: float, tolerance: Tolerance
) -> tuple[bool, float, float | None]:
    """Return ``(ok, abs_diff, rel_diff)`` for one scalar pair (RX-13).

    Semantics, stated because "within tolerance" is ambiguous in the wild:

    * ``abs_diff`` is ``|observed - expected|``.
    * ``rel_diff`` is ``abs_diff / |expected|``, or ``None`` when ``expected`` is
      zero -- a relative tolerance against zero is undefined, and returning
      ``inf`` would make an exact match look like an infinite disagreement.
    * Exact equality always passes, including the zero-against-zero case.
    * When both tolerances are declared, satisfying *either* passes. This is the
      same disjunction ``math.isclose`` uses, chosen so that a contract can
      declare an absolute floor for small magnitudes and a relative band for
      large ones.
    """
    abs_diff = abs(observed - expected)
    rel_diff = abs_diff / abs(expected) if expected != 0 else None
    if abs_diff == 0.0:
        return True, 0.0, rel_diff
    ok = False
    if tolerance.abs_tol is not None and abs_diff <= tolerance.abs_tol:
        ok = True
    if not ok and tolerance.rel_tol is not None and rel_diff is not None:
        ok = rel_diff <= tolerance.rel_tol
    return ok, abs_diff, rel_diff


def _render(value: float | str | tuple[float, ...]) -> str:
    """Render a compared value as reviewable text for the check record."""
    if isinstance(value, tuple):
        head = ", ".join(repr(item) for item in value[:_VECTOR_PREVIEW])
        suffix = f", ... ({len(value)} elements)" if len(value) > _VECTOR_PREVIEW else ""
        return f"[{head}{suffix}]"
    return repr(value)


def _blocked(check_id: str, name: str, summary: str, **details: str) -> CheckResult:
    """Build a ``BLOCKED`` check: evidence absent, so nothing was concluded (RX-17)."""
    return CheckResult(
        check_id=check_id,
        status=CheckStatus.BLOCKED,
        summary=summary,
        output_name=name,
        details=details,
    )


def compare_output(
    *,
    name: str,
    kind: OutputKind,
    declared_unit: str | None,
    tolerance: Tolerance | None,
    expected: OutputValue | None,
    observed: OutputValue | None,
) -> CheckResult:
    """Compare one declared output and return its check result (RX-13, RX-17).

    Decision order, and why:

    #. **Absent evidence first.** A missing reference or a missing produced value
       is ``BLOCKED``; the verifier abstains instead of inferring agreement
       (RX-17).
    #. **The reference must agree with the contract about units.** If the
       reference declares a different unit from the contract, the evidence
       contradicts the declaration it is meant to support, so the check is
       ``BLOCKED`` rather than resolved in either direction.
    #. **A candidate unit mismatch is a FAILURE with a unit diagnostic** -- never
       a conversion (RX-13).
    #. **Then, and only then, the numbers.**
    """
    check_id = check_id_for_output(name)
    if expected is None:
        return _blocked(
            check_id,
            name,
            f"no reference value for output {name!r}; verification abstains",
            reason="reference-output-absent",
        )
    if observed is None:
        return _blocked(
            check_id,
            name,
            f"the run produced no value for declared output {name!r}; verification abstains",
            reason="candidate-output-absent",
        )

    if declared_unit is not None and expected.unit is not None and expected.unit != declared_unit:
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.BLOCKED,
            summary=(
                f"reference unit {expected.unit!r} for {name!r} contradicts the contract's "
                f"declared unit {declared_unit!r}; the reference cannot support the contract"
            ),
            output_name=name,
            unit_expected=declared_unit,
            unit_observed=expected.unit,
            details={"reason": "reference-unit-contradicts-contract"},
        )

    reference_unit = declared_unit or expected.unit
    if (
        reference_unit is not None
        and observed.unit is not None
        and observed.unit != reference_unit
    ):
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.FAILED,
            summary=(
                f"unit mismatch for output {name!r}: contract declares {reference_unit!r}, "
                f"the run declares {observed.unit!r}. No conversion was performed (RX-13)"
            ),
            output_name=name,
            expected=_render(expected.value),
            observed=_render(observed.value),
            unit_expected=reference_unit,
            unit_observed=observed.unit,
            details={"reason": "unit-mismatch", "conversion": "refused"},
        )

    if kind in UNCOMPARABLE_KINDS:
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.SKIPPED,
            summary=(
                f"no comparator is implemented for output kind {kind.value} in this build, "
                f"so {name!r} was not evaluated"
            ),
            output_name=name,
            details={"reason": "no-comparator-for-kind", "kind": kind.value},
        )

    if not kind.is_numeric:
        match = expected.value == observed.value
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.PASSED if match else CheckStatus.FAILED,
            summary=(
                f"output {name!r} ({kind.value}) compared by exact content: "
                f"{'identical' if match else 'different'}"
            ),
            output_name=name,
            expected=_render(expected.value),
            observed=_render(observed.value),
            unit_expected=reference_unit,
            unit_observed=observed.unit,
            details={"comparison": "exact-content"},
        )

    if not expected.is_numeric or not observed.is_numeric:
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.ERRORED,
            summary=(
                f"output {name!r} is declared {kind.value} but the payload is not numeric; "
                "no admissible comparison exists"
            ),
            output_name=name,
            expected=_render(expected.value),
            observed=_render(observed.value),
            details={"reason": "declared-numeric-payload-not-numeric"},
        )
    if tolerance is None:
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.ERRORED,
            summary=(
                f"output {name!r} is numeric but the contract declares no tolerance; the "
                "verifier will not invent a threshold (RX-13)"
            ),
            output_name=name,
            details={"reason": "no-declared-tolerance"},
        )

    expected_is_vector = isinstance(expected.value, tuple)
    observed_is_vector = isinstance(observed.value, tuple)
    if expected_is_vector != observed_is_vector:
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.FAILED,
            summary=(
                f"shape mismatch for output {name!r}: reference is "
                f"{'a vector' if expected_is_vector else 'a scalar'} and the run produced "
                f"{'a vector' if observed_is_vector else 'a scalar'}"
            ),
            output_name=name,
            expected=_render(expected.value),
            observed=_render(observed.value),
            details={"reason": "shape-mismatch"},
        )

    if expected_is_vector:
        reference_vector: tuple[float, ...] = expected.value  # type: ignore[assignment]
        observed_vector: tuple[float, ...] = observed.value  # type: ignore[assignment]
        if len(reference_vector) != len(observed_vector):
            return CheckResult(
                check_id=check_id,
                status=CheckStatus.FAILED,
                summary=(
                    f"length mismatch for output {name!r}: reference has "
                    f"{len(reference_vector)} elements, the run produced "
                    f"{len(observed_vector)}"
                ),
                output_name=name,
                expected=_render(expected.value),
                observed=_render(observed.value),
                details={"reason": "length-mismatch"},
            )
        worst_abs = 0.0
        worst_rel: float | None = None
        failures = 0
        for reference_item, observed_item in zip(
            reference_vector, observed_vector, strict=True
        ):
            ok, abs_diff, rel_diff = within_tolerance(reference_item, observed_item, tolerance)
            if not ok:
                failures += 1
            worst_abs = max(worst_abs, abs_diff)
            if rel_diff is not None:
                worst_rel = rel_diff if worst_rel is None else max(worst_rel, rel_diff)
        passed = failures == 0
        return CheckResult(
            check_id=check_id,
            status=CheckStatus.PASSED if passed else CheckStatus.FAILED,
            summary=(
                f"output {name!r} elementwise comparison: "
                f"{len(reference_vector) - failures}/{len(reference_vector)} elements within "
                f"tolerance (abs_tol={tolerance.abs_tol}, rel_tol={tolerance.rel_tol})"
            ),
            output_name=name,
            expected=_render(expected.value),
            observed=_render(observed.value),
            abs_diff=worst_abs,
            rel_diff=worst_rel,
            unit_expected=reference_unit,
            unit_observed=observed.unit,
            details={
                "comparison": "elementwise-abs-rel",
                "elements": str(len(reference_vector)),
                "elements_outside_tolerance": str(failures),
            },
        )

    reference_scalar = float(expected.value)  # type: ignore[arg-type]
    observed_scalar = float(observed.value)  # type: ignore[arg-type]
    ok, abs_diff, rel_diff = within_tolerance(reference_scalar, observed_scalar, tolerance)
    return CheckResult(
        check_id=check_id,
        status=CheckStatus.PASSED if ok else CheckStatus.FAILED,
        summary=(
            f"output {name!r} {'within' if ok else 'outside'} declared tolerance "
            f"(abs_diff={abs_diff:.6g}, abs_tol={tolerance.abs_tol}, "
            f"rel_tol={tolerance.rel_tol})"
        ),
        output_name=name,
        expected=repr(reference_scalar),
        observed=repr(observed_scalar),
        abs_diff=abs_diff,
        rel_diff=rel_diff if rel_diff is not None and math.isfinite(rel_diff) else None,
        unit_expected=reference_unit,
        unit_observed=observed.unit,
        details={"comparison": "abs-rel"},
    )

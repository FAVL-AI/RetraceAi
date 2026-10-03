"""Methodology-delta detection: the rule numeric agreement may never override.

RX-14, stated as sharply as it deserves: **if the run's declared exclusions,
seed, split, population or units differ from the contract's, the outcome is
``CHANGED_RESULT`` even if every single number agrees.** A reanalysis that
happens to land on the same figures is still a reanalysis, and reporting it as a
reproduction is the specific scientific error this product exists to prevent.

That is why detection lives in its own module with its own tests, and why
:func:`detect_methodology_deltas` takes no numeric input at all: there is no
code path by which a numeric result could influence whether a delta is reported.
:mod:`retrace_verifier.verify` consults this module *before* it considers
reporting a reproduction, and the frozen
:class:`~retrace_contracts.VerificationReport` refuses
``REPRODUCED_WITHIN_CONTRACT`` whenever a delta is present -- so the rule is
enforced twice, independently, by two packages.

An **absent** declaration is not agreement. A run that declares no methodology
has not shown that it followed the contract's, so
:func:`methodology_declaration_check` reports ``BLOCKED`` and the outcome
becomes ``BLOCKED_MISSING_EVIDENCE``.
"""

from __future__ import annotations

from retrace_contracts import (
    CheckResult,
    CheckStatus,
    MethodologyAspect,
    MethodologyDelta,
    ResultContract,
)

from .document import CandidateMethodology

__all__ = [
    "METHODOLOGY_DECLARATION_CHECK_ID",
    "detect_methodology_deltas",
    "methodology_declaration_check",
]

METHODOLOGY_DECLARATION_CHECK_ID: str = "methodology:declared"
"""Id of the check that records whether the run declared its methodology at all."""


def methodology_declaration_check(methodology: CandidateMethodology | None) -> CheckResult:
    """Report whether the run declared a methodology (RX-14, RX-17).

    ``BLOCKED`` when it did not: absence of a declaration is absence of
    evidence, and the verifier abstains rather than assuming the contract's
    methodology was followed.
    """
    if methodology is None:
        return CheckResult(
            check_id=METHODOLOGY_DECLARATION_CHECK_ID,
            status=CheckStatus.BLOCKED,
            summary=(
                "the run declared no methodology, so agreement with the contract's "
                "exclusions, seed, split, population and units cannot be established; "
                "verification abstains (RX-14, RX-17)"
            ),
            details={"reason": "methodology-declaration-absent"},
        )
    return CheckResult(
        check_id=METHODOLOGY_DECLARATION_CHECK_ID,
        status=CheckStatus.PASSED,
        summary="the run declared its methodology; it is compared field by field below",
        details={"reason": "methodology-declaration-present"},
    )


def _delta(
    aspect: MethodologyAspect, expected: str, observed: str, description: str
) -> MethodologyDelta:
    """Build one named delta."""
    return MethodologyDelta(
        aspect=aspect, expected=expected, observed=observed, description=description
    )


def detect_methodology_deltas(
    contract: ResultContract, methodology: CandidateMethodology | None
) -> tuple[MethodologyDelta, ...]:
    """Return every methodology difference between contract and run (RX-14).

    Takes no numeric argument, by design: nothing about the produced values can
    reach this decision.

    Compared surfaces, each mapped to the
    :class:`~retrace_contracts.MethodologyAspect` a reviewer can go and read:

    ``EXCLUSIONS``
        The set of applied exclusion rule ids, compared as sets so that
        ordering -- which carries no methodological meaning -- does not raise a
        false delta, while a *missing* or *extra* rule does.
    ``SEED``
        Compared including the ``None`` cases: a contract that declares a seed
        and a run that declares none have not done the same thing.
    ``SPLIT``
        Strategy, train fraction and split seed, each individually.
    ``POPULATION``
        Expected record count, and the selection rule when the run declares one.
    ``UNITS``
        Per-output units. A unit change is both a methodology delta here *and* a
        failed check in :mod:`retrace_verifier.comparison`; it is reported in
        both places because it is both things.

    Returns an empty tuple when ``methodology`` is ``None``: absence is handled
    by :func:`methodology_declaration_check` as missing evidence, and inventing
    deltas from an absent declaration would attribute changes nobody declared.
    """
    if methodology is None:
        return ()
    deltas: list[MethodologyDelta] = []

    declared_exclusions = {rule.rule_id for rule in contract.exclusions}
    applied_exclusions = set(methodology.exclusions)
    if declared_exclusions != applied_exclusions:
        missing = sorted(declared_exclusions - applied_exclusions)
        extra = sorted(applied_exclusions - declared_exclusions)
        deltas.append(
            _delta(
                MethodologyAspect.EXCLUSIONS,
                ", ".join(sorted(declared_exclusions)) or "(none declared)",
                ", ".join(sorted(applied_exclusions)) or "(none applied)",
                "the set of applied exclusion rules differs from the contract's"
                + (f"; not applied: {', '.join(missing)}" if missing else "")
                + (f"; applied but not declared: {', '.join(extra)}" if extra else ""),
            )
        )

    if contract.seed != methodology.seed:
        deltas.append(
            _delta(
                MethodologyAspect.SEED,
                repr(contract.seed),
                repr(methodology.seed),
                "the seed used differs from the contract's declared seed, so the run is not "
                "the same computation even where its outputs agree",
            )
        )

    contract_split = contract.split
    run_split = methodology.split
    if (contract_split is None) != (run_split is None):
        deltas.append(
            _delta(
                MethodologyAspect.SPLIT,
                "(no split declared)" if contract_split is None else repr(contract_split.strategy),
                "(no split performed)" if run_split is None else repr(run_split.strategy),
                "one of the contract and the run declares a split and the other does not",
            )
        )
    elif contract_split is not None and run_split is not None:
        if contract_split.strategy != run_split.strategy:
            deltas.append(
                _delta(
                    MethodologyAspect.SPLIT,
                    contract_split.strategy,
                    run_split.strategy,
                    "the split strategy differs from the contract's",
                )
            )
        if contract_split.train_fraction != run_split.train_fraction:
            deltas.append(
                _delta(
                    MethodologyAspect.SPLIT,
                    f"train_fraction={contract_split.train_fraction!r}",
                    f"train_fraction={run_split.train_fraction!r}",
                    "the train fraction differs from the contract's",
                )
            )
        if contract_split.seed != run_split.seed:
            deltas.append(
                _delta(
                    MethodologyAspect.SPLIT,
                    f"split seed={contract_split.seed!r}",
                    f"split seed={run_split.seed!r}",
                    "the split seed differs from the contract's",
                )
            )

    run_population = methodology.population
    if run_population is not None:
        if contract.population.expected_count != run_population.count:
            deltas.append(
                _delta(
                    MethodologyAspect.POPULATION,
                    f"expected_count={contract.population.expected_count}",
                    f"count={run_population.count}",
                    "the run analysed a different number of records than the contract "
                    "declares, which is a changed population rather than a numeric difference",
                )
            )
        if (
            run_population.selection_rule is not None
            and run_population.selection_rule != contract.population.selection_rule
        ):
            deltas.append(
                _delta(
                    MethodologyAspect.POPULATION,
                    contract.population.selection_rule,
                    run_population.selection_rule,
                    "the population selection rule differs from the contract's",
                )
            )

    declared_units = dict(contract.units)
    for definition in contract.output_definitions:
        if definition.unit is not None:
            declared_units.setdefault(definition.name, definition.unit)
    for name, run_unit in sorted(methodology.units.items()):
        contract_unit = declared_units.get(name)
        if contract_unit is not None and contract_unit != run_unit:
            deltas.append(
                _delta(
                    MethodologyAspect.UNITS,
                    f"{name}={contract_unit}",
                    f"{name}={run_unit}",
                    f"output {name!r} was produced in a different unit from the contract's "
                    "declaration; no conversion is performed (RX-13)",
                )
            )
    return tuple(deltas)

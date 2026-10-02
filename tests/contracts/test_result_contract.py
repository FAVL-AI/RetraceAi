"""The hashed result contract and its approval linkage (RX-03, RX-04, RX-13).

"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import AUTHOR, build_approval, build_contract, digest  # noqa: F401
from pydantic import ValidationError
from retrace_contracts import (
    ApprovalInvalidated,
    ComparisonSpec,
    ContractImmutable,
    ContractNotApproved,
    ExclusionRule,
    OutputDefinition,
    OutputKind,
    Population,
    ReferenceInput,
    ResultContract,
    SplitSpec,
    Tolerance,
)

# One altered value per declared field. Each alteration keeps the contract
# internally valid, so the only thing under test is the digest's sensitivity.
FIELD_MUTATIONS: dict[str, Any] = {
    "reference_inputs": (
        ReferenceInput(
            path="data/penguins_synthetic.csv",
            sha256=digest("reference-input"),
            role="raw-measurements",
        ),
        ReferenceInput(
            path="data/reference_means.json",
            sha256=digest("reference-output"),
            role="reference-output",
        ),
    ),
    "output_definitions": (
        OutputDefinition(
            name="mean_body_mass", kind=OutputKind.SCALAR, unit="g", dtype="float32"
        ),
        OutputDefinition(name="summary_note", kind=OutputKind.TEXT),
    ),
    "population": Population(
        expected_count=334, selection_rule="rows with no missing measurement column"
    ),
    "units": {},
    "exclusions": (
        ExclusionRule(rule_id="excl.other", description="a different exclusion rule"),
    ),
    "seed": 1,
    "split": None,
    "comparison": ComparisonSpec(
        algorithm="exact-match",
        tolerances={"mean_body_mass": Tolerance(abs_tol=1e-6, rel_tol=1e-9)},
    ),
    "required_checks": ("chk.population-count",),
    "known_limits": ("SYNTHETIC fixture data only.",),
    "contract_version": 2,
    "created_by": "F. A. Van Laarhoven",
}


def test_every_declared_field_is_covered_by_the_mutation_matrix() -> None:
    """Meta-test: adding a contract field without a hash test fails here.

    Without this, the parametrised hash test below silently stops covering the
    contract the moment a field is added.
    """
    declared = set(ResultContract.model_fields) - set(ResultContract.CANONICAL_EXCLUDE)
    assert declared == set(FIELD_MUTATIONS)


@pytest.mark.parametrize("field", sorted(FIELD_MUTATIONS))
def test_changing_any_field_changes_the_contract_hash(field: str) -> None:
    """RX-03: any change to any declared field changes contract_hash."""
    baseline = build_contract()
    mutated = build_contract(**{field: FIELD_MUTATIONS[field]})
    assert mutated != baseline, f"{field} mutation produced an identical record"
    assert mutated.contract_hash != baseline.contract_hash


def test_semantically_equal_contracts_hash_equal() -> None:
    """RX-03: construction order and container type are not semantic."""
    first = build_contract(
        units={"mean_body_mass": "g"},
        comparison=ComparisonSpec(
            algorithm="elementwise-abs-rel",
            tolerances={"mean_body_mass": Tolerance(abs_tol=1e-6, rel_tol=1e-9)},
        ),
    )
    # Same declaration, built from lists instead of tuples and with the
    # tolerance keywords supplied in the other order.
    second = build_contract(
        reference_inputs=list(first.reference_inputs),
        output_definitions=list(first.output_definitions),
        required_checks=list(first.required_checks),
        known_limits=list(first.known_limits),
        comparison=ComparisonSpec(
            algorithm="elementwise-abs-rel",
            tolerances={"mean_body_mass": Tolerance(rel_tol=1e-9, abs_tol=1e-6)},
        ),
    )
    assert first.contract_hash == second.contract_hash


def test_contract_round_trips_through_its_own_dump() -> None:
    """RX-03: a contract reconstructed from its dump is the same contract."""
    original = build_contract()
    restored = ResultContract.model_validate(original.model_dump(mode="python"))
    assert restored == original
    assert restored.contract_hash == original.contract_hash


def test_contract_round_trips_through_json() -> None:
    """RX-03: JSON serialisation preserves the hash, so bundles stay verifiable."""
    original = build_contract()
    restored = ResultContract.model_validate_json(original.model_dump_json())
    assert restored.contract_hash == original.contract_hash


def test_contract_hash_is_not_a_stored_field() -> None:
    """RX-03: the digest is computed, so it cannot disagree with the content."""
    assert "contract_hash" not in ResultContract.model_fields


def test_approval_is_deliberately_excluded_from_the_hash() -> None:
    """RX-03/RX-05: an approval binds contract_hash, so it is not inside it.

    This exclusion is the single exception to "every field is hashed" and is
    asserted here so it stays a deliberate decision rather than drift.
    """
    assert ResultContract.CANONICAL_EXCLUDE == frozenset({"approval"})
    unapproved = build_contract()
    approved = unapproved.with_approval(
        build_approval(contract_hash=unapproved.contract_hash)
    )
    assert approved.contract_hash == unapproved.contract_hash
    assert "approval" not in approved.canonical_payload()


def test_mutating_the_units_mapping_changes_the_hash() -> None:
    """RX-03: the digest follows content, including the mutable units mapping.

    `units` is a dict because RX-03 specifies a mapping, so it is only
    shallow-immutable. This test records the consequence the class docstring
    declares: a mutated contract no longer matches any approval bound to its
    previous hash.
    """
    contract = build_contract()
    before = contract.contract_hash
    contract.units["mean_body_mass"] = "kg"
    assert contract.contract_hash != before


def test_known_limits_must_be_non_empty() -> None:
    """RX-03 negative control: a contract stating no limits is refused."""
    with pytest.raises(ValidationError):
        build_contract(known_limits=())


def test_whitespace_only_known_limit_is_refused() -> None:
    """RX-03 negative control: a blank limit is not a stated limit."""
    with pytest.raises(ValidationError):
        build_contract(known_limits=("   ",))


def test_output_definitions_must_be_non_empty() -> None:
    """RX-03 negative control: there is nothing to reproduce with no outputs."""
    with pytest.raises(ValidationError):
        build_contract(output_definitions=())


def test_duplicate_output_names_are_refused() -> None:
    """RX-03 negative control: an ambiguous output name is refused."""
    duplicate = OutputDefinition(name="mean_body_mass", kind=OutputKind.TEXT)
    with pytest.raises(ValidationError, match="duplicate output name"):
        build_contract(
            output_definitions=(
                OutputDefinition(name="mean_body_mass", kind=OutputKind.SCALAR, unit="g"),
                duplicate,
            )
        )


def test_duplicate_reference_paths_are_refused() -> None:
    """RX-03 negative control: the same reference file declared twice."""
    reference = ReferenceInput(
        path="data/penguins_synthetic.csv", sha256=digest("x"), role="raw"
    )
    with pytest.raises(ValidationError, match="duplicate reference input path"):
        build_contract(reference_inputs=(reference, reference))


def test_duplicate_exclusion_ids_are_refused() -> None:
    """RX-14 negative control: two exclusions cannot share an id."""
    rule = ExclusionRule(rule_id="excl.a", description="first")
    other = ExclusionRule(rule_id="excl.a", description="second")
    with pytest.raises(ValidationError, match="duplicate exclusion rule_id"):
        build_contract(exclusions=(rule, other))


def test_duplicate_required_checks_are_refused() -> None:
    """RX-03 negative control: a repeated check id inflates apparent coverage."""
    with pytest.raises(ValidationError, match="duplicate required_check"):
        build_contract(required_checks=("chk.a", "chk.a"))


def test_units_for_an_undeclared_output_are_refused() -> None:
    """RX-03 negative control: a unit for a non-existent output is dead declaration."""
    with pytest.raises(ValidationError, match="undeclared output"):
        build_contract(units={"not_an_output": "g"})


def test_tolerance_for_an_undeclared_output_is_refused() -> None:
    """RX-03 negative control: a tolerance that can never be applied."""
    with pytest.raises(ValidationError, match="undeclared output"):
        build_contract(
            comparison=ComparisonSpec(
                algorithm="elementwise-abs-rel",
                tolerances={
                    "mean_body_mass": Tolerance(abs_tol=1.0),
                    "ghost": Tolerance(abs_tol=1.0),
                },
            )
        )


def test_unit_disagreement_inside_the_contract_is_refused() -> None:
    """RX-13: a unit mismatch is a failure, never a conversion."""
    with pytest.raises(ValidationError, match="unit mismatch"):
        build_contract(units={"mean_body_mass": "kg"})


def test_numeric_output_without_a_tolerance_is_refused() -> None:
    """RX-13 negative control: the verifier may not invent a threshold."""
    with pytest.raises(ValidationError, match="no\\s+declared tolerance"):
        build_contract(
            comparison=ComparisonSpec(algorithm="elementwise-abs-rel", tolerances={})
        )


def test_non_numeric_output_needs_no_tolerance() -> None:
    """RX-13 positive control: the tolerance rule applies only to numeric kinds."""
    contract = build_contract(
        output_definitions=(OutputDefinition(name="summary_note", kind=OutputKind.TEXT),),
        units={},
        comparison=ComparisonSpec(algorithm="exact-bytes", tolerances={}),
    )
    assert contract.comparison.tolerances == {}


def test_tolerance_with_no_declared_precision_is_refused() -> None:
    """RX-13 negative control: 'compare to no precision' is not a comparison."""
    with pytest.raises(ValidationError):
        Tolerance()


@pytest.mark.parametrize("value", [-1.0, float("inf"), float("nan")])
def test_invalid_tolerance_values_are_refused(value: float) -> None:
    """RX-13 negative control: a negative or infinite tolerance accepts anything."""
    with pytest.raises(ValidationError):
        Tolerance(abs_tol=value)


@pytest.mark.parametrize("fraction", [0.0, 1.0, -0.1, 1.1, float("nan")])
def test_split_fraction_must_be_strictly_inside_zero_and_one(fraction: float) -> None:
    """RX-03 negative control: an all-or-nothing 'split' is not a split."""
    with pytest.raises(ValidationError):
        SplitSpec(strategy="stratified", train_fraction=fraction)


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../outside.csv", "data/../../outside.csv", "C:/data.csv", "data\\x.csv", ""],
)
def test_reference_input_path_must_be_safe_and_relative(path: str) -> None:
    """RX-06/RX-42 negative control: an escaping reference path is refused."""
    with pytest.raises(ValidationError):
        ReferenceInput(path=path, sha256=digest("x"), role="raw")


@pytest.mark.parametrize(
    "bad_digest",
    ["", "abc", digest("x").upper(), digest("x")[:63], digest("x") + "0", "z" * 64],
)
def test_reference_input_sha256_must_be_lowercase_hex_64(bad_digest: str) -> None:
    """RX-01 negative control: a malformed digest is not accepted as a digest."""
    with pytest.raises(ValidationError):
        ReferenceInput(path="data/x.csv", sha256=bad_digest, role="raw")


def test_contract_version_must_be_at_least_one() -> None:
    """RX-03 negative control: version 0 is not a released declaration."""
    with pytest.raises(ValidationError):
        build_contract(contract_version=0)


def test_unknown_field_is_refused() -> None:
    """RX-10: an unexpected key is refused, not absorbed."""
    with pytest.raises(ValidationError):
        build_contract(sneaky_field="value")


def test_contract_is_immutable_with_a_named_exception() -> None:
    """RX-03: in-place mutation of a hashed record raises ContractImmutable."""
    contract = build_contract()
    with pytest.raises(ContractImmutable) as caught:
        contract.seed = 99
    assert caught.value.field == "seed"
    assert caught.value.record == "ResultContract"


def test_require_approval_raises_when_unapproved() -> None:
    """RX-04: acceptance against an unapproved contract raises ContractNotApproved."""
    contract = build_contract()
    assert contract.is_approved is False
    with pytest.raises(ContractNotApproved) as caught:
        contract.require_approval()
    assert caught.value.contract_hash == contract.contract_hash


def test_with_approval_links_a_matching_approval() -> None:
    """RX-04: a matching approval makes the contract approved, hash unchanged."""
    contract = build_contract()
    approval = build_approval(contract_hash=contract.contract_hash)
    approved = contract.with_approval(approval)
    assert approved.is_approved is True
    assert approved.require_approval() is approval
    assert contract.is_approved is False, "with_approval must not mutate the original"


def test_with_approval_refuses_an_approval_for_another_contract() -> None:
    """RX-05 negative control: an approval for a different hash cannot be attached."""
    contract = build_contract()
    foreign = build_approval(contract_hash=digest("some-other-contract"))
    with pytest.raises(ApprovalInvalidated) as caught:
        contract.with_approval(foreign)
    assert caught.value.field == "contract_hash"


def test_constructing_with_a_mismatched_approval_is_refused() -> None:
    """RX-05 negative control: the mismatch cannot be smuggled past the constructor."""
    foreign = build_approval(contract_hash=digest("some-other-contract"))
    with pytest.raises(ValidationError, match="different contract_hash"):
        build_contract(approval=foreign)


def test_is_approved_is_false_without_an_approval() -> None:
    """RX-04: absence of an approval is never read as approval."""
    assert build_contract(approval=None).is_approved is False


def test_canonical_document_is_inspectable() -> None:
    """RX-03: the exact digested string is available for review and diffing."""
    contract = build_contract()
    document = contract.canonical_document()
    assert document.startswith('{"@canonical_form":1,"@type":"retrace.ResultContract"')
    assert "approval" not in document

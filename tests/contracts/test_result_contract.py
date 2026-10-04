"""The hashed result contract and its approval reference (RX-03, RX-04, RX-13).

Covers the reconciliation recorded in
``docs/evidence/SPEC_RECONCILIATION_CLOSURE.md`` section 2: the original's field
names, the five fields the reconstruction had lost, the ``APPROVED`` conditional,
the ``NO_REFERENCE`` admissibility rule (RX-12, RX-17) and the external payload
boundary (RX-10, RX-47).

"""

from __future__ import annotations

from typing import Any

import pytest
from contracts_support import (  # noqa: F401
    AUTHOR,
    SERVER_ESTABLISHED,
    build_approval,
    build_contract,
    build_draft,
    declaration_fields,
    digest,
)
from pydantic import ValidationError
from retrace_contracts import (
    ComparisonSpec,
    ContractImmutable,
    ContractNotApproved,
    ContractStatus,
    ExclusionRule,
    OutputDefinition,
    OutputKind,
    Population,
    ReferenceInput,
    ReferenceKind,
    ResultContract,
    ResultContractDraft,
    SplitSpec,
    Tolerance,
    persist_contract_draft,
)
from retrace_contracts.result_contract import SCHEMA_VERSION, SERVER_ESTABLISHED_FIELDS

# One altered value per declared field. Each alteration keeps the contract
# internally valid, so the only thing under test is the digest's sensitivity.
FIELD_MUTATIONS: dict[str, Any] = {
    "contract_id": "rc-0002",
    "tenant_id": "tenant-0002",
    "project_id": "proj-other",
    "version": 2,
    "status": ContractStatus.SUPERSEDED,
    "reference_kind": ReferenceKind.NO_REFERENCE,
    "inputs": (
        ReferenceInput(
            id="data/penguins_synthetic.csv",
            sha256=digest("reference-input"),
            role="raw-measurements",
        ),
        ReferenceInput(
            id="data/reference_means.json",
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
    "limitations": ("SYNTHETIC fixture data only.",),
    "created_by": "F. A. Van Laarhoven",
    "approval_ref": "ap-ledger-0001",
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
        inputs=list(first.inputs),
        output_definitions=list(first.output_definitions),
        required_checks=list(first.required_checks),
        limitations=list(first.limitations),
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


# --------------------------------------------------------------------------- #
# The original's field names (closure section 2)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("original_name", "retired_name"),
    [
        ("version", "contract_version"),
        ("inputs", "reference_inputs"),
        ("limitations", "known_limits"),
        ("approval_ref", "approval"),
    ],
)
def test_the_originals_field_name_wins(original_name: str, retired_name: str) -> None:
    """Closure section 2: the recovered original's name is the name we carry.

    Asserting the retired spelling is *absent* matters as much as asserting the
    new one is present: a model that accepted both would let two names for one
    concept circulate, and `extra="forbid"` is what makes the old spelling a
    refusal rather than a silently ignored key.
    """
    assert original_name in ResultContract.model_fields
    assert retired_name not in ResultContract.model_fields
    with pytest.raises(ValidationError):
        build_contract(**{retired_name: "whatever"})


def test_reference_input_uses_the_originals_id_field_name() -> None:
    """Closure section 2: `ReferenceInput.path` is now `id`; `role` is kept."""
    assert set(ReferenceInput.model_fields) == {"id", "sha256", "role"}
    with pytest.raises(ValidationError):
        ReferenceInput(path="data/x.csv", sha256=digest("x"), role="raw")  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "field",
    ["contract_id", "tenant_id", "project_id", "version", "status", "reference_kind"],
)
def test_the_fields_the_reconstruction_had_lost_are_required(field: str) -> None:
    """Closure section 2 negative control: each recovered field is mandatory.

    `tenant_id` is the sharpest of these: without it a contract cannot be
    isolated by the RLS proven in `tests/postgres` (RX-47), so a contract that
    could omit it would not join to the tenancy half of the system at all.
    """
    fields = declaration_fields()
    fields.update(SERVER_ESTABLISHED)
    fields.pop(field)
    with pytest.raises(ValidationError):
        ResultContract(**fields)


# --------------------------------------------------------------------------- #
# Closed enums (closure section 4)
# --------------------------------------------------------------------------- #
def test_reference_kind_has_exactly_the_three_original_values() -> None:
    """Closure section 4: the original's vocabulary, with nothing added."""
    assert {member.value for member in ReferenceKind} == {
        "HISTORICAL_REFERENCE",
        "NEW_TEACHING_REFERENCE",
        "NO_REFERENCE",
    }


def test_contract_status_has_exactly_the_three_original_values() -> None:
    """Closure section 2: DRAFT / APPROVED / SUPERSEDED, and no fourth."""
    assert {member.value for member in ContractStatus} == {
        "DRAFT",
        "APPROVED",
        "SUPERSEDED",
    }


def test_synthetic_is_not_a_reference_kind() -> None:
    """Closure section 4 negative control: data provenance is a separate attribute.

    `SYNTHETIC` describes where the data came from. Admitting it here would let
    "the fixture data is synthetic" be stored in the field that answers "is
    there a reference to reproduce against?", which are different questions.
    """
    assert "SYNTHETIC" not in ReferenceKind.__members__
    with pytest.raises(ValueError):
        ReferenceKind("SYNTHETIC")
    with pytest.raises(ValidationError):
        build_contract(reference_kind="SYNTHETIC")


@pytest.mark.parametrize("bad", ["APPROVED_BY_CLIENT", "approved", "PENDING", ""])
def test_an_unlisted_status_is_refused(bad: str) -> None:
    """RX-04 negative control: the status vocabulary is closed."""
    with pytest.raises(ValidationError):
        build_contract(status=bad)


# --------------------------------------------------------------------------- #
# NO_REFERENCE admissibility (RX-12, RX-17)
# --------------------------------------------------------------------------- #
def test_no_reference_forbids_the_reproduced_outcome() -> None:
    """RX-12/RX-17: with no reference, `REPRODUCED_WITHIN_CONTRACT` is inadmissible.

    This is the machine-checkable form of the rule the verifier must consult.
    """
    contract = build_contract(reference_kind=ReferenceKind.NO_REFERENCE)
    assert contract.permits_reproduced_outcome is False
    assert contract.reference_kind.permits_reproduced_outcome is False


@pytest.mark.parametrize(
    "kind", [ReferenceKind.HISTORICAL_REFERENCE, ReferenceKind.NEW_TEACHING_REFERENCE]
)
def test_a_contract_with_a_reference_permits_the_reproduced_outcome(
    kind: ReferenceKind,
) -> None:
    """RX-12 positive control: the gate is not simply always False.

    A property that returned False for every input would also pass the negative
    control above while blocking every legitimate pass, so both directions are
    asserted.
    """
    assert build_contract(reference_kind=kind).permits_reproduced_outcome is True


def test_every_reference_kind_is_covered_by_the_admissibility_tests() -> None:
    """Meta-test: a fourth reference kind cannot slip past the two tests above."""
    covered = {
        ReferenceKind.NO_REFERENCE,
        ReferenceKind.HISTORICAL_REFERENCE,
        ReferenceKind.NEW_TEACHING_REFERENCE,
    }
    assert set(ReferenceKind) == covered


# --------------------------------------------------------------------------- #
# The APPROVED conditional and the approval reference (closure sections 2, 6)
# --------------------------------------------------------------------------- #
def test_approved_status_requires_an_approval_ref() -> None:
    """Closure section 2 negative control: the original's conditional is enforced.

    `if status == APPROVED then approval_ref is required`. Without this, a
    record could claim approval while naming no ledger entry, which is an
    unfalsifiable claim.
    """
    with pytest.raises(ValidationError, match="approval_ref is absent"):
        build_contract(status=ContractStatus.APPROVED)


@pytest.mark.parametrize("empty", [None, ""])
def test_approved_status_refuses_an_empty_approval_ref(empty: str | None) -> None:
    """Closure section 2 negative control: a blank reference is not a reference."""
    with pytest.raises(ValidationError):
        build_contract(status=ContractStatus.APPROVED, approval_ref=empty)


def test_an_approved_contract_names_its_ledger_record() -> None:
    """RX-04 positive control: APPROVED plus a reference is accepted."""
    contract = build_contract(status=ContractStatus.APPROVED, approval_ref="ap-0001")
    assert contract.is_approved is True
    assert contract.require_approval_ref() == "ap-0001"


@pytest.mark.parametrize("status", [ContractStatus.DRAFT, ContractStatus.SUPERSEDED])
def test_require_approval_ref_raises_when_not_approved(status: ContractStatus) -> None:
    """RX-04: acceptance against an unapproved contract raises ContractNotApproved.

    SUPERSEDED is included deliberately: a contract that *was* approved and has
    since been replaced must not keep authorising acceptance.
    """
    contract = build_contract(status=status, approval_ref="ap-0001")
    assert contract.is_approved is False
    with pytest.raises(ContractNotApproved) as caught:
        contract.require_approval_ref()
    assert caught.value.contract_hash == contract.contract_hash


def test_approval_ref_is_a_string_reference_not_an_embedded_record() -> None:
    """Closure section 6: the approval is referenced, never embedded.

    An embedded approval would have to contain the hash of the material it sits
    inside. Asserting the field refuses an Approval object is what keeps the
    recursion from being reintroduced.
    """
    approval = build_approval(contract_hash=digest("whatever"))
    with pytest.raises(ValidationError):
        build_contract(status=ContractStatus.APPROVED, approval_ref=approval)


def test_nothing_is_withheld_from_the_contract_digest() -> None:
    """Closure section 6: with no embedded approval there is nothing to exclude."""
    assert ResultContract.CANONICAL_EXCLUDE == frozenset()


def test_changing_approval_ref_changes_the_hash_without_hashing_the_approval() -> None:
    """Closure section 6: the digest covers the reference, not the approval record.

    Two properties in one test because they are two halves of the same decision:
    the reference is content (so it is hashed), and the approval record is not
    reachable from the contract at all (so no approval digest can recurse into
    the contract digest).
    """
    first = build_contract(status=ContractStatus.APPROVED, approval_ref="ap-0001")
    second = build_contract(status=ContractStatus.APPROVED, approval_ref="ap-0002")
    assert first.approval_ref != second.approval_ref
    assert first.contract_hash != second.contract_hash

    payload = first.canonical_payload()
    assert payload["approval_ref"] == "ap-0001"
    # The hashed payload carries the reference as a bare string: no approval
    # fields, and in particular no approval digest, are reachable from it.
    assert isinstance(payload["approval_ref"], str)
    for approval_field in ("approval", "candidate_hash", "approved_by", "binding_digest"):
        assert approval_field not in payload
    assert "binding_digest" not in first.canonical_document()


def test_approving_a_contract_changes_its_contract_hash() -> None:
    """`status` and `approval_ref` are hashed content, so the lifecycle moves it.

    This was originally recorded as an open consequence, with the guidance that
    the ledger must compare against the hash captured at approval time. That
    guidance has been SUPERSEDED by a fix rather than left as a caller
    obligation: approvals bind `declaration_digest`, which excludes the lifecycle
    label. The assertion here now checks the BEHAVIOUR - audit still sees the
    change, and the declaration's identity survives it - instead of asserting
    the wording of a limitation note, which is an implementation detail of the
    documentation and the wrong thing for a test to pin.
    """
    draft_state = build_contract(status=ContractStatus.DRAFT)
    approved_state = build_contract(status=ContractStatus.APPROVED, approval_ref="ap-0001")
    assert draft_state.contract_hash != approved_state.contract_hash
    assert draft_state.declaration_digest == approved_state.declaration_digest


# --------------------------------------------------------------------------- #
# The external payload boundary (RX-10, RX-47)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field", list(SERVER_ESTABLISHED_FIELDS))
def test_the_external_draft_cannot_carry_a_server_established_field(field: str) -> None:
    """RX-10/RX-47 negative control: a client cannot submit its own tenant or status.

    The refusal matters more than the omission. If the field were merely
    dropped, a client would be told its submission succeeded while the
    `tenant_id` it chose -- or the `APPROVED` it claimed -- was discarded, and
    nothing would surface the attempt.
    """
    values = {
        "contract_id": "rc-attacker",
        "tenant_id": "tenant-victim",
        "status": ContractStatus.APPROVED,
        "approval_ref": "ap-forged",
    }
    assert field not in ResultContractDraft.model_fields
    with pytest.raises(ValidationError) as caught:
        build_draft(**{field: values[field]})
    assert "extra_forbidden" in str(caught.value)


def test_the_draft_carries_exactly_the_client_authorable_declaration() -> None:
    """RX-10: the boundary model's shape is asserted, not assumed."""
    assert set(ResultContractDraft.model_fields) == set(ResultContract.model_fields) - set(
        SERVER_ESTABLISHED_FIELDS
    )


def test_persisting_a_draft_produces_an_equivalent_contract() -> None:
    """RX-10 positive control: the boundary is passable with server-held values."""
    draft = build_draft()
    contract = persist_contract_draft(
        draft, contract_id="rc-0001", tenant_id="tenant-0001", status=ContractStatus.DRAFT
    )
    assert contract == build_contract()
    assert contract.tenant_id == "tenant-0001"
    assert contract.status is ContractStatus.DRAFT
    assert contract.approval_ref is None


def test_persisting_a_draft_takes_tenancy_from_the_caller_not_the_payload() -> None:
    """RX-47: the tenant is whatever the server passed, and the draft cannot say.

    Negative control for the same property: the draft carries `project_id`
    (which the server authorises) but has no way to express `tenant_id` at all,
    so there is no payload value for this function to prefer by mistake.
    """
    draft = build_draft(project_id="proj-penguins")
    contract = persist_contract_draft(draft, contract_id="rc-9", tenant_id="tenant-server")
    assert contract.tenant_id == "tenant-server"
    assert "tenant_id" not in draft.model_dump()


def test_the_draft_is_held_to_the_same_scientific_invariants() -> None:
    """RX-03/RX-13: a malformed declaration is refused at the boundary.

    A boundary model that validated less would accept a submission and refuse it
    later, after the client had been told it succeeded.
    """
    with pytest.raises(ValidationError, match="no\\s+declared tolerance"):
        build_draft(comparison=ComparisonSpec(algorithm="elementwise-abs-rel", tolerances={}))
    with pytest.raises(ValidationError):
        build_draft(limitations=())
    with pytest.raises(ValidationError, match="duplicate input id"):
        reference = ReferenceInput(id="data/x.csv", sha256=digest("x"), role="raw")
        build_draft(inputs=(reference, reference))


def test_persisting_refuses_an_approved_status_with_no_reference() -> None:
    """RX-04 negative control: the conditional holds on the persistence path too."""
    with pytest.raises(ValidationError, match="approval_ref is absent"):
        persist_contract_draft(
            build_draft(),
            contract_id="rc-1",
            tenant_id="tenant-1",
            status=ContractStatus.APPROVED,
        )


# --------------------------------------------------------------------------- #
# Document shape version vs scientific version (closure section 5)
# --------------------------------------------------------------------------- #
def test_schema_version_and_contract_version_are_not_conflated() -> None:
    """Closure section 5: two different versions, neither derived from the other.

    `SCHEMA_VERSION` versions the document *shape* for everyone;
    `ResultContract.version` versions one researcher's declaration. A contract
    at version 7 does not imply shape 7, and bumping the shape does not bump
    anyone's contract.
    """
    assert "SCHEMA_VERSION" not in ResultContract.model_fields
    contract = build_contract(version=7)
    assert contract.version == 7
    assert SCHEMA_VERSION == 2
    assert contract.version != SCHEMA_VERSION
    # The shape version is a module constant, so no instance can move it.
    assert SCHEMA_VERSION == 2


def test_contract_version_must_be_at_least_one() -> None:
    """RX-03 negative control: version 0 is not a released declaration."""
    with pytest.raises(ValidationError):
        build_contract(version=0)


# --------------------------------------------------------------------------- #
# Invariants retained from before the reconciliation
# --------------------------------------------------------------------------- #
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


def test_limitations_must_be_non_empty() -> None:
    """Closure section 2 negative control: deliberately stricter than the original.

    The original requires `limitations` to be present but permits an empty
    array. A contract stating no limits claims the declaration has no boundary,
    so the stricter rule is kept.
    """
    with pytest.raises(ValidationError):
        build_contract(limitations=())


def test_whitespace_only_limitation_is_refused() -> None:
    """RX-03 negative control: a blank limit is not a stated limit."""
    with pytest.raises(ValidationError):
        build_contract(limitations=("   ",))


def test_output_definitions_must_be_non_empty() -> None:
    """RX-03 negative control: there is nothing to reproduce with no outputs."""
    with pytest.raises(ValidationError):
        build_contract(output_definitions=())


def test_inputs_must_be_non_empty() -> None:
    """Closure section 2 negative control: the original's `minItems: 1` is adopted.

    A contract pinning no inputs has no input identity for RX-01 to check.
    """
    with pytest.raises(ValidationError):
        build_contract(inputs=())


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


def test_duplicate_input_ids_are_refused() -> None:
    """RX-03 negative control: the same input declared twice."""
    reference = ReferenceInput(
        id="data/penguins_synthetic.csv", sha256=digest("x"), role="raw"
    )
    with pytest.raises(ValidationError, match="duplicate input id"):
        build_contract(inputs=(reference, reference))


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
    "bad_id",
    ["/etc/passwd", "../outside.csv", "data/../../outside.csv", "C:/data.csv", "data\\x.csv", ""],
)
def test_reference_input_id_must_be_safe_and_relative(bad_id: str) -> None:
    """RX-06/RX-42 negative control: an escaping input id is refused.

    The original schema constrains `id` only to a non-empty string. Keeping the
    traversal rule is stricter than the original and is what stops an id from
    resolving outside the snapshot when the verifier reads the pinned bytes.
    """
    with pytest.raises(ValidationError):
        ReferenceInput(id=bad_id, sha256=digest("x"), role="raw")


@pytest.mark.parametrize(
    "bad_digest",
    ["", "abc", digest("x").upper(), digest("x")[:63], digest("x") + "0", "z" * 64],
)
def test_reference_input_sha256_must_be_lowercase_hex_64(bad_digest: str) -> None:
    """RX-01 negative control: a malformed digest is not accepted as a digest."""
    with pytest.raises(ValidationError):
        ReferenceInput(id="data/x.csv", sha256=bad_digest, role="raw")


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


def test_the_draft_is_immutable_too() -> None:
    """RX-03: the boundary payload is a frozen record, not a mutable bag."""
    draft = build_draft()
    with pytest.raises(ContractImmutable):
        draft.seed = 99


def test_canonical_document_is_inspectable() -> None:
    """RX-03: the exact digested string is available for review and diffing."""
    contract = build_contract()
    document = contract.canonical_document()
    assert document.startswith('{"@canonical_form":1,"@type":"retrace.ResultContract"')
    assert '"tenant_id":"tenant-0001"' in document


def test_the_draft_digests_under_its_own_type_tag() -> None:
    """RX-03: a draft and a contract with the same declaration do not collide.

    Domain separation is the point: a payload that has not been through the
    server must not produce the digest of a persisted record.
    """
    draft = build_draft()
    contract = build_contract()
    assert draft.canonical_type_tag() == "retrace.ResultContractDraft"
    assert contract.canonical_type_tag() == "retrace.ResultContract"
    assert draft.content_digest() != contract.contract_hash


# --------------------------------------------------------------------------- #
# declaration_digest - what an approval binds (RX-03, RX-05)
#
# The reconciliation made `approval_ref` and `status` plain hashed content, which
# meant DRAFT, APPROVED and SUPERSEDED versions of one contract had three
# different `contract_hash` values - so an approval binding the DRAFT hash
# matched nothing once the record it approved was marked APPROVED. Approving a
# contract would have invalidated the approval it recorded. `declaration_digest`
# excludes the lifecycle label; `contract_hash` still covers everything for audit.
# --------------------------------------------------------------------------- #
def test_the_declaration_digest_is_stable_across_the_lifecycle(
    contract_factory,
) -> None:
    """DRAFT -> APPROVED -> SUPERSEDED is the same declaration throughout."""
    draft = contract_factory()
    approved = contract_factory(status=ContractStatus.APPROVED, approval_ref="ap-1")
    superseded = contract_factory(status=ContractStatus.SUPERSEDED, approval_ref="ap-1")
    assert draft.declaration_digest == approved.declaration_digest
    assert approved.declaration_digest == superseded.declaration_digest


def test_contract_hash_still_changes_across_the_lifecycle(contract_factory) -> None:
    """DISCRIMINATION CONTROL: the two digests must not be the same thing.

    If `contract_hash` were also stable here, `declaration_digest` would be
    redundant and this file would be testing nothing. Audit wants every change
    visible; approval wants the declaration's identity. Both, separately.
    """
    draft = contract_factory()
    approved = contract_factory(status=ContractStatus.APPROVED, approval_ref="ap-1")
    assert draft.contract_hash != approved.contract_hash
    assert draft.declaration_digest != draft.contract_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 2),
        ("created_by", "someone-else"),
        ("limitations", ("a different limit",)),
        ("reference_kind", ReferenceKind.NO_REFERENCE),
        ("seed", 999),
        ("population", Population(expected_count=999, selection_rule="all")),
    ],
)
def test_any_declaration_edit_changes_the_declaration_digest(
    contract_factory, field: str, value: object
) -> None:
    """The property that matters: editing the declaration invalidates approval."""
    before = contract_factory()
    after = contract_factory(**{field: value})
    assert before.declaration_digest != after.declaration_digest, (
        f"editing {field} left the declaration digest unchanged, so an approval "
        "would survive a change to the material it authorised"
    )


def test_widening_a_tolerance_changes_the_declaration_digest(contract_factory) -> None:
    """The anti-goalpost-move case, stated separately because it is the one an
    author has the strongest incentive to attempt after seeing a result."""
    before = contract_factory()
    widened = ComparisonSpec(
        algorithm=before.comparison.algorithm,
        tolerances={
            name: Tolerance(abs_tol=99.0) for name in before.comparison.tolerances
        },
    )
    after = contract_factory(comparison=widened)
    assert before.declaration_digest != after.declaration_digest

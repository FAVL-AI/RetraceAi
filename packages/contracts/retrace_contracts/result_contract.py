"""The versioned, hashed result contract (RX-03, RX-04).

A result contract is the scientific declaration a reproduction attempt is
judged against: which inputs count as reference, what the outputs are, which
population and exclusions apply, which seed and split, how a comparison is
made and to what tolerance, which checks are required -- and what the authors
already know the contract cannot establish.

Two design rules shape this module:

1. **The hash is the identity.** ``contract_hash`` is a SHA-256 over the
   canonical form in :mod:`retrace_contracts.canonical`. Semantically equal
   contracts hash equal; changing any declared field changes the hash (RX-03).
2. **Approval is a link to the hash, never a field inside it.** An approval
   binds ``contract_hash``, so it cannot take part in computing it. The
   ``approval`` field is therefore the single member of
   :attr:`ResultContract.CANONICAL_EXCLUDE`, and the exclusion is asserted in
   the tests so it stays deliberate.

"""

from __future__ import annotations

from typing import Annotated, ClassVar

from pydantic import Field, field_validator, model_validator

from .approval import Approval
from .base import FrozenRecord, Identifier, NonEmptyStr, Sha256Hex
from .enums import OutputKind
from .exceptions import ApprovalInvalidated, ContractNotApproved
from .paths import validate_relative_path

__all__ = [
    "ComparisonSpec",
    "ExclusionRule",
    "OutputDefinition",
    "Population",
    "ReferenceInput",
    "ResultContract",
    "SplitSpec",
    "Tolerance",
]

NonNegativeFiniteFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
UnitFraction = Annotated[float, Field(gt=0.0, lt=1.0, allow_inf_nan=False)]


class ReferenceInput(FrozenRecord):
    """One reference input pinned by content digest (RX-01, RX-03).

    ``path`` is snapshot-relative and traversal-free; ``sha256`` pins the exact
    bytes, so "the contract's reference inputs" is a verifiable statement rather
    than a filename convention.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ReferenceInput"

    path: NonEmptyStr = Field(description="Snapshot-relative path to the reference input.")
    sha256: Sha256Hex = Field(description="SHA-256 of the exact reference bytes.")
    role: NonEmptyStr = Field(
        description="Why this input is referenced, e.g. 'raw-measurements' or 'reference-output'."
    )

    @field_validator("path")
    @classmethod
    def _path_is_snapshot_relative(cls, value: str) -> str:
        """Refuse absolute or traversing reference paths (RX-06, RX-42)."""
        return validate_relative_path(value, field="ReferenceInput.path")


class OutputDefinition(FrozenRecord):
    """One declared output of the workflow (RX-03, RX-13).

    ``unit`` is optional only for dimensionless or non-numeric outputs. When it
    is present it must agree with the contract-level ``units`` mapping; a
    contract that declares two different units for the same output is
    self-contradictory and is refused (see :class:`ResultContract`).
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.OutputDefinition"

    name: Identifier = Field(description="Output name, unique within the contract.")
    kind: OutputKind = Field(description="Output kind; decides which comparison is admissible.")
    unit: NonEmptyStr | None = Field(
        default=None,
        description="Physical unit, or None for a dimensionless or non-numeric output.",
    )
    dtype: NonEmptyStr | None = Field(
        default=None, description="Declared data type, e.g. 'float64' or 'int32'."
    )


class Population(FrozenRecord):
    """The expected population and how it is selected (RX-03, RX-14).

    ``expected_count`` is the row/record count the contract asserts. A
    reproduction that produces a different count is a changed population, which
    is a methodology delta (RX-14), not a numeric difference.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.Population"

    expected_count: int = Field(ge=0, description="Expected number of rows/records.")
    selection_rule: NonEmptyStr = Field(
        description="The rule by which records enter the population, stated explicitly."
    )


class SplitSpec(FrozenRecord):
    """A declared train/evaluation split (RX-03, RX-14).

    ``train_fraction`` is strictly between 0 and 1: a 'split' that assigns
    everything to one side is not a split, and silently accepting 0.0 or 1.0
    would let a contract declare a split it does not perform.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.SplitSpec"

    strategy: NonEmptyStr = Field(description="Split strategy, e.g. 'stratified-by-species'.")
    train_fraction: UnitFraction = Field(description="Fraction assigned to train; 0 < f < 1.")
    seed: int | None = Field(default=None, description="Split seed, or None if not seeded.")


class Tolerance(FrozenRecord):
    """Per-output comparison tolerance (RX-03, RX-13).

    At least one of ``abs_tol`` / ``rel_tol`` must be declared. A tolerance
    record with neither would mean "compare to no stated precision", which is
    not a comparison, so it is refused. Non-finite and negative tolerances are
    refused for the same reason: a tolerance of ``inf`` accepts everything.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.Tolerance"

    abs_tol: NonNegativeFiniteFloat | None = Field(
        default=None, description="Absolute tolerance; finite and non-negative."
    )
    rel_tol: NonNegativeFiniteFloat | None = Field(
        default=None, description="Relative tolerance; finite and non-negative."
    )

    @model_validator(mode="after")
    def _at_least_one_tolerance(self) -> Tolerance:
        """Refuse a tolerance that declares no precision at all (RX-13)."""
        if self.abs_tol is None and self.rel_tol is None:
            raise ValueError(
                "Tolerance must declare abs_tol, rel_tol, or both; "
                "a comparison with no stated precision is not a comparison"
            )
        return self


class ComparisonSpec(FrozenRecord):
    """The comparison algorithm and its per-output tolerances (RX-03, RX-13)."""

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ComparisonSpec"

    algorithm: NonEmptyStr = Field(
        description="Named comparison algorithm, e.g. 'elementwise-abs-rel'."
    )
    tolerances: dict[str, Tolerance] = Field(
        default_factory=dict,
        description="Output name -> tolerance. Keys must name declared outputs.",
    )


class ExclusionRule(FrozenRecord):
    """One explicit exclusion rule (RX-03, RX-14).

    Exclusions are structured rather than free prose so that an altered
    exclusion can be reported as a named methodology delta.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ExclusionRule"

    rule_id: Identifier = Field(description="Stable id, unique within the contract.")
    description: NonEmptyStr = Field(description="What is excluded and why.")
    expression: NonEmptyStr | None = Field(
        default=None,
        description="Optional machine-checkable form of the rule. Not evaluated by this layer.",
    )


class ResultContract(FrozenRecord):
    """A versioned, hashed scientific declaration (RX-03, RX-04).

    Invariants enforced at construction, each with a negative control in
    ``tests/contracts/test_result_contract.py``:

    * ``known_limits`` is non-empty. A contract that states no limits is not
      acceptable: it claims the declaration has no boundary, which is never
      true of a real scientific result.
    * ``output_definitions`` is non-empty. There is nothing to reproduce
      otherwise.
    * output names, reference paths, exclusion ids and required check ids are
      each unique.
    * every key of ``units`` and of ``comparison.tolerances`` names a declared
      output -- a tolerance for an output that does not exist is dead
      declaration that reads as coverage.
    * ``units[name]`` agrees with that output's own ``unit`` when both are
      given (RX-13: unit mismatch is a failure, never a conversion).
    * every numeric output has a declared tolerance; without one the verifier
      has no admissible comparison and would have to invent a threshold.

    Immutability: sequence fields are ``tuple`` so they cannot be appended to
    after construction. ``units`` and ``comparison.tolerances`` are ``dict``
    because RX-03 specifies a mapping, and pydantic cannot freeze a dict in
    place -- see :attr:`KNOWN_SHAPE_LIMITS`.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ResultContract"
    CANONICAL_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"approval"})

    KNOWN_SHAPE_LIMITS: ClassVar[tuple[str, ...]] = (
        "`units` and `comparison.tolerances` are dicts, so they are only "
        "shallow-immutable: mutating one in place after construction changes "
        "`contract_hash` with no exception raised. Treat a constructed contract "
        "as read-only; the digest follows content, so a mutated contract no "
        "longer matches any approval bound to its previous hash.",
        "`contract_hash` covers declared content only. It is not a signature "
        "and asserts nothing about who authored or approved the contract.",
    )

    reference_inputs: tuple[ReferenceInput, ...] = Field(
        default=(), description="Inputs that count as reference, pinned by digest (RX-01)."
    )
    output_definitions: tuple[OutputDefinition, ...] = Field(
        min_length=1, description="The outputs this contract judges."
    )
    population: Population = Field(description="Expected record count and selection rule.")
    units: dict[str, str] = Field(
        default_factory=dict, description="Output name -> unit. Keys must name declared outputs."
    )
    exclusions: tuple[ExclusionRule, ...] = Field(
        default=(), description="Explicit exclusion rules (RX-14)."
    )
    seed: int | None = Field(default=None, description="Seed, or None when none is declared.")
    split: SplitSpec | None = Field(default=None, description="Declared split, or None.")
    comparison: ComparisonSpec = Field(description="Comparison algorithm and tolerances.")
    required_checks: tuple[Identifier, ...] = Field(
        default=(), description="Ids of the checks a verification must run."
    )
    known_limits: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="What this contract does NOT establish. Must be non-empty.",
    )
    contract_version: int = Field(ge=1, description="Monotonic contract version.")
    created_by: NonEmptyStr = Field(description="Identity of the contract author.")
    approval: Approval | None = Field(
        default=None,
        description=(
            "Approval linkage (RX-04/RX-05). Excluded from contract_hash because an "
            "approval binds to that hash and cannot be inside it."
        ),
    )

    @model_validator(mode="after")
    def _check_internal_consistency(self) -> ResultContract:
        """Enforce the contract-level invariants listed in the class docstring."""
        output_names = [definition.name for definition in self.output_definitions]
        duplicates = sorted({name for name in output_names if output_names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate output name(s): {', '.join(duplicates)}")

        paths = [reference.path for reference in self.reference_inputs]
        duplicate_paths = sorted({path for path in paths if paths.count(path) > 1})
        if duplicate_paths:
            raise ValueError(f"duplicate reference input path(s): {', '.join(duplicate_paths)}")

        rule_ids = [rule.rule_id for rule in self.exclusions]
        duplicate_rules = sorted({rid for rid in rule_ids if rule_ids.count(rid) > 1})
        if duplicate_rules:
            raise ValueError(f"duplicate exclusion rule_id(s): {', '.join(duplicate_rules)}")

        duplicate_checks = sorted(
            {check for check in self.required_checks if self.required_checks.count(check) > 1}
        )
        if duplicate_checks:
            raise ValueError(f"duplicate required_check id(s): {', '.join(duplicate_checks)}")

        known_outputs = set(output_names)
        unknown_units = sorted(set(self.units) - known_outputs)
        if unknown_units:
            raise ValueError(
                f"units names undeclared output(s): {', '.join(unknown_units)}; "
                "a unit for an output that does not exist is dead declaration"
            )
        unknown_tolerances = sorted(set(self.comparison.tolerances) - known_outputs)
        if unknown_tolerances:
            raise ValueError(
                "comparison.tolerances names undeclared output(s): "
                f"{', '.join(unknown_tolerances)}"
            )

        for definition in self.output_definitions:
            declared_unit = self.units.get(definition.name)
            if declared_unit is not None and definition.unit is not None:
                if declared_unit != definition.unit:
                    raise ValueError(
                        f"unit mismatch for output {definition.name!r}: "
                        f"units={declared_unit!r} but OutputDefinition.unit={definition.unit!r}. "
                        "A unit disagreement is a failure, never a conversion (RX-13)"
                    )
            if definition.kind.is_numeric and definition.name not in self.comparison.tolerances:
                raise ValueError(
                    f"numeric output {definition.name!r} (kind={definition.kind.value}) has no "
                    "declared tolerance; the verifier would have to invent a threshold (RX-13)"
                )

        if self.approval is not None and self.approval.contract_hash != self.contract_hash:
            raise ValueError(
                "linked approval binds a different contract_hash "
                f"({self.approval.contract_hash}) than this contract ({self.contract_hash})"
            )
        return self

    @property
    def contract_hash(self) -> str:
        """SHA-256 over the canonical form of the declared contract (RX-03).

        Covers every declared field and excludes only ``approval``, which binds
        to this value. Recomputed on access; it is never stored, so a contract
        cannot carry a digest that disagrees with its own content.
        """
        return self.content_digest()

    @property
    def is_approved(self) -> bool:
        """Whether a linked approval binds exactly this contract hash (RX-04).

        ``False`` when there is no approval, and ``False`` when the linked
        approval binds a different hash. The constructor already refuses a
        mismatched link, so a ``False`` here means "no approval present".
        """
        return self.approval is not None and self.approval.contract_hash == self.contract_hash

    def require_approval(self) -> Approval:
        """Return the linked approval or raise :class:`ContractNotApproved` (RX-04).

        The acceptance path for a candidate repair calls this instead of testing
        a boolean, so the refusal is a named exception that cannot be read as a
        falsy value.
        """
        if not self.is_approved:
            raise ContractNotApproved(contract_hash=self.contract_hash)
        assert self.approval is not None  # narrowed by is_approved
        return self.approval

    def with_approval(self, approval: Approval) -> ResultContract:
        """Return a new contract carrying ``approval`` (RX-04, RX-05).

        The contract itself is never mutated. Raises
        :class:`ApprovalInvalidated` if the approval binds a different
        ``contract_hash``, because attaching such an approval would create a
        record that claims an approval it does not have.
        """
        if approval.contract_hash != self.contract_hash:
            raise ApprovalInvalidated(
                field="contract_hash",
                fields=("contract_hash",),
                expected={"contract_hash": approval.contract_hash},
                observed={"contract_hash": self.contract_hash},
                approval_id=approval.approval_id,
            )
        return self.model_copy(update={"approval": approval})

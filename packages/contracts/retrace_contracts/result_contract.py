"""The versioned, hashed result contract (RX-03, RX-04, RX-12, RX-17, RX-47).

A result contract is the scientific declaration a reproduction attempt is
judged against: which inputs are pinned, what the outputs are, which population
and exclusions apply, which seed and split, how a comparison is made and to
what tolerance, which checks are required -- and what the authors already know
the contract cannot establish.

This module implements the field-by-field decisions recorded in
``docs/evidence/SPEC_RECONCILIATION_CLOSURE.md`` section 2, which reconciles
this model against the recovered original ``result-contract.schema.json``. The
original's names win; the original's required set is adopted; the extension
fields the original cannot express are kept and recorded there.

Four design rules shape this module:

1. **The hash is the identity.** ``contract_hash`` is a SHA-256 over the
   canonical form in :mod:`retrace_contracts.canonical`. Semantically equal
   contracts hash equal; changing any declared field changes the hash (RX-03).
2. **An approval is referenced, never embedded.** ``approval_ref`` is a string
   reference into the approval ledger. Embedding the approval inside the
   material it authorises was a digest-recursion hazard: the approval binds a
   contract hash, so it could not be inside the value it binds. Because
   ``approval_ref`` is now plain content, :attr:`ResultContract.CANONICAL_EXCLUDE`
   is empty and nothing is withheld from the digest (closure section 6).
3. **Identity, tenancy and lifecycle are server-established.** ``contract_id``,
   ``tenant_id``, ``status`` and ``approval_ref`` are not client-authorable; a
   client-supplied ``"APPROVED"`` establishes nothing. The external payload is
   :class:`ResultContractDraft`, which cannot carry them at all (RX-10, RX-47).
4. **``NO_REFERENCE`` can never be read as a pass.** The contract answers that
   question itself through :attr:`ResultContract.permits_reproduced_outcome`,
   so the verifier consults a declared property instead of re-deriving the rule
   (RX-12, RX-17).

"""

from __future__ import annotations

from typing import Annotated, ClassVar, Final

from pydantic import Field, field_validator, model_validator

from .base import FrozenRecord, Identifier, NonEmptyStr, Sha256Hex
from .canonical import canonical_digest
from .enums import ContractStatus, OutputKind, ReferenceKind
from .exceptions import ContractNotApproved
from .paths import validate_relative_path

__all__ = [
    "ComparisonSpec",
    "ExclusionRule",
    "OutputDefinition",
    "Population",
    "ReferenceInput",
    "ResultContract",
    "ResultContractDraft",
    "SCHEMA_VERSION",
    "SERVER_ESTABLISHED_FIELDS",
    "SplitSpec",
    "Tolerance",
    "persist_contract_draft",
]

SCHEMA_VERSION: Final[int] = 2
"""Version of the result-contract DOCUMENT SHAPE -- not of any one contract.

Distinct from :attr:`ResultContract.version`, which is the revision number of a
*particular scientific declaration* and is authored by a researcher. This
constant moves when the shape of the document changes for everyone, and the two
must never be derived from one another (closure section 5). It is ``2`` because
the reconciliation renamed four fields and added five required ones: a document
version that does not move across a breaking shape change is a version that
lies. ``retrace_contracts.export_schemas`` stamps it into the generated
schema's ``$id``, so the constant is load-bearing rather than decorative.
"""

SERVER_ESTABLISHED_FIELDS: Final[tuple[str, ...]] = (
    "contract_id",
    "tenant_id",
    "status",
    "approval_ref",
)
"""Fields a client may never submit; the server establishes each one.

``tenant_id`` decides which rows RLS will let a principal see (RX-47), and
``status``/``approval_ref`` are the authority claim itself (RX-04). A payload
that could carry them would let a client choose its own tenant or declare its
own approval. :class:`ResultContractDraft` omits every name in this tuple and
inherits ``extra="forbid"``, so submitting one is refused rather than ignored.
"""

NonNegativeFiniteFloat = Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
UnitFraction = Annotated[float, Field(gt=0.0, lt=1.0, allow_inf_nan=False)]


class ReferenceInput(FrozenRecord):
    """One pinned contract input, identified and digested (RX-01, RX-03).

    ``id`` adopts the original schema's field name (it was ``path``). The
    original constrains it only to a non-empty string; this model keeps the
    stricter rule that it is a snapshot-relative, traversal-free POSIX path,
    because that is what the verifier resolves when it reads the bytes the
    digest pins (RX-06, RX-42). A stricter constraint still satisfies the
    original.

    ``role`` is a recorded extension: the original has no way to say whether a
    pinned input is raw measurement data or the reference output a result is
    compared against, and the verifier needs that distinction to tell
    ``BLOCKED_MISSING_EVIDENCE`` from ``EXECUTED_NOT_VERIFIED``.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ReferenceInput"

    id: NonEmptyStr = Field(description="Snapshot-relative identifier of the pinned input.")
    sha256: Sha256Hex = Field(description="SHA-256 of the exact pinned bytes.")
    role: NonEmptyStr = Field(
        description="Why this input is pinned, e.g. 'raw-measurements' or 'reference-output'."
    )

    @field_validator("id")
    @classmethod
    def _id_is_snapshot_relative(cls, value: str) -> str:
        """Refuse an absolute or traversing input id (RX-06, RX-42)."""
        return validate_relative_path(value, field="ReferenceInput.id")


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
    """The comparison algorithm and its per-output tolerances (RX-03, RX-13).

    Recorded drift: the recovered original carries a tolerance on each required
    check rather than in one contract-level mapping, and closure section 3
    decided to adopt that object form. It is sequenced after this change
    because it alters the verifier's comparison path, so until it lands the
    tolerances still live here. That is recorded drift, not silence.
    """

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


def _check_declaration_consistency(
    *,
    inputs: tuple[ReferenceInput, ...],
    output_definitions: tuple[OutputDefinition, ...],
    units: dict[str, str],
    exclusions: tuple[ExclusionRule, ...],
    comparison: ComparisonSpec,
    required_checks: tuple[str, ...],
) -> None:
    """Enforce the invariants shared by a draft and a persisted contract (RX-03, RX-13).

    Factored out so the external payload is held to exactly the same scientific
    rules as the persisted record. A boundary model that validated less would
    push refusals past the boundary, where the caller has already been told the
    submission was accepted.

    Raises
    ------
    ValueError:
        Naming the specific rule broken. Pydantic turns this into a
        ``ValidationError`` at model construction.
    """
    output_names = [definition.name for definition in output_definitions]
    duplicates = sorted({name for name in output_names if output_names.count(name) > 1})
    if duplicates:
        raise ValueError(f"duplicate output name(s): {', '.join(duplicates)}")

    input_ids = [item.id for item in inputs]
    duplicate_ids = sorted({value for value in input_ids if input_ids.count(value) > 1})
    if duplicate_ids:
        raise ValueError(f"duplicate input id(s): {', '.join(duplicate_ids)}")

    rule_ids = [rule.rule_id for rule in exclusions]
    duplicate_rules = sorted({rid for rid in rule_ids if rule_ids.count(rid) > 1})
    if duplicate_rules:
        raise ValueError(f"duplicate exclusion rule_id(s): {', '.join(duplicate_rules)}")

    duplicate_checks = sorted(
        {check for check in required_checks if required_checks.count(check) > 1}
    )
    if duplicate_checks:
        raise ValueError(f"duplicate required_check id(s): {', '.join(duplicate_checks)}")

    known_outputs = set(output_names)
    unknown_units = sorted(set(units) - known_outputs)
    if unknown_units:
        raise ValueError(
            f"units names undeclared output(s): {', '.join(unknown_units)}; "
            "a unit for an output that does not exist is dead declaration"
        )
    unknown_tolerances = sorted(set(comparison.tolerances) - known_outputs)
    if unknown_tolerances:
        raise ValueError(
            f"comparison.tolerances names undeclared output(s): {', '.join(unknown_tolerances)}"
        )

    for definition in output_definitions:
        declared_unit = units.get(definition.name)
        if declared_unit is not None and definition.unit is not None:
            if declared_unit != definition.unit:
                raise ValueError(
                    f"unit mismatch for output {definition.name!r}: "
                    f"units={declared_unit!r} but OutputDefinition.unit={definition.unit!r}. "
                    "A unit disagreement is a failure, never a conversion (RX-13)"
                )
        if definition.kind.is_numeric and definition.name not in comparison.tolerances:
            raise ValueError(
                f"numeric output {definition.name!r} (kind={definition.kind.value}) has no "
                "declared tolerance; the verifier would have to invent a threshold (RX-13)"
            )


class ResultContractDraft(FrozenRecord):
    """The EXTERNAL create/update payload for a result contract (RX-10, RX-47).

    This is a security boundary, not a convenience type. Every field in
    :data:`SERVER_ESTABLISHED_FIELDS` is absent here, and ``FrozenRecord`` sets
    ``extra="forbid"``, so a client that submits ``tenant_id`` (choosing which
    tenant's rows it joins, defeating the RLS proven in ``tests/postgres``) or
    ``status="APPROVED"`` (claiming its own authority) is **refused** rather
    than having the field quietly dropped. Dropping would be worse than
    refusing: the client would be told its submission succeeded while the value
    it cared about was discarded.

    The draft is held to the same scientific invariants as the persisted record
    via :func:`_check_declaration_consistency`, so a malformed declaration is
    refused at the boundary rather than after persistence.

    Use :func:`persist_contract_draft` to combine a draft with the
    server-established values and obtain a :class:`ResultContract`.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ResultContractDraft"

    project_id: Identifier = Field(
        description="Project the contract belongs to. Authorised server-side against the caller."
    )
    version: int = Field(ge=1, description="Monotonic revision of this scientific declaration.")
    reference_kind: ReferenceKind = Field(
        description="What kind of reference this contract is judged against (RX-12, RX-17)."
    )
    inputs: tuple[ReferenceInput, ...] = Field(
        min_length=1, description="Pinned inputs, each identified and digested (RX-01)."
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
        description="Ids of the checks a verification must run."
    )
    limitations: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="What this contract does NOT establish. Must be non-empty.",
    )
    created_by: NonEmptyStr = Field(
        description="Identity the author claims. Server-side authentication is the authority."
    )

    @model_validator(mode="after")
    def _check_internal_consistency(self) -> ResultContractDraft:
        """Hold the external payload to the persisted record's invariants (RX-03)."""
        _check_declaration_consistency(
            inputs=self.inputs,
            output_definitions=self.output_definitions,
            units=self.units,
            exclusions=self.exclusions,
            comparison=self.comparison,
            required_checks=self.required_checks,
        )
        return self


class ResultContract(FrozenRecord):
    """A versioned, hashed scientific declaration (RX-03, RX-04, RX-12, RX-47).

    Field names follow the recovered original (closure section 2): ``version``
    (was ``contract_version``), ``inputs`` (was ``reference_inputs``),
    ``limitations`` (was ``known_limits``) and ``approval_ref`` (was an embedded
    ``approval``). ``contract_id``, ``tenant_id``, ``project_id``, ``status``
    and ``reference_kind`` are additions the original required and the
    reconstruction had lost.

    Invariants enforced at construction, each with a negative control in
    ``tests/contracts/test_result_contract.py``:

    * ``limitations`` is non-empty. The original does not require this; it is
      deliberately stricter, because a contract that states no limits claims
      the declaration has no boundary, which is never true of a real result.
    * ``output_definitions`` and ``inputs`` are non-empty. There is nothing to
      reproduce without an output, and nothing to pin without an input.
    * output names, input ids, exclusion ids and required check ids are each
      unique.
    * every key of ``units`` and of ``comparison.tolerances`` names a declared
      output -- a tolerance for an output that does not exist is dead
      declaration that reads as coverage.
    * ``units[name]`` agrees with that output's own ``unit`` when both are
      given (RX-13: unit mismatch is a failure, never a conversion).
    * every numeric output has a declared tolerance; without one the verifier
      has no admissible comparison and would have to invent a threshold.
    * ``status == APPROVED`` requires a non-empty ``approval_ref``. This is the
      original's conditional, and it means an approved contract always names
      the ledger record that approved it.

    Immutability: sequence fields are ``tuple`` so they cannot be appended to
    after construction. ``units`` and ``comparison.tolerances`` are ``dict``
    because RX-03 specifies a mapping, and pydantic cannot freeze a dict in
    place -- see :attr:`KNOWN_SHAPE_LIMITS`.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ResultContract"
    CANONICAL_EXCLUDE: ClassVar[frozenset[str]] = frozenset()

    #: Fields that are LIFECYCLE METADATA rather than scientific declaration, and
    #: are therefore excluded from :attr:`declaration_digest`.
    #:
    #: WHY THIS EXISTS. `contract_hash` covers every field, including `status` and
    #: `approval_ref`. That is correct for audit - any change at all is visible -
    #: but it makes the lifecycle transition destroy the identity of the thing
    #: being approved: a DRAFT, the same contract APPROVED, and the same contract
    #: SUPERSEDED produce three different `contract_hash` values. An Approval that
    #: bound the DRAFT hash then matches nothing once the record it approved is
    #: marked APPROVED, so approving a contract would invalidate the very approval
    #: it records.
    #:
    #: The same science, differently labelled, is the same science. So approvals
    #: bind `declaration_digest`, which covers the declaration and not its label.
    #: Changing ANY declared field - an input, a tolerance, an exclusion, the seed,
    #: the reference kind, the version - still changes it and still invalidates the
    #: approval, which is the property that matters.
    DECLARATION_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"status", "approval_ref"})

    KNOWN_SHAPE_LIMITS: ClassVar[tuple[str, ...]] = (
        "`units` and `comparison.tolerances` are dicts, so they are only "
        "shallow-immutable: mutating one in place after construction changes "
        "`contract_hash` with no exception raised. Treat a constructed contract "
        "as read-only; the digest follows content, so a mutated contract no "
        "longer matches any approval bound to its previous hash.",
        "`contract_hash` covers declared content only. It is not a signature "
        "and asserts nothing about who authored or approved the contract.",
        "`contract_hash` covers `status` and `approval_ref`, so moving a "
        "contract from DRAFT to APPROVED changes it. That is intended for audit "
        "- any change at all stays visible - and it is why approvals bind "
        "`declaration_digest` instead, which excludes the lifecycle label and is "
        "therefore stable across DRAFT -> APPROVED -> SUPERSEDED while still "
        "changing on any edit to the declaration. Binding `contract_hash` would "
        "mean approving a contract invalidated the approval it recorded.",
        "`declaration_digest` is NOT a signature either. It establishes that two "
        "declarations are the same declaration; it says nothing about who "
        "approved one, which is the ledger's job.",
        "`status` is a server-established mirror of the approval ledger, not an "
        "independent authority. A record whose status says APPROVED but whose "
        "`approval_ref` does not resolve in the ledger is not approved; this "
        "layer cannot detect that, because it performs no I/O.",
    )

    contract_id: Identifier = Field(
        description="Stable identity, independent of the content hash. Server-established."
    )
    tenant_id: Identifier = Field(
        description="Owning tenant. The key tenant isolation is enforced on (RX-47, RX-49)."
    )
    project_id: Identifier = Field(description="Owning project within the tenant.")
    version: int = Field(
        ge=1,
        description=(
            "Monotonic revision of this scientific declaration. Distinct from "
            "SCHEMA_VERSION, which versions the document shape."
        ),
    )
    status: ContractStatus = Field(
        description="Lifecycle status. Server-established from the approval ledger (RX-04)."
    )
    reference_kind: ReferenceKind = Field(
        description="What kind of reference this contract is judged against (RX-12, RX-17)."
    )
    inputs: tuple[ReferenceInput, ...] = Field(
        min_length=1, description="Pinned inputs, each identified and digested (RX-01)."
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
        description="Ids of the checks a verification must run."
    )
    limitations: tuple[NonEmptyStr, ...] = Field(
        min_length=1,
        description="What this contract does NOT establish. Must be non-empty.",
    )
    created_by: NonEmptyStr = Field(description="Identity of the contract author.")
    approval_ref: Identifier | None = Field(
        default=None,
        description=(
            "Reference to the approval ledger record (RX-04/RX-05), or None. A "
            "reference rather than an embedded approval: an approval binds this "
            "contract's hash and so cannot be a recursive part of it."
        ),
    )

    @model_validator(mode="after")
    def _check_internal_consistency(self) -> ResultContract:
        """Enforce the invariants listed in the class docstring."""
        _check_declaration_consistency(
            inputs=self.inputs,
            output_definitions=self.output_definitions,
            units=self.units,
            exclusions=self.exclusions,
            comparison=self.comparison,
            required_checks=self.required_checks,
        )
        if self.status is ContractStatus.APPROVED and not self.approval_ref:
            raise ValueError(
                "status is APPROVED but approval_ref is absent; an approved contract "
                "must name the ledger record that approved it (RX-04)"
            )
        return self

    @property
    def contract_hash(self) -> str:
        """SHA-256 over the canonical form of the declared contract (RX-03).

        Covers every declared field, with nothing excluded. Recomputed on
        access; it is never stored, so a contract cannot carry a digest that
        disagrees with its own content.
        """
        return self.content_digest()

    @property
    def declaration_digest(self) -> str:
        """Digest of the scientific DECLARATION, excluding its lifecycle label.

        This is what an :class:`~retrace_contracts.Approval` binds. See
        :attr:`DECLARATION_EXCLUDE` for why it is not ``contract_hash``.

        Stable across ``DRAFT -> APPROVED -> SUPERSEDED`` and across setting
        ``approval_ref``; changed by any edit to the declaration itself.
        """
        payload = self.canonical_payload()
        for name in type(self).DECLARATION_EXCLUDE:
            payload.pop(name, None)
        return canonical_digest(payload, type_tag=f"{self.canonical_type_tag()}#declaration")

    @property
    def permits_reproduced_outcome(self) -> bool:
        """Whether ``REPRODUCED_WITHIN_CONTRACT`` is admissible at all (RX-12, RX-17).

        ``False`` exactly when ``reference_kind`` is ``NO_REFERENCE``: with no
        numerical reference there is nothing a result could have been reproduced
        *against*, so the pass outcome is not merely unlikely but inadmissible.
        Checks that need no reference may still run; their outcome is
        ``EXECUTED_NOT_VERIFIED`` or ``BLOCKED_MISSING_EVIDENCE``.

        Exposed as a declared property so the verifier consults the contract
        instead of re-deriving the rule from ``reference_kind``. A rule
        re-implemented at the point of use is a rule that can be forgotten at
        one of those points.
        """
        return self.reference_kind.permits_reproduced_outcome

    @property
    def is_approved(self) -> bool:
        """Whether this record claims approval (RX-04).

        ``True`` only when ``status`` is ``APPROVED``, which the constructor
        guarantees implies a non-empty ``approval_ref``.

        This is a claim recorded by the server, **not** an independent
        verification: resolving ``approval_ref`` against the ledger and checking
        the approval's five bound fields belongs to the domain layer, which has
        the ledger. This layer performs no I/O and cannot do it.
        """
        return self.status is ContractStatus.APPROVED

    def require_approval_ref(self) -> str:
        """Return ``approval_ref`` or raise :class:`ContractNotApproved` (RX-04).

        The acceptance path for a candidate repair calls this instead of testing
        a boolean, so the refusal is a named exception that cannot be read as a
        falsy value. The returned reference still has to be resolved in the
        ledger by the caller; this method only refuses to hand back a reference
        the record does not claim.
        """
        if not self.is_approved or self.approval_ref is None:
            raise ContractNotApproved(contract_hash=self.contract_hash)
        return self.approval_ref


def persist_contract_draft(
    draft: ResultContractDraft,
    *,
    contract_id: str,
    tenant_id: str,
    status: ContractStatus = ContractStatus.DRAFT,
    approval_ref: str | None = None,
) -> ResultContract:
    """Combine an external draft with server-established values (RX-10, RX-47).

    This is the only intended route from the boundary payload to the persisted
    record. Keeping it a function rather than a method on the draft means the
    server-established values arrive as explicit keyword arguments at the call
    site, where a reviewer can see which value came from the request and which
    came from the authenticated session.

    Parameters
    ----------
    draft:
        The validated external payload. Its scientific invariants have already
        been enforced by :class:`ResultContractDraft`.
    contract_id:
        Server-minted stable identity.
    tenant_id:
        The authenticated principal's tenant. Never taken from the request body
        (RX-47).
    status:
        Lifecycle status, defaulting to ``DRAFT``. ``APPROVED`` is only
        legitimate when the approval ledger already holds the record named by
        ``approval_ref``; the model refuses ``APPROVED`` without one, but it
        cannot check the ledger from here.
    approval_ref:
        Reference to the approval ledger record, when one exists.

    Returns
    -------
    ResultContract:
        The persisted record, revalidated in full.
    """
    return ResultContract(
        contract_id=contract_id,
        tenant_id=tenant_id,
        project_id=draft.project_id,
        version=draft.version,
        status=status,
        reference_kind=draft.reference_kind,
        inputs=draft.inputs,
        output_definitions=draft.output_definitions,
        population=draft.population,
        units=dict(draft.units),
        exclusions=draft.exclusions,
        seed=draft.seed,
        split=draft.split,
        comparison=draft.comparison,
        required_checks=draft.required_checks,
        limitations=draft.limitations,
        created_by=draft.created_by,
        approval_ref=approval_ref,
    )

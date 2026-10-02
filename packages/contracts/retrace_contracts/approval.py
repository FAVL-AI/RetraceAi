"""The approval record shape (RX-05).

An approval in RETRACE is not a flag. It is a statement that a named human
approved *one specific combination* of five pieces of evidence:

==============================  ==========================================
Bound field                     What it pins
==============================  ==========================================
``contract_hash``               the scientific declaration being judged
``candidate_hash``              the exact repair candidate
``input_snapshot_id``           the immutable inputs it was judged against
``environment_policy_digest``   the execution envelope it may run in
``action_digest``               the action the approval authorises
==============================  ==========================================

If any one of them changes, the approval no longer describes what is about to
happen, so it is void and :meth:`Approval.validate_binding` says which field
moved. This module defines the *shape* and the binding check only; creating,
storing and revoking approval records belongs to the domain layer.

"""

from __future__ import annotations

from typing import ClassVar

from pydantic import AwareDatetime, Field

from .base import FrozenRecord, Identifier, NonEmptyStr, Sha256Hex
from .canonical import canonical_digest
from .exceptions import ApprovalInvalidated

__all__ = ["Approval"]


class Approval(FrozenRecord):
    """A human approval binding five pieces of evidence together (RX-05).

    The record is frozen: an approval whose bound fields could be edited after
    the fact would be an audit record that cannot be audited.

    ``approved_at`` must be supplied by the caller as a timezone-aware
    ``datetime``. This model never reads the clock -- a record that stamps
    itself cannot be reconstructed from evidence or tested deterministically.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.Approval"

    BOUND_FIELDS: ClassVar[tuple[str, ...]] = (
        "contract_hash",
        "candidate_hash",
        "input_snapshot_id",
        "environment_policy_digest",
        "action_digest",
    )
    """The five fields the approval binds, in declaration order (RX-05)."""

    approval_id: Identifier = Field(description="Stable id of this approval record.")
    contract_hash: Sha256Hex = Field(
        description="Hash of the ResultContract this approval judges (RX-03)."
    )
    candidate_hash: Sha256Hex = Field(
        description="Hash of the exact repair candidate approved (RX-06)."
    )
    input_snapshot_id: Identifier = Field(
        description="Id of the immutable input snapshot used (RX-01)."
    )
    environment_policy_digest: Sha256Hex = Field(
        description="Digest of the execution policy the run must obey (RX-08)."
    )
    action_digest: Sha256Hex = Field(
        description="Digest of the action this approval authorises, and no other."
    )
    approved_by: NonEmptyStr = Field(description="Identity of the approving human.")
    approved_at: AwareDatetime = Field(
        description="When the approval was given. Timezone-aware; supplied by the caller."
    )

    @property
    def bound_values(self) -> dict[str, str]:
        """Return the five bound fields as a mapping, in declaration order (RX-05)."""
        return {name: getattr(self, name) for name in type(self).BOUND_FIELDS}

    @property
    def binding_digest(self) -> str:
        """SHA-256 over exactly the five bound fields (RX-05).

        Deliberately excludes ``approval_id``, ``approved_by`` and
        ``approved_at``: the binding digest answers "is this the combination
        that was approved?", not "who approved it and when?". Use
        :meth:`~retrace_contracts.base.FrozenRecord.content_digest` for a digest
        over the whole record.
        """
        return canonical_digest(self.bound_values, type_tag="retrace.Approval.binding")

    def validate_binding(self, **observed: str) -> None:
        """Raise :class:`ApprovalInvalidated` if any bound field changed (RX-05).

        All five bound fields must be supplied. A partial call is a programming
        error and raises :class:`ValueError` rather than passing, because a
        binding check that silently skips the field it was not given is a check
        that cannot detect the thing it claims to detect.

        Parameters
        ----------
        **observed:
            The five bound field names mapped to the values actually observed
            at the point of use.

        Raises
        ------
        ValueError:
            If any bound field is missing from the call, or an unknown keyword
            is supplied.
        ApprovalInvalidated:
            If any supplied value differs from the approved value. The
            exception names every changed field, first-in-declaration-order
            first.
        """
        bound = type(self).BOUND_FIELDS
        unknown = sorted(set(observed) - set(bound))
        if unknown:
            raise ValueError(
                f"validate_binding received unknown field(s): {', '.join(unknown)}; "
                f"bound fields are {', '.join(bound)}"
            )
        missing = [name for name in bound if name not in observed]
        if missing:
            raise ValueError(
                "validate_binding requires every bound field; "
                f"missing: {', '.join(missing)}. A partial binding check cannot "
                "detect a change in a field it was not given."
            )

        changed: list[str] = []
        expected_values: dict[str, str] = {}
        observed_values: dict[str, str] = {}
        for name in bound:
            approved_value = getattr(self, name)
            observed_value = observed[name]
            if observed_value != approved_value:
                changed.append(name)
                expected_values[name] = approved_value
                observed_values[name] = observed_value

        if changed:
            raise ApprovalInvalidated(
                field=changed[0],
                fields=tuple(changed),
                expected=expected_values,
                observed=observed_values,
                approval_id=self.approval_id,
            )

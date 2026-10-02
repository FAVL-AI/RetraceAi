"""Shared record base class and constrained field types.

Every hashed RETRACE record derives from :class:`FrozenRecord`, which supplies
three properties the authority layer depends on:

1. **Immutability with a named refusal** -- assigning to a declared field raises
   :class:`~retrace_contracts.exceptions.ContractImmutable` rather than a
   generic validation error, because a content-addressed record that can be
   mutated in place is a record whose digest lies (RX-03).
2. **Closed shape** -- ``extra="forbid"`` means an unexpected key in a
   deserialised payload is refused, not absorbed. This is the defensive-parsing
   posture RX-10 asks of anything that reads run output or an imported bundle.
3. **A content digest** over the canonical form defined in
   :mod:`retrace_contracts.canonical` (RX-03).

"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, StringConstraints

from .canonical import canonical_digest, canonical_json
from .exceptions import ContractImmutable

__all__ = [
    "FrozenRecord",
    "Identifier",
    "LongText",
    "NonEmptyStr",
    "Sha256Hex",
]

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A lowercase hex SHA-256 digest. Uppercase or truncated digests are refused."""

Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:+-]*$",
    ),
]
"""An opaque identifier. Constrained so an id cannot smuggle markup or a path."""

NonEmptyStr = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4096)
]
"""A required single-value string. Whitespace-only input is refused."""

LongText = Annotated[str, StringConstraints(min_length=1, max_length=1_048_576)]
"""Free text such as a rationale or a unified diff. Not whitespace-stripped."""


class FrozenRecord(BaseModel):
    """Immutable, closed-shape, content-addressed record base (RX-03).

    Subclasses set :attr:`CANONICAL_TYPE_TAG` to give their digests domain
    separation, and may list field names in :attr:`CANONICAL_EXCLUDE` for fields
    that must not take part in the digest (the only legitimate case is a field
    that *binds to* the digest and therefore cannot be inside it).
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_default=True,
        validate_assignment=False,
        ser_json_timedelta="iso8601",
    )

    CANONICAL_TYPE_TAG: ClassVar[str] = ""
    CANONICAL_EXCLUDE: ClassVar[frozenset[str]] = frozenset()

    def __setattr__(self, name: str, value: Any) -> None:
        """Refuse mutation of a declared field by name (RX-03).

        Raises :class:`ContractImmutable` for any declared field. Non-field
        attributes fall through to pydantic, which refuses them too; the two
        refusals are kept distinct so a caller can tell "this record is frozen"
        from "this field does not exist".
        """
        if name in type(self).model_fields:
            raise ContractImmutable(record=type(self).__name__, field=name)
        super().__setattr__(name, value)

    @classmethod
    def canonical_type_tag(cls) -> str:
        """Return the domain-separation tag used in this record's digest."""
        return cls.CANONICAL_TYPE_TAG or f"retrace.{cls.__name__}"

    def canonical_payload(self) -> dict[str, Any]:
        """Return the field mapping that takes part in this record's digest.

        ``None`` values are retained (never dropped) so that an explicitly null
        field and an omitted-but-defaulted field digest identically (RX-03).
        """
        payload = self.model_dump(mode="python")
        for excluded in type(self).CANONICAL_EXCLUDE:
            payload.pop(excluded, None)
        return payload

    def canonical_document(self) -> str:
        """Return the exact canonical JSON string that is digested (RX-03).

        Exposed for review and for diffing two records whose digests disagree.
        """
        return canonical_json(self.canonical_payload(), type_tag=self.canonical_type_tag())

    def content_digest(self) -> str:
        """Return the lowercase hex SHA-256 of this record's canonical form (RX-03)."""
        return canonical_digest(self.canonical_payload(), type_tag=self.canonical_type_tag())

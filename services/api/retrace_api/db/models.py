"""Tenancy baseline models (RX-47, RX-48, RX-49).

Mirrors `infra/sql/001_tenancy.sql` exactly - column order included, because the
upgrade test compares the realised catalogue of a migrated database against a
freshly built one and attribute numbers are part of that catalogue.

=============================================================================
WHY THE COMPOSITE FOREIGN KEY IS NOT REDUNDANT WITH ROW-LEVEL SECURITY
=============================================================================

PostgreSQL's referential-integrity checks BYPASS row-level security. The
server performs them with an internal query that is not subject to the policies
on the referenced table, and it does so deliberately: an RI check that could be
made to miss rows by a policy would let a dangling reference be created, which
would corrupt the constraint's own guarantee.

The consequence for tenancy is the part that is easy to get wrong. With a
SINGLE-column foreign key - `result_contracts.project_id -> projects.id` - a
caller carrying tenant B's identity can reference tenant A's project. The row is
invisible to that caller on `SELECT`; the RI check sees it anyway; the insert
succeeds; a cross-tenant relationship now exists in the database. RLS did its
job on reads and still did not prevent the relationship.

The COMPOSITE key is what prevents it. Because the parent key is
`(tenant_id, id)` and the child reference is `(tenant_id, project_id)`, a row
claiming `tenant_id = B` can only satisfy the constraint by pointing at a parent
whose `tenant_id` is also B. The mismatch is a plain referential failure, so it
is refused by the constraint regardless of which policies apply and regardless of
whether the caller can see either row.

Both mechanisms are therefore required, and neither substitutes for the other:
RLS confines what a request can read and write, the composite key confines what
can be RELATED. `tests/migrations/test_cross_tenant_reference.py` demonstrates
the bypass on a contained single-column fixture and then shows the composite form
refusing the identical insert, so this comment is backed by an executed
observation rather than by assertion.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from retrace_api.db.base import Base

__all__ = ["Project", "ResultContractRow"]


class Project(Base):
    """A tenant-owned project (RX-49: the parent of the composite reference)."""

    __tablename__ = "projects"

    #: RX-49: `tenant_id` leads the composite primary key, so every child
    #: reference has to carry the tenant and cannot be satisfied across tenants.
    tenant_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False
    )


class ResultContractRow(Base):
    """The persisted row for a result contract (RX-49).

    NAMED `ResultContractRow`, not `ResultContract`. `retrace_contracts`
    already exports a pydantic `ResultContract` which is the authoring source and
    the thing that gets hashed; this is a tenancy-scoped pointer to it holding the
    content hash and the ledger-derived approval flag. Giving them the same name
    in two layers is how a digest ends up being computed over the wrong object.
    """

    __tablename__ = "result_contracts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, nullable=False)
    contract_hash: Mapped[str] = mapped_column(sa.CHAR(64), nullable=False)
    #: Server-set from the ledger, never client-supplied. Kept as a denormalised
    #: flag for querying only; `docs/evidence/SPEC_RECONCILIATION_CLOSURE.md` S6
    #: records that the ledger remains the authority for approval.
    approved: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("false")
    )

    __table_args__ = (
        # RX-49. See the module docstring: referential integrity bypasses RLS, so
        # this constraint - not the policy - is what makes a cross-tenant
        # relationship unconstructible.
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
        ),
        # PostgreSQL does NOT index foreign-key columns automatically, and the
        # table's own primary key is `(tenant_id, id)`, so it cannot serve a
        # lookup by `(tenant_id, project_id)`. Without this index every parent
        # DELETE or tenant-scoped listing is a sequential scan. The name comes
        # from the naming convention and matches what `CREATE INDEX` without a
        # name would have produced.
        sa.Index(None, "tenant_id", "project_id"),
    )

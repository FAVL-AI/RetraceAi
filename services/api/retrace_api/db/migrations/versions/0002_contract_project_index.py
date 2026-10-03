"""Index the composite foreign-key columns on result_contracts.

Revision: 0002_contract_project_index
Revises: 0001_tenancy_baseline

Serves RX-49 (the composite tenant reference stays usable at scale).

WHY THIS IS A SEPARATE REVISION RATHER THAN PART OF THE BASELINE.

The baseline revision has to be catalogue-identical to the hand-applied
`infra/sql/001_tenancy.sql`, because that file is what already exists in at
least one environment and the chain adopts rather than stamps it. That file
creates no index beyond the primary keys. Folding this index into 0001 would mean
the baseline revision produced something the hand-applied schema does not have,
and the adoption path would then have to decide whether a database missing the
index is "equivalent" - a judgement call that is better replaced by a second
revision that simply adds it. An upgraded database and a fresh database both end
at this head, so they converge; they just converge in two steps.

WHY THE INDEX IS NEEDED AT ALL.

PostgreSQL does NOT index foreign-key columns automatically. It indexes the
REFERENCED side (`projects_pkey` covers `(tenant_id, id)`), which is what the
insert-time check uses, but nothing covers the REFERENCING side. The consequence
is two-fold: every `DELETE` or key `UPDATE` on `projects` has to scan
`result_contracts` to enforce the constraint, and `result_contracts`' own primary
key is `(tenant_id, id)`, so it cannot serve a lookup by
`(tenant_id, project_id)` either. Listing a tenant's contracts for one project -
the ordinary query - is a sequential scan without this index.

The name is PostgreSQL's own default for an unnamed `CREATE INDEX` on these
columns, which is also what the metadata naming convention produces, so the
models and the realised catalogue agree.

`IF NOT EXISTS` is used so the revision is idempotent: a database where an
operator already added the index by hand upgrades cleanly instead of failing on
a duplicate name.

REVISION IDS MUST FIT 32 CHARACTERS. Alembic hardcodes `alembic_version.
version_num` as `varchar(32)` (`alembic/runtime/migration.py`), so a longer id is
accepted by the script directory and then fails at the very END of the upgrade
with `StringDataRightTruncation` - after the DDL has already run. This revision
was first named `0002_result_contract_project_index` (34 characters) and did
exactly that. Shortened; recorded here because the failure mode is late, looks
like a data error rather than a naming problem, and will recur the next time a
revision is named descriptively.
"""

from __future__ import annotations

from alembic import op

revision = "0002_contract_project_index"
down_revision = "0001_tenancy_baseline"
branch_labels = None
depends_on = None

INDEX_NAME = "result_contracts_tenant_id_project_id_idx"


def upgrade() -> None:
    """Add the index covering the referencing side of the composite key."""
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "  # noqa: S608
        "ON result_contracts (tenant_id, project_id)"
    )


def downgrade() -> None:
    """Drop the index.

    This downgrade IS implemented, unlike 0001's, and the difference is the
    point: dropping an index destroys no data and loses nothing that re-running
    `upgrade` does not restore, so there is no reason to refuse it. A blanket
    "all downgrades are destructive" rule would be as unhelpful as a blanket
    "every migration must be reversible" one. Judged per revision.
    """
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")  # noqa: S608

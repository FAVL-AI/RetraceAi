"""Tenancy baseline: tables, composite keys, and row-level security.

Revision: 0001_tenancy_baseline
Revises: None

Serves RX-47 (RLS plus FORCE), RX-48 (transaction-local identity predicate) and
RX-49 (composite tenant keys).

=============================================================================
WHY THIS REVISION ADOPTS AN EXISTING SCHEMA INSTEAD OF STAMPING IT
=============================================================================

`infra/sql/001_tenancy.sql` is already applied in at least one environment and
carries no version identity, so a database may arrive at this revision with the
tables ALREADY PRESENT. The two usual answers are both wrong here:

  * `alembic stamp 0001_tenancy_baseline` records the revision without looking at
    the database. If the hand-applied schema differs in any way - a single-column
    primary key, a missing FORCE, a policy someone dropped - the version table
    now ASSERTS a state the database does not satisfy, and every later migration
    builds on that false premise. Stamping is a claim of equivalence made without
    evidence.
  * `CREATE TABLE` unconditionally fails on an existing table, so an operator
    would have to drop the tables - destroying tenant data - to adopt the chain.

So this revision CONVERGES instead. For each table it either creates it, or
verifies that the existing one already enforces the baseline's structure and
adopts it. Verification is not cosmetic: it asserts the primary key is composite
and leads with `tenant_id`, and that the foreign key is the composite
`(tenant_id, project_id) -> projects(tenant_id, id)` form. Anything else raises
`BaselineDivergence` and the migration refuses, because a single-column foreign
key does NOT enforce RX-49 (referential integrity bypasses RLS - see
`retrace_api/db/models.py`) and adopting it would record a head revision the
database does not honour.

The security configuration is then applied unconditionally, because it is
idempotent and because a pre-existing schema is exactly where a dropped policy or
a missing FORCE is likely to be found.

Equivalence is not merely argued: `tests/migrations/test_upgrade_from_manual_schema.py`
applies `infra/sql/001_tenancy.sql` into a fresh database with a row of fixture
data, upgrades to head, asserts the fixture data survives, and asserts the
realised catalogue is IDENTICAL to one built fresh from the migrations.

OFFLINE (`--sql`) GENERATION. The adoption branch needs to inspect the database,
and offline mode has no connection, so it cannot run. Rather than guess, the
offline path emits the FRESH-INSTALL script with its precondition written into the
script itself: it must not be applied to a database that already carries the
hand-applied schema. Nothing in an offline script has been checked against a
target, and saying so in the artefact is the only honest option.

=============================================================================
WHY THE RLS STATEMENTS ARE HAND-WRITTEN
=============================================================================

Alembic autogenerate cannot express `ENABLE`/`FORCE ROW LEVEL SECURITY`,
policies or grants. It does not emit them, and - the dangerous half - it reports
NO DIFFERENCE for a database that is missing all of them. Every statement in
`retrace_api.db.security` is therefore written by hand, and the authoritative
check is a read of the realised `pg_class`/`pg_policies` catalogue rather than a
clean autogenerate diff.

GRANTS AND ROLE CREATION ARE NOT HERE. They are a separate, privileged,
operator-run step (`retrace_api.bootstrap.roles`). A migration that creates its
own consumer's role conflates two identities with deliberately different
privileges, and it would also mean the migration credential had CREATEROLE.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

from retrace_api.db.security import security_statements
from retrace_api.errors import BaselineDivergence, DestructiveDowngradeRefused

revision = "0001_tenancy_baseline"
down_revision = None
branch_labels = None
depends_on = None

#: The structure a pre-existing table must already have to be adopted. Key ORDER
#: is part of the expectation: `(id, tenant_id)` enforces the same uniqueness but
#: cannot serve a tenant-scoped primary-key lookup, and the difference would be
#: invisible to a set comparison.
_EXPECTED_PRIMARY_KEY: dict[str, tuple[str, ...]] = {
    "projects": ("tenant_id", "id"),
    "result_contracts": ("tenant_id", "id"),
}

#: RX-49. The composite reference, as (child columns, parent table, parent columns).
_EXPECTED_FOREIGN_KEY: dict[str, tuple[tuple[str, ...], str, tuple[str, ...]]] = {
    "result_contracts": (("tenant_id", "project_id"), "projects", ("tenant_id", "id")),
}


def _primary_key_columns(bind: sa.Connection, table: str) -> tuple[str, ...]:
    """Read the realised primary key in key order, from the catalogue."""
    got = bind.execute(
        sa.text(
            "SELECT array_agg(a.attname ORDER BY k.ord) "
            "FROM pg_constraint ct "
            "JOIN LATERAL unnest(ct.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
            "JOIN pg_attribute a ON a.attrelid = ct.conrelid AND a.attnum = k.attnum "
            "WHERE ct.contype = 'p' AND ct.conrelid = to_regclass('public.' || :t)"
        ),
        {"t": table},
    ).scalar()
    return tuple(got or ())


def _foreign_keys(
    bind: sa.Connection, table: str
) -> tuple[tuple[tuple[str, ...], str, tuple[str, ...]], ...]:
    rows = bind.execute(
        sa.text(
            "SELECT "
            "  (SELECT array_agg(a.attname ORDER BY k.ord) "
            "     FROM unnest(ct.conkey) WITH ORDINALITY AS k(attnum, ord) "
            "     JOIN pg_attribute a ON a.attrelid = ct.conrelid AND a.attnum = k.attnum), "
            "  ct.confrelid::regclass::text, "
            "  (SELECT array_agg(a.attname ORDER BY k.ord) "
            "     FROM unnest(ct.confkey) WITH ORDINALITY AS k(attnum, ord) "
            "     JOIN pg_attribute a ON a.attrelid = ct.confrelid AND a.attnum = k.attnum) "
            "FROM pg_constraint ct "
            "WHERE ct.contype = 'f' AND ct.conrelid = to_regclass('public.' || :t) "
            "ORDER BY ct.conname"
        ),
        {"t": table},
    ).all()
    return tuple(
        (tuple(r[0] or ()), str(r[1]), tuple(r[2] or ())) for r in rows
    )


def _assert_adoptable(bind: sa.Connection, table: str) -> None:
    """Refuse to adopt a table that does not already enforce the baseline (RX-49)."""
    realised_pk = _primary_key_columns(bind, table)
    expected_pk = _EXPECTED_PRIMARY_KEY[table]
    if realised_pk != expected_pk:
        raise BaselineDivergence(
            f"table {table!r} already exists with primary key {realised_pk or '(none)'}, "
            f"but the tenancy baseline requires {expected_pk}. A primary key that does not "
            "lead with tenant_id cannot be the target of a composite tenant reference "
            "(RX-49), so this schema is NOT equivalent to the baseline and will not be "
            "adopted. Resolve the divergence deliberately; do not stamp this revision."
        )
    expected_fk = _EXPECTED_FOREIGN_KEY.get(table)
    if expected_fk is None:
        return
    realised_fks = _foreign_keys(bind, table)
    if expected_fk not in realised_fks:
        raise BaselineDivergence(
            f"table {table!r} already exists without the composite foreign key "
            f"{expected_fk[0]} -> {expected_fk[1]}{expected_fk[2]}; found {realised_fks or '()'}. "
            "PostgreSQL performs referential-integrity checks WITHOUT row-level security, so a "
            "single-column reference lets one tenant point at another tenant's row even though "
            "it cannot read it. Row-level security does not close this; only the composite key "
            "does. Refusing to adopt."
        )


def _create_projects() -> None:
    op.create_table(
        "projects",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        # RX-49. Named explicitly to match what PostgreSQL assigns when the same
        # table is created by plain SQL, so a database built from this migration
        # and one built from infra/sql/001_tenancy.sql are catalogue-identical.
        sa.PrimaryKeyConstraint("tenant_id", "id", name="projects_pkey"),
    )


def _create_result_contracts() -> None:
    op.create_table(
        "result_contracts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("contract_hash", sa.CHAR(64), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="result_contracts_pkey"),
        # RX-49: the enforcement. tenant_id appears on BOTH sides, so a child row
        # can only reference a parent in its own tenant.
        sa.ForeignKeyConstraint(
            ["tenant_id", "project_id"],
            ["projects.tenant_id", "projects.id"],
            name="result_contracts_tenant_id_project_id_fkey",
        ),
    )


_CREATORS = {"projects": _create_projects, "result_contracts": _create_result_contracts}

#: Emitted at the top of an OFFLINE (`--sql`) script. Offline mode has no
#: connection - `op.get_bind()` returns a `MockConnection`, which SQLAlchemy
#: cannot inspect - so the adoption branch cannot run and the script is
#: necessarily the CREATE path. That is a real precondition, not a detail, so the
#: script says so in its own text rather than leaving the reader to infer it from
#: the migration source. Found by running `alembic upgrade head --sql`, which
#: failed with `NoInspectionAvailable` before this branch existed.
_OFFLINE_PRECONDITION = """
-- =========================================================================
-- PRECONDITION: this script assumes the tables DO NOT EXIST.
--
-- It was generated OFFLINE, with no connection to the target database, so the
-- adoption path in revision 0001_tenancy_baseline could not run - that path
-- inspects the realised catalogue and refuses a schema that does not already
-- enforce the composite keys. Nothing here has been checked against the target.
--
-- Do NOT apply this to a database already carrying infra/sql/001_tenancy.sql or
-- any earlier tenancy schema: the CREATE TABLE statements will fail, and they
-- will fail partway. For such a database run the ONLINE upgrade
-- (`python -m retrace_api.db.migrate upgrade`), which inspects before it acts.
-- =========================================================================
"""


def upgrade() -> None:
    """Create or adopt the tenancy baseline, then apply its security configuration."""
    if context.is_offline_mode():
        # No connection exists, so nothing can be inspected and nothing may be
        # claimed about the target. Emit the fresh-install path with its
        # precondition stated in the script itself.
        op.execute(_OFFLINE_PRECONDITION)
        _create_projects()
        _create_result_contracts()
        _apply_security()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names(schema="public"))

    # Parent first: result_contracts' foreign key needs projects to exist.
    for table in ("projects", "result_contracts"):
        if table in existing:
            _assert_adoptable(bind, table)
        else:
            _CREATORS[table]()

    _apply_security()


def _apply_security() -> None:
    """Apply the hand-written RLS configuration (RX-47, RX-48).

    Issued through `op.execute` from `security_statements()` - the SAME generator
    the forward-repair path executes - so the migration and the repair cannot
    install different configurations. Going through `op.execute` rather than the
    connection also means this works in offline mode, where there is no
    connection to execute against.

    Applied unconditionally. An adopted pre-existing schema is the most likely
    place to find a dropped policy or a missing FORCE, and every statement is
    idempotent.
    """
    for statement in security_statements():
        op.execute(statement)


def downgrade() -> None:
    """Refused: dropping these tables destroys every tenant's rows.

    Reversibility is not an unconditional virtue. There is no non-destructive
    downgrade of a baseline that introduces the only tables in the schema, and an
    operator reaching for `alembic downgrade` mid-incident is the least likely
    moment for "drop all tenant data" to be what was meant.

    The supported recovery route is FORWARD, and it is tested:

        python -m retrace_api.db.migrate repair-security

    re-applies the RLS configuration idempotently on a database at head, which
    covers the realistic failure (a policy dropped by hand, FORCE switched off to
    debug something and never restored) without touching a row. To remove the
    schema in a disposable environment, drop the database.
    """
    raise DestructiveDowngradeRefused(
        "refusing to downgrade 0001_tenancy_baseline: dropping projects and "
        "result_contracts destroys every tenant's rows. For a database at head whose "
        "row-level security has drifted, the supported recovery is forward repair - "
        "`python -m retrace_api.db.migrate repair-security` - which is idempotent and "
        "touches no rows. To discard a disposable environment, drop the database."
    )

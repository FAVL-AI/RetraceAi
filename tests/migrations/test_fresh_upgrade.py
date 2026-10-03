"""An empty database upgraded to head: what it actually enforces (RX-47, RX-48, RX-49).

Every assertion here reads the REALISED PostgreSQL CATALOGUE - `pg_class`,
`pg_policies`, `pg_constraint`, `pg_index` - and never the migration text. The
two can disagree for ordinary reasons (a statement inside a transaction that
rolled back, a DO block that swallowed an error, a restore from before the
policies were applied), and a check that read the migration file would report
success in every one of those cases.

The inspection is itself shown to be able to FAIL: see
`test_the_security_inspection_reports_an_unforced_table`, which builds a table
with ENABLE and no FORCE and asserts the inspection names it. Without that
control, a passing result here would be consistent with an inspection that
reports "secure" unconditionally.

IDENTITY: the migrations and these reads run as `retrace_app`, the disposable
container's POSTGRES_USER. See `conftest.py` for the full identity table and the
limitation that this identity is a superuser in this container.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from retrace_api.bootstrap.roles import grant_runtime_privileges
from retrace_api.db import migrate
from retrace_api.db.catalogue import (
    read_foreign_keys,
    read_indexes,
    read_primary_key,
    read_table_security,
)
from retrace_api.db.security import POLICY_NAME, REALISED_POLICY_PREDICATE, SECURED_TABLES

pytestmark = pytest.mark.integration

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

FK_INDEX = "result_contracts_tenant_id_project_id_idx"


def _engine(url: sa.URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


@pytest.fixture
def head_database(fresh_database: sa.URL) -> sa.URL:
    """An empty database upgraded to head, as the migration identity."""
    migrate.upgrade(fresh_database, "head")
    return fresh_database


def test_fresh_upgrade_produces_the_expected_structure(head_database: sa.URL) -> None:
    """Tables, COMPOSITE primary keys, the COMPOSITE foreign key, and the index.

    RX-49. Key ORDER is asserted, not just membership: `(id, tenant_id)` enforces
    the same uniqueness but cannot serve a tenant-scoped primary-key lookup, and a
    set comparison would call the two equal.
    """
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            tables = set(sa.inspect(c).get_table_names(schema="public"))
            pk_projects = read_primary_key(c, "projects")
            pk_contracts = read_primary_key(c, "result_contracts")
            fks = read_foreign_keys(c, "result_contracts")
            indexes = {ix.name: ix for ix in read_indexes(c, "result_contracts")}
    finally:
        engine.dispose()

    assert tables == {"projects", "result_contracts", "alembic_version"}, tables
    assert pk_projects == ("tenant_id", "id"), pk_projects
    assert pk_contracts == ("tenant_id", "id"), pk_contracts

    assert len(fks) == 1, fks
    fk = fks[0]
    assert fk.is_composite, f"foreign key is not composite: {fk}"
    assert fk.columns == ("tenant_id", "project_id"), fk
    assert fk.referenced_table == "projects", fk
    assert fk.referenced_columns == ("tenant_id", "id"), fk

    assert FK_INDEX in indexes, sorted(indexes)
    assert indexes[FK_INDEX].columns == ("tenant_id", "project_id"), indexes[FK_INDEX]


def test_fresh_upgrade_enables_and_forces_row_level_security(head_database: sa.URL) -> None:
    """RX-47: both flags, read from `pg_class`.

    FORCE is the half that is easy to omit. ENABLE alone leaves the table's OWNER
    exempt, and the owner is the migration identity - so without FORCE an
    isolation test run as the owner would pass against a table that offers no
    isolation at all.
    """
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            facts = read_table_security(c, SECURED_TABLES)
    finally:
        engine.dispose()

    for table in SECURED_TABLES:
        assert facts[table].exists, f"{table} missing"
        assert facts[table].row_security, f"{table}: relrowsecurity is false"
        assert facts[table].force_row_security, f"{table}: relforcerowsecurity is false"


def test_fresh_upgrade_installs_the_tenant_isolation_policies(head_database: sa.URL) -> None:
    """RX-48: the policy exists on every secured table, with the realised predicate.

    The predicate is compared against the text PostgreSQL deparsed back out of
    `pg_policies`, not against the text that was sent. A statement can be
    accepted and stored as something subtly different; only the realised form
    says what will be evaluated.
    """
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            facts = read_table_security(c, SECURED_TABLES)
    finally:
        engine.dispose()

    for table in SECURED_TABLES:
        policies = {p.name: p for p in facts[table].policies}
        assert POLICY_NAME in policies, f"{table}: policies are {sorted(policies)}"
        policy = policies[POLICY_NAME]
        assert policy.command == "ALL", policy
        assert policy.using == REALISED_POLICY_PREDICATE, policy.using
        # WITH CHECK is asserted separately from USING. Omitting it would leave
        # reads filtered while writes could still store another tenant's id.
        assert policy.with_check == REALISED_POLICY_PREDICATE, policy.with_check
        assert facts[table].is_isolated, facts[table]


def test_the_policy_fails_closed_without_a_tenant_context(
    head_database: sa.URL, scratch, runtime_role_name: str, runtime_password: str
) -> None:
    """RX-48, BEHAVIOURALLY: no context and an emptied context both match no rows.

    The text assertion above says the predicate is the intended one; this says the
    intended one does what it is for. Both are needed - the `nullif` exists
    precisely because a transaction-local setting reverts to the EMPTY STRING
    rather than to NULL, and the difference between "matches nothing" and "raises
    invalid_text_representation" is invisible in the policy text.

    IDENTITY: `retrace_svc`, the runtime role, which is NOSUPERUSER and
    NOBYPASSRLS. A superuser bypasses row-level security entirely, so this
    property cannot be demonstrated as the admin identity. The role's credential
    is READ from `.env` and never re-set.
    """
    pid = uuid.uuid4()
    admin = _engine(head_database)
    try:
        with admin.begin() as c:
            grant_runtime_privileges(c, role=runtime_role_name, tables=SECURED_TABLES)
            c.execute(
                sa.text(
                    "INSERT INTO projects (tenant_id, id, name, created_at) "
                    "VALUES (:t, :i, 'A-project', now())"
                ),
                {"t": TENANT_A, "i": pid},
            )
    finally:
        admin.dispose()

    svc = _engine(scratch.url_for(head_database, user=runtime_role_name,
                                 password=runtime_password))
    try:
        with svc.connect() as c:
            # No context at all.
            unset = c.execute(sa.text("SELECT count(*) FROM projects")).scalar()
            # Context explicitly emptied - the state a pooled connection is left
            # in after a transaction that set it locally.
            c.execute(sa.text("SELECT set_config('retrace.tenant_id', '', true)"))
            emptied = c.execute(sa.text("SELECT count(*) FROM projects")).scalar()
            # And the positive half, so the zeros above are not simply an empty table.
            c.execute(
                sa.text("SELECT set_config('retrace.tenant_id', :t, true)"),
                {"t": str(TENANT_A)},
            )
            own = c.execute(sa.text("SELECT count(*) FROM projects")).scalar()
            c.execute(
                sa.text("SELECT set_config('retrace.tenant_id', :t, true)"),
                {"t": str(TENANT_B)},
            )
            other = c.execute(sa.text("SELECT count(*) FROM projects")).scalar()
    finally:
        svc.dispose()

    assert unset == 0, "rows visible with NO tenant context set"
    assert emptied == 0, "rows visible with an EMPTY tenant context"
    assert own == 1, (
        "DISCRIMINATION FAILED: the row is not visible to its OWN tenant either, so the "
        "two zeros above are consistent with an empty table and prove nothing about isolation"
    )
    assert other == 0, "another tenant could see the row"


def test_fresh_upgrade_records_the_single_head_revision(head_database: sa.URL) -> None:
    """The database records the revision, and the chain has exactly one head."""
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            recorded = migrate.current_revision(c)
    finally:
        engine.dispose()
    assert recorded == migrate.head_revision(), recorded
    assert recorded == "0002_contract_project_index", recorded


def test_an_unmigrated_database_records_no_revision(fresh_database: sa.URL) -> None:
    """Vacuity guard for the assertion above.

    If `current_revision` returned the head id for every database - including one
    that has never been migrated - the test above would pass without the
    migration having run. It must return None here.
    """
    engine = _engine(fresh_database)
    try:
        with engine.connect() as c:
            assert migrate.current_revision(c) is None
    finally:
        engine.dispose()


def test_the_security_inspection_reports_an_unforced_table(head_database: sa.URL) -> None:
    """NEGATIVE CONTROL for every RLS assertion in this module.

    Builds two tables the inspection should condemn - one with ENABLE and no
    FORCE and no policy, one with nothing at all - and asserts it reports them as
    not isolated while still reporting the migrated tables as isolated. A check
    that has never been observed to fail is not evidence that the property holds;
    it may simply be unable to detect the violation.

    The tables are contained: created in this test's own disposable database,
    never referenced by the schema, and dropped with the database.
    """
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            c.exec_driver_sql("CREATE TABLE enabled_not_forced (x int)")
            c.exec_driver_sql("ALTER TABLE enabled_not_forced ENABLE ROW LEVEL SECURITY")
            c.exec_driver_sql("CREATE TABLE no_rls_at_all (x int)")
        with engine.connect() as c:
            facts = read_table_security(
                c,
                (*SECURED_TABLES, "enabled_not_forced", "no_rls_at_all", "absent_table"),
            )
    finally:
        engine.dispose()

    unforced = facts["enabled_not_forced"]
    assert unforced.exists and unforced.row_security, unforced
    assert not unforced.force_row_security, (
        "the inspection reported FORCE on a table created without it - it cannot "
        "discriminate, so the passing results in this module prove nothing"
    )
    assert unforced.policies == (), unforced
    assert not unforced.is_isolated

    bare = facts["no_rls_at_all"]
    assert bare.exists and not bare.row_security and not bare.is_isolated, bare

    # An ABSENT table must not read as secured either: reporting a missing table
    # as isolated would hide a migration that never created it.
    missing = facts["absent_table"]
    assert not missing.exists and not missing.is_isolated, missing

    # And the real tables are still reported as isolated in the same read, so the
    # control did not simply break the inspection for everything.
    for table in SECURED_TABLES:
        assert facts[table].is_isolated, facts[table]

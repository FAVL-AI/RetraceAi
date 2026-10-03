"""The privileged bootstrap step: role creation and grants (RX-47).

WHY THIS IS A SEPARATE STEP FROM THE MIGRATIONS, tested separately. Putting role
creation in a migration would mean the migration credential held CREATEROLE,
which turns a compromised deploy step into privilege escalation; and roles are
CLUSTER-wide while migrations are per-database, so a role-creating migration run
against a second database would silently re-alter the first database's runtime
identity. The ordered procedure is in services/api/MIGRATIONS.md.

WHAT IS ASSERTED, beyond "it ran":

  * the created role has the attributes that make RLS apply to it, read from
    `pg_roles` rather than inferred from the statement that was sent;
  * it holds exactly the four DML privileges and NOT `TRUNCATE`, which is the
    dangerous one - `DELETE` is filtered by the policy, `TRUNCATE` empties the
    table for every tenant at once and is not policed by row-level security;
  * the withholding is demonstrated behaviourally as well as from
    `information_schema`, because a privilege listing can be read correctly and
    still be the wrong listing;
  * a role NAME containing quoting metacharacters is quoted rather than executed.

IDENTITY: `retrace_app` for every statement here. Every role these tests create
is a throwaway `retrace_tmp_*` (plus the one deliberately hostile name), dropped
in teardown after the database. `retrace_svc` is never re-keyed - doing so would
change the credential `tests/postgres` connects with.
"""

from __future__ import annotations

import psycopg
import pytest
import sqlalchemy as sa
from retrace_api.bootstrap.roles import (
    BOOTSTRAP_SETTINGS,
    BOOTSTRAP_SQL,
    RUNTIME_PRIVILEGES,
    WITHHELD_PRIVILEGES,
    assert_runtime_role_is_unprivileged,
    create_service_role,
    grant_runtime_privileges,
)
from retrace_api.db import migrate
from retrace_api.db.catalogue import read_role_facts, read_table_grants
from retrace_api.db.security import SECURED_TABLES
from retrace_api.errors import RolePrivilegeError

pytestmark = pytest.mark.integration

#: A role name built from quoting metacharacters. Not a credit or a command: it
#: is the string an attacker would supply if the bootstrap formatted its
#: identifier into SQL, and the point is that it is stored as a NAME.
HOSTILE_ROLE_NAME = 'rt"; DROP TABLE projects; --'


def _engine(url: sa.URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


@pytest.fixture
def head_database(fresh_database: sa.URL) -> sa.URL:
    migrate.upgrade(fresh_database, "head")
    return fresh_database


def test_the_bootstrap_sql_reads_the_declared_settings() -> None:
    """DRIFT CHECK, no database needed.

    The DO blocks are plain strings with the setting names spelled out, so they
    cannot be interpolated into - but that means a renamed `_GUC_*` constant would
    leave the SQL reading a setting nobody sets, and `current_setting` on an unset
    custom GUC raises rather than returning NULL, so the failure would surface as
    an opaque server error during bootstrap. This asserts the two spellings agree.
    """
    joined = "\n".join(BOOTSTRAP_SQL)
    for setting in BOOTSTRAP_SETTINGS:
        assert f"current_setting('{setting}')" in joined, (
            f"{setting!r} is declared but no bootstrap statement reads it"
        )
    create_sql, grant_sql = BOOTSTRAP_SQL
    assert "CREATE ROLE %I" in create_sql and "PASSWORD %L" in create_sql, create_sql
    # The identifier and the literal must use the server's own quoting
    # specifiers. `%s` would interpolate unquoted.
    assert "%s" not in create_sql and "%s" not in grant_sql
    for withheld in ("TRUNCATE", "REFERENCES", "TRIGGER"):
        assert withheld not in grant_sql, f"the grant block mentions {withheld}"


def test_create_service_role_produces_a_role_rls_applies_to(
    head_database: sa.URL, scratch
) -> None:
    """RX-47: the created role has the attributes that keep it subject to policies."""
    role, secret = scratch.role_name(), scratch.secret()
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            create_service_role(c, role=role, password=secret)
        with engine.connect() as c:
            facts = read_role_facts(c, role)
            assert_runtime_role_is_unprivileged(c, role)
    finally:
        engine.dispose()

    assert facts.exists, facts
    assert not facts.superuser and not facts.bypass_rls, facts
    assert not facts.create_db and not facts.create_role, facts
    assert facts.can_login, "the runtime role must be able to log in"


def test_create_service_role_is_idempotent(head_database: sa.URL, scratch) -> None:
    """Re-running it must succeed and leave the same attributes.

    This is what makes a planned credential rotation a re-run of one documented
    command rather than a hand-written ALTER.
    """
    role = scratch.role_name()
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            create_service_role(c, role=role, password=scratch.secret())
        with engine.connect() as c:
            first = read_role_facts(c, role)
        with engine.begin() as c:
            create_service_role(c, role=role, password=scratch.secret())
        with engine.connect() as c:
            second = read_role_facts(c, role)
    finally:
        engine.dispose()
    assert first == second, (first, second)


def test_the_created_role_can_connect_with_the_credential_it_was_given(
    head_database: sa.URL, scratch
) -> None:
    """The credential actually works, which the attribute read cannot show.

    Without this, `create_service_role` could set no usable password and every
    other assertion in this module would still pass.
    """
    role, secret = scratch.role_name(), scratch.secret()
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            create_service_role(c, role=role, password=secret)
        with engine.begin() as c:
            grant_runtime_privileges(c, role=role, tables=SECURED_TABLES)
    finally:
        engine.dispose()

    runtime = _engine(scratch.url_for(head_database, user=role, password=secret))
    try:
        with runtime.connect() as c:
            who = c.execute(sa.text("SELECT current_user")).scalar()
    finally:
        runtime.dispose()
    assert who == role, who


def test_create_service_role_refuses_an_empty_credential(
    head_database: sa.URL, scratch
) -> None:
    """NEGATIVE CONTROL: no invented credential, and no passwordless role.

    A bootstrap that generated a credential would create one nobody recorded and
    therefore nobody can rotate; one that accepted an empty string would create a
    LOGIN role whose authentication depends entirely on `pg_hba.conf`.
    """
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            with pytest.raises(RolePrivilegeError):
                create_service_role(c, role=scratch.role_name(), password="")
            with pytest.raises(RolePrivilegeError):
                create_service_role(c, role="", password=scratch.secret())
    finally:
        engine.dispose()


def test_grant_gives_exactly_the_dml_privileges(head_database: sa.URL, scratch) -> None:
    """RX-47: four privileges, and not one more, read from `information_schema`."""
    role, secret = scratch.role_name(), scratch.secret()
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            create_service_role(c, role=role, password=secret)
        with engine.begin() as c:
            grant_runtime_privileges(c, role=role, tables=SECURED_TABLES)
        with engine.connect() as c:
            granted = {t: read_table_grants(c, t, role) for t in SECURED_TABLES}
            # The version table is deliberately NOT granted: the runtime identity
            # has no business reading or writing the schema's revision.
            version_grants = read_table_grants(c, "alembic_version", role)
    finally:
        engine.dispose()

    for table, privileges in granted.items():
        assert privileges == tuple(sorted(RUNTIME_PRIVILEGES)), f"{table}: {privileges}"
        for withheld in WITHHELD_PRIVILEGES:
            assert withheld not in privileges, f"{table} granted {withheld}"
    assert version_grants == (), version_grants


def test_the_granted_role_cannot_truncate(head_database: sa.URL, scratch) -> None:
    """NEGATIVE CONTROL, behavioural: the most important withholding.

    `DELETE` is filtered by the tenant policy, so a request can at worst delete
    its own tenant's rows. `TRUNCATE` is NOT policed by row-level security: one
    statement would empty the table for every tenant. The privilege listing above
    says it was not granted; this says the server refuses it.

    The matching policed `DELETE` is asserted to be permitted in the same test, so
    the refusal is specific to TRUNCATE rather than a broken connection.
    """
    role, secret = scratch.role_name(), scratch.secret()
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            create_service_role(c, role=role, password=secret)
        with engine.begin() as c:
            grant_runtime_privileges(c, role=role, tables=SECURED_TABLES)
    finally:
        engine.dispose()

    runtime = _engine(scratch.url_for(head_database, user=role, password=secret))
    try:
        with runtime.connect() as c:
            with pytest.raises(sa.exc.ProgrammingError) as caught:
                c.exec_driver_sql("TRUNCATE projects")
            c.rollback()
            c.execute(
                sa.text("SELECT set_config('retrace.tenant_id', gen_random_uuid()::text, true)")
            )
            deleted = c.execute(sa.text("DELETE FROM projects")).rowcount
            c.rollback()
    finally:
        runtime.dispose()
    assert isinstance(caught.value.orig, psycopg.errors.InsufficientPrivilege), caught.value.orig
    assert deleted == 0, deleted


def test_grant_refuses_a_table_name_that_would_split(
    head_database: sa.URL, scratch
) -> None:
    """NEGATIVE CONTROL for the one place the table list is encoded as text.

    The list crosses into SQL as a single comma-separated setting and is split
    server-side, so a comma inside a name would silently become two names - and
    the grant would then be applied to tables nobody asked for, or fail
    confusingly. Refused up front instead.
    """
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            with pytest.raises(RolePrivilegeError) as caught:
                grant_runtime_privileges(
                    c, role=scratch.role_name(), tables=("projects,result_contracts",)
                )
            with pytest.raises(RolePrivilegeError):
                grant_runtime_privileges(c, role=scratch.role_name(), tables=())
    finally:
        engine.dispose()
    assert "comma" in str(caught.value), caught.value


def test_a_hostile_role_name_is_quoted_and_not_executed(
    head_database: sa.URL, scratch
) -> None:
    """NEGATIVE CONTROL for the injection surface the bootstrap deliberately avoids.

    `CREATE ROLE` cannot take the role name as a bind parameter, so the obvious
    implementation formats it into the statement - and that is where injection
    enters a bootstrap script. Here the name is passed as a bind parameter to
    `set_config` and quoted server-side with `format('%I')`.

    The name used contains a double quote, a statement separator, a DROP and a
    comment marker. The assertions are that it became a ROLE NAME, verbatim, and
    that `projects` is still there.
    """
    name = scratch.register_role(HOSTILE_ROLE_NAME)
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            create_service_role(c, role=name, password=scratch.secret())
        with engine.connect() as c:
            facts = read_role_facts(c, name)
            tables = set(sa.inspect(c).get_table_names(schema="public"))
    finally:
        engine.dispose()

    assert facts.exists, "the hostile name did not become a role, so nothing was demonstrated"
    assert facts.name == HOSTILE_ROLE_NAME, facts.name
    assert not facts.superuser and not facts.bypass_rls, facts
    assert "projects" in tables, "the injected statement executed - projects was dropped"

"""Attributes of the identity the runtime actually connects as (RX-47).

WHY THIS IS NOT A FORMALITY. A superuser, a `BYPASSRLS` role, and a table's owner
without `FORCE ROW LEVEL SECURITY` are all exempt from row-level security. If the
application connects as any of them, `tenant_isolation` is decorative - and, worse
for evidence, an isolation test run as that identity PASSES against a database
with no policies at all. So the role attributes are a precondition for every
other isolation claim in this repository, including the ones in `tests/postgres`.

Read from the realised `pg_roles` and `pg_class`, never from the bootstrap
script's intent: the script may have been run with different arguments, against a
different cluster, or not at all.

Each check is paired with a role that VIOLATES it, so the check is shown to be
able to fail. A privilege check that has only ever been run against a correct role
is indistinguishable from one that returns success unconditionally.

IDENTITY: `retrace_app` for the catalogue reads and for creating the throwaway
roles; `retrace_svc` for the one test that connects as the runtime identity. The
`retrace_svc` credential is READ from `.env` and never re-set - re-keying it would
break `tests/postgres`, which connects as that role.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from retrace_api.bootstrap.roles import (
    assert_runtime_role_is_unprivileged,
    grant_runtime_privileges,
)
from retrace_api.db import migrate
from retrace_api.db.catalogue import read_role_facts, tables_owned_by
from retrace_api.db.security import SECURED_TABLES
from retrace_api.errors import RolePrivilegeError

pytestmark = pytest.mark.integration


def _engine(url: sa.URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


@pytest.fixture
def head_database(fresh_database: sa.URL) -> sa.URL:
    migrate.upgrade(fresh_database, "head")
    return fresh_database


def _create_role(url: sa.URL, name: str, attributes: str) -> None:
    """Create a throwaway role with the given attribute clause.

    The attribute clause is a literal from this module and the name comes from
    `Scratch.role_name()` (a prefix plus random hex), so neither is input. Quoted
    server-side with `format('%I')` rather than interpolated, for the same reason
    `retrace_api.bootstrap.roles` does it that way.
    """
    engine = _engine(url)
    try:
        with engine.begin() as c:
            c.execute(
                sa.text("SELECT set_config('retrace.test_role', :r, true)"), {"r": name}
            )
            c.execute(
                sa.text(
                    "DO $t$ BEGIN EXECUTE format('CREATE ROLE %I " + attributes + "', "
                    "current_setting('retrace.test_role')); END $t$;"
                )
            )
    finally:
        engine.dispose()


def test_the_runtime_role_is_not_superuser_and_cannot_bypass_rls(
    head_database: sa.URL, runtime_role_name: str
) -> None:
    """RX-47: the two attributes that decide whether RLS applies at all."""
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            facts = read_role_facts(c, runtime_role_name)
    finally:
        engine.dispose()
    assert facts.exists, f"{runtime_role_name} does not exist; nothing was verified"
    assert not facts.superuser, facts
    assert not facts.bypass_rls, facts
    assert not facts.create_db, facts
    assert not facts.create_role, facts
    assert facts.can_login, "the runtime role cannot log in, so it is not the runtime identity"


def test_the_runtime_role_owns_no_tables_in_a_migrated_database(
    head_database: sa.URL, runtime_role_name: str
) -> None:
    """RX-47: ownership is the third exemption, and the easiest to acquire by accident.

    An owner is exempt from its table's policies unless FORCE is set. Owning
    nothing removes the exemption structurally, instead of depending on FORCE
    being remembered for every table anyone adds later.
    """
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            owned = tables_owned_by(c, runtime_role_name)
            # Discrimination: the migration identity DOES own the tables, so the
            # empty result above is a fact about this role rather than a query
            # that returns nothing for everyone.
            migrator = str(c.execute(sa.text("SELECT current_user")).scalar())
            by_migrator = tables_owned_by(c, migrator)
    finally:
        engine.dispose()
    assert owned == (), f"the runtime role owns tables: {owned}"
    assert set(by_migrator) >= set(SECURED_TABLES), (
        "the ownership query found nothing for the migration identity either, so the "
        f"empty result for the runtime role proves nothing: {by_migrator}"
    )


def test_the_privilege_assertion_accepts_the_runtime_role(
    head_database: sa.URL, runtime_role_name: str
) -> None:
    """The positive case: the real runtime identity passes."""
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            assert_runtime_role_is_unprivileged(c, runtime_role_name)  # must not raise
    finally:
        engine.dispose()


def test_the_runtime_role_cannot_change_the_schema_that_polices_it(
    head_database: sa.URL, scratch, runtime_role_name: str, runtime_password: str
) -> None:
    """RX-47: the separation that makes the runtime credential safe to deploy.

    With DML granted and nothing else, the runtime identity must still be unable
    to create a table or drop the policy confining it. If it could drop the
    policy, a request-handling defect could DISABLE isolation rather than merely
    violate it.
    """
    admin = _engine(head_database)
    try:
        with admin.begin() as c:
            grant_runtime_privileges(c, role=runtime_role_name, tables=SECURED_TABLES)
    finally:
        admin.dispose()

    svc = _engine(
        scratch.url_for(head_database, user=runtime_role_name, password=runtime_password)
    )
    try:
        with svc.connect() as c:
            with pytest.raises(sa.exc.ProgrammingError):
                c.exec_driver_sql("CREATE TABLE should_not_exist (x int)")
            c.rollback()
            with pytest.raises(sa.exc.ProgrammingError):
                c.exec_driver_sql("DROP POLICY tenant_isolation ON projects")
            c.rollback()
            # And the privilege it DOES have still works, so the two refusals are
            # not simply a broken connection.
            granted = c.execute(sa.text("SELECT count(*) FROM projects")).scalar()
    finally:
        svc.dispose()
    assert granted == 0, granted


# --------------------------------------------------------------------------- #
# Negative controls. Each creates a role that violates one condition and asserts
# the check names it. Roles are prefixed `retrace_tmp_`, registered for teardown
# BEFORE creation, and dropped after the database.
# --------------------------------------------------------------------------- #
def test_the_privilege_assertion_rejects_a_bypassrls_role(
    head_database: sa.URL, scratch
) -> None:
    """NEGATIVE CONTROL: BYPASSRLS is exempt from every policy, FORCE or not."""
    name = scratch.role_name()
    _create_role(head_database, name, "NOLOGIN NOSUPERUSER BYPASSRLS")
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            with pytest.raises(RolePrivilegeError) as caught:
                assert_runtime_role_is_unprivileged(c, name)
    finally:
        engine.dispose()
    assert "BYPASSRLS" in str(caught.value), caught.value


def test_the_privilege_assertion_rejects_a_superuser_role(
    head_database: sa.URL, scratch
) -> None:
    """NEGATIVE CONTROL: a superuser bypasses RLS entirely.

    Created NOLOGIN. `rolsuper` is what the check reads, so withholding LOGIN
    costs the control nothing and means a teardown failure could not leave a
    usable superuser credential behind in the shared disposable cluster.
    """
    name = scratch.role_name()
    _create_role(head_database, name, "NOLOGIN SUPERUSER")
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            with pytest.raises(RolePrivilegeError) as caught:
                assert_runtime_role_is_unprivileged(c, name)
    finally:
        engine.dispose()
    assert "SUPERUSER" in str(caught.value), caught.value


def test_the_privilege_assertion_rejects_a_table_owning_role(
    head_database: sa.URL, scratch
) -> None:
    """NEGATIVE CONTROL: ownership, on a contained throwaway table.

    The table is created for this test and dropped with the database; the baseline
    tables' ownership is not touched.
    """
    name = scratch.role_name()
    _create_role(head_database, name, "NOLOGIN NOSUPERUSER NOBYPASSRLS")
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            c.exec_driver_sql("CREATE TABLE owned_elsewhere (x int)")
            c.execute(
                sa.text("SELECT set_config('retrace.test_role', :r, true)"), {"r": name}
            )
            c.execute(
                sa.text(
                    "DO $t$ BEGIN EXECUTE format('ALTER TABLE owned_elsewhere OWNER TO %I', "
                    "current_setting('retrace.test_role')); END $t$;"
                )
            )
        with engine.connect() as c:
            with pytest.raises(RolePrivilegeError) as caught:
                assert_runtime_role_is_unprivileged(c, name)
    finally:
        engine.dispose()
    assert "owned_elsewhere" in str(caught.value), caught.value


def test_the_privilege_assertion_refuses_an_absent_role(head_database: sa.URL) -> None:
    """VACUITY GUARD: a role that does not exist must not read as unprivileged.

    This is the most likely real state on a database where the bootstrap step was
    skipped, and it is exactly the case a naive "no privileges found" check would
    report as safe.
    """
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            with pytest.raises(RolePrivilegeError) as caught:
                assert_runtime_role_is_unprivileged(c, "retrace_role_that_does_not_exist")
    finally:
        engine.dispose()
    assert "does not exist" in str(caught.value), caught.value


def test_an_unprivileged_throwaway_role_passes(head_database: sa.URL, scratch) -> None:
    """Discrimination for the four controls above.

    They prove the check refuses. This proves it does not refuse everything: a
    freshly created NOSUPERUSER / NOBYPASSRLS role owning nothing passes. A check
    that rejected every role would satisfy all four controls and be useless.
    """
    name = scratch.role_name()
    _create_role(head_database, name, "NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE")
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            assert_runtime_role_is_unprivileged(c, name)  # must not raise
    finally:
        engine.dispose()

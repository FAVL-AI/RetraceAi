"""PostgreSQL row-level security proofs (RX-47, RX-48, RX-49).

Run against real PostgreSQL. SQLite evidence is NOT accepted for these
properties: RLS, FORCE RLS, role attributes and transaction-local settings are
PostgreSQL behaviours and only PostgreSQL can demonstrate them.

Every isolation claim here is paired with a DISCRIMINATION control proving the
rows actually exist and are visible to a role that bypasses RLS. Without that
control, an empty result set is indistinguishable from an empty table, and the
test would "pass" against a database containing nothing.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.integration

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
NOW = dt.datetime(2026, 10, 2, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def seeded(owner_dsn: str):
    """One project per tenant, inserted by the owner with RLS satisfied."""
    pa, pb = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(owner_dsn) as c:
        with c.cursor() as cur:
            rows = ((TENANT_A, pa, "A-project"), (TENANT_B, pb, "B-project"))
            for tid, pid, name in rows:
                cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(tid),))
                cur.execute(
                    "insert into projects (tenant_id, id, name, created_at) values (%s,%s,%s,%s)",
                    (tid, pid, name, NOW),
                )
        c.commit()
    yield pa, pb
    with psycopg.connect(owner_dsn) as c:
        c.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
        c.execute("delete from projects where tenant_id = %s", (TENANT_A,))
        c.commit()
    with psycopg.connect(owner_dsn) as c:
        c.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_B),))
        c.execute("delete from projects where tenant_id = %s", (TENANT_B,))
        c.commit()


def test_service_role_is_not_superuser_or_bypassrls(svc_dsn: str) -> None:
    """RX-47: if the service role could bypass RLS, every policy below is decorative."""
    with psycopg.connect(svc_dsn) as c:
        row = c.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
    assert row == (False, False), f"service role can bypass RLS: {row}"


def test_service_role_owns_no_tables(svc_dsn: str) -> None:
    """A table's owner is exempt from RLS unless FORCE is set; own nothing anyway."""
    with psycopg.connect(svc_dsn) as c:
        owned = c.execute(
            "select relname from pg_class c join pg_roles r on r.oid = c.relowner "
            "where r.rolname = current_user and c.relkind = 'r'"
        ).fetchall()
    assert owned == [], f"service role owns tables: {owned}"


def test_rls_is_enabled_and_forced(svc_dsn: str) -> None:
    with psycopg.connect(svc_dsn) as c:
        rows = dict(
            c.execute(
                "select relname, relrowsecurity and relforcerowsecurity from pg_class "
                "where relname in ('projects','result_contracts')"
            ).fetchall()
        )
    assert rows == {"projects": True, "result_contracts": True}, rows


def test_tenant_sees_only_its_own_rows(svc_dsn: str, seeded) -> None:
    """RX-47 the positive case."""
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
        names = [r[0] for r in cur.execute("select name from projects").fetchall()]
    assert names == ["A-project"], names


def test_cross_tenant_read_returns_nothing(svc_dsn: str, seeded) -> None:
    """RX-47: tenant A must not see tenant B's row even by explicit id."""
    _, pb = seeded
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
        rows = cur.execute("select * from projects where id = %s", (pb,)).fetchall()
    assert rows == [], "tenant A read tenant B's row"


def test_discrimination_the_hidden_row_really_exists(owner_dsn: str, seeded) -> None:
    """NEGATIVE CONTROL for the two tests above.

    The rows are invisible to tenant A because of RLS, not because the table is
    empty. Read them with a BYPASSRLS role and prove both are present. Without
    this, an empty database would make the isolation tests pass vacuously.
    """
    _, pb = seeded
    with psycopg.connect(owner_dsn) as c:
        total = c.execute("select count(*) from projects").fetchone()[0]
        b_visible = c.execute("select name from projects where id = %s", (pb,)).fetchall()
    assert total >= 2, f"fixture did not seed both tenants: {total}"
    assert b_visible == [("B-project",)], b_visible


def test_unset_tenant_sees_nothing_fails_closed(svc_dsn: str, seeded) -> None:
    """RX-48: a missing identity must hide everything, never default to visible."""
    with psycopg.connect(svc_dsn) as c:
        rows = c.execute("select * from projects").fetchall()
    assert rows == [], "rows visible with NO tenant context set"


def test_identity_does_not_leak_between_transactions(svc_dsn: str, seeded) -> None:
    """RX-48: SET LOCAL is transaction-scoped, so a pooled connection cannot
    carry one request's tenant into the next request on the same connection."""
    with psycopg.connect(svc_dsn) as c:
        with c.cursor() as cur:
            cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
            assert cur.execute("select count(*) from projects").fetchone()[0] == 1
        c.commit()
        # Same physical connection, new transaction, no identity set.
        leaked = c.execute("select count(*) from projects").fetchone()[0]
    assert leaked == 0, "tenant identity leaked into the next transaction"


def test_cannot_insert_a_row_for_another_tenant(svc_dsn: str) -> None:
    """RX-47 WITH CHECK: writing across the boundary is refused, not silently retagged."""
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute(
                "insert into projects (tenant_id, id, name, created_at) values (%s,%s,%s,%s)",
                (TENANT_B, uuid.uuid4(), "smuggled", NOW),
            )
        c.rollback()


def test_composite_fk_blocks_cross_tenant_reference(owner_dsn: str, seeded) -> None:
    """RX-49: a child row cannot point at a parent belonging to another tenant."""
    pa, _ = seeded
    with psycopg.connect(owner_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_B),))
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            cur.execute(
                "insert into result_contracts (tenant_id, id, project_id, contract_hash) "
                "values (%s,%s,%s,%s)",
                (TENANT_B, uuid.uuid4(), pa, "0" * 64),
            )
        c.rollback()


def test_service_role_cannot_create_tables(svc_dsn: str) -> None:
    """Least privilege: the application cannot change the schema it is policed by."""
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            cur.execute("create table should_not_exist (x int)")
        c.rollback()

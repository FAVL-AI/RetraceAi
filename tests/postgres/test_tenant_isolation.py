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


# --------------------------------------------------------------------------- #
# Pooled-connection and context-shape cases.
#
# The empty-string finding is NOT universal: `set_config(..., is_local => true)`
# reverts to '' at transaction end, which is what the nullif() in the policy
# exists for. A SESSION-level setting behaves differently and is covered
# separately below, so the regression test does not overclaim.
# --------------------------------------------------------------------------- #
def test_empty_string_context_sees_nothing(svc_dsn: str, seeded) -> None:
    """The exact regression: '' must match no rows, not raise and not leak."""
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", ("",))
        rows = cur.execute("select * from projects").fetchall()
    assert rows == [], "empty tenant context returned rows"


def test_malformed_context_is_refused_not_coerced(svc_dsn: str, seeded) -> None:
    """A non-uuid tenant context must fail, never silently match something."""
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", ("not-a-uuid",))
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            cur.execute("select * from projects").fetchall()
        c.rollback()


def test_session_level_context_is_the_other_case(svc_dsn: str, seeded) -> None:
    """A SESSION setting persists past commit, which is exactly why requests must
    use the transaction-local form. Documented as a hazard, not a recommendation."""
    with psycopg.connect(svc_dsn) as c:
        with c.cursor() as cur:
            # is_local=false is the SESSION-level form, and unlike `SET SESSION`
            # it accepts a bind parameter, so no interpolation is needed.
            cur.execute("select set_config('retrace.tenant_id', %s, false)", (str(TENANT_A),))
            assert cur.execute("select count(*) from projects").fetchone()[0] == 1
        c.commit()
        # Still set: a pooled connection would carry tenant A into the next request.
        leaked = c.execute("select count(*) from projects").fetchone()[0]
    assert leaked == 1, (
        "expected the session-level setting to persist; if this changes, the "
        "argument for SET LOCAL in request handling needs restating"
    )


def test_rollback_discards_the_write_and_the_identity(svc_dsn: str, seeded) -> None:
    """RX-48: neither the row nor the tenant context survives a rollback."""
    new_id = uuid.uuid4()
    with psycopg.connect(svc_dsn) as c:
        with c.cursor() as cur:
            cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
            cur.execute(
                "insert into projects (tenant_id, id, name, created_at) values (%s,%s,%s,%s)",
                (TENANT_A, new_id, "rolled-back", NOW),
            )
            assert cur.execute("select count(*) from projects").fetchone()[0] == 2
        c.rollback()
        assert c.execute("select count(*) from projects").fetchone()[0] == 0, (
            "identity survived the rollback"
        )
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
        assert cur.execute(
            "select count(*) from projects where id = %s", (new_id,)
        ).fetchone()[0] == 0, "the rolled-back row persisted"


def test_alternating_tenants_on_one_reused_connection(svc_dsn: str, seeded) -> None:
    """The pooling case: three transactions, three identities, one socket."""
    with psycopg.connect(svc_dsn) as c:
        seen = []
        for tenant in (TENANT_A, TENANT_B, TENANT_A):
            with c.cursor() as cur:
                cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(tenant),))
                seen.append(
                    [r[0] for r in cur.execute("select name from projects").fetchall()]
                )
            c.commit()
    assert seen == [["A-project"], ["B-project"], ["A-project"]], seen


def test_cross_tenant_update_and_delete_affect_nothing(svc_dsn: str, seeded) -> None:
    """Writes are policed too: tenant A cannot reach tenant B's row to change it."""
    _, pb = seeded
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_A),))
        cur.execute("update projects set name = %s where id = %s", ("hijacked", pb))
        assert cur.rowcount == 0, "a cross-tenant UPDATE matched rows"
        cur.execute("delete from projects where id = %s", (pb,))
        assert cur.rowcount == 0, "a cross-tenant DELETE matched rows"
        c.commit()
    with psycopg.connect(svc_dsn) as c, c.cursor() as cur:
        cur.execute("select set_config('retrace.tenant_id', %s, true)", (str(TENANT_B),))
        assert cur.execute("select name from projects where id = %s", (pb,)).fetchone() == (
            "B-project",
        ), "tenant B's row was modified across the boundary"


@pytest.mark.skip(
    reason=(
        "NOT_RUN, not passing: requires services/api, which does not exist. The "
        "requirement is that the application derives the tenant from an "
        "AUTHENTICATED principal and never from a caller-supplied value. These "
        "tests set the context directly, so they prove the database half only. "
        "Kept as an explicit, visible gap rather than omitted."
    )
)
def test_tenant_context_comes_from_authenticated_authorisation() -> None:  # pragma: no cover
    raise AssertionError("unimplemented gate")

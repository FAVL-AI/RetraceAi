"""The composite key, and the RLS bypass that makes it necessary (RX-49).

=============================================================================
THE CLAIM UNDER TEST
=============================================================================

PostgreSQL's referential-integrity checks BYPASS row-level security. The server
performs them with an internal query that is not subject to the referenced
table's policies, deliberately: an RI check that a policy could make miss rows
would let a dangling reference be created and would break the constraint's own
guarantee.

The consequence for tenancy is the part that is easy to get wrong, and it is the
reason `retrace_api/db/models.py` carries a comment saying the composite foreign
key is NOT redundant with RLS. With a SINGLE-column foreign key, a caller
carrying tenant B's identity can reference tenant A's row: the row is invisible to
it on SELECT, the RI check sees it anyway, and the insert succeeds. RLS filtered
the reads and still did not prevent the RELATIONSHIP.

This module does not assert that claim from documentation. It DEMONSTRATES it:

  1. `test_referential_integrity_bypasses_row_level_security` builds a contained
     single-column-FK table and shows the cross-tenant insert SUCCEEDING while the
     referenced row is provably invisible to the inserting identity. That is a
     test whose PASS condition is the vulnerability - which is what makes it
     evidence rather than restatement.
  2. `test_the_composite_form_refuses_the_identical_insert` runs the same insert
     against the composite form and shows it refused.
  3. `test_the_composite_key_refuses_a_cross_tenant_reference_on_the_real_schema`
     does it on `result_contracts` itself, AS A SUPERUSER - so row-level security
     is bypassed for the inserting identity too and the refusal can only have come
     from the constraint.

The demonstration tables are created in each test's own disposable database,
named `demo_*`, referenced by nothing, and dropped with the database. They are a
contained fixture that violates the property, which is what rule 5 of the brief
asks for.

IDENTITY: `retrace_app` (superuser) creates the fixtures and performs the
superuser-level refusal test; a throwaway `retrace_tmp_*` role created through
the real bootstrap path performs the bypass demonstration, because a superuser
could not demonstrate it - it bypasses RLS for reads as well, so the referenced
row would not be invisible to it.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
import sqlalchemy as sa
from retrace_api.bootstrap.roles import create_service_role, grant_runtime_privileges
from retrace_api.db import migrate
from retrace_api.db.security import apply_security_configuration

pytestmark = pytest.mark.integration

TENANT_A = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
TENANT_B = uuid.UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

DEMO_TABLES = ("demo_single_fk", "demo_composite_fk")

#: A unique index on `projects(id)` alone. Needed only so a SINGLE-column foreign
#: key can target it - the baseline schema deliberately has no such index,
#: because `(tenant_id, id)` is the only key a reference should be able to use.
_DEMO_UNIQUE_ID = "CREATE UNIQUE INDEX demo_projects_id_key ON projects (id)"

#: The vulnerable shape: one column, referencing `projects(id)`. `tenant_id` is
#: present and policed, so the table looks tenant-scoped; the REFERENCE is not.
_DEMO_SINGLE_FK = """
CREATE TABLE demo_single_fk (
    tenant_id  uuid NOT NULL,
    id         uuid NOT NULL,
    project_id uuid NOT NULL REFERENCES projects (id),
    PRIMARY KEY (tenant_id, id)
)
"""

#: The correct shape: the tenant travels with the reference.
_DEMO_COMPOSITE_FK = """
CREATE TABLE demo_composite_fk (
    tenant_id  uuid NOT NULL,
    id         uuid NOT NULL,
    project_id uuid NOT NULL,
    PRIMARY KEY (tenant_id, id),
    FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)
)
"""

_INSERT_DEMO_SINGLE = (
    "INSERT INTO demo_single_fk (tenant_id, id, project_id) VALUES (:t, :i, :p)"
)
_INSERT_DEMO_COMPOSITE = (
    "INSERT INTO demo_composite_fk (tenant_id, id, project_id) VALUES (:t, :i, :p)"
)


def _engine(url: sa.URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


@pytest.fixture
def demonstration(fresh_database: sa.URL, scratch):
    """A migrated database, the two demo tables, and an unprivileged role.

    Returns `(admin_url, runtime_url, project_a_id)`. Tenant A owns one project;
    the runtime role is granted DML on `projects` and both demo tables, and every
    one of them has RLS enabled, FORCED and policed by the same predicate the
    migrations install - so the demo differs from the real schema in exactly one
    respect: the shape of the foreign key.
    """
    migrate.upgrade(fresh_database, "head")
    role = scratch.role_name()
    secret = scratch.secret()
    project_a = uuid.uuid4()

    engine = _engine(fresh_database)
    try:
        with engine.begin() as c:
            c.exec_driver_sql(_DEMO_UNIQUE_ID)
            c.exec_driver_sql(_DEMO_SINGLE_FK)
            c.exec_driver_sql(_DEMO_COMPOSITE_FK)
            apply_security_configuration(c, DEMO_TABLES)
            create_service_role(c, role=role, password=secret)
        with engine.begin() as c:
            grant_runtime_privileges(c, role=role, tables=("projects", *DEMO_TABLES))
            c.execute(
                sa.text(
                    "INSERT INTO projects (tenant_id, id, name, created_at) "
                    "VALUES (:t, :i, 'A-project', now())"
                ),
                {"t": TENANT_A, "i": project_a},
            )
    finally:
        engine.dispose()

    return fresh_database, scratch.url_for(fresh_database, user=role, password=secret), project_a


def test_referential_integrity_bypasses_row_level_security(demonstration) -> None:
    """NEGATIVE CONTROL, and the justification for the composite key (RX-49).

    The PASS condition here is the cross-tenant insert SUCCEEDING. That is
    deliberate: it is the only way to show that row-level security does not close
    this, and therefore that the composite foreign key in the real schema is
    load-bearing rather than belt-and-braces.

    Three facts are asserted together, because any one alone would be
    unconvincing:

      * tenant B cannot SELECT tenant A's project - RLS is working;
      * tenant B's insert into the single-column-FK table SUCCEEDS anyway - the RI
        check saw the row RLS hid;
      * the row that was written does reference tenant A's project - so a
        cross-tenant relationship now exists in the database.
    """
    _admin_url, runtime_url, project_a = demonstration
    child_id = uuid.uuid4()

    runtime = _engine(runtime_url)
    try:
        with runtime.begin() as c:
            c.execute(
                sa.text("SELECT set_config('retrace.tenant_id', :t, true)"),
                {"t": str(TENANT_B)},
            )
            visible = c.execute(
                sa.text("SELECT count(*) FROM projects WHERE id = :p"), {"p": project_a}
            ).scalar()
            assert visible == 0, (
                "tenant A's project is visible to tenant B, so row-level security is not "
                "working here and the demonstration would be about nothing"
            )
            # The vulnerability: this must SUCCEED.
            c.execute(
                sa.text(_INSERT_DEMO_SINGLE),
                {"t": TENANT_B, "i": child_id, "p": project_a},
            )
        with runtime.begin() as c:
            c.execute(
                sa.text("SELECT set_config('retrace.tenant_id', :t, true)"),
                {"t": str(TENANT_B)},
            )
            written = c.execute(
                sa.text("SELECT tenant_id, project_id FROM demo_single_fk WHERE id = :i"),
                {"i": child_id},
            ).first()
    finally:
        runtime.dispose()

    assert written is not None, (
        "the cross-tenant insert did not persist; if it was refused, the premise of the "
        "composite-key argument needs restating against this server version"
    )
    assert tuple(written) == (TENANT_B, project_a), (
        f"expected a tenant B row referencing tenant A's project, got {written}"
    )


def test_the_composite_form_refuses_the_identical_insert(demonstration) -> None:
    """The other half of the pair: same identity, same values, composite key (RX-49).

    Only the shape of the foreign key differs from the test above, so the change
    in outcome is attributable to that and to nothing else.
    """
    _admin_url, runtime_url, project_a = demonstration
    runtime = _engine(runtime_url)
    try:
        with runtime.begin() as c:
            c.execute(
                sa.text("SELECT set_config('retrace.tenant_id', :t, true)"),
                {"t": str(TENANT_B)},
            )
            with pytest.raises(sa.exc.IntegrityError) as caught:
                c.execute(
                    sa.text(_INSERT_DEMO_COMPOSITE),
                    {"t": TENANT_B, "i": uuid.uuid4(), "p": project_a},
                )
    finally:
        runtime.dispose()
    assert isinstance(caught.value.orig, psycopg.errors.ForeignKeyViolation), caught.value.orig


def test_the_composite_key_refuses_a_cross_tenant_reference_on_the_real_schema(
    fresh_database: sa.URL,
) -> None:
    """RX-49 on `result_contracts` itself, with RLS taken out of the picture.

    Run as the SUPERUSER migration identity, which bypasses row-level security
    entirely. That is the point: a refusal observed as this identity cannot be
    attributed to a policy, so the composite foreign key is the only thing that
    can have produced it.

    The matching same-tenant insert is asserted to SUCCEED in the same test, so
    the refusal is not simply "inserts into this table fail".
    """
    migrate.upgrade(fresh_database, "head")
    project_a, project_b = uuid.uuid4(), uuid.uuid4()

    engine = _engine(fresh_database)
    try:
        with engine.begin() as c:
            for tenant, pid, name in (
                (TENANT_A, project_a, "A-project"),
                (TENANT_B, project_b, "B-project"),
            ):
                c.execute(
                    sa.text(
                        "INSERT INTO projects (tenant_id, id, name, created_at) "
                        "VALUES (:t, :i, :n, now())"
                    ),
                    {"t": tenant, "i": pid, "n": name},
                )

        with engine.begin() as c:
            # Same tenant: must succeed, so the refusal below is specific.
            c.execute(
                sa.text(
                    "INSERT INTO result_contracts "
                    "(tenant_id, id, project_id, contract_hash) VALUES (:t, :i, :p, :h)"
                ),
                {"t": TENANT_B, "i": uuid.uuid4(), "p": project_b, "h": "b" * 64},
            )

        with engine.begin() as c:
            with pytest.raises(sa.exc.IntegrityError) as caught:
                c.execute(
                    sa.text(
                        "INSERT INTO result_contracts "
                        "(tenant_id, id, project_id, contract_hash) VALUES (:t, :i, :p, :h)"
                    ),
                    {"t": TENANT_B, "i": uuid.uuid4(), "p": project_a, "h": "a" * 64},
                )
    finally:
        engine.dispose()

    assert isinstance(caught.value.orig, psycopg.errors.ForeignKeyViolation), caught.value.orig
    assert "result_contracts_tenant_id_project_id_fkey" in str(caught.value), caught.value

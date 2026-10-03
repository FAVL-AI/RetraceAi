"""Upgrading the hand-applied schema, and proving it equivalent (RX-47, RX-48, RX-49).

THE SITUATION BEING TESTED. `infra/sql/001_tenancy.sql` is already applied in at
least one environment and records no version identity. A database in that state
has both tables and an empty `alembic_version`, so the migration chain has to
reach head from there WITHOUT destroying data and WITHOUT asserting a state it
has not checked.

WHY THERE IS NO `alembic stamp` HERE. Stamping records a revision without looking
at the database. If the hand-applied schema differed in any way - a single-column
key, a dropped policy - the version table would then assert a state the database
does not satisfy and every later migration would build on that false premise.
`0001` converges instead: it verifies the existing structure and adopts it, or
raises `BaselineDivergence` and refuses.

The directive allows stamping only with equivalence proved. This module proves
equivalence anyway, because the claim is worth having independently of how the
revision is recorded: the realised catalogue of an UPGRADED database is compared
field by field with that of a database built FRESH from the migrations. And the
comparison is shown to be able to fail
(`test_the_catalogue_comparison_detects_a_real_difference`), so equality is not
the vacuous result of comparing two empty readings.

WHAT THE COMPARISON EXCLUDES, AND WHY THAT IS NARROWING RATHER THAN HIDING.
Privileges. The hand-applied file grants DML to `retrace_svc`; the migrations do
not, because grants are a separate privileged bootstrap step. Including ACLs would
make the two paths differ for a reason unrelated to schema equivalence. They are
asserted separately in `test_bootstrap_roles.py`.

IDENTITY: `retrace_app` throughout - it creates the databases, applies the
fixture, and runs the migrations.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable

import pytest
import sqlalchemy as sa
from retrace_api.db import migrate
from retrace_api.db.catalogue import realised_catalogue
from retrace_api.db.security import SECURED_TABLES
from retrace_api.errors import BaselineDivergence

pytestmark = pytest.mark.integration

TENANT = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
CREATED_AT = dt.datetime(2026, 10, 3, 9, 30, tzinfo=dt.UTC)
CONTRACT_HASH = "c" * 64

#: Structure the adoption path must REFUSE: a single-column primary key. It
#: enforces uniqueness of `id` but cannot be the target of a composite tenant
#: reference, so it does not satisfy RX-49.
_DIVERGENT_SINGLE_COLUMN_PK = """
CREATE TABLE projects (
    tenant_id  uuid        NOT NULL,
    id         uuid        NOT NULL PRIMARY KEY,
    name       text        NOT NULL,
    created_at timestamptz NOT NULL
)
"""

#: Structure the adoption path must also refuse: the right primary keys but a
#: SINGLE-COLUMN foreign key. This is the dangerous near-miss - it looks correct
#: and reads correctly, and referential integrity bypasses row-level security, so
#: it permits exactly the cross-tenant reference RX-49 exists to prevent.
_DIVERGENT_SINGLE_COLUMN_FK_PARENT = """
CREATE TABLE projects (
    tenant_id  uuid        NOT NULL,
    id         uuid        NOT NULL,
    name       text        NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, id),
    UNIQUE (id)
)
"""
_DIVERGENT_SINGLE_COLUMN_FK_CHILD = """
CREATE TABLE result_contracts (
    tenant_id     uuid     NOT NULL,
    id            uuid     NOT NULL,
    project_id    uuid     NOT NULL REFERENCES projects (id),
    contract_hash char(64) NOT NULL,
    approved      boolean  NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, id)
)
"""

_INSERT_PROJECT = (
    "INSERT INTO projects (tenant_id, id, name, created_at) VALUES (:t, :i, :n, :c)"
)
_INSERT_CONTRACT = (
    "INSERT INTO result_contracts (tenant_id, id, project_id, contract_hash, approved) "
    "VALUES (:t, :i, :p, :h, true)"
)


def _engine(url: sa.URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


@pytest.fixture
def prior_schema_with_data(
    fresh_database: sa.URL, apply_manual_schema: Callable[[sa.URL], None]
) -> tuple[sa.URL, uuid.UUID, uuid.UUID]:
    """A fresh database carrying the hand-applied schema and one row in each table.

    The fixture DATA is the point: an upgrade that rebuilt the tables would lose
    it, and nothing about the resulting catalogue would reveal that.
    """
    apply_manual_schema(fresh_database)
    project_id, contract_id = uuid.uuid4(), uuid.uuid4()
    engine = _engine(fresh_database)
    try:
        with engine.begin() as c:
            # Set the tenant context even though this identity is a superuser and
            # bypasses RLS. If the identity is ever changed to a non-superuser
            # owner, the fixture must still satisfy the WITH CHECK clause.
            c.execute(
                sa.text("SELECT set_config('retrace.tenant_id', :t, true)"),
                {"t": str(TENANT)},
            )
            c.execute(
                sa.text(_INSERT_PROJECT),
                {"t": TENANT, "i": project_id, "n": "pre-existing", "c": CREATED_AT},
            )
            c.execute(
                sa.text(_INSERT_CONTRACT),
                {"t": TENANT, "i": contract_id, "p": project_id, "h": CONTRACT_HASH},
            )
    finally:
        engine.dispose()
    return fresh_database, project_id, contract_id


def test_the_prior_schema_records_no_revision(
    prior_schema_with_data: tuple[sa.URL, uuid.UUID, uuid.UUID],
) -> None:
    """Establishes the starting condition the upgrade has to cope with.

    Without this, a test that upgraded a database which already recorded a
    revision would be exercising a different and much easier path.
    """
    url, _, _ = prior_schema_with_data
    engine = _engine(url)
    try:
        with engine.connect() as c:
            tables = set(sa.inspect(c).get_table_names(schema="public"))
            assert migrate.current_revision(c) is None
    finally:
        engine.dispose()
    assert {"projects", "result_contracts"} <= tables, tables
    assert "alembic_version" not in tables, tables


def test_upgrade_from_the_prior_schema_preserves_the_fixture_data(
    prior_schema_with_data: tuple[sa.URL, uuid.UUID, uuid.UUID],
) -> None:
    """The data survives, value for value, and the revision is recorded (RX-49)."""
    url, project_id, contract_id = prior_schema_with_data
    migrate.upgrade(url, "head")

    engine = _engine(url)
    try:
        with engine.connect() as c:
            revision = migrate.current_revision(c)
            project = c.execute(
                sa.text(
                    "SELECT tenant_id, id, name, created_at FROM projects WHERE id = :i"
                ),
                {"i": project_id},
            ).first()
            contract = c.execute(
                sa.text(
                    "SELECT tenant_id, id, project_id, contract_hash, approved "
                    "FROM result_contracts WHERE id = :i"
                ),
                {"i": contract_id},
            ).first()
    finally:
        engine.dispose()

    assert revision == migrate.head_revision(), revision
    assert project is not None, "the pre-existing project row did not survive the upgrade"
    assert tuple(project) == (TENANT, project_id, "pre-existing", CREATED_AT), project
    assert contract is not None, "the pre-existing contract row did not survive the upgrade"
    assert tuple(contract) == (TENANT, contract_id, project_id, CONTRACT_HASH, True), contract


def test_upgrade_from_the_prior_schema_matches_a_fresh_upgrade(
    prior_schema_with_data: tuple[sa.URL, uuid.UUID, uuid.UUID], scratch
) -> None:
    """Equivalence: the two routes realise the SAME catalogue (RX-47, RX-48, RX-49).

    Structure, column order, constraint names, indexes, RLS flags and the
    deparsed policy predicates all compared. Privileges excluded by design - see
    the module docstring.
    """
    upgraded_url, _, _ = prior_schema_with_data
    migrate.upgrade(upgraded_url, "head")

    fresh_url = scratch.database()
    migrate.upgrade(fresh_url, "head")

    upgraded_engine, fresh_engine = _engine(upgraded_url), _engine(fresh_url)
    try:
        with upgraded_engine.connect() as c:
            upgraded = realised_catalogue(c, SECURED_TABLES)
        with fresh_engine.connect() as c:
            fresh = realised_catalogue(c, SECURED_TABLES)
    finally:
        upgraded_engine.dispose()
        fresh_engine.dispose()

    assert upgraded == fresh, (
        "an upgraded database and a freshly built one do not realise the same "
        "catalogue, so the chain does not converge"
    )
    # Guard against the comparison being between two empty readings.
    assert upgraded["projects"]["primary_key"] == ["tenant_id", "id"], upgraded["projects"]
    assert upgraded["result_contracts"]["policies"], upgraded["result_contracts"]


def test_the_catalogue_comparison_detects_a_real_difference(
    prior_schema_with_data: tuple[sa.URL, uuid.UUID, uuid.UUID], scratch
) -> None:
    """NEGATIVE CONTROL for the equivalence assertion above.

    Two databases are brought to head, then ONE has the foreign-key index dropped
    - a real, single difference. The comparison must report them as unequal. If it
    did not, the equality assertion above would be worthless: it would pass for
    any two databases.
    """
    url_a, _, _ = prior_schema_with_data
    migrate.upgrade(url_a, "head")
    url_b = scratch.database()
    migrate.upgrade(url_b, "head")

    engine_a, engine_b = _engine(url_a), _engine(url_b)
    try:
        with engine_a.connect() as c:
            before = realised_catalogue(c, SECURED_TABLES)
        with engine_b.connect() as c:
            baseline = realised_catalogue(c, SECURED_TABLES)
        assert before == baseline, "the two databases did not start out equal"

        with engine_b.begin() as c:
            c.exec_driver_sql("DROP INDEX result_contracts_tenant_id_project_id_idx")
        with engine_b.connect() as c:
            damaged = realised_catalogue(c, SECURED_TABLES)
    finally:
        engine_a.dispose()
        engine_b.dispose()

    assert damaged != before, (
        "the catalogue comparison did NOT notice a dropped index, so it cannot "
        "substantiate the equivalence claim in this module"
    )
    names_before = {ix["name"] for ix in before["result_contracts"]["indexes"]}
    names_after = {ix["name"] for ix in damaged["result_contracts"]["indexes"]}
    assert names_before - names_after == {"result_contracts_tenant_id_project_id_idx"}


def test_adoption_refuses_a_single_column_primary_key(fresh_database: sa.URL) -> None:
    """NEGATIVE CONTROL: the adoption path must not adopt a divergent schema (RX-49).

    A `projects` table keyed on `id` alone cannot be the target of a composite
    tenant reference. Adopting it would record head on a database that does not
    enforce RX-49 - the exact failure `alembic stamp` would have produced
    silently.
    """
    engine = _engine(fresh_database)
    try:
        with engine.begin() as c:
            c.exec_driver_sql(_DIVERGENT_SINGLE_COLUMN_PK)
    finally:
        engine.dispose()

    with pytest.raises(BaselineDivergence) as caught:
        migrate.upgrade(fresh_database, "head")
    message = str(caught.value)
    assert "projects" in message, message
    assert "tenant_id" in message, message
    # The refusal must not leave a revision recorded: a half-adopted database
    # claiming head would be worse than one claiming nothing.
    engine = _engine(fresh_database)
    try:
        with engine.connect() as c:
            assert migrate.current_revision(c) is None, "a refused adoption recorded a revision"
    finally:
        engine.dispose()


def test_adoption_refuses_a_single_column_foreign_key(fresh_database: sa.URL) -> None:
    """NEGATIVE CONTROL: the dangerous near-miss (RX-49).

    Correct primary keys, but `project_id -> projects(id)`. It reads correctly and
    it is the form that lets one tenant reference another tenant's row, because
    PostgreSQL's referential-integrity check bypasses row-level security. The
    adoption path must refuse it rather than treat the composite key as an
    optional refinement.
    """
    engine = _engine(fresh_database)
    try:
        with engine.begin() as c:
            c.exec_driver_sql(_DIVERGENT_SINGLE_COLUMN_FK_PARENT)
            c.exec_driver_sql(_DIVERGENT_SINGLE_COLUMN_FK_CHILD)
    finally:
        engine.dispose()

    with pytest.raises(BaselineDivergence) as caught:
        migrate.upgrade(fresh_database, "head")
    message = str(caught.value)
    assert "result_contracts" in message, message
    assert "referential-integrity" in message or "referential integrity" in message, message


def test_adoption_accepts_the_real_prior_schema(
    prior_schema_with_data: tuple[sa.URL, uuid.UUID, uuid.UUID],
) -> None:
    """Discrimination for the two controls above.

    They prove the adoption check REFUSES. This proves it does not refuse
    everything - the genuine hand-applied schema is adopted. A check that
    rejected every input would satisfy both negative controls and be useless.
    """
    url, _, _ = prior_schema_with_data
    migrate.upgrade(url, "head")  # must not raise
    engine = _engine(url)
    try:
        with engine.connect() as c:
            assert migrate.current_revision(c) == migrate.head_revision()
    finally:
        engine.dispose()

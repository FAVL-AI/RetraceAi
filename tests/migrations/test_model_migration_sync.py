"""The models and the migrations must define the SAME schema (RX-47, RX-49).

WHY THIS TEST EXISTS. The revision scripts spell their DDL out rather than
calling `Base.metadata.create_all`, which is correct - a migration has to stay
fixed while the models move on, or replaying history would reproduce today's
schema at every revision rather than the schema of the time. The cost of that
correctness is that the two can DRIFT: a column added to a model with no
revision, or a revision that creates something the models do not describe. Either
way the ORM would then issue statements against a shape the database does not
have, and the failure would appear at runtime as an unrelated error.

So the two are compared through the only thing that settles it: the realised
PostgreSQL catalogue of a database built each way. One database is brought to
head by the migration chain; another has the schema created from
`Base.metadata`; the catalogues must be identical.

This also demonstrates the point the naming convention in `retrace_api/db/base.py`
exists for. Because the convention reproduces PostgreSQL's own default names, the
ORM-built tables carry `projects_pkey` and
`result_contracts_tenant_id_project_id_fkey` - the same names the hand-written
migration assigns and the same names plain SQL would produce. An Alembic-flavoured
convention would make this comparison fail on names alone.

IDENTITY: `retrace_app` for both databases.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from retrace_api.db import migrate
from retrace_api.db.base import Base
from retrace_api.db.catalogue import realised_catalogue
from retrace_api.db.security import SECURED_TABLES, apply_security_configuration

pytestmark = pytest.mark.integration


def _engine(url: sa.URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


def _catalogue(url: sa.URL) -> dict[str, Any]:
    engine = _engine(url)
    try:
        with engine.connect() as c:
            return realised_catalogue(c, SECURED_TABLES)
    finally:
        engine.dispose()


def _build_from_models(url: sa.URL) -> None:
    engine = _engine(url)
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as c:
            # The security configuration is NOT in the metadata - row-level
            # security, FORCE and policies cannot be expressed there. That is the
            # same blind spot that makes `alembic revision --autogenerate`
            # unusable for these properties, so the comparison applies the same
            # hand-written DDL to both sides and compares the realised result.
            apply_security_configuration(c, SECURED_TABLES)
    finally:
        engine.dispose()


def test_the_models_and_the_migrations_realise_the_same_schema(
    fresh_database: sa.URL, scratch
) -> None:
    """Drift detector: head and `Base.metadata` must agree, catalogue for catalogue."""
    migrate.upgrade(fresh_database, "head")
    from_migrations = _catalogue(fresh_database)

    model_url = scratch.database()
    _build_from_models(model_url)
    from_models = _catalogue(model_url)

    assert from_models == from_migrations, (
        "the SQLAlchemy models and the migration chain define different schemas; "
        "whichever is wrong, the ORM will issue statements the database cannot satisfy"
    )
    # Guard against comparing two empty readings.
    assert from_migrations["projects"]["primary_key"] == ["tenant_id", "id"]
    assert from_migrations["result_contracts"]["foreign_keys"], from_migrations


def test_the_comparison_detects_a_divergent_model_definition(
    fresh_database: sa.URL, scratch
) -> None:
    """NEGATIVE CONTROL for the drift detector.

    A deliberately divergent definition - the same two tables with a
    SINGLE-column primary key and a single-column foreign key, which is precisely
    the drift that would silently void RX-49 - is built in its own database and
    the comparison must report it as different.

    Built from an independent `MetaData`, so the real `Base.metadata` is not
    mutated and the test cannot leak a corrupted definition into another test.
    """
    migrate.upgrade(fresh_database, "head")
    correct = _catalogue(fresh_database)

    divergent = sa.MetaData()
    sa.Table(
        "projects",
        divergent,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="projects_pkey"),
    )
    sa.Table(
        "result_contracts",
        divergent,
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("contract_hash", sa.CHAR(64), nullable=False),
        sa.Column("approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("tenant_id", "id", name="result_contracts_pkey"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="result_contracts_project_id_fkey"
        ),
    )

    divergent_url = scratch.database()
    engine = _engine(divergent_url)
    try:
        divergent.create_all(engine)
        with engine.begin() as c:
            apply_security_configuration(c, SECURED_TABLES)
    finally:
        engine.dispose()
    observed = _catalogue(divergent_url)

    assert observed != correct, (
        "the catalogue comparison did not notice a single-column primary key and a "
        "single-column foreign key, so it cannot detect model/migration drift"
    )
    assert observed["projects"]["primary_key"] == ["id"], observed["projects"]
    assert not observed["result_contracts"]["foreign_keys"][0]["columns"] == [
        "tenant_id",
        "project_id",
    ], observed["result_contracts"]

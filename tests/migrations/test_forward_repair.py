"""Forward repair, and why it is offered instead of a destructive downgrade.

Serves RX-47 and RX-48.

THE FAILURE THIS RECOVERS FROM is not a bad migration. It is drift on a database
already AT HEAD: a policy dropped by hand during an incident, `FORCE` switched
off to debug something and never restored, a restore from a dump taken before the
policies were applied. Re-running `upgrade` fixes none of that, because the
version table already says head and Alembic has nothing left to run. So the
recovery route has to be something other than the migration chain, and it must
not be "downgrade and re-upgrade" - that would drop every tenant's rows to
reinstate a policy.

`repair_security_configuration` re-applies the idempotent security DDL, then
READS THE CATALOGUE BACK and raises `SchemaRepairFailed` if the tables are still
not isolated. The readback is the part that makes it evidence: statements can
return without error inside a transaction that later rolls back, and an operator
told "repaired" on that basis would walk away from an exposed database.

The downgrade policy is judged PER REVISION rather than by a blanket rule, and
both halves are tested here: `0001` refuses because dropping the tenancy tables
destroys data, `0002` permits it because dropping an index destroys nothing.

IDENTITY: `retrace_app` - repair applies owner-only DDL (`ALTER TABLE ... FORCE
ROW LEVEL SECURITY`, `CREATE POLICY`), which the runtime role cannot run. That
is the point of RX-47, not an inconvenience.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from retrace_api.db import migrate
from retrace_api.db.catalogue import TableSecurity, read_table_security, realised_catalogue
from retrace_api.db.security import SECURED_TABLES
from retrace_api.errors import (
    DestructiveDowngradeRefused,
    SchemaRepairFailed,
    SchemaRevisionMismatch,
)

pytestmark = pytest.mark.integration

FK_INDEX = "result_contracts_tenant_id_project_id_idx"

#: Three realistic, independent forms of drift, applied together.
_DAMAGE = (
    "DROP POLICY tenant_isolation ON projects",
    "ALTER TABLE projects DISABLE ROW LEVEL SECURITY",
    "ALTER TABLE result_contracts NO FORCE ROW LEVEL SECURITY",
)


def _engine(url: sa.URL) -> sa.Engine:
    return sa.create_engine(url, poolclass=sa.pool.NullPool)


@pytest.fixture
def head_database(fresh_database: sa.URL) -> sa.URL:
    migrate.upgrade(fresh_database, "head")
    return fresh_database


def _damage(url: sa.URL) -> None:
    engine = _engine(url)
    try:
        with engine.begin() as c:
            for statement in _DAMAGE:
                c.exec_driver_sql(statement)
    finally:
        engine.dispose()


def test_the_damage_fixture_really_breaks_isolation(head_database: sa.URL) -> None:
    """Precondition for every repair test: the damage must be observable.

    If the fixture did not actually change anything, a repair test would pass by
    comparing a healthy database with itself and would say nothing about repair.
    """
    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            before = read_table_security(c, SECURED_TABLES)
    finally:
        engine.dispose()
    assert all(f.is_isolated for f in before.values()), before

    _damage(head_database)

    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            after = read_table_security(c, SECURED_TABLES)
    finally:
        engine.dispose()
    assert not after["projects"].row_security, after["projects"]
    assert after["projects"].policies == (), after["projects"]
    assert not after["result_contracts"].force_row_security, after["result_contracts"]
    assert not any(f.is_isolated for f in after.values()), after


def test_repair_restores_the_realised_configuration(head_database: sa.URL, scratch) -> None:
    """The recovery path: damaged -> repaired -> catalogue-identical to a fresh head.

    Compared against a SEPARATE, freshly built database rather than against a
    reading taken before the damage. A before/after comparison on one database
    would be satisfied by a repair that restored whatever it happened to have
    recorded; comparing with an independently built head says the database now
    matches what the migrations define.
    """
    reference_url = scratch.database()
    migrate.upgrade(reference_url, "head")
    reference_engine = _engine(reference_url)
    try:
        with reference_engine.connect() as c:
            reference = realised_catalogue(c, SECURED_TABLES)
    finally:
        reference_engine.dispose()

    _damage(head_database)

    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            report = migrate.repair_security_configuration(c)
        with engine.connect() as c:
            repaired = realised_catalogue(c, SECURED_TABLES)
            revision = migrate.current_revision(c)
    finally:
        engine.dispose()

    assert repaired == reference, "repair did not restore the configuration a fresh head has"
    assert report.changed, "the report claims nothing changed, but the database was damaged"
    assert report.statements, "no statements were recorded, so the report is not evidence"
    # Repair is not a migration: it must not move the recorded revision.
    assert revision == migrate.head_revision(), revision


def test_repair_touches_no_rows(head_database: sa.URL) -> None:
    """RX-52-adjacent, and the reason this is offered instead of a downgrade.

    A recovery route that destroys data is not a recovery route. The row inserted
    here must be present, unchanged, after the repair.
    """
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            c.execute(
                sa.text(
                    "INSERT INTO projects (tenant_id, id, name, created_at) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 'survivor', now())"
                )
            )
        _damage(head_database)
        with engine.begin() as c:
            migrate.repair_security_configuration(c)
        with engine.connect() as c:
            names = c.execute(sa.text("SELECT name FROM projects")).scalars().all()
    finally:
        engine.dispose()
    assert list(names) == ["survivor"], names


def test_repair_is_idempotent_on_a_healthy_database(head_database: sa.URL) -> None:
    """Running it when nothing is wrong must be safe and must say so.

    `changed` is False here and True in the damaged case, so the report
    distinguishes the two instead of claiming a repair either way.
    """
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            first = migrate.repair_security_configuration(c)
        with engine.begin() as c:
            second = migrate.repair_security_configuration(c)
    finally:
        engine.dispose()
    assert not first.changed, first
    assert not second.changed, second
    assert first.after == second.after


def test_repair_refuses_a_database_that_is_not_at_head(fresh_database: sa.URL) -> None:
    """NEGATIVE CONTROL for the revision guard.

    A database at `0001` is upgraded no further. Repair must refuse rather than
    configure the tables this head knows about and report success - on a real
    schema that would leave later tenant-bearing tables unprotected while telling
    the operator everything was fine.
    """
    migrate.upgrade(fresh_database, "0001_tenancy_baseline")
    engine = _engine(fresh_database)
    try:
        with engine.begin() as c:
            with pytest.raises(SchemaRevisionMismatch) as caught:
                migrate.repair_security_configuration(c)
    finally:
        engine.dispose()
    message = str(caught.value)
    assert "0001_tenancy_baseline" in message, message
    assert migrate.head_revision() in message, message


def test_repair_refuses_an_unmigrated_database(fresh_database: sa.URL) -> None:
    """The same guard, with no revision recorded at all."""
    engine = _engine(fresh_database)
    try:
        with engine.begin() as c:
            with pytest.raises(SchemaRevisionMismatch):
                migrate.repair_security_configuration(c)
    finally:
        engine.dispose()


def test_repair_reports_failure_when_the_ddl_silently_does_nothing(
    head_database: sa.URL, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NEGATIVE CONTROL for the readback.

    FAULT INJECTION: `apply_security_configuration` is replaced with a no-op that
    returns an empty statement list, which is exactly the shape of the failure the
    readback exists to catch - DDL that appears to have run and has not taken
    effect (a transaction that rolls back, a statement swallowed by a DO block, a
    permissions change that made the ALTER a silent no-op in some future server).

    Without the readback, repair would return a `RepairReport` here and the
    operator would walk away from a database with no policies at all. With it, the
    call raises `SchemaRepairFailed` and names the tables.
    """
    _damage(head_database)
    monkeypatch.setattr(
        migrate, "apply_security_configuration", lambda *_args, **_kwargs: ()
    )
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            with pytest.raises(SchemaRepairFailed) as caught:
                migrate.repair_security_configuration(c)
    finally:
        engine.dispose()
    message = str(caught.value)
    assert "projects" in message, message
    assert "result_contracts" in message, message


@pytest.mark.parametrize(
    ("exists", "enabled", "forced", "policies", "expected"),
    [
        (True, True, True, True, True),
        (True, True, True, False, False),   # FORCE with no policy: denies all, broken
        (True, True, False, True, False),   # ENABLE only: the OWNER stays exempt
        (True, False, True, True, False),   # policy present but RLS off: inert
        (True, False, False, False, False),
        (False, True, True, True, False),   # absent table must never read as isolated
    ],
)
def test_the_isolation_verdict_requires_all_three_conditions(
    exists: bool, enabled: bool, forced: bool, policies: bool, expected: bool
) -> None:
    """NEGATIVE CONTROL for the predicate the readback depends on.

    `is_isolated` is what decides whether a repair succeeded, so it must be shown
    to reject every deficient combination rather than only to accept the good one.
    No database needed: this is the predicate itself.
    """
    facts = TableSecurity(
        table="t",
        exists=exists,
        row_security=enabled,
        force_row_security=forced,
        policies=(("p",) if policies else ()),  # type: ignore[arg-type]
    )
    assert facts.is_isolated is expected, facts


def test_the_baseline_downgrade_is_refused_and_names_the_repair_route(
    head_database: sa.URL,
) -> None:
    """RX-47: a downgrade that would destroy tenant data must refuse, and say what to do.

    The refusal is asserted together with the state afterwards: the tables are
    still there, the data is still there, and the recorded revision is unchanged.
    A refusal that had already dropped the index or the policies would be worse
    than no refusal, because it would leave the database in a state nobody chose.
    """
    engine = _engine(head_database)
    try:
        with engine.begin() as c:
            c.execute(
                sa.text(
                    "INSERT INTO projects (tenant_id, id, name, created_at) "
                    "VALUES (gen_random_uuid(), gen_random_uuid(), 'keep-me', now())"
                )
            )
    finally:
        engine.dispose()

    with pytest.raises(DestructiveDowngradeRefused) as caught:
        migrate.downgrade(head_database, "base")
    message = str(caught.value)
    assert "repair-security" in message, message
    assert "projects" in message and "result_contracts" in message, message

    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            tables = set(sa.inspect(c).get_table_names(schema="public"))
            names = c.execute(sa.text("SELECT name FROM projects")).scalars().all()
            revision = migrate.current_revision(c)
            indexes = {
                ix["name"] for ix in realised_catalogue(c, SECURED_TABLES)[
                    "result_contracts"
                ]["indexes"]
            }
    finally:
        engine.dispose()
    assert {"projects", "result_contracts"} <= tables, tables
    assert list(names) == ["keep-me"], names
    assert revision == migrate.head_revision(), revision
    assert FK_INDEX in indexes, "the refused downgrade had already dropped the index"


def test_the_index_downgrade_is_permitted_and_reversible(head_database: sa.URL) -> None:
    """The other half of the per-revision judgement.

    `0002` drops only an index: nothing is destroyed and `upgrade` restores it. A
    blanket "all downgrades are destructive" rule would refuse this for no
    benefit, which is why the decision is made per revision and not globally.
    """

    def _indexes(url: sa.URL) -> set[str]:
        engine = _engine(url)
        try:
            with engine.connect() as c:
                catalogue = realised_catalogue(c, SECURED_TABLES)
            return {ix["name"] for ix in catalogue["result_contracts"]["indexes"]}
        finally:
            engine.dispose()

    assert FK_INDEX in _indexes(head_database)

    migrate.downgrade(head_database, "0001_tenancy_baseline")
    assert FK_INDEX not in _indexes(head_database), "the index survived its own downgrade"

    engine = _engine(head_database)
    try:
        with engine.connect() as c:
            assert migrate.current_revision(c) == "0001_tenancy_baseline"
    finally:
        engine.dispose()

    migrate.upgrade(head_database, "head")
    assert FK_INDEX in _indexes(head_database), "re-upgrading did not restore the index"

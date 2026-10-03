"""Fixtures for the migration tests (RX-47, RX-48, RX-49).

These run against the DISPOSABLE PostgreSQL in `infra/docker-compose.yml` and are
SKIPPED - never silently passed - when it is unreachable. SQLite cannot exhibit
row-level security, FORCE RLS, role attributes or transaction-local settings, so
it must not stand in for PostgreSQL here.

CONNECTION DETAILS come from the repo `.env`, read with the same reader shape as
`tests/postgres/conftest.py`. The reader is duplicated; the SECRETS are not. Both
files parse the one `.env`, so there is a single place a password lives and
neither test tree can drift onto a stale copy of it.

ISOLATION FROM `tests/postgres`. Every test here creates and drops its OWN
database, named `retrace_mig_<random>`. That matters for more than tidiness:
`tests/postgres` asserts against the `projects` and `result_contracts` tables in
the shared `retrace` database, and a migration test that upgraded, damaged or
repaired those tables would make the two suites order-dependent - the failure
would appear in whichever ran second and point at the wrong code.

The one piece of shared state these tests touch is the CLUSTER-WIDE role list,
because roles are not per-database. It is handled as follows:

  * `retrace_svc`, the runtime identity `tests/postgres` connects as, is only ever
    READ here. Its password is never re-set, because `create_service_role` would
    re-key it and break the other suite's credential.
  * every role these tests CREATE is named `retrace_tmp_<random>` and dropped in
    teardown, databases first so that per-database grants are gone before the
    role is dropped.

Applying `infra/sql/001_tenancy.sql` as the prior-schema fixture does execute its
`CREATE ROLE retrace_svc` guard, but that statement is `IF NOT EXISTS`-guarded and
the accompanying `ALTER ROLE` sets only the attributes `retrace_svc` already has
and no password. Verified by reading the file rather than assumed.

=============================================================================
COMMANDS RUN WHILE BUILDING THIS, AND THE IDENTITY EACH USED
=============================================================================

Test suite, and the regression run (identity: the local workstation user;
database identities as noted inside each test):

    ./scripts/test.sh tests/migrations
    ./scripts/test.sh                            (full suite, for regression)
    ./scripts/test.sh tests/postgres             (unchanged by this work)
    ./scripts/test.sh tests/governance           (attribution control)

Static checks (identity: the local workstation user, no database):

    env -u PYTHONPATH ./.venv/bin/python -m ruff check services/api tests/migrations
    env -u PYTHONPATH ./.venv/bin/python -m mypy services/api tests/migrations

The documented operator commands, run by hand against a throwaway database to
confirm they work rather than asserting that they do. `PYTHONPATH` is set
explicitly because the venv's editable install predates this package (see
services/api/MIGRATIONS.md). Database identity for each is the one named in the
environment variables shown:

    SP=services/api
    # no database identity
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.db.migrate heads
    # refused with NEEDS_CONFIGURATION, no identity configured
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.db.migrate current
    # RETRACE_BOOTSTRAP_USER=retrace_app  (privileged bootstrap identity)
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.bootstrap create-role
    # RETRACE_MIGRATION_USER=retrace_app  (schema owner)
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.db.migrate upgrade
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.bootstrap grant
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.db.migrate current
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.db.migrate repair-security
    # refused with DestructiveDowngradeRefused, as designed
    env -u PYTHONPATH PYTHONPATH=$SP python -m retrace_api.db.migrate downgrade base
    # the ordinary alembic CLI, offline, no connection made
    cd services/api && env -u PYTHONPATH PYTHONPATH=$SP python -m alembic upgrade head --sql

A wheel was also built and inspected to confirm the package and its revision
scripts are distributed (identity: the local workstation user, no database):

    env -u PYTHONPATH ./.venv/bin/python -m build --wheel --outdir <scratch> .

Database identities used BY the tests, all against 127.0.0.1:5440:

    retrace_app  - POSTGRES_USER of the disposable container, and a SUPERUSER
                   because the postgres image makes it one. Used to CREATE and
                   DROP the per-test databases, to apply the prior-schema
                   fixture, to run the migrations (it owns the tables it
                   creates), and - deliberately - to assert the composite
                   foreign key refuses a cross-tenant insert even when
                   row-level security cannot be what refused it.
    retrace_svc  - the runtime identity. Connected to only to confirm it is
                   subject to the policies; never mutated.
    retrace_tmp_<random>
                 - throwaway roles created by the bootstrap and negative-control
                   tests, dropped in teardown.

NOT EXERCISED HERE, and not claimed: the migration identity is `retrace_app`,
which this container makes a superuser. The tests therefore demonstrate that the
RUNTIME role is unprivileged (which is the RX-47 property) but do NOT demonstrate
a production arrangement in which the migration identity is itself a
non-superuser owner. That needs a cluster this repository does not provision.
"""

from __future__ import annotations

import os
import pathlib
import secrets
import uuid
from collections.abc import Callable, Iterator

import pytest
import sqlalchemy as sa

psycopg = pytest.importorskip("psycopg", reason="psycopg not installed")

REPO = pathlib.Path(__file__).resolve().parents[2]
MANUAL_SQL = REPO / "infra" / "sql" / "001_tenancy.sql"

#: Prefix for every database these tests create, so a leaked one is identifiable.
DB_PREFIX = "retrace_mig"
#: Prefix for every throwaway role, distinct from `retrace_svc`.
ROLE_PREFIX = "retrace_tmp"


def _env() -> dict[str, str]:
    """Read the repo `.env`, then let real environment variables win.

    Same shape as `tests/postgres/conftest.py::_env`. Kept rather than imported
    because importing across two conftest packages couples the suites' collection
    order; the duplicated code is a six-line parser, and the secrets stay in the
    single `.env`.
    """
    env: dict[str, str] = {}
    envfile = REPO / ".env"
    if envfile.is_file():
        for raw in envfile.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    env.update(
        {k: v for k, v in os.environ.items() if k.startswith(("RETRACE_", "POSTGRES_"))}
    )
    return env


def _url(user: str, password_key: str, database: str) -> sa.URL:
    e = _env()
    secret = e.get(password_key)
    if not secret:
        pytest.skip(f"{password_key} not set")
    return sa.URL.create(
        "postgresql+psycopg",
        username=user,
        password=secret,
        host="127.0.0.1",
        port=int(e.get("RETRACE_PG_PORT", "5440")),
        database=database,
    )


@pytest.fixture(scope="session")
def admin_url() -> sa.URL:
    """The container's POSTGRES_USER, pointed at the maintenance database.

    A SUPERUSER, because the postgres image makes POSTGRES_USER one. Used for
    CREATE/DROP DATABASE, for the prior-schema fixture, for running migrations,
    and as the identity that proves a refusal came from a CONSTRAINT rather than
    from row-level security - a superuser bypasses RLS entirely, so a refusal
    observed as this role cannot be attributed to a policy.
    """
    return _url("retrace_app", "POSTGRES_PASSWORD", "retrace")


@pytest.fixture(scope="session")
def runtime_role_name() -> str:
    """The runtime identity's role name, as the application would connect."""
    return "retrace_svc"


@pytest.fixture(scope="session")
def runtime_password() -> str:
    """The runtime identity's existing credential. READ ONLY - never re-set."""
    e = _env()
    secret = e.get("RETRACE_SVC_PASSWORD")
    if not secret:
        pytest.skip("RETRACE_SVC_PASSWORD not set")
    return secret


@pytest.fixture(scope="session", autouse=True)
def _require_postgres(admin_url: sa.URL) -> None:
    engine = sa.create_engine(admin_url, poolclass=sa.pool.NullPool,
                              connect_args={"connect_timeout": 5})
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any connection failure is a skip
        pytest.skip(f"disposable PostgreSQL unreachable: {exc}")
    finally:
        engine.dispose()


class Scratch:
    """Creates per-test databases and roles, and drops them in the right order.

    Databases are dropped BEFORE roles. Per-database privilege grants are
    recorded as dependencies on the role, so `DROP ROLE` fails while a database
    still holds a grant to it - and the resulting teardown error would be
    reported against whichever test ran last rather than the one that leaked.
    """

    def __init__(self, admin_url: sa.URL) -> None:
        self._admin_url = admin_url
        self._databases: list[str] = []
        self._roles: list[str] = []

    def _admin_autocommit(self) -> sa.Engine:
        # CREATE/DROP DATABASE cannot run inside a transaction block.
        return sa.create_engine(
            self._admin_url, poolclass=sa.pool.NullPool, isolation_level="AUTOCOMMIT"
        )

    def database(self) -> sa.URL:
        """Create an empty database and return its URL for the admin identity."""
        name = f"{DB_PREFIX}_{uuid.uuid4().hex[:12]}"
        engine = self._admin_autocommit()
        try:
            with engine.connect() as connection:
                quoted = connection.dialect.identifier_preparer.quote(name)
                connection.exec_driver_sql(f"CREATE DATABASE {quoted}")
        finally:
            engine.dispose()
        self._databases.append(name)
        return self._admin_url.set(database=name)

    def role_name(self) -> str:
        """Reserve a throwaway role name and register it for teardown.

        Registered BEFORE creation on purpose: a creation that partially
        succeeded and then raised would otherwise leak a cluster-wide role.
        """
        return self.register_role(f"{ROLE_PREFIX}_{uuid.uuid4().hex[:12]}")

    def register_role(self, name: str) -> str:
        """Register an arbitrary role name for teardown.

        Used by the injection control, which needs a role whose NAME contains
        quoting metacharacters. Teardown quotes it with SQLAlchemy's identifier
        preparer, so a hostile name is dropped rather than executed.
        """
        self._roles.append(name)
        return name

    def secret(self) -> str:
        """A fresh random credential, so no password literal appears in a test."""
        return secrets.token_hex(16)

    def url_for(self, url: sa.URL, *, user: str, password: str) -> sa.URL:
        """The same database, as a different identity."""
        return url.set(username=user, password=password)

    def cleanup(self) -> None:
        engine = self._admin_autocommit()
        try:
            with engine.connect() as connection:
                preparer = connection.dialect.identifier_preparer
                for name in reversed(self._databases):
                    connection.exec_driver_sql(
                        f"DROP DATABASE IF EXISTS {preparer.quote(name)} WITH (FORCE)"
                    )
                for name in reversed(self._roles):
                    connection.exec_driver_sql(
                        f"DROP ROLE IF EXISTS {preparer.quote(name)}"
                    )
        finally:
            engine.dispose()


@pytest.fixture
def scratch(admin_url: sa.URL) -> Iterator[Scratch]:
    """Per-test disposable databases and roles."""
    s = Scratch(admin_url)
    try:
        yield s
    finally:
        s.cleanup()


@pytest.fixture
def fresh_database(scratch: Scratch) -> sa.URL:
    """An empty database, as the admin identity."""
    return scratch.database()


@pytest.fixture(scope="session")
def manual_schema_sql() -> str:
    """The hand-applied prior schema, read from the repository.

    Read, never reproduced: a copy in a test file would let the fixture drift away
    from the file whose adoption is being proved, and the test would then be
    proving equivalence to something nobody deploys.
    """
    if not MANUAL_SQL.is_file():
        pytest.skip(f"{MANUAL_SQL} not present")
    return MANUAL_SQL.read_text(encoding="utf-8")


@pytest.fixture
def apply_manual_schema(manual_schema_sql: str) -> Callable[[sa.URL], None]:
    """Apply `infra/sql/001_tenancy.sql` verbatim into a database."""

    def _apply(url: sa.URL) -> None:
        engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
        try:
            with engine.begin() as connection:
                # exec_driver_sql, not text(): the file contains `$$`-quoted DO
                # blocks and `:=` assignments, and SQLAlchemy's bind-parameter
                # parser would try to interpret the colons.
                #
                # HAZARD, checked rather than assumed: psycopg parses `%` as a
                # placeholder marker even when no parameters are passed, so a `%`
                # anywhere in this file would fail here with "only '%s', '%b',
                # '%t' are allowed as placeholders". The file currently contains
                # none (`grep -c '%'` returns 0). If one is ever added, double it
                # or send the statements individually - do not reach for `text()`,
                # which breaks on the `:=` assignments instead.
                connection.exec_driver_sql(manual_schema_sql)
        finally:
            engine.dispose()

    return _apply

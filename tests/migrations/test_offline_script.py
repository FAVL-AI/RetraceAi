"""Offline (`--sql`) generation, and the precondition it must state (RX-47, RX-48).

Offline mode produces a script for someone to review and apply by hand, which is
how a change to a production tenancy schema should be seen before it runs. It has
no connection: `op.get_bind()` returns a `MockConnection` that SQLAlchemy cannot
inspect, so the adoption branch of `0001_tenancy_baseline` CANNOT run. Running
`alembic upgrade head --sql` before that was handled failed with
`NoInspectionAvailable` partway through the script.

The resolution is not to pretend. The offline path emits the FRESH-INSTALL
statements and writes its precondition into the script itself, because an
artefact that has checked nothing about its target must say so where the person
applying it will read it - not only in the migration source they may never open.

This module needs no container. It is marked `integration` with the rest of the
directory so `tests/migrations` deselects as one unit.
"""

from __future__ import annotations

import io

import pytest
from alembic import command
from retrace_api.db import migrate
from retrace_api.db.security import POLICY_NAME, POLICY_PREDICATE

pytestmark = pytest.mark.integration

#: Not a real target. Offline mode never connects; the URL is present only so the
#: dialect is known, and pointing it at an unroutable address makes that explicit
#: - if this test ever starts connecting, it fails rather than quietly touching a
#: database.
OFFLINE_URL = "postgresql+psycopg://nobody:nothing@192.0.2.1:1/offline"


def _generate() -> str:
    buffer = io.StringIO()
    config = migrate.make_config(url=OFFLINE_URL)
    # `output_buffer`, not `stdout`. `EnvironmentContext.configure` reads
    # `config.output_buffer`; `config.stdout` is only where the CLI's own
    # messages go, so setting that one captures nothing and the script would be
    # compared against an empty string. The first version of this test did
    # exactly that and the assertions failed with `script == ''`.
    config.output_buffer = buffer
    command.upgrade(config, "head", sql=True)
    generated = buffer.getvalue()
    assert generated, "offline generation produced nothing; the buffer is not wired up"
    return generated


@pytest.fixture(scope="module")
def script() -> str:
    return _generate()


def test_the_offline_script_contains_the_whole_baseline(script: str) -> None:
    """Tables, composite keys with their names, and the index from 0002."""
    assert "CREATE TABLE projects" in script, script[:400]
    assert "CREATE TABLE result_contracts" in script, script[:400]
    assert "CONSTRAINT projects_pkey PRIMARY KEY (tenant_id, id)" in script
    assert "CONSTRAINT result_contracts_pkey PRIMARY KEY (tenant_id, id)" in script
    assert (
        "CONSTRAINT result_contracts_tenant_id_project_id_fkey "
        "FOREIGN KEY(tenant_id, project_id) REFERENCES projects (tenant_id, id)"
    ) in script, script
    assert "result_contracts_tenant_id_project_id_idx" in script


def test_the_offline_script_contains_the_security_configuration(script: str) -> None:
    """RX-47, RX-48: the part autogenerate would have silently omitted.

    If the offline path had been written with `apply_security_configuration`
    against the connection instead of `op.execute`, these statements would be
    absent from the script and an operator applying it by hand would create the
    tables with NO isolation at all - and nothing in the script would say so.
    """
    for table in ("projects", "result_contracts"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in script
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY" in script
        assert f"CREATE POLICY {POLICY_NAME} ON {table}" in script
    assert script.count(POLICY_PREDICATE) >= 4, (
        "expected the predicate in USING and WITH CHECK on both tables"
    )


def test_the_offline_script_states_its_precondition(script: str) -> None:
    """The script must declare that it checked nothing and assumes an empty database."""
    assert "PRECONDITION" in script, script[:600]
    assert "Do NOT apply this to a database already carrying" in script
    assert "Nothing here has been checked against the target" in script
    assert "python -m retrace_api.db.migrate upgrade" in script


def test_the_offline_script_is_genuinely_unconditional(script: str) -> None:
    """NEGATIVE CONTROL for the precondition: it must be a real constraint.

    If the CREATE TABLE statements were `IF NOT EXISTS`, the warning would be
    theatre - the script would be safe to apply anywhere and the comment would be
    noise that teaches the reader to ignore such comments. They are
    unconditional, so the precondition is load-bearing and the refusal to guess
    was the right call.
    """
    create_section = script.split("CREATE TABLE projects", 1)[1]
    assert "IF NOT EXISTS" not in create_section.split("CREATE POLICY", 1)[0], create_section
    # The DROP POLICY statements ARE guarded, deliberately: re-applying the
    # security configuration must be idempotent for the forward-repair path.
    assert "DROP POLICY IF EXISTS" in script


def test_the_offline_script_records_the_head_revision(script: str) -> None:
    """The script writes the revision it brings the database to.

    Without it, an offline apply would leave `alembic_version` empty and the next
    online upgrade would try to run 0001 again - on a database that now has the
    tables, which is the adoption path, which would then be reached for the wrong
    reason.
    """
    assert "CREATE TABLE alembic_version" in script
    assert migrate.head_revision() in script, migrate.head_revision()

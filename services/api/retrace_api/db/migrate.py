"""Programmatic migration driver and the forward-repair path (RX-47, RX-48, RX-49).

COMMANDS, AND WHICH IDENTITY RUNS EACH. Full detail in services/api/MIGRATIONS.md.

    python -m retrace_api.db.migrate current           migration identity, read only
    python -m retrace_api.db.migrate heads             no database needed
    python -m retrace_api.db.migrate upgrade           MIGRATION identity (schema owner)
    python -m retrace_api.db.migrate downgrade REV     MIGRATION identity; 0001 refuses
    python -m retrace_api.db.migrate repair-security   MIGRATION identity (owner-only DDL)

The runtime service role can run NONE of these. `ALTER TABLE ... FORCE ROW LEVEL
SECURITY` and `CREATE POLICY` are owner-only, and that is the point of RX-47: the
identity that handles requests cannot alter the policies that confine it.

WHY A PROGRAMMATIC DRIVER AND NOT JUST THE `alembic` CLI.

Two concrete reasons, not a preference. First, the CLI resolves its URL through
an ini option, and ConfigParser applies `%` interpolation to option values, so a
password containing `%` is silently corrupted and surfaces as an authentication
failure. `config.attributes` carries a `URL` object instead and is immune.
Second, the tests need the migration to run on a connection THEY own, so the
assertions that follow observe the same transaction. Both routes share one env.py
and one script directory, so neither can drift from the other.

WHY FORWARD REPAIR EXISTS AND WHAT IT IS NOT.

The realistic failure is not a bad migration; it is drift on a database already
at head - a policy dropped during an incident, FORCE switched off to debug
something and never restored, a restore from a dump taken before the policies
were applied. None of that is fixed by re-running `upgrade`, because the version
table already says head. `repair_security_configuration` re-applies the
idempotent security DDL and then READS THE CATALOGUE BACK to confirm the result,
raising `SchemaRepairFailed` if it is still not isolated. It touches no rows, so
it is not a destructive downgrade, and it is not an alternative to a migration:
it cannot create a table or change a key.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import URL, Connection, create_engine, inspect, make_url, text
from sqlalchemy.pool import NullPool

from retrace_api.db.catalogue import TableSecurity, read_table_security, realised_catalogue
from retrace_api.db.security import SECURED_TABLES, apply_security_configuration
from retrace_api.errors import (
    MigrationConfigurationError,
    SchemaRepairFailed,
    SchemaRevisionMismatch,
)

__all__ = [
    "MIGRATIONS_PATH",
    "RepairReport",
    "current_revision",
    "downgrade",
    "head_revision",
    "make_config",
    "repair_security_configuration",
    "upgrade",
]

#: Absolute path to the script directory, derived from this module's location so
#: the commands work from any working directory. A relative `script_location`
#: would resolve against the caller's cwd and silently find nothing.
MIGRATIONS_PATH = Path(__file__).resolve().parent / "migrations"

_VERSION_TABLE = "alembic_version"


@dataclass(frozen=True)
class RepairReport:
    """What a forward repair actually did, with the catalogue before and after.

    The before/after states are the evidence. A report that said only "repaired"
    would not distinguish a database that needed repair from one that did not,
    and could not show that the repair changed anything.
    """

    revision: str | None
    statements: tuple[str, ...]
    before: dict[str, TableSecurity]
    after: dict[str, TableSecurity]

    @property
    def changed(self) -> bool:
        return self.before != self.after


def make_config(
    *, connection: Connection | None = None, url: URL | str | None = None
) -> Config:
    """Build an Alembic config with no ini file required.

    Exactly one of `connection` or `url` is normally supplied; with neither,
    env.py falls back to the environment and raises
    `MigrationConfigurationError` if that is not configured either.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_PATH))
    if connection is not None:
        config.attributes["connection"] = connection
    if url is not None:
        config.attributes["url"] = make_url(url) if isinstance(url, str) else url
    return config


def head_revision() -> str:
    """The single head revision id, read from the script directory.

    Raises if the chain has branched into multiple heads. A schema with two heads
    has no single definition of "current", and `upgrade head` would be ambiguous.
    """
    script = ScriptDirectory.from_config(make_config())
    heads = script.get_heads()
    if len(heads) != 1:
        raise MigrationConfigurationError(
            f"the migration chain has {len(heads)} heads {heads}; a tenancy schema must "
            "have exactly one so that 'head' names a single state"
        )
    return heads[0]


def current_revision(connection: Connection) -> str | None:
    """The revision the DATABASE records, or None if it has never been migrated.

    Read from `alembic_version` rather than inferred from the presence of tables:
    a database carrying the hand-applied `infra/sql/001_tenancy.sql` has both
    tables and no revision at all, which is precisely the case the baseline
    revision's adoption path exists for.
    """
    if _VERSION_TABLE not in set(inspect(connection).get_table_names(schema="public")):
        return None
    return connection.execute(
        text(f"SELECT version_num FROM {_VERSION_TABLE}")  # noqa: S608
    ).scalar()


def _run(
    target: Connection | URL | str, action: str, revision: str
) -> None:
    runner = getattr(command, action)
    if isinstance(target, Connection):
        runner(make_config(connection=target), revision)
        return
    url = make_url(target) if isinstance(target, str) else target
    engine = create_engine(url, poolclass=NullPool)
    try:
        with engine.begin() as connection:
            runner(make_config(connection=connection), revision)
    finally:
        engine.dispose()


def upgrade(target: Connection | URL | str, revision: str = "head") -> None:
    """Upgrade `target` to `revision`, running as the MIGRATION identity."""
    _run(target, "upgrade", revision)


def downgrade(target: Connection | URL | str, revision: str) -> None:
    """Downgrade `target` to `revision`.

    `0001_tenancy_baseline` refuses with `DestructiveDowngradeRefused` and names
    the forward-repair route; `0002` drops only an index and permits it. The
    judgement is per revision, not a blanket rule.
    """
    _run(target, "downgrade", revision)


def repair_security_configuration(
    connection: Connection, *, expect_revision: str | None = None
) -> RepairReport:
    """Re-apply the RLS configuration on a database AT HEAD and verify the result.

    Serves RX-47 and RX-48. Forward, idempotent, and touches no rows - the
    supported recovery route for configuration drift, and the reason a
    destructive downgrade is not the only option offered.

    Requires the database to be at head (override with `expect_revision` only to
    pin a specific revision deliberately). See `SchemaRevisionMismatch` for why
    repairing a database at an unknown revision would produce a misleading
    success.
    """
    wanted = expect_revision if expect_revision is not None else head_revision()
    recorded = current_revision(connection)
    if recorded != wanted:
        raise SchemaRevisionMismatch(
            f"database records revision {recorded!r}, expected {wanted!r}. Forward repair "
            "re-applies the security configuration for the tables THIS head knows about; on "
            "a database at another revision it would silently leave other tenant-bearing "
            "tables unprotected while reporting success. Run `upgrade` first."
        )

    before = read_table_security(connection, SECURED_TABLES)
    statements = apply_security_configuration(connection, SECURED_TABLES)
    after = read_table_security(connection, SECURED_TABLES)

    # Read back, do not assume. The statements above can return without error
    # inside a transaction that is later rolled back; reporting success on that
    # basis would send the operator away from a database that is still exposed.
    unprotected = sorted(name for name, facts in after.items() if not facts.is_isolated)
    if unprotected:
        raise SchemaRepairFailed(
            f"after repair these tables are still not isolated: {unprotected}. "
            "ENABLE, FORCE and at least one policy are all required; the realised "
            f"catalogue reports {[after[name] for name in unprotected]}"
        )
    return RepairReport(
        revision=recorded, statements=statements, before=before, after=after
    )


def _resolved_url() -> URL:
    from retrace_api.db.engine import migration_url_from_env

    return migration_url_from_env()


def _cmd_current(_: argparse.Namespace) -> int:
    engine = create_engine(_resolved_url(), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            print(current_revision(connection) or "(no revision recorded)")
    finally:
        engine.dispose()
    return 0


def _cmd_heads(_: argparse.Namespace) -> int:
    print(head_revision())
    return 0


def _cmd_upgrade(args: argparse.Namespace) -> int:
    upgrade(_resolved_url(), args.revision)
    print(f"upgraded to {args.revision}")
    return 0


def _cmd_downgrade(args: argparse.Namespace) -> int:
    downgrade(_resolved_url(), args.revision)
    print(f"downgraded to {args.revision}")
    return 0


def _cmd_repair(_: argparse.Namespace) -> int:
    engine = create_engine(_resolved_url(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            report = repair_security_configuration(connection)
            catalogue: dict[str, Any] = realised_catalogue(connection, SECURED_TABLES)
    finally:
        engine.dispose()
    for statement in report.statements:
        print(f"applied: {statement}")
    print(f"revision: {report.revision}  changed: {report.changed}")
    for table, facts in sorted(catalogue.items()):
        print(
            f"{table}: row_security={facts['row_security']} "
            f"force={facts['force_row_security']} "
            f"policies={[p['name'] for p in facts['policies']]}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns a process exit code; never raises for a refusal."""
    parser = argparse.ArgumentParser(
        prog="python -m retrace_api.db.migrate",
        description=(
            "Tenancy schema migrations. Runs as the SCHEMA-OWNING migration identity "
            "(RETRACE_MIGRATION_USER), never as the runtime service role."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("current", help="print the revision the database records").set_defaults(
        handler=_cmd_current
    )
    sub.add_parser("heads", help="print the head revision in this checkout").set_defaults(
        handler=_cmd_heads
    )
    up = sub.add_parser("upgrade", help="upgrade the database")
    up.add_argument("revision", nargs="?", default="head")
    up.set_defaults(handler=_cmd_upgrade)
    down = sub.add_parser("downgrade", help="downgrade (0001 refuses; see its docstring)")
    down.add_argument("revision")
    down.set_defaults(handler=_cmd_downgrade)
    sub.add_parser(
        "repair-security",
        help="re-apply row-level security on a database at head (forward, non-destructive)",
    ).set_defaults(handler=_cmd_repair)

    args = parser.parse_args(argv)
    handler: Any = args.handler
    return int(handler(args))


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())

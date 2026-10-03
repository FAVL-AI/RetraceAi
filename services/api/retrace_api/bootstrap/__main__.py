"""Operator-run bootstrap CLI (RX-47).

    python -m retrace_api.bootstrap create-role   BOOTSTRAP identity (needs CREATEROLE)
    python -m retrace_api.bootstrap grant         MIGRATION identity (owns the tables)

ORDER MATTERS AND THE STEPS ARE NOT INTERCHANGEABLE:

    1. create-role   - cluster-wide, once per cluster (and again to rotate a
                       credential). Runs as the privileged bootstrap identity.
    2. upgrade       - `python -m retrace_api.db.migrate upgrade`, as the
                       schema-owning migration identity. Creates the tables.
    3. grant         - per database, AFTER the tables exist, as their owner.
                       Granting before step 2 would fail on absent tables.

WHY THE PASSWORD IS READ FROM THE ENVIRONMENT AND NOT TAKEN AS AN ARGUMENT.

`ps` shows the full command line of every process to any local user, and shell
history files keep it afterwards. A credential passed as `--password` is
therefore disclosed to the machine, not merely to the database. It is read from
`RETRACE_RUNTIME_PASSWORD` instead - which is also the variable the application
itself reads, so the two cannot be set to different values by accident.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from retrace_api.bootstrap.roles import (
    assert_runtime_role_is_unprivileged,
    create_service_role,
    grant_runtime_privileges,
)
from retrace_api.db.engine import (
    RUNTIME_CREDENTIAL_VAR,
    RUNTIME_USER_VAR,
    bootstrap_url_from_env,
    migration_url_from_env,
)
from retrace_api.db.security import SECURED_TABLES
from retrace_api.errors import MigrationConfigurationError


def _runtime_identity() -> tuple[str, str]:
    role = os.environ.get(RUNTIME_USER_VAR)
    secret = os.environ.get(RUNTIME_CREDENTIAL_VAR)
    missing = [v for v, got in ((RUNTIME_USER_VAR, role), (RUNTIME_CREDENTIAL_VAR, secret))
               if not got]
    if missing or role is None or secret is None:
        raise MigrationConfigurationError(
            "the runtime identity to bootstrap is not configured; set "
            f"{' and '.join(missing)}"
        )
    return role, secret


def _cmd_create_role(_: argparse.Namespace) -> int:
    role, secret = _runtime_identity()
    engine = create_engine(bootstrap_url_from_env(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            create_service_role(connection, role=role, password=secret)
        # Verified in a SEPARATE transaction, after the commit. Reading the role
        # back inside the creating transaction would observe uncommitted state,
        # so a rolled-back bootstrap would still have reported success.
        with engine.connect() as connection:
            assert_runtime_role_is_unprivileged(connection, role)
    finally:
        engine.dispose()
    print(f"runtime role {role!r} created or re-keyed, and verified unprivileged")
    return 0


def _cmd_grant(_: argparse.Namespace) -> int:
    role, _secret = _runtime_identity()
    # The MIGRATION identity, not the bootstrap one: GRANT requires ownership of
    # the tables, and the migration identity is what created them.
    engine = create_engine(migration_url_from_env(), poolclass=NullPool)
    try:
        with engine.begin() as connection:
            grant_runtime_privileges(connection, role=role, tables=SECURED_TABLES)
    finally:
        engine.dispose()
    print(f"granted DML on {list(SECURED_TABLES)} to {role!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m retrace_api.bootstrap",
        description="Privileged, operator-run database bootstrap. Never part of a deploy.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "create-role",
        help="create or re-key the unprivileged runtime role (bootstrap identity)",
    ).set_defaults(handler=_cmd_create_role)
    sub.add_parser(
        "grant",
        help="grant the runtime role DML on the secured tables (migration identity)",
    ).set_defaults(handler=_cmd_grant)
    args = parser.parse_args(argv)
    handler = args.handler
    return int(handler(args))


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    sys.exit(main())

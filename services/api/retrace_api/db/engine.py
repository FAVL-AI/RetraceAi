"""Database URL resolution for the three distinct identities (RX-47).

THREE IDENTITIES, THREE CREDENTIALS, AND WHY THEY MUST NOT BE ONE.

  bootstrap  - creates the runtime role and grants it DML. Needs CREATEROLE (or
               superuser) and ownership of the tables to grant on them. Used for
               two explicit, operator-run steps and nothing else.
  migration  - owns the schema, so it can CREATE TABLE, ALTER TABLE ... FORCE ROW
               LEVEL SECURITY and CREATE POLICY. Runs `alembic upgrade head`.
  runtime    - the application. SELECT/INSERT/UPDATE/DELETE only, NOSUPERUSER,
               NOBYPASSRLS, owns nothing. Cannot change the schema it is policed
               by and cannot alter the policies that confine it.

Collapsing migration into runtime is the common shortcut and it voids RX-47 in
two ways at once: the runtime identity becomes the table owner (exempt from its
own policies unless FORCE is set on every table, forever), and it gains the
ability to `DROP POLICY tenant_isolation`, so a request-handling bug could
disable isolation rather than merely violate it.

Each identity therefore reads its own variables, and there is NO fallback from
one to another and no default DSN. A missing credential raises
`MigrationConfigurationError` carrying NEEDS_CONFIGURATION - never a guessed
localhost URL, because `alembic upgrade head` against an unintended database is
not undone by re-running it.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from sqlalchemy import URL, make_url

from retrace_api.errors import MigrationConfigurationError

__all__ = [
    "BOOTSTRAP_CREDENTIAL_VAR",
    "BOOTSTRAP_USER_VAR",
    "DIRECT_URL_VAR",
    "DRIVER",
    "MIGRATION_CREDENTIAL_VAR",
    "MIGRATION_USER_VAR",
    "RUNTIME_CREDENTIAL_VAR",
    "RUNTIME_USER_VAR",
    "build_url",
    "bootstrap_url_from_env",
    "migration_url_from_env",
    "runtime_url_from_env",
]

#: psycopg 3 is the installed driver. Pinned in the URL rather than left to
#: SQLAlchemy's default, which is psycopg2 and is not installed here - the
#: failure would otherwise surface as an import error inside Alembic.
DRIVER: Final = "postgresql+psycopg"

DIRECT_URL_VAR: Final = "RETRACE_DATABASE_URL"
HOST_VAR: Final = "RETRACE_PG_HOST"
PORT_VAR: Final = "RETRACE_PG_PORT"
DB_VAR: Final = "RETRACE_PG_DATABASE"
MIGRATION_USER_VAR: Final = "RETRACE_MIGRATION_USER"
MIGRATION_CREDENTIAL_VAR: Final = "RETRACE_MIGRATION_PASSWORD"
BOOTSTRAP_USER_VAR: Final = "RETRACE_BOOTSTRAP_USER"
BOOTSTRAP_CREDENTIAL_VAR: Final = "RETRACE_BOOTSTRAP_PASSWORD"
RUNTIME_USER_VAR: Final = "RETRACE_RUNTIME_USER"
RUNTIME_CREDENTIAL_VAR: Final = "RETRACE_RUNTIME_PASSWORD"

_DEFAULT_HOST: Final = "127.0.0.1"
_DEFAULT_PORT: Final = 5432
_DEFAULT_DATABASE: Final = "retrace"


def build_url(
    *, host: str, port: int, database: str, username: str, password: str
) -> URL:
    """Compose a SQLAlchemy URL without string formatting.

    `URL.create` is used rather than an f-string on purpose. A password
    containing `@`, `/`, `#` or `%` silently corrupts a hand-built URL, and `%`
    is additionally consumed by Alembic's ConfigParser if the URL is written into
    an ini option. Neither failure is visible until a connection is refused for
    the wrong reason.
    """
    return URL.create(
        DRIVER, username=username, password=password, host=host, port=port, database=database
    )


def _resolve(
    env: Mapping[str, str], user_var: str, password_var: str, identity: str
) -> URL:
    direct = env.get(DIRECT_URL_VAR)
    if direct:
        # A fully specified URL wins and is NOT recombined with the per-identity
        # variables: merging the two would produce a URL nobody wrote. Parsed by
        # SQLAlchemy rather than split by hand so a percent- or at-sign-bearing
        # password is decoded the same way the driver will decode it.
        return make_url(direct)
    username = env.get(user_var)
    password = env.get(password_var)
    missing = [v for v, got in ((user_var, username), (password_var, password)) if not got]
    if missing or username is None or password is None:
        raise MigrationConfigurationError(
            f"the {identity} database identity is not configured; "
            f"set {' and '.join(missing)} (or {DIRECT_URL_VAR} for a complete URL)"
        )
    port_raw = env.get(PORT_VAR, str(_DEFAULT_PORT))
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise MigrationConfigurationError(
            f"{PORT_VAR}={port_raw!r} is not an integer port"
        ) from exc
    return build_url(
        host=env.get(HOST_VAR, _DEFAULT_HOST),
        port=port,
        database=env.get(DB_VAR, _DEFAULT_DATABASE),
        username=username,
        password=password,
    )


def migration_url_from_env(env: Mapping[str, str] | None = None) -> URL:
    """URL for the schema-owning migration identity (RX-47)."""
    return _resolve(
        os.environ if env is None else env,
        MIGRATION_USER_VAR,
        MIGRATION_CREDENTIAL_VAR,
        "migration",
    )


def bootstrap_url_from_env(env: Mapping[str, str] | None = None) -> URL:
    """URL for the privileged bootstrap identity (RX-47)."""
    return _resolve(
        os.environ if env is None else env,
        BOOTSTRAP_USER_VAR,
        BOOTSTRAP_CREDENTIAL_VAR,
        "bootstrap",
    )


def runtime_url_from_env(env: Mapping[str, str] | None = None) -> URL:
    """URL for the unprivileged runtime identity (RX-47)."""
    return _resolve(
        os.environ if env is None else env,
        RUNTIME_USER_VAR,
        RUNTIME_CREDENTIAL_VAR,
        "runtime",
    )

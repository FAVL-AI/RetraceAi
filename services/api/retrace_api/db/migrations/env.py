"""Alembic environment for the tenancy schema (RX-47, RX-48, RX-49).

HOW THE DATABASE URL IS RESOLVED, AND WHY THERE IS NO DEFAULT.

In precedence order:

  1. `config.attributes["connection"]` - an already-open SQLAlchemy Connection.
     This is how `tests/migrations` runs: the test owns the transaction, so the
     migration and the assertions that follow it see the same state and a test
     cannot accidentally observe a committed side effect of a previous one.
  2. `config.attributes["url"]` - a URL object passed programmatically. Used
     rather than an ini option because a password containing `%` is consumed by
     ConfigParser interpolation, which fails as an authentication error and
     sends the reader looking in the wrong place.
  3. `RETRACE_MIGRATION_USER` / `RETRACE_MIGRATION_PASSWORD` (plus the optional
     host/port/database variables), or a complete `RETRACE_DATABASE_URL`.
  4. `sqlalchemy.url` from `alembic.ini`, if one was supplied.

If none resolves, `MigrationConfigurationError` is raised. There is deliberately
no fallback to a localhost default: an unintended `alembic upgrade head` is not
undone by running it again, and the identity that runs migrations is privileged.

WHY `include_schemas` IS NOT SET AND AUTOGENERATE IS LEFT NARROW.

Autogenerate cannot express row-level security, FORCE ROW LEVEL SECURITY,
policies or grants, and it reports NO DIFFERENCE for a database missing all of
them. Treating a clean autogenerate diff as "the schema matches" would therefore
be a false negative on exactly the properties RX-47 and RX-48 are about. The
authoritative comparison is the realised-catalogue check in `tests/migrations`,
which reads `pg_class` and `pg_policies` instead.
"""

from __future__ import annotations

from typing import Any

from alembic import context
from sqlalchemy import Connection, engine_from_config, pool

from retrace_api.db.base import metadata
from retrace_api.db.engine import migration_url_from_env
from retrace_api.errors import MigrationConfigurationError

config = context.config

#: Target metadata for autogenerate. Narrow on purpose: see the module docstring.
target_metadata = metadata


def _configured_url() -> str | None:
    url: Any = config.attributes.get("url")
    if url is not None:
        return url.render_as_string(hide_password=False) if hasattr(url, "render_as_string") \
            else str(url)
    try:
        return migration_url_from_env().render_as_string(hide_password=False)
    except MigrationConfigurationError:
        return config.get_main_option("sqlalchemy.url", None)


def _run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Compare types and server defaults so a drifted column is reported
        # rather than ignored. This does not rescue the RLS blind spot above; it
        # only narrows the structural one.
        compare_type=True,
        compare_server_default=True,
        # The version table belongs to the schema being migrated, not to a
        # separate bookkeeping schema, so a database dump carries its own
        # revision identity with it. A restore that loses `alembic_version` is a
        # database whose schema state is unknown.
        version_table="alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit SQL without connecting (`alembic upgrade head --sql`).

    Useful for review by a DBA who will apply the change by hand, which is how a
    change to a production tenancy schema should be seen before it runs.
    """
    url = _configured_url()
    if url is None:
        raise MigrationConfigurationError(
            "offline migration needs a URL; pass config.attributes['url'] or set "
            "RETRACE_MIGRATION_USER/RETRACE_MIGRATION_PASSWORD"
        )
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table="alembic_version",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run against a live connection."""
    existing: Connection | None = config.attributes.get("connection")
    if existing is not None:
        _run(existing)
        return

    url = _configured_url()
    if url is None:
        raise MigrationConfigurationError(
            "no database URL resolved; pass config.attributes['connection'] or "
            "config.attributes['url'], or set RETRACE_MIGRATION_USER and "
            "RETRACE_MIGRATION_PASSWORD"
        )
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        _run(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

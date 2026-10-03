"""Runtime role creation, grants, and the privilege assertion (RX-47).

=============================================================================
WHY THE ROLE NAME AND PASSWORD ARE NEVER FORMATTED INTO SQL
=============================================================================

`CREATE ROLE` and `GRANT` take identifiers and a password literal, and neither
can be a bind parameter - which is why this is normally written as an f-string
and why that is the standard place SQL injection enters a bootstrap script.

The statements below avoid it entirely. Both values are sent as ORDINARY BIND
PARAMETERS to `set_config(..., is_local => true)`, and a `DO` block reads them
back with `current_setting` and quotes them with `format`'s `%I` (identifier) and
`%L` (literal) specifiers, which are the server's own quoting functions. The SQL
text is a module-level constant: nothing is interpolated into it, so there is no
injection surface even for a hostile role name.

`is_local => true` also means the values are discarded when the transaction ends
rather than persisting on a pooled connection.

HONEST LIMITATION. The password still reaches the server, because
`CREATE ROLE ... PASSWORD` is the only way to set one. It travels as a bind
parameter rather than inside a statement string, so it is not in the statement
text that `log_statement = 'ddl'` would record, but a server configured with
`log_statement = 'all'` plus parameter logging would capture it, and
`pg_stat_activity` can show a statement mid-execution. There is no way around
that from the client side. It is one reason this step is operator-run and
out-of-band rather than part of a deploy pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Connection, text

from retrace_api.db.catalogue import read_role_facts, tables_owned_by
from retrace_api.db.security import SECURED_TABLES
from retrace_api.errors import RolePrivilegeError

__all__ = [
    "BOOTSTRAP_SETTINGS",
    "BOOTSTRAP_SQL",
    "RUNTIME_PRIVILEGES",
    "WITHHELD_PRIVILEGES",
    "assert_runtime_role_is_unprivileged",
    "create_service_role",
    "grant_runtime_privileges",
]

#: What the runtime identity is granted on each tenant-bearing table.
RUNTIME_PRIVILEGES: tuple[str, ...] = ("SELECT", "INSERT", "UPDATE", "DELETE")

#: What it is deliberately NOT granted, and why each matters:
#:
#:   TRUNCATE   - not policed by row-level security. `DELETE` is filtered by the
#:                policy; `TRUNCATE` empties the table for every tenant at once.
#:                This is the single most important withholding here.
#:   REFERENCES - lets the grantee create a foreign key pointing at the table,
#:                and referential-integrity checks bypass RLS, so a crafted
#:                reference becomes a read oracle for rows it cannot select.
#:   TRIGGER    - a trigger runs as the table owner in enough cases to matter.
#:   CREATE     - on the schema; revoked explicitly below, because PUBLIC held it
#:                by default before PostgreSQL 15 and an inherited grant would
#:                let the runtime identity create tables it then owns (and an
#:                owner is exempt from RLS unless FORCE is set).
WITHHELD_PRIVILEGES: tuple[str, ...] = ("TRUNCATE", "REFERENCES", "TRIGGER", "CREATE")

#: Transaction-local settings used to pass values WITHOUT formatting them into
#: SQL. Named without a credential-shaped identifier so the constant is not
#: mistaken for a stored secret - each holds the NAME of a setting, not a value.
_GUC_ROLE = "retrace.bootstrap_role"
_GUC_AUTH = "retrace.bootstrap_auth"
_GUC_TABLES = "retrace.bootstrap_tables"

#: The SQL below is a PLAIN string with the setting names spelled out, not an
#: f-string interpolating the constants above. Keeping it free of every
#: formatting construct means there is no mechanism by which anything could be
#: interpolated into it later - including by an edit that looked harmless - and
#: it needs no lint suppression, so no suppression is sitting here waiting to
#: cover a real finding. The cost is that the names appear twice;
#: `tests/migrations/test_bootstrap_roles.py` asserts the two spellings agree, so
#: a renamed constant fails a test rather than silently reading an unset setting.
#:
#: Role attributes, and why each: NOSUPERUSER and NOBYPASSRLS decide whether RLS
#: applies at all; NOINHERIT means membership in another role must be taken
#: deliberately with SET ROLE instead of applying silently; NOREPLICATION keeps
#: the physical replication stream, which carries every tenant's data, out of
#: reach.
_CREATE_ROLE = """
DO $bootstrap$
DECLARE
    v_role text := current_setting('retrace.bootstrap_role');
    v_auth text := current_setting('retrace.bootstrap_auth');
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
        EXECUTE format(
            'CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE '
            'NOINHERIT NOREPLICATION PASSWORD %L', v_role, v_auth);
    ELSE
        EXECUTE format(
            'ALTER ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE '
            'NOINHERIT NOREPLICATION PASSWORD %L', v_role, v_auth);
    END IF;
END
$bootstrap$;
"""

_GRANT = """
DO $bootstrap$
DECLARE
    v_role text := current_setting('retrace.bootstrap_role');
    v_tables text[] := string_to_array(current_setting('retrace.bootstrap_tables'), ',');
    v_table text;
BEGIN
    EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', v_role);
    -- Revoked, not merely "not granted": before PostgreSQL 15 PUBLIC held CREATE
    -- on the public schema, so a role could inherit it and create tables it owns.
    EXECUTE format('REVOKE CREATE ON SCHEMA public FROM %I', v_role);
    FOREACH v_table IN ARRAY v_tables LOOP
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO %I', v_table, v_role);
    END LOOP;
END
$bootstrap$;
"""


#: The settings the SQL above reads, exposed so a test can assert the plain SQL
#: and these constants have not drifted apart.
BOOTSTRAP_SETTINGS: tuple[str, ...] = (_GUC_ROLE, _GUC_AUTH, _GUC_TABLES)

#: The two statement blocks, exposed for the same drift check.
BOOTSTRAP_SQL: tuple[str, ...] = (_CREATE_ROLE, _GRANT)


def create_service_role(connection: Connection, *, role: str, password: str) -> None:
    """Create or re-key the unprivileged runtime role (RX-47).

    Runs as the PRIVILEGED BOOTSTRAP identity: needs CREATEROLE or superuser.
    Idempotent - an existing role is re-set to the same attributes and the
    supplied password, which is what makes this safe to re-run during a planned
    credential rotation and also why `role` must name the intended role: running
    it with the wrong name re-keys the wrong identity.

    No password default and no generated fallback. A bootstrap that invents a
    credential is a bootstrap whose credential nobody recorded.
    """
    if not role or not password:
        raise RolePrivilegeError(
            "create_service_role requires both a role name and a password; refusing to "
            "invent either, because a credential nobody chose is a credential nobody rotated"
        )
    connection.execute(
        text("SELECT set_config(:name, :value, true)"), {"name": _GUC_ROLE, "value": role}
    )
    connection.execute(
        text("SELECT set_config(:name, :value, true)"), {"name": _GUC_AUTH, "value": password}
    )
    connection.execute(text(_CREATE_ROLE))


def grant_runtime_privileges(
    connection: Connection, *, role: str, tables: Sequence[str] = SECURED_TABLES
) -> None:
    """Grant the runtime role DML on `tables` and nothing else (RX-47).

    Runs as the identity that OWNS the tables - normally the migration identity,
    after `upgrade` has created them. Must therefore run AFTER migrations, which
    is why role bootstrap and grants are two steps and not one.

    `tables` is an EXPLICIT LIST, never `ALL TABLES IN SCHEMA`. A wildcard grant
    would hand privileges to every tenant-bearing table added later, including
    before anyone had configured its row-level security - the table would be
    readable across tenants for exactly as long as it took someone to notice. An
    explicit list fails closed instead: a new table is simply inaccessible until
    it is added here and to `SECURED_TABLES`.
    """
    if not tables:
        raise RolePrivilegeError("grant_runtime_privileges called with no tables")
    if any("," in t for t in tables):
        # The table list crosses into SQL as one comma-separated setting, split
        # server-side. A comma inside a name would split it into two.
        raise RolePrivilegeError(f"table names must not contain a comma: {list(tables)}")
    connection.execute(
        text("SELECT set_config(:name, :value, true)"), {"name": _GUC_ROLE, "value": role}
    )
    connection.execute(
        text("SELECT set_config(:name, :value, true)"),
        {"name": _GUC_TABLES, "value": ",".join(tables)},
    )
    connection.execute(text(_GRANT))


def assert_runtime_role_is_unprivileged(connection: Connection, role: str) -> None:
    """Refuse a runtime identity that would not be subject to RLS (RX-47).

    Raises `RolePrivilegeError` naming what is wrong. Checks, and why each:

      exists       - an ABSENT role must not read as unprivileged. Reporting
                     "no privileges found" for a role that does not exist is a
                     vacuous pass, and it is the likely state on a database where
                     bootstrap was skipped.
      superuser    - exempt from every policy, FORCE or not.
      BYPASSRLS    - exempt from every policy, FORCE or not.
      owns tables  - an owner is exempt unless FORCE ROW LEVEL SECURITY is set on
                     that table. Owning nothing removes the exemption structurally
                     rather than depending on FORCE being remembered for every
                     table added in future.
      CREATEDB /
      CREATEROLE   - not RLS bypasses, but least-privilege violations: CREATEROLE
                     can create roles carrying attributes the creator holds.

    Checked against the realised catalogue, never against the bootstrap script's
    intent: the script may have been run with different arguments, or not at all.
    """
    facts = read_role_facts(connection, role)
    if not facts.exists:
        raise RolePrivilegeError(
            f"role {role!r} does not exist, so NOTHING about its privileges was verified. "
            "An absent role must not be reported as unprivileged - run the bootstrap step."
        )
    offences: list[str] = []
    if facts.superuser:
        offences.append("is SUPERUSER (exempt from every policy, FORCE or not)")
    if facts.bypass_rls:
        offences.append("has BYPASSRLS (exempt from every policy, FORCE or not)")
    if facts.create_db:
        offences.append("has CREATEDB")
    if facts.create_role:
        offences.append("has CREATEROLE (can create roles with attributes it holds)")
    owned = tables_owned_by(connection, role)
    if owned:
        offences.append(
            f"owns tables {list(owned)} (an owner is exempt from RLS without FORCE)"
        )
    if offences:
        raise RolePrivilegeError(
            f"runtime role {role!r} is not safe to police with row-level security: "
            + "; ".join(offences)
        )

"""Realised-catalogue inspection (RX-47, RX-48, RX-49).

WHY READ THE CATALOGUE INSTEAD OF THE MIGRATION TEXT.

A migration script is a statement of intent. What a database actually enforces is
in `pg_class`, `pg_policies`, `pg_constraint` and `pg_index`, and the two can
disagree for ordinary reasons: a statement was run inside a transaction that
later rolled back, a DO block swallowed an error, someone dropped a policy by
hand during an incident, a restore was taken from before the migration. A check
that reads the migration file would pass in every one of those cases while the
database was unprotected.

So every assertion about isolation in `tests/migrations/` is made against the
functions here, which read the server's own catalogue. `read_table_security` is
itself shown to be able to FAIL in
`tests/migrations/test_fresh_upgrade.py::test_the_security_inspection_reports_an_unforced_table`,
against a table deliberately created with ENABLE and no FORCE. An inspection
never shown to report a defect is not evidence that there is no defect.

WHAT `realised_catalogue` DELIBERATELY EXCLUDES.

Privileges. Grants are a separate, privileged bootstrap step (see
`retrace_api.bootstrap.roles`), so a database built fresh by the migrations alone
holds no grants while a database carrying the hand-applied
`infra/sql/001_tenancy.sql` does. Including ACLs would make the two paths differ
for a reason that has nothing to do with schema equivalence. They are compared
separately by `read_table_grants`, so the exclusion narrows the claim rather than
hiding a difference.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, text

from retrace_api.db.security import SECURED_TABLES

__all__ = [
    "ColumnFacts",
    "ForeignKeyFacts",
    "IndexFacts",
    "PolicyFacts",
    "RoleFacts",
    "TableSecurity",
    "read_columns",
    "read_foreign_keys",
    "read_indexes",
    "read_primary_key",
    "read_role_facts",
    "read_table_grants",
    "read_table_security",
    "realised_catalogue",
    "tables_owned_by",
]


@dataclass(frozen=True)
class PolicyFacts:
    """One row of `pg_policies`, as the server deparsed it."""

    name: str
    command: str
    roles: tuple[str, ...]
    using: str | None
    with_check: str | None


@dataclass(frozen=True)
class TableSecurity:
    """The realised RLS state of one table."""

    table: str
    exists: bool
    row_security: bool
    force_row_security: bool
    policies: tuple[PolicyFacts, ...] = field(default_factory=tuple)

    @property
    def is_isolated(self) -> bool:
        """True only when RLS is enabled, FORCED, and at least one policy exists.

        All three are required. ENABLE without FORCE exempts the owner; FORCE
        without a policy denies everything (fail-closed, but the application is
        broken); a policy without ENABLE is inert and enforces nothing.
        """
        return self.exists and self.row_security and self.force_row_security and bool(self.policies)


@dataclass(frozen=True)
class ColumnFacts:
    """A column as realised, including its ordinal position."""

    position: int
    name: str
    type_name: str
    not_null: bool
    default: str | None


@dataclass(frozen=True)
class ForeignKeyFacts:
    """A foreign key with both sides' column lists, in constraint order."""

    name: str
    columns: tuple[str, ...]
    referenced_table: str
    referenced_columns: tuple[str, ...]

    @property
    def is_composite(self) -> bool:
        return len(self.columns) > 1


@dataclass(frozen=True)
class IndexFacts:
    name: str
    columns: tuple[str, ...]
    unique: bool


@dataclass(frozen=True)
class RoleFacts:
    """Cluster-wide attributes of a database role (RX-47)."""

    name: str
    exists: bool
    superuser: bool
    bypass_rls: bool
    create_db: bool
    create_role: bool
    can_login: bool


def read_table_security(
    connection: Connection, tables: Sequence[str] = SECURED_TABLES
) -> dict[str, TableSecurity]:
    """Read ENABLE/FORCE RLS and the policies for each table (RX-47, RX-48).

    A table that does not exist is reported as `exists=False` rather than
    omitted, so a caller cannot mistake "absent" for "secured".
    """
    rows = connection.execute(
        text(
            "SELECT relname, relrowsecurity, relforcerowsecurity "
            "FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace "
            "AND relkind = 'r' AND relname = ANY(:names)"
        ),
        {"names": list(tables)},
    ).all()
    realised = {r[0]: (bool(r[1]), bool(r[2])) for r in rows}

    policy_rows = connection.execute(
        text(
            "SELECT tablename, policyname, cmd, roles::text[], qual, with_check "
            "FROM pg_policies WHERE schemaname = 'public' AND tablename = ANY(:names) "
            "ORDER BY tablename, policyname"
        ),
        {"names": list(tables)},
    ).all()
    policies: dict[str, list[PolicyFacts]] = {}
    for table, name, cmd, roles, qual, with_check in policy_rows:
        policies.setdefault(table, []).append(
            PolicyFacts(
                name=name,
                command=cmd,
                roles=tuple(roles or ()),
                using=qual,
                with_check=with_check,
            )
        )

    out: dict[str, TableSecurity] = {}
    for table in tables:
        if table not in realised:
            out[table] = TableSecurity(table=table, exists=False, row_security=False,
                                       force_row_security=False)
            continue
        enabled, forced = realised[table]
        out[table] = TableSecurity(
            table=table,
            exists=True,
            row_security=enabled,
            force_row_security=forced,
            policies=tuple(policies.get(table, ())),
        )
    return out


def read_columns(connection: Connection, table: str) -> tuple[ColumnFacts, ...]:
    """Columns in attribute order, with realised type, nullability and default."""
    rows = connection.execute(
        text(
            "SELECT a.attnum, a.attname, format_type(a.atttypid, a.atttypmod), "
            "a.attnotnull, pg_get_expr(d.adbin, d.adrelid) "
            "FROM pg_attribute a "
            "JOIN pg_class c ON c.oid = a.attrelid "
            "LEFT JOIN pg_attrdef d ON d.adrelid = c.oid AND d.adnum = a.attnum "
            "WHERE c.relnamespace = 'public'::regnamespace AND c.relname = :t "
            "AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum"
        ),
        {"t": table},
    ).all()
    return tuple(
        ColumnFacts(position=r[0], name=r[1], type_name=r[2], not_null=bool(r[3]), default=r[4])
        for r in rows
    )


def read_primary_key(connection: Connection, table: str) -> tuple[str, ...]:
    """Primary-key columns IN KEY ORDER (RX-49).

    Key order matters and a set would discard it: `(tenant_id, id)` and
    `(id, tenant_id)` enforce the same uniqueness but index differently, and only
    the first lets a tenant-scoped lookup use the primary key.
    """
    row = connection.execute(
        text(
            "SELECT array_agg(a.attname ORDER BY k.ord) "
            "FROM pg_constraint ct "
            "JOIN LATERAL unnest(ct.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE "
            "JOIN pg_attribute a ON a.attrelid = ct.conrelid AND a.attnum = k.attnum "
            "WHERE ct.contype = 'p' AND ct.conrelid = to_regclass('public.' || :t)"
        ),
        {"t": table},
    ).scalar()
    return tuple(row or ())


def read_foreign_keys(connection: Connection, table: str) -> tuple[ForeignKeyFacts, ...]:
    """Foreign keys with both column lists in constraint order (RX-49)."""
    rows = connection.execute(
        text(
            "SELECT ct.conname, "
            "  (SELECT array_agg(a.attname ORDER BY k.ord) "
            "     FROM unnest(ct.conkey) WITH ORDINALITY AS k(attnum, ord) "
            "     JOIN pg_attribute a ON a.attrelid = ct.conrelid AND a.attnum = k.attnum), "
            "  ct.confrelid::regclass::text, "
            "  (SELECT array_agg(a.attname ORDER BY k.ord) "
            "     FROM unnest(ct.confkey) WITH ORDINALITY AS k(attnum, ord) "
            "     JOIN pg_attribute a ON a.attrelid = ct.confrelid AND a.attnum = k.attnum) "
            "FROM pg_constraint ct "
            "WHERE ct.contype = 'f' AND ct.conrelid = to_regclass('public.' || :t) "
            "ORDER BY ct.conname"
        ),
        {"t": table},
    ).all()
    return tuple(
        ForeignKeyFacts(
            name=r[0],
            columns=tuple(r[1] or ()),
            referenced_table=r[2],
            referenced_columns=tuple(r[3] or ()),
        )
        for r in rows
    )


def read_indexes(connection: Connection, table: str) -> tuple[IndexFacts, ...]:
    """Indexes with their column lists, primary-key indexes included."""
    rows = connection.execute(
        text(
            "SELECT i.relname, ix.indisunique, "
            "  (SELECT array_agg(a.attname ORDER BY k.ord) "
            "     FROM unnest(ix.indkey::int[]) WITH ORDINALITY AS k(attnum, ord) "
            "     JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = k.attnum) "
            "FROM pg_index ix "
            "JOIN pg_class i ON i.oid = ix.indexrelid "
            "WHERE ix.indrelid = to_regclass('public.' || :t) ORDER BY i.relname"
        ),
        {"t": table},
    ).all()
    return tuple(
        IndexFacts(name=r[0], unique=bool(r[1]), columns=tuple(r[2] or ())) for r in rows
    )


def read_table_grants(connection: Connection, table: str, grantee: str) -> tuple[str, ...]:
    """Privileges `grantee` holds on `table`, sorted (RX-47).

    Kept out of `realised_catalogue` on purpose - see the module docstring.
    """
    rows = connection.execute(
        text(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_schema = 'public' AND table_name = :t AND grantee = :g"
        ),
        {"t": table, "g": grantee},
    ).scalars().all()
    return tuple(sorted(set(rows)))


def read_role_facts(connection: Connection, role: str) -> RoleFacts:
    """Cluster-wide role attributes (RX-47).

    Role attributes are cluster-global, not per-database, so this answers the
    same from any database in the cluster.
    """
    row = connection.execute(
        text(
            "SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin "
            "FROM pg_roles WHERE rolname = :r"
        ),
        {"r": role},
    ).first()
    if row is None:
        return RoleFacts(
            name=role, exists=False, superuser=False, bypass_rls=False,
            create_db=False, create_role=False, can_login=False,
        )
    return RoleFacts(
        name=role,
        exists=True,
        superuser=bool(row[0]),
        bypass_rls=bool(row[1]),
        create_db=bool(row[2]),
        create_role=bool(row[3]),
        can_login=bool(row[4]),
    )


def tables_owned_by(connection: Connection, role: str) -> tuple[str, ...]:
    """Ordinary tables in the current database owned by `role` (RX-47).

    A table's owner is exempt from its policies unless FORCE ROW LEVEL SECURITY
    is set, so the runtime identity owning nothing removes a whole class of
    exemption rather than relying on FORCE being present on every table added
    later.
    """
    rows = connection.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE r.rolname = :r AND c.relkind = 'r' "
            "AND c.relnamespace = 'public'::regnamespace ORDER BY c.relname"
        ),
        {"r": role},
    ).scalars().all()
    return tuple(rows)


def realised_catalogue(
    connection: Connection, tables: Sequence[str] = SECURED_TABLES
) -> dict[str, Any]:
    """The comparable realised state: structure plus RLS configuration.

    Serves RX-47, RX-48 and RX-49. Returned as plain nested built-ins so two
    databases can be compared with `==` and a failure prints a readable diff.
    Privileges are excluded by design (module docstring).
    """
    security = read_table_security(connection, tables)
    return {
        table: {
            "exists": security[table].exists,
            "columns": [
                {
                    "position": c.position,
                    "name": c.name,
                    "type": c.type_name,
                    "not_null": c.not_null,
                    "default": c.default,
                }
                for c in read_columns(connection, table)
            ],
            "primary_key": list(read_primary_key(connection, table)),
            "foreign_keys": [
                {
                    "name": fk.name,
                    "columns": list(fk.columns),
                    "references": fk.referenced_table,
                    "referenced_columns": list(fk.referenced_columns),
                }
                for fk in read_foreign_keys(connection, table)
            ],
            "indexes": [
                {"name": ix.name, "columns": list(ix.columns), "unique": ix.unique}
                for ix in read_indexes(connection, table)
            ],
            "row_security": security[table].row_security,
            "force_row_security": security[table].force_row_security,
            "policies": [
                {
                    "name": p.name,
                    "command": p.command,
                    "roles": list(p.roles),
                    "using": p.using,
                    "with_check": p.with_check,
                }
                for p in security[table].policies
            ],
        }
        for table in tables
    }

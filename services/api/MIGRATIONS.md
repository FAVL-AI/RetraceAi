# Tenancy schema: migrations, bootstrap, and which identity runs what

Serves RX-47 (RLS plus a non-privileged service role), RX-48 (transaction-local
identity) and RX-49 (composite tenant keys).

This replaces hand-applying `infra/sql/001_tenancy.sql`. That file stays in the
tree because it is already applied in at least one environment and the migration
chain has to be able to adopt it; it is not the installation route for anything
new.

## 1. The three identities

A single database credential for all three is the ordinary shortcut and it voids
RX-47. The reason is mechanical, not stylistic: a superuser, a `BYPASSRLS` role,
and a table's owner without `FORCE ROW LEVEL SECURITY` are all exempt from the
policies. If the application connects as any of them, `tenant_isolation` is
decorative — and an isolation test run as that identity proves nothing, because
it would pass against a database with no policies at all.

| Identity | Env vars | Privileges it needs | What it runs |
|---|---|---|---|
| **bootstrap** | `RETRACE_BOOTSTRAP_USER`, `RETRACE_BOOTSTRAP_PASSWORD` | `CREATEROLE` (or superuser) | `python -m retrace_api.bootstrap create-role` |
| **migration** | `RETRACE_MIGRATION_USER`, `RETRACE_MIGRATION_PASSWORD` | owns the schema: `CREATE TABLE`, `ALTER TABLE … FORCE ROW LEVEL SECURITY`, `CREATE POLICY`, `GRANT` | `python -m retrace_api.db.migrate upgrade`, `… repair-security`, `python -m retrace_api.bootstrap grant` |
| **runtime** | `RETRACE_RUNTIME_USER`, `RETRACE_RUNTIME_PASSWORD` | `SELECT/INSERT/UPDATE/DELETE` on the secured tables and nothing else; `NOSUPERUSER`, `NOBYPASSRLS`, owns no tables | the application. **No migration command.** |

The runtime identity holds no migration credential. That is the load-bearing
separation: it cannot `DROP POLICY tenant_isolation`, so a request-handling
defect can at worst violate isolation, never disable it.

Host, port and database come from `RETRACE_PG_HOST` (default `127.0.0.1`),
`RETRACE_PG_PORT` (default `5432`) and `RETRACE_PG_DATABASE` (default
`retrace`). A complete `RETRACE_DATABASE_URL` overrides the per-identity
variables and is **not** merged with them.

There is **no default DSN**. An unconfigured identity raises
`MigrationConfigurationError` carrying `NEEDS_CONFIGURATION`, because
`alembic upgrade head` against an unintended database is not undone by running it
again.

## 2. The ordered procedure

```
# 1. once per cluster, and again only to rotate the runtime credential.
#    Operator-run, out of band. Not part of a deploy.
RETRACE_RUNTIME_PASSWORD=... python -m retrace_api.bootstrap create-role

# 2. every deploy, as the schema-owning migration identity.
python -m retrace_api.db.migrate upgrade

# 3. after step 2, because GRANT needs the tables to exist.
#    Per database. As the migration identity, which owns them.
python -m retrace_api.bootstrap grant

# verification, any time, read-only
python -m retrace_api.db.migrate current
```

Steps 1 and 3 are separate from the migration chain on purpose. Putting role
creation in a migration would mean the migration credential had `CREATEROLE`,
turning a compromised deploy step into privilege escalation; and roles are
cluster-wide while migrations are per-database, so a role-creating migration run
against a second database would silently re-alter the first database's runtime
identity, including its password.

`grant` uses an **explicit table list**, never `GRANT … ON ALL TABLES IN
SCHEMA`. A wildcard would hand privileges to every tenant-bearing table added
later — including before anyone had configured its row-level security. The
explicit list fails closed: a new table is inaccessible until it is added to
`SECURED_TABLES` and granted deliberately.

## 3. What the migrations do, and what Alembic cannot do for them

| Revision | Content |
|---|---|
| `0001_tenancy_baseline` | `projects` and `result_contracts`; composite primary keys `(tenant_id, id)`; the composite foreign key `(tenant_id, project_id) → projects(tenant_id, id)`; `ENABLE` + `FORCE ROW LEVEL SECURITY`; the `tenant_isolation` policies |
| `0002_contract_project_index` | the index covering the referencing side of the composite key |

**Autogenerate does not produce any of the security configuration.** Row-level
security, `FORCE ROW LEVEL SECURITY`, policies and grants are not expressible in
SQLAlchemy metadata, so `alembic revision --autogenerate` emits none of them —
and, the dangerous half, reports *no difference* for a database that is missing
all of them. A clean autogenerate diff is therefore not evidence that isolation
is in place. Every security statement is hand-written in
`retrace_api/db/security.py`, and the authoritative check reads the realised
`pg_class` / `pg_policies` catalogue instead.

The policy predicate is:

```sql
tenant_id = nullif(current_setting('retrace.tenant_id', true), '')::uuid
```

The `nullif` is load-bearing. A setting established with
`set_config(…, is_local => true)` reverts to the **empty string** at transaction
end, not to `NULL`. Without the `nullif`, the next statement on a pooled
connection evaluates `''::uuid` and raises `invalid_text_representation` instead
of matching no rows. That still denies the data, so it is not an isolation hole —
but it turns an ordinary "no tenant context set" request into a hard error that
looks like a bug, and the obvious "fix" for it is to loosen the policy.

## 4. Adoption, not stamping

A database may already carry the hand-applied `infra/sql/001_tenancy.sql` and no
`alembic_version`. `0001` handles that by **converging**: per table it either
creates it, or verifies the existing one already has the composite primary key
and the composite foreign key and adopts it. Anything else raises
`BaselineDivergence` and refuses.

`alembic stamp` is deliberately *not* the documented route. Stamping records a
revision without inspecting the database, so a divergent hand-applied schema
would leave the version table asserting a state the database does not satisfy,
and every later migration would build on that false premise.

Equivalence is proved rather than argued:
`tests/migrations/test_upgrade_from_manual_schema.py` applies the SQL file into a
fresh database with a row of fixture data, upgrades to head, asserts the fixture
data survives, and asserts the realised catalogue is **identical** to one built
fresh from the migrations. Privileges are excluded from that comparison (grants
are the separate bootstrap step above) and are asserted separately.

## 5. Recovery

The realistic failure is drift on a database already at head: a policy dropped
during an incident, `FORCE` switched off to debug something and never restored, a
restore from a dump predating the policies. Re-running `upgrade` fixes none of
it, because the version table already says head.

```
python -m retrace_api.db.migrate repair-security
```

re-applies the idempotent security DDL, then **reads the catalogue back** and
raises `SchemaRepairFailed` if the tables are still not isolated. It touches no
rows. It refuses to run on a database that is not at head
(`SchemaRevisionMismatch`), because repairing the tables *this* head knows about
while silently leaving others unprotected would be a misleading success.

`downgrade` is judged per revision rather than by a blanket rule:

- `0001_tenancy_baseline` **refuses** (`DestructiveDowngradeRefused`). Dropping
  `projects` and `result_contracts` destroys every tenant's rows, and an operator
  reaching for a downgrade mid-incident is the least likely moment for that to be
  what was meant. The refusal message names the repair command.
- `0002` permits it. Dropping an index destroys nothing and `upgrade` restores
  it.

To discard a disposable environment, drop the database.

## 6. Evidence

`tests/migrations/` runs against the disposable PostgreSQL in
`infra/docker-compose.yml`, marked `integration`. Each test creates and drops its
own database, so it cannot collide with `tests/postgres`. Connection details are
read from the repo `.env` following the same pattern as
`tests/postgres/conftest.py`; no credential is duplicated into a test file.

Covered: a fresh upgrade's realised catalogue; upgrade from the hand-applied
schema with fixture-data survival and catalogue equivalence; forward repair after
deliberate damage; runtime-role attributes and ownership; bootstrap create and
grant.

Negative controls, because a check never shown to fail is not evidence:

- a cross-tenant composite-FK insert is refused — asserted as a **superuser**, so
  row-level security cannot be what refused it and only the constraint can be;
- the same insert **succeeds** against a contained single-column-FK fixture,
  demonstrating that referential integrity bypasses RLS and that the composite
  key is therefore not redundant with it;
- the catalogue inspection reports a table deliberately created with `ENABLE` and
  no `FORCE`, so a passing inspection is not vacuous;
- the role-attribute check rejects a throwaway `BYPASSRLS` role;
- the adoption path refuses a table with a single-column primary key;
- `0001`'s downgrade raises rather than dropping the tables.

## 7. Limitations, stated rather than implied

- **No HTTP surface, and no authenticated tenant context.** This package
  implements the database half of RX-47/RX-48 only. That the value written into
  `retrace.tenant_id` is derived from an authenticated principal — rather than
  from anything a caller supplied — is **not implemented and not proven**. The
  corresponding gate in `tests/postgres/test_tenant_isolation.py` remains skipped
  as `NOT_RUN`, and nothing here changes that.
- **Not RX-61.** Versioned migrations make the schema state addressable, which a
  restore exercise needs, but measured RPO/RTO, observability over the documented
  journey and an incident runbook with a named owner are not implemented.
- **The bootstrap password reaches the server.** `CREATE ROLE … PASSWORD` is the
  only way to set one. It travels as a bind parameter rather than inside a
  statement string, so `log_statement = 'ddl'` does not capture it, but a server
  logging all statements with parameters would. That is unavoidable from the
  client side and is part of why the step is operator-run and out of band.
- **`alembic_version` lives in the migrated schema**, so a dump carries its own
  revision identity. A restore that loses that table is a database whose schema
  state is unknown; `repair-security` will refuse it rather than guess.
- **The commands above need `retrace_api` on the import path.** This package was
  added after the editable install in `.venv` was generated, and a setuptools
  editable install resolves top-level names from a static map written at install
  time — so `import retrace_api` fails until someone re-runs
  `pip install -e '.[dev]'`. The test suite is unaffected (pyproject's
  `[tool.pytest.ini_options] pythonpath` includes `services/api`), and the
  package *does* reach the built wheel — verified by building one and listing it.
  Until the editable install is refreshed, run the CLI with
  `PYTHONPATH=services/api`. Refreshing it is an install step, not a code change,
  and has deliberately not been performed here.
- **`script.py.mako` is not in the wheel** — verified by inspecting a built one.
  Only `.py` files under the discovery roots are packaged, so an installed
  distribution can `upgrade` and `downgrade` but cannot `alembic revision`
  (the template is missing). Fixing that needs a `package-data` entry in
  `pyproject.toml`, which is outside this change's scope. Authoring new revisions
  from a source checkout is unaffected.
- **`tests/packaging/test_distribution.py::EXPECTED_TOP_LEVEL` does not list
  `retrace_api`.** That file is the guard against a package existing in the tree
  and silently missing from the wheel, so `retrace_api` belongs in it. It is
  outside this change's scope and is left for whoever owns that file; the wheel
  was verified by hand in the meantime.

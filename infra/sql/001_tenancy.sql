-- RETRACE tenancy baseline (RX-47, RX-48, RX-49).
--
-- WHY A SEPARATE SERVICE ROLE. The postgres image creates POSTGRES_USER as a
-- SUPERUSER, and a superuser (or a BYPASSRLS role, or a table's owner) is NOT
-- subject to row-level security. Running the application as that role would
-- make every RLS policy below decorative, and an RLS test run as that role
-- would prove nothing at all. So: the bootstrap role owns the schema, and the
-- application connects as retrace_svc, which is NOSUPERUSER, NOBYPASSRLS and
-- owns nothing.
--
-- FORCE ROW LEVEL SECURITY is also set, so the owner is subject to the policies
-- too. Without it, ENABLE alone leaves the owner exempt.

CREATE TABLE IF NOT EXISTS projects (
    tenant_id   uuid        NOT NULL,
    id          uuid        NOT NULL,
    name        text        NOT NULL,
    created_at  timestamptz NOT NULL,
    -- RX-49: composite primary key. A child row must reference (tenant_id, id)
    -- as a pair, so a cross-tenant foreign reference cannot be constructed.
    PRIMARY KEY (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS result_contracts (
    tenant_id     uuid        NOT NULL,
    id            uuid        NOT NULL,
    project_id    uuid        NOT NULL,
    contract_hash char(64)    NOT NULL,
    approved      boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (tenant_id, id),
    -- The composite FK is the enforcement: tenant_id must match on both sides.
    FOREIGN KEY (tenant_id, project_id) REFERENCES projects (tenant_id, id)
);

ALTER TABLE projects          ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects          FORCE  ROW LEVEL SECURITY;
ALTER TABLE result_contracts  ENABLE ROW LEVEL SECURITY;
ALTER TABLE result_contracts  FORCE  ROW LEVEL SECURITY;

-- RX-48: identity comes from a TRANSACTION-LOCAL setting, so a pooled
-- connection cannot carry one request's tenant into the next. current_setting
-- with missing_ok=true yields NULL when unset, and NULL = anything is NULL, so
-- an unset tenant matches NOTHING. The policy therefore FAILS CLOSED rather
-- than defaulting to visible.
--
-- NULLIF IS LOAD-BEARING, found by a real test against real PostgreSQL. A
-- setting established with set_config(..., is_local => true) does not return to
-- NULL when the transaction ends - it returns to the EMPTY STRING. Without the
-- nullif, the next statement on that pooled connection evaluates ''::uuid and
-- raises invalid_text_representation instead of simply matching no rows. That
-- still denies the data, but it turns a clean empty result into an error on a
-- perfectly ordinary pooled-connection code path. SQLite cannot exhibit this;
-- it was only visible because the test runs against PostgreSQL.
DROP POLICY IF EXISTS tenant_isolation ON projects;
CREATE POLICY tenant_isolation ON projects
    USING      (tenant_id = nullif(current_setting('retrace.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('retrace.tenant_id', true), '')::uuid);

DROP POLICY IF EXISTS tenant_isolation ON result_contracts;
CREATE POLICY tenant_isolation ON result_contracts
    USING      (tenant_id = nullif(current_setting('retrace.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = nullif(current_setting('retrace.tenant_id', true), '')::uuid);

-- The application role. Owns nothing, cannot bypass RLS, cannot DDL.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'retrace_svc') THEN
        CREATE ROLE retrace_svc LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB
            NOCREATEROLE NOINHERIT PASSWORD 'svc_placeholder_set_by_bootstrap';
    END IF;
END $$;

ALTER ROLE retrace_svc NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;

GRANT USAGE ON SCHEMA public TO retrace_svc;
GRANT SELECT, INSERT, UPDATE, DELETE ON projects, result_contracts TO retrace_svc;
-- Deliberately NOT granted: CREATE on schema, ownership, TRUNCATE, REFERENCES.
REVOKE CREATE ON SCHEMA public FROM retrace_svc;

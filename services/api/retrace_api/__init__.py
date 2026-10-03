"""RETRACE API service package - persistence surface only (RX-47, RX-48, RX-49).

SCOPE OF THIS PACKAGE AS IT STANDS. Only the database surface is implemented:
SQLAlchemy metadata, the tenancy models, versioned Alembic migrations, the
privileged bootstrap step and a forward-repair entry point. There are NO HTTP
endpoints here yet, and nothing in this package authenticates a caller.

That boundary matters for an honest reading of the tenancy requirement. The
database half of RX-47/RX-48 is enforced here and demonstrated against real
PostgreSQL in `tests/migrations/`. The other half - that the tenant identity
written into `retrace.tenant_id` is derived from an AUTHENTICATED principal and
never from a caller-supplied value - is NOT implemented and NOT proven. The
corresponding gate in `tests/postgres/test_tenant_isolation.py` is explicitly
skipped as NOT_RUN for that reason, and this package does not change that.

What this package does deliver is that the schema those properties depend on is
reproducible: `infra/sql/001_tenancy.sql` is a hand-applied file with no version
identity, so two environments can diverge with nothing recording it. A versioned
migration chain makes the schema state addressable, which is also the
precondition for the restore exercise RX-61 requires (a restore cannot be
verified against a schema that cannot be rebuilt). RX-61 itself - measured
RPO/RTO, observability, a runbook with a named owner - is NOT implemented here.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Package version. Deliberately independent of the schema revision: the schema
#: version is the Alembic head recorded in `alembic_version`, and conflating the
#: two would let a code release imply a schema state it never applied.
__version__ = "0.0.0"

"""Declarative base and metadata naming convention (RX-47, RX-49).

WHY THE NAMING CONVENTION MIRRORS POSTGRESQL'S OWN DEFAULTS.

The usual advice is to adopt an Alembic-flavoured convention (`pk_projects`,
`fk_result_contracts_...`). That advice is wrong for this repository, and the
reason is evidential rather than aesthetic.

`infra/sql/001_tenancy.sql` is already applied in at least one environment, and
it names nothing explicitly, so PostgreSQL assigned `projects_pkey`,
`result_contracts_pkey` and `result_contracts_tenant_id_project_id_fkey`. The
migration chain has to be able to show that a database upgraded from that
hand-applied state and a database built fresh from the migrations end up with the
SAME realised catalogue. If the convention here produced different constraint
names, that comparison would fail on names alone - and the only ways to make it
pass would be to rename constraints on every existing database (a lock on a
production table, for a cosmetic gain) or to exclude names from the comparison
(which would also stop the comparison noticing a genuinely missing constraint).

So the convention reproduces PostgreSQL's defaults exactly. The patterns below
are the server's own: `<table>_pkey`, `<table>_<cols>_key`, `<table>_<cols>_fkey`,
`<table>_<cols>_idx`. Verified against the realised catalogue of the already
applied schema, not assumed from documentation.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

__all__ = ["NAMING_CONVENTION", "Base", "metadata"]

#: PostgreSQL's own default constraint and index names, expressed as a SQLAlchemy
#: naming convention. `%(column_0_N_name)s` joins every constrained column with
#: an underscore, which is what the server does.
NAMING_CONVENTION: dict[str, str] = {
    "pk": "%(table_name)s_pkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
}

#: Single metadata object for the tenancy schema. `tests/migrations` compares it
#: against the realised catalogue produced by `alembic upgrade head`, so the
#: models and the migrations cannot drift apart silently.
metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Base(DeclarativeBase):
    """Declarative base bound to the conventioned metadata."""

    metadata = metadata

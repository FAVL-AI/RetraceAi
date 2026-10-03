"""${message}

Revision: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}

RX-*: name the requirement this revision serves. A revision whose docstring does
not say which property it exists to establish cannot be reviewed against one.

BEFORE COMMITTING A GENERATED REVISION, READ THIS.

Autogenerate does NOT emit row-level security, FORCE ROW LEVEL SECURITY,
policies or grants, and it reports NO DIFFERENCE when they are absent. If this
revision adds or renames a table carrying `tenant_id`, the RLS configuration for
it must be written BY HAND - add the table to
`retrace_api.db.security.SECURED_TABLES` and call
`apply_security_configuration` here - and the realised-catalogue assertions in
`tests/migrations` must be extended to cover it. A generated diff that looks
clean is not evidence that isolation is in place.

A downgrade that would drop a tenant-bearing table must raise
`DestructiveDowngradeRefused` and name the forward-repair route instead.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}

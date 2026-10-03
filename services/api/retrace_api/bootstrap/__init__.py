"""Privileged bootstrap, deliberately separate from migrations (RX-47).

Role creation and privilege grants live here and NOT in a migration. Three
reasons, in order of importance:

  1. The migration credential would otherwise need CREATEROLE. A credential that
     can create roles can create a role with attributes it holds, which turns a
     compromised migration step into a privilege-escalation path.
  2. Roles are CLUSTER-wide while migrations are per-database. A migration that
     creates a role mutates shared state outside the database it claims to be
     migrating, so running it against a second database would silently re-alter
     the first's runtime identity - including, if written carelessly, its password.
  3. The two steps have different cadences. Migrations run on every deploy; role
     bootstrap runs once, by an operator, and is the step where a credential is
     chosen. Running it on every deploy is how a password ends up in a pipeline
     variable.

See services/api/MIGRATIONS.md for the ordered procedure and which identity runs
each step.
"""

from __future__ import annotations

from retrace_api.bootstrap.roles import (
    RUNTIME_PRIVILEGES,
    assert_runtime_role_is_unprivileged,
    create_service_role,
    grant_runtime_privileges,
)

__all__ = [
    "RUNTIME_PRIVILEGES",
    "assert_runtime_role_is_unprivileged",
    "create_service_role",
    "grant_runtime_privileges",
]

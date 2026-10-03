"""Database surface: metadata, tenancy models, migrations, forward repair.

Serves RX-47 (RLS plus a non-privileged service role), RX-48 (transaction-local
identity) and RX-49 (composite tenant keys). See `models.py` for why the
composite foreign key is NOT redundant with row-level security.
"""

from __future__ import annotations

from retrace_api.db.base import NAMING_CONVENTION, Base, metadata
from retrace_api.db.models import Project, ResultContractRow
from retrace_api.db.security import (
    POLICY_NAME,
    POLICY_PREDICATE,
    SECURED_TABLES,
    TENANT_SETTING,
    apply_security_configuration,
    security_statements,
)

__all__ = [
    "NAMING_CONVENTION",
    "POLICY_NAME",
    "POLICY_PREDICATE",
    "SECURED_TABLES",
    "TENANT_SETTING",
    "Base",
    "Project",
    "ResultContractRow",
    "apply_security_configuration",
    "metadata",
    "security_statements",
]

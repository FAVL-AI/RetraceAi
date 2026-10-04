"""Transaction-local database tenant context (RX-47, RX-48).

WHY `set_config(..., true)` AND NOT `SET LOCAL`.

``SET LOCAL retrace.tenant_id = ...`` takes a literal. It does NOT accept a bind
parameter, so using it forces the tenant value to be interpolated into SQL text
- which is the one place a tenant identifier must never be built by string
concatenation, because that identifier decides which rows row-level security
will reveal. ``set_config('retrace.tenant_id', $1, true)`` takes the value as a
PARAMETER, so the driver sends it out of band and no quoting decision is made in
this process. The third argument ``true`` is ``is_local``: the setting reverts
when the transaction ends, which is what makes connection pooling safe.

WHY THE CONTEXT IS ASSERTED BEFORE ANY QUERY AND NOT AFTER.

Reading the setting back after a query would discover the mistake once the query
had already run. Under the policy in ``retrace_api.db.security`` an unset context
yields NULL and therefore no rows - it fails closed - but "no rows" is
indistinguishable from "the tenant genuinely has no rows", so a missing context
would surface as an empty list rather than as an error, and the bug would ship.
:func:`assert_tenant_context` is therefore called immediately after the context
is applied and before the handler is given the connection, and it raises
:class:`~retrace_api.web.errors.TenantContextMissing` rather than returning a
value a caller could ignore.

WHY THE VALUE IS VALIDATED EVEN THOUGH IT COMES FROM THE DIRECTORY.

The tenant reaching this module has already been authorised, so validating its
shape adds no authorisation. It is validated anyway because the policy predicate
casts the setting to ``uuid``: a value that is not a UUID makes every query in
the transaction raise ``invalid_text_representation`` from inside the policy,
which reads like a database fault rather than a bad identifier. Refusing it here
names the actual problem.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterator

from retrace_api.db.security import TENANT_SETTING
from retrace_api.web.errors import TenantContextMissing
from sqlalchemy import Connection, Engine, text

__all__ = [
    "apply_tenant_context",
    "assert_tenant_context",
    "normalise_tenant_id",
    "read_tenant_context",
    "tenant_transaction",
]

_SET_CONTEXT = text(f"SELECT set_config('{TENANT_SETTING}', :tenant_value, true)")
_READ_CONTEXT = text(f"SELECT nullif(current_setting('{TENANT_SETTING}', true), '')")


def normalise_tenant_id(tenant_id: str) -> str:
    """Return the canonical string form of ``tenant_id`` (RX-48).

    Canonical rather than as-supplied: ``A1B2...`` and ``a1b2...`` are the same
    UUID but different strings, and a predicate comparing strings in one place
    and UUIDs in another would disagree about them.
    """
    try:
        return str(uuid.UUID(str(tenant_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise TenantContextMissing(
            f"tenant identifier {tenant_id!r} is not a UUID, so it cannot be used as the "
            "transaction-local tenant context",
            remedy="resolve the tenant from an authorised membership rather than from input",
        ) from exc


def apply_tenant_context(connection: Connection, tenant_id: str) -> str:
    """Set the transaction-local tenant and return the canonical value (RX-48).

    Must be called inside an open transaction. Outside one, SQLAlchemy would
    autocommit the ``SELECT set_config(...)`` and the ``is_local`` setting would
    revert immediately, leaving the next statement with no context at all.
    """
    if not connection.in_transaction():
        raise TenantContextMissing(
            "apply_tenant_context was called outside a transaction; a transaction-local "
            "setting applied outside one reverts before the next statement runs",
            remedy="open a transaction first, or use tenant_transaction()",
        )
    canonical = normalise_tenant_id(tenant_id)
    connection.execute(_SET_CONTEXT, {"tenant_value": canonical})
    return canonical


def read_tenant_context(connection: Connection) -> str | None:
    """Read the transaction-local tenant back, or ``None`` when unset."""
    value = connection.execute(_READ_CONTEXT).scalar_one_or_none()
    return None if value is None else str(value)


def assert_tenant_context(connection: Connection, expected: str) -> str:
    """Fail closed unless the context is present AND equal to ``expected`` (RX-48).

    Equality matters as much as presence. On a pooled connection a transaction
    that inherited a *different* tenant's context would pass a presence-only
    check and then read the wrong tenant's rows - which is precisely threat T4.
    """
    canonical = normalise_tenant_id(expected)
    observed = read_tenant_context(connection)
    if observed is None:
        raise TenantContextMissing(
            "no transaction-local tenant context is set; the query was not issued",
            remedy="apply the authorised tenant with apply_tenant_context before querying",
        )
    if observed != canonical:
        raise TenantContextMissing(
            "the transaction-local tenant context does not match the authorised tenant; "
            "the query was not issued",
            remedy="do not reuse a connection across tenants without reapplying the context",
            extra={"observed_matches_expected": False},
        )
    return canonical


@contextlib.contextmanager
def tenant_transaction(engine: Engine, tenant_id: str) -> Iterator[Connection]:
    """A transaction whose tenant context is set and verified before use (RX-48).

    Rolls back on any exception, so a handler that raises part way through leaves
    no partial row behind. The context is applied and asserted INSIDE the
    transaction, so a failure to establish it aborts before the handler receives
    the connection.
    """
    with engine.begin() as connection:
        canonical = apply_tenant_context(connection, tenant_id)
        assert_tenant_context(connection, canonical)
        yield connection

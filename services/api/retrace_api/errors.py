"""Named refusals for the persistence surface (RX-47, RX-48, RX-49).

Every path that cannot be completed in this environment raises one of these
rather than returning a success-shaped value or quietly doing something weaker.
A migration that silently adopts a schema it did not verify, or a repair that
reports success without reading the realised catalogue back, would be worse than
an outright failure: it would move the evidence in the wrong direction.
"""

from __future__ import annotations

__all__ = [
    "BaselineDivergence",
    "DestructiveDowngradeRefused",
    "MigrationConfigurationError",
    "PersistenceError",
    "RolePrivilegeError",
    "SchemaRepairFailed",
    "SchemaRevisionMismatch",
]


class PersistenceError(RuntimeError):
    """Base class for every refusal raised by this package."""


class MigrationConfigurationError(PersistenceError):
    """No usable database URL was supplied, so no migration can be attempted.

    Raised instead of falling back to a default DSN. A default would silently
    point a migration at the wrong database, and `alembic upgrade head` against
    the wrong database is not recoverable by re-running it.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(f"NEEDS_CONFIGURATION: {detail}")


class BaselineDivergence(PersistenceError):
    """An existing table does not match the tenancy baseline it would be adopted as.

    The baseline migration adopts a pre-existing hand-applied schema rather than
    stamping it, but adoption is conditional on the enforcement structure already
    being correct. A table whose primary key is not composite, or whose foreign
    key is not composite, does NOT enforce RX-49, and adopting it would record a
    head revision that the database does not actually satisfy.
    """


class DestructiveDowngradeRefused(PersistenceError):
    """A downgrade that would drop tenant-bearing tables is refused.

    Reversibility is not an unconditional virtue. Dropping `projects` or
    `result_contracts` destroys every tenant's rows, and an operator reaching for
    a downgrade during an incident is the least likely moment for that to be the
    intended outcome. The supported recovery route is forward repair; the message
    names it.
    """


class SchemaRevisionMismatch(PersistenceError):
    """An operation that requires the database to be at head found another revision.

    Forward repair re-applies the security configuration for the tables the
    CURRENT head knows about. On a database behind head those tables may not
    exist yet, and on one ahead of this code's head there may be tenant-bearing
    tables this code has never heard of - repairing the ones it knows and
    reporting success would leave the others unprotected and say nothing about
    them.
    """


class SchemaRepairFailed(PersistenceError):
    """Repair ran, but the realised catalogue still does not satisfy isolation.

    Raised after reading the catalogue BACK. A repair that reports success
    because its statements returned without error is not evidence: the statements
    can succeed inside a transaction that later rolls back, and the operator's
    conclusion would be exactly wrong.
    """


class RolePrivilegeError(PersistenceError):
    """The runtime database identity holds a privilege that would void RLS.

    A superuser, a BYPASSRLS role, or a table owner without FORCE ROW LEVEL
    SECURITY is not subject to the policies, so every policy would be decorative
    and any isolation test run as that identity would prove nothing.
    """

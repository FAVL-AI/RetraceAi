"""Principals, verified membership and server-managed sessions (RX-45, RX-46, RX-47).

THE ONE RULE THIS MODULE EXISTS TO ENFORCE.

The effective tenant and the effective actor come from the authenticated
session plus a membership lookup. Nothing a client sends - path segment, header
or body field - can establish either. A client may *request* a workspace; the
request is then checked against the directory, and an unverified request is
refused.

WHY MEMBERSHIP IS NOT STORED IN THE SESSION.

Caching the membership set at sign-in makes revocation take effect only when
the session expires, which is exactly the stale-permission failure T6 describes.
:meth:`MembershipDirectory.membership` is therefore consulted on every request.
That costs a lookup per request and is the correct trade.

WHY THE SESSION STORE IS IN MEMORY, AND WHAT THAT COSTS.

This tranche must not add a database table: the migration suite asserts the
realised schema is exactly ``projects``, ``result_contracts`` and
``alembic_version``, so a sessions table would break a proof that is already
executed. The store is therefore process-local, which has two real
consequences, recorded rather than hidden:

* sessions do not survive a restart, and
* they are not shared between workers, so a multi-process deployment would
  reject requests that land on the wrong worker.

Neither weakens a security property - a lost session fails CLOSED - but neither
is acceptable for a hosted deployment, and both are listed as limitations.

NO PASSWORD STORE, NO TOKEN FORMAT, NO CUSTOM CRYPTOGRAPHY.

RX-45 specifies OIDC and forbids custom cryptography. Session identifiers are
opaque 32-byte random strings from :mod:`secrets`; they carry no claims, so
there is nothing to sign and no signature to get wrong. Authenticating a human
is the identity provider's job, and no provider is configured here.

WHAT IS AND IS NOT COMPARED IN CONSTANT TIME, STATED ACCURATELY.

The CSRF token IS compared with :func:`secrets.compare_digest`, in
:func:`csrf_tokens_match`. The session identifier is NOT: :meth:`SessionStore
.resolve` is a dictionary lookup, which is not constant-time with respect to the
key. That is a deliberate trade and it is recorded rather than described as
something it is not - a linear constant-time scan of every live session would
make the lookup O(sessions) on every request, and the identifier it protects is
32 bytes of entropy that an attacker would have to recover through a hash-table
timing signal. If that trade is ever revisited, the remedy is a keyed lookup of
a short prefix followed by a constant-time comparison of the remainder, not a
scan.
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

__all__ = [
    "InMemoryMembershipDirectory",
    "Membership",
    "MembershipDirectory",
    "Principal",
    "SESSION_ID_BYTES",
    "SessionRecord",
    "SessionStore",
    "WorkspaceRole",
    "csrf_tokens_match",
]

#: 32 bytes of entropy per identifier. ``token_urlsafe`` renders this as 43
#: characters; the length is stated here rather than inferred from the string so
#: a future change cannot quietly shorten it.
SESSION_ID_BYTES: Final = 32


class WorkspaceRole(str, Enum):
    """What a principal may do inside one workspace (RX-46).

    Ordered by capability, and the ordering is used - ``APPROVER`` implies
    ``MEMBER`` implies ``VIEWER``. ``APPROVER`` is separate from ``MEMBER``
    because approving a repair is the authority step: if proposing and approving
    were one role, a single compromised account would be the whole control.
    """

    VIEWER = "VIEWER"
    MEMBER = "MEMBER"
    APPROVER = "APPROVER"
    ADMIN = "ADMIN"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def permits(self, required: WorkspaceRole) -> bool:
        """Whether this role satisfies ``required``."""
        return self.rank >= required.rank


_ROLE_RANK: Final[dict[WorkspaceRole, int]] = {
    WorkspaceRole.VIEWER: 0,
    WorkspaceRole.MEMBER: 1,
    WorkspaceRole.APPROVER: 2,
    WorkspaceRole.ADMIN: 3,
}


@dataclass(frozen=True)
class Principal:
    """An authenticated subject (RX-45).

    ``subject`` is the identity provider's stable subject identifier. It is NOT
    an email address: RX-46 forbids inferring membership from an email domain,
    and keying authorisation on an address invites exactly that.
    """

    subject: str
    display_name: str = ""

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("a principal must have a non-empty subject")


@dataclass(frozen=True)
class Membership:
    """A verified membership of one workspace (RX-46, RX-47)."""

    tenant_id: str
    role: WorkspaceRole


class MembershipDirectory:
    """Resolves which workspaces a principal actually belongs to (RX-46, RX-47).

    An interface, not an abstract base: the production implementation would read
    an identity provider's group claims or a membership table, and neither
    exists in this build. Any implementation must answer from stored state, not
    from the request.
    """

    def membership(self, principal: Principal, tenant_id: str) -> Membership | None:
        """Return the membership, or ``None`` when there is none."""
        raise NotImplementedError

    def memberships(self, principal: Principal) -> tuple[Membership, ...]:
        """Every membership held by ``principal``."""
        raise NotImplementedError


class InMemoryMembershipDirectory(MembershipDirectory):
    """A directory held in memory, for the unit suite and for test fixtures.

    Explicitly NOT a production component: it is populated by the process that
    constructs it, so it proves the authorisation LOGIC and proves nothing about
    where real memberships come from. The production directory is unimplemented
    and listed as a blocker.
    """

    def __init__(self, grants: Mapping[str, Mapping[str, WorkspaceRole]] | None = None) -> None:
        self._grants: dict[str, dict[str, WorkspaceRole]] = {
            subject: dict(tenants) for subject, tenants in (grants or {}).items()
        }

    def grant(self, subject: str, tenant_id: str, role: WorkspaceRole) -> None:
        """Record a membership. Server-side only; no route reaches this."""
        self._grants.setdefault(subject, {})[tenant_id] = role

    def revoke(self, subject: str, tenant_id: str) -> None:
        self._grants.get(subject, {}).pop(tenant_id, None)

    def membership(self, principal: Principal, tenant_id: str) -> Membership | None:
        role = self._grants.get(principal.subject, {}).get(tenant_id)
        return None if role is None else Membership(tenant_id=tenant_id, role=role)

    def memberships(self, principal: Principal) -> tuple[Membership, ...]:
        held = self._grants.get(principal.subject, {})
        return tuple(
            Membership(tenant_id=tenant, role=role) for tenant, role in sorted(held.items())
        )


@dataclass(frozen=True)
class SessionRecord:
    """One server-managed session (RX-45).

    The cookie carries ``session_id`` and nothing else. Everything the server
    needs about the session lives here, server-side, so a client cannot edit any
    of it - which is the property a self-contained signed token would have to
    recover with cryptography this build is forbidden from writing.
    """

    session_id: str
    principal: Principal
    csrf_token: str
    created_at: dt.datetime
    expires_at: dt.datetime

    def expired_at(self, now: dt.datetime) -> bool:
        return now >= self.expires_at


class SessionStore:
    """Creates, resolves and destroys server-managed sessions (RX-45).

    Session fixation is prevented structurally: there is no API that adopts a
    caller-supplied identifier. :meth:`establish` always mints a fresh one, and
    :meth:`rotate` replaces an existing session's identifier while keeping its
    principal, which is what an elevation step would call.
    """

    def __init__(self, *, ttl_seconds: int, max_sessions: int = 10_000) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_sessions <= 0:
            raise ValueError("max_sessions must be positive")
        self._ttl = dt.timedelta(seconds=ttl_seconds)
        self._max = max_sessions
        self._records: OrderedDict[str, SessionRecord] = OrderedDict()

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())

    def __len__(self) -> int:
        return len(self._records)

    def establish(self, principal: Principal, *, now: dt.datetime) -> SessionRecord:
        """Mint a new session for an ALREADY AUTHENTICATED principal (RX-45).

        This is a server-side call. It is reached from an identity provider
        callback - which this build does not have - and from test fixtures that
        inject a principal. It is deliberately not reachable from any route:
        grep the routers and no handler calls it, which is why an unauthenticated
        caller cannot mint a session for itself.
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware; sessions are stored in UTC")
        self._evict_expired(now)
        while len(self._records) >= self._max:
            self._records.popitem(last=False)
        record = SessionRecord(
            session_id=secrets.token_urlsafe(SESSION_ID_BYTES),
            principal=principal,
            csrf_token=secrets.token_urlsafe(SESSION_ID_BYTES),
            created_at=now,
            expires_at=now + self._ttl,
        )
        self._records[record.session_id] = record
        return record

    def rotate(self, session_id: str, *, now: dt.datetime) -> SessionRecord | None:
        """Replace a session's identifier, keeping its principal (RX-45)."""
        existing = self.resolve(session_id, now=now)
        if existing is None:
            return None
        self.destroy(session_id)
        return self.establish(existing.principal, now=now)

    def resolve(self, session_id: str | None, *, now: dt.datetime) -> SessionRecord | None:
        """Return the live session, or ``None``.

        An expired record is removed here rather than merely ignored, so a
        resolve cannot be followed by a successful second resolve of the same id.
        """
        if not session_id:
            return None
        record = self._records.get(session_id)
        if record is None:
            return None
        if record.expired_at(now):
            del self._records[record.session_id]
            return None
        return record

    def destroy(self, session_id: str) -> None:
        self._records.pop(session_id, None)

    def _evict_expired(self, now: dt.datetime) -> None:
        stale = [sid for sid, record in self._records.items() if record.expired_at(now)]
        for sid in stale:
            del self._records[sid]

    def subjects(self) -> Iterable[str]:
        """Subjects with a live session. Diagnostics only; no route exposes it."""
        return (record.principal.subject for record in self._records.values())


def csrf_tokens_match(*values: str | None) -> bool:
    """Constant-time equality across every supplied token (RX-45).

    Takes the WHOLE set so a caller cannot accidentally compare two of three.
    Any absent or empty value is a refusal, so a request that omits the header
    cannot match a session whose token is somehow also empty.
    """
    if len(values) < 2:
        raise ValueError("at least two values are required for a comparison")
    if any(not value for value in values):
        return False
    first = values[0] or ""
    return all(secrets.compare_digest(first, value or "") for value in values[1:])

"""Idempotency keys for mutating routes (RX-53).

WHAT AN IDEMPOTENCY KEY HAS TO DO, AND THE PART THAT IS USUALLY MISSED.

Replaying a stored response for a repeated key is the easy half. The half that
matters is the case where the SAME key arrives with a DIFFERENT request body. A
store that keys only on the key would return the first response, and the second
request - a different contract, a different approval - would be silently
discarded while its caller was told it succeeded. So the request digest is
stored with the key and compared: a repeat with the same digest replays, a
repeat with a different digest is REFUSED.

THE KEY IS SCOPED PER TENANT AND PER ROUTE.

Two tenants that choose the same key must not collide, and a key used on
``POST .../contracts`` must not replay onto ``POST .../approvals``. The stored
key is therefore the triple (tenant, route template, key).

RESERVATION HAPPENS BEFORE THE EFFECT.

:meth:`IdempotencyStore.reserve` records the key as in-flight before the handler
runs, so a second concurrent request with the same key is refused rather than
both proceeding. The window is not closed across processes - this store is
process-local for the same reason the session store is - and that limitation is
recorded rather than papered over.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Final

from retrace_api.web.errors import IdempotencyRefused

__all__ = [
    "IdempotencyStore",
    "StoredOutcome",
    "request_digest",
]

_MAX_ENTRIES: Final = 4096
_KEY_MAX_LENGTH: Final = 200


def request_digest(*, method: str, route: str, tenant_id: str, body: bytes) -> str:
    """SHA-256 over the parts that make two requests the same request (RX-53).

    The method, the route template, the tenant and the exact body bytes. The
    body is hashed as BYTES, not as parsed JSON: two payloads that parse to the
    same object but differ textually are different requests as far as a replay
    is concerned, and normalising them here would mean deciding what counts as
    equivalent, which is the contract layer's job and not this one's.
    """
    digest = hashlib.sha256()
    for part in (method.upper(), route, tenant_id):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    digest.update(body)
    return digest.hexdigest()


@dataclass(frozen=True)
class StoredOutcome:
    """A completed response held against its key."""

    status_code: int
    body: dict[str, Any]
    digest: str


@dataclass
class _Entry:
    digest: str
    outcome: StoredOutcome | None


class IdempotencyStore:
    """Process-local idempotency records (RX-53).

    Bounded: the oldest entry is evicted past the cap, so a flood of unique keys
    cannot grow the store without limit. Eviction means a very old key could be
    replayed as new - which is why the cap is generous relative to any realistic
    burst, and why this is recorded as a limitation of a process-local store
    rather than claimed as a durable dedup log.
    """

    def __init__(self, max_entries: int = _MAX_ENTRIES) -> None:
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self._max = max_entries
        self._entries: OrderedDict[tuple[str, str, str], _Entry] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    @staticmethod
    def validate_key(key: str | None) -> str:
        """Require a usable key, and refuse an unusable one (RX-53)."""
        if key is None or not key.strip():
            raise IdempotencyRefused(
                "this route requires an Idempotency-Key header",
                remedy="send a unique Idempotency-Key per logical operation and reuse "
                "it only to retry that exact operation",
                code="IDEMPOTENCY_KEY_REQUIRED",
                status_code=400,
            )
        cleaned = key.strip()
        if len(cleaned) > _KEY_MAX_LENGTH:
            raise IdempotencyRefused(
                f"the Idempotency-Key exceeds {_KEY_MAX_LENGTH} characters",
                remedy="use a shorter unique key, such as a UUID",
                code="IDEMPOTENCY_KEY_REQUIRED",
                status_code=400,
            )
        return cleaned

    def reserve(
        self, *, tenant_id: str, route: str, key: str, digest: str
    ) -> StoredOutcome | None:
        """Claim the key, or return the stored outcome of an identical replay.

        Returns ``None`` when the caller should proceed. Raises when the key was
        used for a different request, or when a request with the same key is
        still in flight.
        """
        identity = (tenant_id, route, key)
        existing = self._entries.get(identity)
        if existing is None:
            while len(self._entries) >= self._max:
                self._entries.popitem(last=False)
            self._entries[identity] = _Entry(digest=digest, outcome=None)
            return None
        if existing.digest != digest:
            raise IdempotencyRefused(
                "this Idempotency-Key was already used for a different request; the "
                "second request was NOT applied and no stored response was replayed",
                remedy="use a fresh key for a new operation, and reuse a key only to "
                "retry the identical request",
                code="IDEMPOTENCY_KEY_REUSED",
            )
        if existing.outcome is None:
            raise IdempotencyRefused(
                "a request with this Idempotency-Key is still in flight",
                remedy="wait for the first attempt to complete before retrying",
                code="IDEMPOTENCY_IN_FLIGHT",
            )
        return existing.outcome

    def complete(
        self, *, tenant_id: str, route: str, key: str, digest: str, status_code: int, body: Any
    ) -> None:
        """Record the response for a reserved key."""
        identity = (tenant_id, route, key)
        entry = self._entries.get(identity)
        stored_body = body if isinstance(body, dict) else {"value": body}
        outcome = StoredOutcome(status_code=status_code, body=stored_body, digest=digest)
        if entry is None:
            self._entries[identity] = _Entry(digest=digest, outcome=outcome)
            return
        entry.outcome = outcome

    def release(self, *, tenant_id: str, route: str, key: str) -> None:
        """Drop a reservation whose handler failed.

        A refused request must not hold its key: the caller should be able to fix
        the payload and retry with the same key. Only a COMPLETED outcome is
        replayable.
        """
        identity = (tenant_id, route, key)
        entry = self._entries.get(identity)
        if entry is not None and entry.outcome is None:
            del self._entries[identity]

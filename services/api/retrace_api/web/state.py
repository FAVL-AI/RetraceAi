"""The composed service state one app instance holds (RX-44, RX-45, RX-47).

WHY EVERY COLLABORATOR IS INJECTED.

The session store, the membership directory, the repository, the storage
factory, the idempotency store, the admission policy and the clock all arrive
as constructor arguments. Two reasons, both practical. First, a test can supply
a deterministic clock and an in-memory repository without monkeypatching a
module global, so the thing under test is the real code path. Second, the
production wiring is then one function (:func:`state_from_config`) that a
reviewer can read end to end to see which component is real and which is
unimplemented - rather than discovering it by grep.

THE CLOCK IS INJECTED FOR A SCIENTIFIC REASON, NOT A CONVENIENCE ONE.

Session expiry, approval timestamps and bundle timestamps are all recorded. A
test that cannot control the clock has to either sleep or assert loosely, and a
loose assertion about an expiry is a test that cannot fail when the expiry is
wrong.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

import sqlalchemy as sa
from retrace_api.web.admission import DEFAULT_ADMISSION_POLICY, AdmissionPolicy, QuarantineArea
from retrace_api.web.config import ApiConfig, ConfigurationError
from retrace_api.web.idempotency import IdempotencyStore
from retrace_api.web.identity import MembershipDirectory, SessionStore
from retrace_api.web.repository import InMemoryRepository, Repository, SqlRepository
from retrace_api.web.workspace import StorageNotConfigured, WorkspaceFactory

__all__ = ["ServiceState", "state_from_config", "utc_now"]


def utc_now() -> dt.datetime:
    """The default clock. Timezone-aware UTC, because every record stores UTC."""
    return dt.datetime.now(tz=dt.UTC)


@dataclass
class ServiceState:
    """Everything a request handler is allowed to reach."""

    config: ApiConfig
    sessions: SessionStore
    directory: MembershipDirectory
    repository: Repository
    workspaces: WorkspaceFactory
    idempotency: IdempotencyStore = field(default_factory=IdempotencyStore)
    admission_policy: AdmissionPolicy = DEFAULT_ADMISSION_POLICY
    clock: Callable[[], dt.datetime] = utc_now
    #: Recorded on every proposal. Distinct from a model provider: the API does
    #: not generate proposals, it records the one the caller submitted, and a
    #: provider identifier that implied otherwise would be a fabrication.
    proposal_provider_id: str = "api-submitted"

    def __post_init__(self) -> None:
        """Refuse a wiring whose two size ceilings contradict each other.

        ``config.max_request_body_bytes`` bounds the body the idempotency
        dependency will buffer; ``admission_policy.max_upload_bytes`` bounds the
        payload admission will accept. If the first is not larger than the
        second, an upload of exactly the admitted size is refused by the request
        ceiling instead - a 413 naming the wrong limit, for a payload the
        admission policy says is fine. Caught here rather than at request time,
        because a misconfigured ceiling should stop a deployment starting rather
        than surface as a confusing refusal under load.
        """
        if self.config.max_request_body_bytes <= self.admission_policy.max_upload_bytes:
            raise ConfigurationError(
                f"max_request_body_bytes={self.config.max_request_body_bytes} is not "
                f"greater than the admission policy's max_upload_bytes="
                f"{self.admission_policy.max_upload_bytes}; an upload of exactly the "
                "admitted size would be refused by the request ceiling, naming the "
                "wrong limit. Leave room for multipart framing as well"
            )

    def now(self) -> dt.datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise ValueError("the configured clock returned a naive datetime")
        return value

    def quarantine(self) -> QuarantineArea:
        """The quarantine area, or a NEEDS_CONFIGURATION refusal (RX-42)."""
        if not self.workspaces.configured:
            raise StorageNotConfigured
        return QuarantineArea(self.workspaces.root / "_quarantine")


def state_from_config(
    config: ApiConfig,
    *,
    directory: MembershipDirectory,
    repository: Repository | None = None,
    clock: Callable[[], dt.datetime] | None = None,
) -> ServiceState:
    """Wire a service state from configuration (RX-45, RX-47).

    ``repository`` defaults to :class:`SqlRepository` when a database URL is
    configured and to :class:`InMemoryRepository` otherwise. The fallback is
    stated in the log-free, obvious way: the in-memory repository is not durable
    and carries no row-level security, and selecting it is a consequence of
    there being no database URL - never a silent preference.

    ``directory`` has NO default. A membership directory decides authorisation,
    and defaulting it to an empty one would make every request a 403 that looked
    like a permissions problem instead of a missing dependency; defaulting it to
    a permissive one would be far worse.
    """
    if repository is None:
        if config.database_url:
            engine = sa.create_engine(config.database_url, poolclass=sa.pool.NullPool)
            repository = SqlRepository(engine)
        else:
            repository = InMemoryRepository()
    return ServiceState(
        config=config,
        sessions=SessionStore(
            ttl_seconds=config.session_ttl_seconds, max_sessions=config.max_sessions
        ),
        directory=directory,
        repository=repository,
        workspaces=WorkspaceFactory(config.storage_root),
        clock=clock or utc_now,
    )

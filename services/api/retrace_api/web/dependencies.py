"""Request-scoped authentication, authorisation and idempotency (RX-45, RX-47, RX-53).

ONE DEPENDENCY CARRIES THE WHOLE REQUEST GATE, AND THAT IS DELIBERATE.

:func:`authorised_workspace` resolves the session, enforces CSRF on unsafe
methods, and then verifies membership of the requested workspace. Putting the
three in one dependency means a route cannot accidentally have tenancy without
CSRF, or CSRF without authentication: a handler that wants the tenant has to
take the dependency that also enforces the other two.

The residual risk is a route that takes NONE of it. That is covered
structurally: ``tests/api/test_route_surface.py`` enumerates every route of the
real application and fails if a workspace-scoped route does not depend on this
function, and fails if an unsafe method is reachable without CSRF enforcement.
A gate that is never shown to detect its own absence is not evidence, so that
test also builds a contained router that omits the dependency and asserts the
check condemns it.

THE ORDER OF THE THREE CHECKS MATTERS.

Authentication first, because without it there is no principal to authorise.
CSRF second, before membership: a cross-site request that happens to name a
workspace the victim belongs to must be refused as CSRF, and resolving
membership first would do a directory lookup on behalf of an attacker-initiated
request. Membership last, and it is a lookup against stored state - never a
comparison against anything in the request.

WHY THE IDEMPOTENCY DEPENDENCY DOES NOT READ THE BODY ITSELF.

RX-53 needs a digest of the request body, and the obvious implementation -
``await request.body()`` in the dependency - was wrong in two ways at once: it
raised ``RuntimeError: Stream consumed`` on every multipart route, because
FastAPI parses a form before it solves dependencies, and it buffered an
unbounded payload on every other route. Both are now handled outside the router
by :class:`retrace_api.web.request_limits.RequestBodyCeiling`, and
:func:`buffered_request_body` reads what that middleware left in the ASGI scope.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import Depends, Path, Request
from retrace_api.web.config import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    IDEMPOTENCY_HEADER_NAME,
    SESSION_COOKIE_NAME,
)
from retrace_api.web.errors import (
    CsrfRefused,
    SessionRequired,
    WorkspaceNotAuthorised,
)
from retrace_api.web.idempotency import StoredOutcome, request_digest
from retrace_api.web.identity import (
    Membership,
    Principal,
    SessionRecord,
    WorkspaceRole,
    csrf_tokens_match,
)
from retrace_api.web.request_limits import BODY_SCOPE_KEY, BODY_UNBUFFERED_MESSAGE
from retrace_api.web.state import ServiceState

__all__ = [
    "AuthorisedWorkspace",
    "Authorised",
    "IGNORED_IDENTITY_HEADERS",
    "IdempotencyScope",
    "SAFE_METHODS",
    "authorised_workspace",
    "buffered_request_body",
    "current_session",
    "idempotency_scope",
    "require_role",
    "service_state",
]

#: Methods that do not mutate and therefore do not require a CSRF token.
#: ``OPTIONS`` is included because the browser's preflight carries no cookies
#: and no custom header by definition; refusing it would break CORS entirely.
SAFE_METHODS: Final[frozenset[str]] = frozenset({"GET", "HEAD", "OPTIONS"})

#: Headers a caller might send hoping they establish identity. They do not. The
#: names are recorded here so a test can assert that sending them changes
#: nothing; the code never reads them.
IGNORED_IDENTITY_HEADERS: Final[tuple[str, ...]] = (
    "x-retrace-actor",
    "x-retrace-tenant-id",
    "x-retrace-subject",
    "x-forwarded-user",
)


def service_state(request: Request) -> ServiceState:
    """The :class:`ServiceState` attached to this application."""
    state = getattr(request.app.state, "retrace", None)
    if state is None:  # pragma: no cover - only reachable if the app is built by hand
        raise RuntimeError("the application has no ServiceState; build it with create_app()")
    return state


def current_session(
    request: Request, state: Annotated[ServiceState, Depends(service_state)]
) -> SessionRecord:
    """Resolve the server-managed session, or refuse (RX-45).

    Reads ONE thing from the request: the HttpOnly session cookie. Everything
    else about the principal comes from the server-side record.
    """
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    session = state.sessions.resolve(cookie, now=state.now())
    if session is None:
        raise SessionRequired(
            "this route requires an authenticated server-managed session",
            remedy="sign in to obtain a session cookie; a header naming an actor or a "
            "tenant is request input and cannot authenticate itself",
        )
    return session


def _enforce_csrf(request: Request, session: SessionRecord) -> None:
    """Double-submit CSRF check for an unsafe method (RX-45)."""
    header = request.headers.get(CSRF_HEADER_NAME)
    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not header:
        raise CsrfRefused(
            f"a mutating request must carry the {CSRF_HEADER_NAME} header",
            remedy=f"copy the {CSRF_COOKIE_NAME} cookie value into the "
            f"{CSRF_HEADER_NAME} header",
        )
    if not cookie:
        raise CsrfRefused(
            f"a mutating request must carry the {CSRF_COOKIE_NAME} cookie",
            remedy="obtain a session, which sets the CSRF cookie alongside it",
        )
    if not csrf_tokens_match(header, cookie, session.csrf_token):
        raise CsrfRefused(
            "the CSRF token did not match; the header, the cookie and the server-side "
            "session record must all agree",
            remedy="refresh the session and resend with the current token",
        )


@dataclass(frozen=True)
class AuthorisedWorkspace:
    """The resolved, verified request context (RX-47).

    ``tenant_id`` here is the ONLY tenant a handler may use. It came from a
    membership lookup, not from the path - the path segment merely said which
    membership to look for.
    """

    session: SessionRecord
    membership: Membership
    route: str

    @property
    def principal(self) -> Principal:
        return self.session.principal

    @property
    def actor(self) -> str:
        return self.session.principal.subject

    @property
    def tenant_id(self) -> str:
        return self.membership.tenant_id

    @property
    def role(self) -> WorkspaceRole:
        return self.membership.role

    def require(self, minimum: WorkspaceRole) -> None:
        """Refuse unless the verified role satisfies ``minimum``."""
        if not self.role.permits(minimum):
            raise WorkspaceNotAuthorised(
                f"this operation requires the {minimum.value} role; the verified "
                f"membership is {self.role.value}",
                remedy=f"ask a workspace administrator for the {minimum.value} role",
                code="ROLE_INSUFFICIENT",
            )


def authorised_workspace(
    request: Request,
    workspace_id: Annotated[str, Path(min_length=1, max_length=128)],
    state: Annotated[ServiceState, Depends(service_state)],
    session: Annotated[SessionRecord, Depends(current_session)],
) -> AuthorisedWorkspace:
    """Authenticate, enforce CSRF on mutations, then verify membership (RX-45, RX-47)."""
    if request.method.upper() not in SAFE_METHODS:
        _enforce_csrf(request, session)
    membership = state.directory.membership(session.principal, workspace_id)
    if membership is None:
        raise WorkspaceNotAuthorised(
            "the authenticated principal is not a verified member of the requested "
            "workspace; naming a workspace does not establish access to it",
            remedy="request membership of the workspace, then retry",
        )
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    return AuthorisedWorkspace(session=session, membership=membership, route=str(template))


Authorised = Annotated[AuthorisedWorkspace, Depends(authorised_workspace)]


def require_role(minimum: WorkspaceRole) -> Callable[[AuthorisedWorkspace], AuthorisedWorkspace]:
    """A dependency that additionally requires ``minimum`` (RX-46)."""

    def _dependency(auth: Authorised) -> AuthorisedWorkspace:
        auth.require(minimum)
        return auth

    return _dependency


class IdempotencyScope:
    """Holds one request's idempotency reservation (RX-53)."""

    def __init__(
        self,
        state: ServiceState,
        *,
        tenant_id: str,
        route: str,
        key: str,
        digest: str,
        replay: StoredOutcome | None,
    ) -> None:
        self._state = state
        self._tenant_id = tenant_id
        self._route = route
        self._key = key
        self._digest = digest
        self.replay = replay
        self._recorded = False

    @property
    def key(self) -> str:
        return self._key

    def record(self, status_code: int, body: object) -> None:
        """Store the response so an identical retry replays it rather than repeating."""
        self._state.idempotency.complete(
            tenant_id=self._tenant_id,
            route=self._route,
            key=self._key,
            digest=self._digest,
            status_code=status_code,
            body=body,
        )
        self._recorded = True

    def abandon(self) -> None:
        """Release an unrecorded reservation so the caller can fix and retry."""
        if not self._recorded:
            self._state.idempotency.release(
                tenant_id=self._tenant_id, route=self._route, key=self._key
            )


def buffered_request_body(request: Request) -> bytes:
    """The body :class:`RequestBodyCeiling` buffered for this request.

    Serves RX-42, RX-51 and RX-53. Reading it from the ASGI scope rather than
    from the request is the whole point: FastAPI parses a form before it solves
    dependencies, and Starlette's form parser consumes the stream without
    caching it, so by the time a dependency runs on a multipart route there is
    nothing left to read. See :mod:`retrace_api.web.request_limits`.

    Raises ``RuntimeError`` when the middleware is absent. That is a wiring
    error, and the alternative is worse than a loud failure: a dependency that
    quietly digested an empty body would give every request on that route the
    same digest, so two genuinely different requests would share one
    idempotency key and the second would be served the first one's response.
    """
    body = request.scope.get(BODY_SCOPE_KEY)
    if not isinstance(body, bytes):
        raise RuntimeError(BODY_UNBUFFERED_MESSAGE)
    return body


async def idempotency_scope(
    request: Request,
    state: Annotated[ServiceState, Depends(service_state)],
    auth: Authorised,
) -> AsyncIterator[IdempotencyScope]:
    """Reserve the request's idempotency key before the handler runs (RX-53).

    The reservation is released if the handler raises, because a refused request
    must not consume its key - the caller should be able to correct the payload
    and retry with the same one. Only a COMPLETED response is replayable.
    """
    key = state.idempotency.validate_key(request.headers.get(IDEMPOTENCY_HEADER_NAME))
    body = buffered_request_body(request)
    digest = request_digest(
        method=request.method, route=auth.route, tenant_id=auth.tenant_id, body=body
    )
    replay = state.idempotency.reserve(
        tenant_id=auth.tenant_id, route=auth.route, key=key, digest=digest
    )
    scope = IdempotencyScope(
        state,
        tenant_id=auth.tenant_id,
        route=auth.route,
        key=key,
        digest=digest,
        replay=replay,
    )
    try:
        yield scope
    except BaseException:
        scope.abandon()
        raise

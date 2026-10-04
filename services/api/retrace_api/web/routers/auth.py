"""Session routes (RX-45).

SIGN-IN REFUSES, AND THAT IS THE CORRECT BEHAVIOUR FOR THIS BUILD.

RX-45 specifies OIDC-based identity. No identity provider is provisioned (see
``docs/security/THREAT_MODEL.md``, "Out of scope"), so ``POST`` on this route
reports ``NEEDS_CONFIGURATION`` and names the absent settings. It does not mint
a session from a submitted name, it does not hash a password, and there is no
password field anywhere in this package: implementing one would be the custom
cryptography RX-45 forbids, and it would make the missing dependency invisible.

A session is created by :meth:`SessionStore.establish`, which is a SERVER-SIDE
call. The identity-provider callback would call it once a provider exists, and
the test fixtures call it to inject an authenticated principal. No route calls
it, which is why an unauthenticated caller cannot mint a session.

ROTATION IS A REAL ROUTE BECAUSE FIXATION IS A REAL ATTACK.

``POST /v1/auth/session/rotate`` replaces the session identifier while keeping
the principal, and re-sets both cookies. It is the operation an elevation step
performs, and having it as a route means the cookie attributes - HttpOnly,
Secure, SameSite - are exercised by a request rather than asserted about a
helper nobody calls.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from retrace_api.web.config import CSRF_COOKIE_NAME, CSRF_HEADER_NAME
from retrace_api.web.cookies import apply_session_cookies, clear_session_cookies
from retrace_api.web.dependencies import (
    SAFE_METHODS,
    current_session,
    service_state,
)
from retrace_api.web.errors import CsrfRefused, IdentityProviderNotConfigured, SessionRequired
from retrace_api.web.identity import SessionRecord, csrf_tokens_match
from retrace_api.web.schemas import SessionResponse
from retrace_api.web.state import ServiceState

__all__ = ["csrf_protected_session", "router"]

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def csrf_protected_session(
    request: Request,
    session: Annotated[SessionRecord, Depends(current_session)],
) -> SessionRecord:
    """A session plus CSRF enforcement, for mutating routes with no workspace.

    The workspace-scoped routes get this from ``authorised_workspace``. The two
    session routes below have no workspace, so they take this instead - and the
    route-surface test requires every unsafe method to depend on one of the two,
    so a third variant cannot be added without being noticed.
    """
    if request.method.upper() in SAFE_METHODS:
        return session
    header = request.headers.get(CSRF_HEADER_NAME)
    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    if not csrf_tokens_match(header, cookie, session.csrf_token):
        raise CsrfRefused(
            "the CSRF token did not match; the header, the cookie and the server-side "
            "session record must all agree",
            remedy=f"copy the {CSRF_COOKIE_NAME} cookie into the {CSRF_HEADER_NAME} header",
        )
    return session


@router.post("/session", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
def begin_sign_in(state: Annotated[ServiceState, Depends(service_state)]) -> Response:
    """Begin a real sign-in. Refuses while no identity provider is configured (RX-45)."""
    if not state.config.identity_provider_configured:
        raise IdentityProviderNotConfigured(
            "no identity provider is configured, so this build cannot authenticate a "
            "human. No local credential is minted in its place",
            remedy="configure an OIDC issuer and client, then retry",
            missing=state.config.missing_identity_settings(),
        )
    # Reached only once an issuer and client are configured. The authorisation-code
    # exchange is NOT implemented, and reporting NEEDS_CONFIGURATION here is the
    # truthful answer: the settings exist but the flow does not.
    raise IdentityProviderNotConfigured(
        "an identity provider is configured but the authorisation-code exchange is "
        "not implemented in this build",
        remedy="implement the OIDC callback against the configured issuer",
        missing=("oidc-authorisation-code-exchange",),
    )


@router.get("/session", response_model=SessionResponse)
def read_session(
    session: Annotated[SessionRecord, Depends(current_session)],
    state: Annotated[ServiceState, Depends(service_state)],
) -> SessionResponse:
    """Report the session's own principal and verified memberships (RX-45).

    The memberships are resolved from the directory on every call, so a
    revocation is visible here immediately rather than at expiry.
    """
    memberships = state.directory.memberships(session.principal)
    return SessionResponse(
        subject=session.principal.subject,
        display_name=session.principal.display_name,
        expires_at=session.expires_at,
        workspaces=tuple(
            {"workspace_id": m.tenant_id, "role": m.role.value} for m in memberships
        ),
    )


@router.post("/session/rotate", response_model=SessionResponse)
def rotate_session(
    response: Response,
    session: Annotated[SessionRecord, Depends(csrf_protected_session)],
    state: Annotated[ServiceState, Depends(service_state)],
) -> SessionResponse:
    """Replace the session identifier, keeping the principal (RX-45)."""
    rotated = state.sessions.rotate(session.session_id, now=state.now())
    if rotated is None:  # pragma: no cover - resolve() already proved it was live
        raise SessionRequired(
            "the session was no longer live when rotation was attempted",
            remedy="sign in again",
        )
    apply_session_cookies(response, rotated, state.config)
    memberships = state.directory.memberships(rotated.principal)
    return SessionResponse(
        subject=rotated.principal.subject,
        display_name=rotated.principal.display_name,
        expires_at=rotated.expires_at,
        workspaces=tuple(
            {"workspace_id": m.tenant_id, "role": m.role.value} for m in memberships
        ),
    )


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
def end_session(
    response: Response,
    session: Annotated[SessionRecord, Depends(csrf_protected_session)],
    state: Annotated[ServiceState, Depends(service_state)],
) -> Response:
    """Destroy the session server-side and clear both cookies (RX-45)."""
    state.sessions.destroy(session.session_id)
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookies(out, state.config)
    return out

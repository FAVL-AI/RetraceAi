"""The application factory (RX-20, RX-44, RX-45).

WHY THIS MODULE HAD TO EXIST BEFORE ANY OF THE REST WAS TRUE.

Every router in this package, the refusal envelope in
:mod:`retrace_api.web.errors` and the dependency gate in
:mod:`retrace_api.web.dependencies` were written against an application that did
not exist: ``dependencies.service_state`` told a caller to "build it with
create_app()", and no module defined ``create_app``. Three consequences, none of
them visible by reading any one file:

* no router was mounted, so no documented route was reachable;
* no handler was installed for :class:`~retrace_api.web.errors.ApiRefusal`,
  which is a plain ``Exception`` - so every typed refusal would have surfaced as
  an unhandled 500, and the carefully distinguished codes would have been
  indistinguishable in exactly the way their own docstring says is unacceptable;
* no CORS policy was applied at all, so "precise CORS" (RX-45) was neither
  satisfied nor violated - it was absent.

THE REFUSAL HANDLER IS THE ONLY TRANSLATION LAYER.

``ApiRefusal`` carries its own status, code, detail and remedy, so the handler
reads them off the exception rather than deciding anything. One handler for the
base class means a refusal added later cannot ship without an envelope, and that
nothing leaks a stack trace: the body is built from
:meth:`ApiRefusal.envelope` and contains no exception text beyond the detail the
refusal chose to publish.

THE BODY CEILING IS MIDDLEWARE AND NOT A DEPENDENCY.

See :mod:`retrace_api.web.request_limits`. In short: FastAPI parses a form
before it solves dependencies, so a dependency is too late to read a multipart
body - and reading one with ``Request.body()`` is unbounded in any case.

CORS IS ABSENT UNLESS CONFIGURED, AND NEVER A WILDCARD.

``ApiConfig`` already refuses ``"*"`` at construction. The middleware is also
only installed when at least one exact origin is configured: installing it with
an empty allowlist would add the machinery and the preflight handling for a
policy that permits nothing, which reads as "CORS is configured" to anyone
inspecting the app. Methods and headers are enumerated rather than wildcarded,
because ``allow_headers=["*"]`` with credentials is the combination that makes a
double-submit CSRF header pointless to enumerate.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from retrace_api.web.config import (
    CSRF_HEADER_NAME,
    IDEMPOTENCY_HEADER_NAME,
    ApiConfig,
    ConfigurationError,
)
from retrace_api.web.errors import ApiRefusal
from retrace_api.web.request_limits import RequestBodyCeiling
from retrace_api.web.routers import auth as auth_router
from retrace_api.web.routers import contracts as contracts_router
from retrace_api.web.routers import evidence as evidence_router
from retrace_api.web.routers import projects as projects_router
from retrace_api.web.routers import proposals as proposals_router
from retrace_api.web.routers import runs as runs_router
from retrace_api.web.routers import uploads as uploads_router
from retrace_api.web.routers import verification as verification_router
from retrace_api.web.state import ServiceState

__all__ = ["ALLOWED_METHODS", "ALLOWED_REQUEST_HEADERS", "ROUTERS", "create_app"]

#: Methods the browser policy permits. Enumerated, and no ``"*"``: the set is
#: exactly what the routers implement, so adding a method to the policy is a
#: decision rather than a consequence.
ALLOWED_METHODS: tuple[str, ...] = ("GET", "HEAD", "OPTIONS", "POST", "PATCH", "DELETE")

#: Request headers the browser policy permits. ``content-type`` for the body,
#: the CSRF header because the double-submit pattern needs it, the idempotency
#: header because every mutation requires it.
ALLOWED_REQUEST_HEADERS: tuple[str, ...] = (
    "content-type",
    CSRF_HEADER_NAME,
    IDEMPOTENCY_HEADER_NAME,
)

#: Every router, in journey order. A closed list, so a router that exists but is
#: never mounted is visible here rather than only in a route listing.
ROUTERS = (
    auth_router.router,
    projects_router.router,
    uploads_router.router,
    contracts_router.router,
    proposals_router.router,
    runs_router.router,
    verification_router.router,
    evidence_router.router,
)


async def _refusal_envelope(request: Request, exc: Exception) -> JSONResponse:
    """Render an :class:`ApiRefusal` as its own envelope.

    Typed as ``Exception`` because that is the signature Starlette's handler
    registry declares. A non-refusal reaching here would be a registration
    mistake, so it is re-raised rather than rendered as a refusal it is not.
    """
    if not isinstance(exc, ApiRefusal):  # pragma: no cover - registration guard
        raise exc
    return JSONResponse(exc.envelope(), status_code=exc.status_code)


def create_app(state: ServiceState) -> FastAPI:
    """Build the application around an already-wired :class:`ServiceState`.

    ``state`` is passed in rather than constructed here: the membership
    directory decides authorisation and the repository decides durability, and a
    factory that chose either of them by default would make the choice invisible
    at the call site. :func:`retrace_api.web.state.state_from_config` is the one
    place production wiring happens.
    """
    config: ApiConfig = state.config
    wildcard = [origin for origin in config.cors_allowed_origins if "*" in origin]
    if wildcard:  # pragma: no cover - ApiConfig refuses this at construction
        raise ConfigurationError(
            f"CORS origins {wildcard} contain a wildcard; RX-45 requires an exact allowlist"
        )
    app = FastAPI(
        title="RETRACE AI API",
        version="0.0.0",
        summary="Scientific workflow repair and verification. Execution is gated by T2.",
    )
    app.state.retrace = state
    app.add_exception_handler(ApiRefusal, _refusal_envelope)
    # Added before CORS so CORS ends up OUTERMOST: a 413 the ceiling writes
    # itself still passes back out through the CORS layer and carries its
    # headers, which is what lets a browser client read the refusal instead of
    # reporting an opaque network error.
    app.add_middleware(RequestBodyCeiling, limit=config.max_request_body_bytes)
    if config.cors_allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_allowed_origins),
            allow_credentials=True,
            allow_methods=list(ALLOWED_METHODS),
            allow_headers=list(ALLOWED_REQUEST_HEADERS),
        )
    for router in ROUTERS:
        app.include_router(router)
    return app

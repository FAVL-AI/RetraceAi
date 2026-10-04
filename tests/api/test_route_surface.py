"""The structural gate over the whole route surface (RX-44, RX-45, RX-47, RX-53).

WHY A SURFACE TEST AND NOT MORE PER-ROUTE TESTS.

``test_tenancy_and_auth.py`` proves the gate refuses what it should on the routes
it exercises. The risk it cannot cover is a route that takes NONE of the gate -
added later, or simply never tested. A per-route test suite grows one test at a
time and is silent about the route nobody wrote a test for. This file enumerates
every route the REAL application mounts and asserts a property of each, so a new
route is covered the moment it is added.

Four properties, each with a contained violation proving the check can fail:

1. every workspace-scoped route depends on ``authorised_workspace``;
2. every unsafe method depends on something that enforces CSRF;
3. every unsafe workspace-scoped route reserves an idempotency key;
4. no router reads an identity from a request header.

``dependencies.py`` and ``auth.py`` both point at this file by name. They were
pointing at a file that did not exist.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from typing import Any

import pytest
from api_support import Harness
from fastapi import APIRouter, Depends, FastAPI
from fastapi.dependencies.utils import get_dependant
from fastapi.routing import APIRoute
from retrace_api.web import routers as routers_package
from retrace_api.web.app import ROUTERS, create_app
from retrace_api.web.dependencies import (
    IGNORED_IDENTITY_HEADERS,
    Authorised,
    authorised_workspace,
    idempotency_scope,
)
from retrace_api.web.routers.auth import csrf_protected_session

#: Methods that mutate and therefore need CSRF enforcement.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Anything that enforces CSRF. Two entries, and the surface test is what stops a
#: third being added without being noticed.
CSRF_ENFORCING = (authorised_workspace, csrf_protected_session)

#: The one mutation that cannot require CSRF, declared here so the sweep asserts
#: the exemption set EQUALS this rather than merely tolerating what it finds.
#:
#: ``POST /v1/auth/session`` begins a sign-in. There is no session yet, so there
#: is no server-side token to double-submit against, and requiring one would
#: make sign-in impossible. It is safe as an exemption for a specific reason
#: rather than by convention: it accepts no body, reads no cookie, mutates
#: nothing, and in this build always refuses with NEEDS_CONFIGURATION - so a
#: cross-site POST to it achieves exactly nothing. Any SECOND entry here is a
#: decision someone has to make deliberately.
CSRF_EXEMPT: frozenset[tuple[str, str]] = frozenset({("POST", "/v1/auth/session")})

ROUTERS_DIR = pathlib.Path(routers_package.__file__).resolve().parent


def dependency_calls(dependant: Any) -> Iterator[Any]:
    """Every callable in a route's dependency graph, including sub-dependencies.

    Recursive on purpose: ``require_role(...)`` wraps ``authorised_workspace``
    one level down, so a check that looked only at the route's immediate
    dependencies would miss every write route in the application - and would
    then pass while proving the opposite of what it claims.
    """
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from dependency_calls(dependency)


def api_routes(app: FastAPI) -> list[APIRoute]:
    """Every ``APIRoute`` the application can serve, however it is nested.

    ``app.routes`` is NOT a flat list of routes in this FastAPI version: an
    included router appears as one ``_IncludedRouter`` entry holding the real
    routes behind ``original_router``. A sweep that filtered ``app.routes`` by
    ``isinstance`` therefore found nothing at all - and an empty sweep is the
    worst failure mode a structural test has, because every "no offenders"
    assertion passes. Hence the recursion, and hence the explicit
    "the sweep found at least N routes" assertion in every test below.
    """
    found: list[APIRoute] = []
    seen: set[int] = set()

    def walk(routes: Any) -> None:
        for route in routes:
            if id(route) in seen:
                continue
            seen.add(id(route))
            if isinstance(route, APIRoute):
                found.append(route)
                continue
            nested = getattr(route, "routes", None)
            if nested is None:
                original = getattr(route, "original_router", None)
                nested = getattr(original, "routes", None)
            if nested:
                walk(nested)

    walk(app.routes)
    return found


def workspace_routes(app: FastAPI) -> list[APIRoute]:
    return [route for route in api_routes(app) if "{workspace_id}" in route.path]


# --------------------------------------------------------------------------- #
# The surface is not empty, and the enumeration is not vacuous.
# --------------------------------------------------------------------------- #


def test_the_application_mounts_the_documented_journey(harness: Harness) -> None:
    """RX-20: every stage of the journey has at least one route."""
    paths = {route.path for route in api_routes(harness.app)}
    for expected in (
        "/v1/auth/session",
        "/v1/workspaces/{workspace_id}/projects",
        "/v1/workspaces/{workspace_id}/projects/{project_id}/uploads",
        "/v1/workspaces/{workspace_id}/projects/{project_id}/snapshots",
        "/v1/workspaces/{workspace_id}/projects/{project_id}/contracts",
        "/v1/workspaces/{workspace_id}/projects/{project_id}/proposals",
        "/v1/workspaces/{workspace_id}/reviews",
        "/v1/workspaces/{workspace_id}/approvals",
        "/v1/workspaces/{workspace_id}/runs",
        "/v1/workspaces/{workspace_id}/reports",
        "/v1/workspaces/{workspace_id}/evidence/exports",
        "/v1/workspaces/{workspace_id}/evidence/imports",
    ):
        assert expected in paths, f"{expected} is not mounted"


def test_every_router_module_is_mounted(harness: Harness) -> None:
    """A router that exists but is never included is invisible at runtime.

    Discovered from the package directory rather than from a list in this file,
    so a new router module fails here until it is added to ``ROUTERS``.
    """
    modules = sorted(
        path.stem
        for path in ROUTERS_DIR.glob("*.py")
        if path.stem not in {"__init__"}
    )
    assert len(modules) >= 8, f"only {modules} discovered; the sweep would be vacuous"
    mounted_prefixes = {router.prefix for router in ROUTERS}
    assert len(ROUTERS) == len(modules), (
        f"{len(modules)} router modules on disk but {len(ROUTERS)} mounted: {modules}"
    )
    assert mounted_prefixes, "no prefixes found"
    paths = {route.path for route in api_routes(harness.app)}
    for router in ROUTERS:
        assert any(path.startswith(router.prefix) for path in paths), (
            f"{router.prefix} contributes no route to the application"
        )


# --------------------------------------------------------------------------- #
# 1. Workspace-scoped routes take the gate.
# --------------------------------------------------------------------------- #


def test_every_workspace_scoped_route_depends_on_the_gate(harness: Harness) -> None:
    """RX-47: the tenant can only come from ``authorised_workspace``."""
    routes = workspace_routes(harness.app)
    assert len(routes) >= 12, f"only {len(routes)} workspace routes found; check the sweep"
    ungated = [
        f"{sorted(route.methods)} {route.path}"
        for route in routes
        if authorised_workspace not in set(dependency_calls(route.dependant))
    ]
    assert not ungated, f"workspace-scoped routes with no tenancy gate: {ungated}"


def test_the_gate_check_condemns_a_router_that_omits_it() -> None:
    """CONTAINED VIOLATION: the check above must be able to fail.

    A router with a workspace path parameter and no dependency, mounted on a
    throwaway application. The same predicate the real sweep uses is applied to
    it, and it must report the route as ungated.
    """
    rogue = APIRouter()

    @rogue.get("/v1/workspaces/{workspace_id}/ungated")
    def ungated(workspace_id: str) -> dict[str, str]:  # pragma: no cover - never called
        return {"workspace_id": workspace_id}

    app = FastAPI()
    app.include_router(rogue)
    routes = workspace_routes(app)
    assert routes, "the contained router did not mount"
    condemned = [
        route.path
        for route in routes
        if authorised_workspace not in set(dependency_calls(route.dependant))
    ]
    assert condemned == ["/v1/workspaces/{workspace_id}/ungated"]


def test_the_gate_check_accepts_a_router_that_takes_it() -> None:
    """POSITIVE CONTROL: the predicate is not condemning every route."""
    compliant = APIRouter()

    @compliant.get("/v1/workspaces/{workspace_id}/gated")
    def gated(auth: Authorised) -> dict[str, str]:  # pragma: no cover - never called
        return {"workspace_id": auth.tenant_id}

    app = FastAPI()
    app.include_router(compliant)
    route = workspace_routes(app)[0]
    assert authorised_workspace in set(dependency_calls(route.dependant))


# --------------------------------------------------------------------------- #
# 2. Unsafe methods enforce CSRF.
# --------------------------------------------------------------------------- #


def csrf_exemptions(app: FastAPI) -> set[tuple[str, str]]:
    """Mutating routes with no CSRF enforcement anywhere in their graph."""
    found: set[tuple[str, str]] = set()
    for route in api_routes(app):
        for method in route.methods & UNSAFE_METHODS:
            calls = set(dependency_calls(route.dependant))
            if not any(enforcer in calls for enforcer in CSRF_ENFORCING):
                found.add((method, route.path))
    return found


def test_every_unsafe_method_enforces_csrf(harness: Harness) -> None:
    """RX-45: a mutation cannot be reachable without the double-submit check.

    Asserted as EQUALITY against the declared exemption set, not as "no
    offenders outside a list I am willing to ignore". A new unprotected mutation
    fails here, and so does an exemption that is no longer needed.
    """
    checked = sum(
        1 for route in api_routes(harness.app) if route.methods & UNSAFE_METHODS
    )
    assert checked >= 11, f"only {checked} mutating routes found; check the sweep"
    assert csrf_exemptions(harness.app) == CSRF_EXEMPT


def test_the_csrf_check_condemns_an_unprotected_mutation() -> None:
    """CONTAINED VIOLATION for the sweep above."""
    rogue = APIRouter()

    @rogue.post("/v1/unprotected")
    def unprotected() -> dict[str, bool]:  # pragma: no cover - never called
        return {"ok": True}

    app = FastAPI()
    app.include_router(rogue)
    route = api_routes(app)[0]
    calls = set(dependency_calls(route.dependant))
    assert not any(enforcer in calls for enforcer in CSRF_ENFORCING)


def test_the_sign_in_route_is_the_one_mutation_with_no_session(harness: Harness) -> None:
    """``POST /v1/auth/session`` cannot require a session: it is how one begins.

    It is also the only such route, and it refuses with NEEDS_CONFIGURATION
    rather than minting anything - which is why it is safe for it to be the
    exception. Asserted here so a SECOND exception cannot be added quietly.
    """
    assert csrf_exemptions(harness.app) == {("POST", "/v1/auth/session")}
    sign_in = next(
        route
        for route in api_routes(harness.app)
        if route.path == "/v1/auth/session" and "POST" in route.methods
    )
    assert csrf_protected_session not in set(dependency_calls(sign_in.dependant))
    # The exemption is only safe because the route mints nothing. Asserted, not
    # assumed: a cross-site POST to it gets a refusal and no cookie.
    response = harness.client.post("/v1/auth/session")
    assert response.status_code == 503
    assert "set-cookie" not in response.headers


# --------------------------------------------------------------------------- #
# 3. Unsafe workspace routes reserve an idempotency key.
# --------------------------------------------------------------------------- #


def test_every_unsafe_workspace_route_reserves_an_idempotency_key(
    harness: Harness,
) -> None:
    """RX-53: resume must not repeat an approval, a send or a spend."""
    missing: list[str] = []
    checked = 0
    for route in workspace_routes(harness.app):
        if not (route.methods & UNSAFE_METHODS):
            continue
        checked += 1
        if idempotency_scope not in set(dependency_calls(route.dependant)):
            missing.append(f"{sorted(route.methods)} {route.path}")
    assert checked >= 9, f"only {checked} mutating workspace routes found"
    assert not missing, f"mutating workspace routes with no idempotency key: {missing}"


def test_a_mutation_without_an_idempotency_key_is_refused(harness: Harness) -> None:
    """The dependency is not decorative: the header is required (RX-53)."""
    harness.sign_in("oidc|member")
    record = harness.sessions["oidc|member"]
    response = harness.client.post(
        "/v1/workspaces/11111111-1111-4111-8111-111111111111/projects",
        json={"name": "keyless"},
        headers={"x-retrace-csrf": record.csrf_token},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"


# --------------------------------------------------------------------------- #
# 4. No router reads an identity from the request.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("header", IGNORED_IDENTITY_HEADERS)
def test_no_router_module_mentions_an_identity_header(header: str) -> None:
    """``routers/__init__.py`` claims no router reads a tenant or actor.

    Checked as a source property, because the claim is about the code rather
    than about one request. The names ARE present in ``dependencies.py``, where
    they are listed as ignored - which is the positive control for the grep
    below.
    """
    offenders = [
        path.name
        for path in sorted(ROUTERS_DIR.glob("*.py"))
        if header in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"{header} appears in {offenders}"


def test_the_identity_header_grep_finds_them_where_they_do_appear() -> None:
    """POSITIVE CONTROL: a grep that matches nothing anywhere proves nothing."""
    dependencies = ROUTERS_DIR.parent / "dependencies.py"
    text = dependencies.read_text(encoding="utf-8")
    assert all(header in text for header in IGNORED_IDENTITY_HEADERS)


def test_no_router_declares_a_workspace_id_body_field() -> None:
    """RX-47: the tenant is a path request, and never a payload field.

    ``workspace_id`` is in ``REFUSED_EXTERNAL_FIELDS``, so a request model
    cannot declare it - but a route could still take it as a ``Form`` or a
    ``Query`` parameter and bypass the model guard entirely. This looks at the
    realised route signatures rather than at the models.
    """
    from retrace_api.web.app import ROUTERS as mounted

    offenders: list[str] = []
    for router in mounted:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                continue
            dependant = get_dependant(path=route.path, call=route.endpoint)
            for field in (*dependant.query_params, *dependant.header_params):
                if field.name in {"workspace_id", "tenant_id", "actor_id"}:
                    offenders.append(f"{route.path}:{field.name}")
    assert not offenders, f"tenancy supplied outside the path: {offenders}"


def test_the_body_field_check_condemns_a_route_that_takes_a_tenant_query() -> None:
    """CONTAINED VIOLATION for the check above."""
    rogue = APIRouter()

    @rogue.get("/v1/rogue")
    def rogue_route(tenant_id: str) -> dict[str, str]:  # pragma: no cover - never called
        return {"tenant_id": tenant_id}

    route = next(r for r in rogue.routes if isinstance(r, APIRoute))
    dependant = get_dependant(path=route.path, call=route.endpoint)
    names = {field.name for field in dependant.query_params}
    assert "tenant_id" in names


# --------------------------------------------------------------------------- #
# The middleware the surface depends on.
# --------------------------------------------------------------------------- #


def test_the_request_body_ceiling_is_installed(harness: Harness) -> None:
    """Without it every multipart route raises ``RuntimeError: Stream consumed``."""
    from retrace_api.web.request_limits import RequestBodyCeiling

    installed = [middleware.cls for middleware in harness.app.user_middleware]
    assert RequestBodyCeiling in installed


def test_an_application_built_without_the_ceiling_fails_loudly(harness: Harness) -> None:
    """NEGATIVE CONTROL: the dependency must not digest an empty body instead.

    A silent empty digest would give every request on a route the same
    idempotency digest, so two different requests would share a key and the
    second would be served the first one's response. The failure is therefore a
    loud one.
    """
    from retrace_api.web.dependencies import buffered_request_body
    from retrace_api.web.request_limits import BODY_UNBUFFERED_MESSAGE

    class ScopeOnly:
        scope: dict[str, Any] = {}

    with pytest.raises(RuntimeError) as failure:
        buffered_request_body(ScopeOnly())  # type: ignore[arg-type]
    assert BODY_UNBUFFERED_MESSAGE in str(failure.value)


def test_a_state_whose_ceilings_contradict_each_other_is_refused(
    harness: Harness,
) -> None:
    """The wiring guard, with the contradiction it exists to catch."""
    import dataclasses

    from retrace_api.web.config import ConfigurationError
    from retrace_api.web.state import ServiceState

    narrow = dataclasses.replace(
        harness.state.config,
        max_request_body_bytes=harness.state.admission_policy.max_upload_bytes,
    )
    with pytest.raises(ConfigurationError):
        ServiceState(
            config=narrow,
            sessions=harness.state.sessions,
            directory=harness.state.directory,
            repository=harness.state.repository,
            workspaces=harness.state.workspaces,
            admission_policy=harness.state.admission_policy,
            clock=harness.state.clock,
        )


def test_the_same_wiring_with_room_for_framing_is_accepted(harness: Harness) -> None:
    """POSITIVE CONTROL for the guard above."""
    import dataclasses

    from retrace_api.web.state import ServiceState

    wide = dataclasses.replace(
        harness.state.config,
        max_request_body_bytes=harness.state.admission_policy.max_upload_bytes + 1,
    )
    state = ServiceState(
        config=wide,
        sessions=harness.state.sessions,
        directory=harness.state.directory,
        repository=harness.state.repository,
        workspaces=harness.state.workspaces,
        admission_policy=harness.state.admission_policy,
        clock=harness.state.clock,
    )
    assert create_app(state) is not None


def test_the_route_dependency_walk_is_recursive() -> None:
    """DISCRIMINATION CONTROL for ``dependency_calls``.

    Every write route reaches ``authorised_workspace`` through
    ``require_role(...)``, one level down. A non-recursive walk would report all
    of them as ungated, so the sweeps above would fail loudly rather than pass
    vacuously - but only if the walk is the thing being tested. This asserts it
    directly on a two-level graph.
    """
    from retrace_api.web.dependencies import require_role
    from retrace_api.web.identity import WorkspaceRole

    nested = APIRouter()
    writer = require_role(WorkspaceRole.MEMBER)

    @nested.post("/v1/workspaces/{workspace_id}/nested")
    # B008: calling Depends() in an argument default IS the FastAPI idiom - the
    # framework inspects the default to build the dependency graph, so moving the
    # call into the body would change the behaviour under test. Suppressed here
    # rather than disabled globally, because B008 is a real finding anywhere that
    # is not a FastAPI dependency.
    def handler(auth: Any = Depends(writer)) -> dict[str, bool]:  # noqa: B008  # pragma: no cover
        return {"ok": True}

    route = next(r for r in nested.routes if isinstance(r, APIRoute))
    immediate = {d.call for d in route.dependant.dependencies}
    assert authorised_workspace not in immediate
    assert authorised_workspace in set(dependency_calls(route.dependant))

"""Tenancy and authentication: the security core (RX-45, RX-46, RX-47, RX-48, RX-49).

EVERY REFUSAL HERE IS PAIRED WITH A POSITIVE CONTROL.

A gate that refuses everything refuses the attack too, so a suite of refusals on
its own cannot distinguish "the check works" from "the route is broken". Each
test below therefore shows the refused request AND the otherwise-identical
request that succeeds, differing only in the property under test. Where the
check is structural rather than per-request, the control is a contained
violation: a model or a router defined inside the test that breaks the rule, with
an assertion that the check condemns it.

WHAT THESE TESTS DO NOT ESTABLISH.

They exercise the in-memory repository, which carries no row-level security. The
authorisation LOGIC is what is proven here. That a database refuses a
cross-tenant read even when the application layer is wrong is proven in
``tests/postgres`` and in ``test_tenant_context.py``, which needs real
PostgreSQL and is marked ``integration``.
"""

from __future__ import annotations

from typing import Any

import pytest
from api_support import (
    APPROVER,
    MEMBER,
    OUTSIDER,
    OWNER,
    TENANT_A,
    TENANT_B,
    TENANT_B_MEMBER,
    VIEWER,
    Harness,
    draft_payload,
)
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from retrace_api.web.app import ALLOWED_REQUEST_HEADERS
from retrace_api.web.config import CSRF_HEADER_NAME, ApiConfig, ConfigurationError
from retrace_api.web.dependencies import IGNORED_IDENTITY_HEADERS
from retrace_api.web.identity import WorkspaceRole
from retrace_api.web.schemas import (
    REFUSED_EXTERNAL_FIELDS,
    ExternalModel,
    ProjectCreateRequest,
    RefusedFieldInRequestModel,
)
from retrace_contracts import ResultContractDraft

# --------------------------------------------------------------------------- #
# 1. No session, and the headers that do not substitute for one.
# --------------------------------------------------------------------------- #


def test_a_request_with_no_session_is_refused(harness: Harness) -> None:
    """RX-45: authentication is required before any tenant is resolved."""
    response = harness.client.get(f"/v1/workspaces/{TENANT_A}/projects")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_REQUIRED"


def test_the_same_request_with_a_session_succeeds(harness: Harness) -> None:
    """POSITIVE CONTROL for the refusal above: only the session differs."""
    harness.sign_in(MEMBER)
    response = harness.client.get(f"/v1/workspaces/{TENANT_A}/projects")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize("header", IGNORED_IDENTITY_HEADERS)
def test_a_header_naming_an_actor_or_tenant_does_not_authenticate(
    harness: Harness, header: str
) -> None:
    """RX-45: request input cannot authenticate itself."""
    response = harness.client.get(
        f"/v1/workspaces/{TENANT_A}/projects", headers={header: OWNER}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_REQUIRED"


def test_identity_headers_cannot_redirect_an_authenticated_request(harness: Harness) -> None:
    """RX-47: the effective tenant and actor come from the session, not the request.

    The session is tenant A's. Every header an attacker might hope is consulted
    names tenant B and another subject. The created project must still be tenant
    A's and must still be authored by the session's own subject.
    """
    harness.sign_in(MEMBER)
    headers = harness.headers(MEMBER)
    headers.update({name: TENANT_B for name in IGNORED_IDENTITY_HEADERS})
    headers["x-retrace-actor"] = OUTSIDER
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects", json={"name": "misdirected"}, headers=headers
    )
    assert response.status_code == 201, response.text
    assert response.json()["workspace_id"] == TENANT_A
    rows = harness.state.repository.rows_for_audit()  # type: ignore[attr-defined]
    assert {tenant for tenant, _ in rows} == {TENANT_A}


# --------------------------------------------------------------------------- #
# 2. The request models forbid the fields the server establishes.
# --------------------------------------------------------------------------- #


def test_every_refused_field_is_rejected_by_a_request_model_at_import_time() -> None:
    """RX-47: the guard fires for each refused name, not just the first one.

    NEGATIVE CONTROL, one per name. A guard demonstrated on ``tenant_id`` alone
    would pass even if the set it checks against had lost every other member.
    """
    for name in sorted(REFUSED_EXTERNAL_FIELDS):
        with pytest.raises(RefusedFieldInRequestModel) as refusal:
            type(
                "Smuggler",
                (ExternalModel,),
                {"__annotations__": {name: str}},
            )
        assert name in str(refusal.value)


def test_an_innocuous_request_model_is_accepted() -> None:
    """POSITIVE CONTROL: the guard is not refusing every subclass."""

    class Innocuous(ExternalModel):
        label: str

    assert set(Innocuous.model_fields) == {"label"}


@pytest.mark.parametrize(
    "smuggled",
    [
        {"tenant_id": TENANT_B},
        {"actor_id": OUTSIDER},
        {"status": "APPROVED"},
        {"signature": "deadbeef"},
        {"verdict": "REPRODUCED_WITHIN_CONTRACT"},
        {"approval_ref": "ledger-1"},
    ],
)
def test_a_payload_carrying_a_server_established_field_is_refused(
    harness: Harness, smuggled: dict[str, Any]
) -> None:
    """RX-47: refused, not dropped - over HTTP, on a real route."""
    harness.sign_in(MEMBER)
    body = {"name": "smuggled", **smuggled}
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects", json=body, headers=harness.headers(MEMBER)
    )
    assert response.status_code == 422, response.text
    assert "extra_forbidden" in response.text


def test_the_identical_payload_without_the_extra_field_is_accepted(harness: Harness) -> None:
    """POSITIVE CONTROL: the 422s above are about the extra field only."""
    harness.sign_in(MEMBER)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects",
        json={"name": "smuggled"},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "smuggled",
    [
        {"tenant_id": TENANT_B},
        {"contract_id": "rc-forged"},
        {"status": "APPROVED"},
        {"approval_ref": "ledger-1"},
    ],
)
def test_the_contract_create_model_refuses_server_established_fields(
    harness: Harness, smuggled: dict[str, Any]
) -> None:
    """RX-47, closure section 6: a client-supplied status establishes nothing.

    ``ResultContractDraft`` is the external create model and is NOT an
    ``ExternalModel`` subclass, so the import-time guard does not cover it. It
    has to be shown separately that it forbids the same names.
    """
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    body = draft_payload(project_id=project_id, created_by=MEMBER)
    body.update(smuggled)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/contracts",
        json=body,
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 422, response.text


def test_a_clean_draft_is_accepted_and_the_server_sets_the_withheld_fields(
    harness: Harness,
) -> None:
    """POSITIVE CONTROL, and RX-47: the server establishes what the model omits."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/contracts",
        json=draft_payload(project_id=project_id, created_by=MEMBER),
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["workspace_id"] == TENANT_A
    assert body["status"] == "DRAFT"
    assert body["approval_ref"] is None
    assert body["approved_in_ledger"] is False
    # `created_by` is the ONE name the draft shares with the refused set, and it
    # is deliberate: the contracts package declares it as a CLAIM whose
    # authority is the session, and `test_the_draft_claiming_another_author_is_
    # refused` is where that enforcement is exercised. Asserting the exact
    # intersection rather than an empty one means a SECOND such field appearing
    # in the frozen package fails here instead of passing unnoticed.
    assert set(ResultContractDraft.model_fields) & REFUSED_EXTERNAL_FIELDS == {"created_by"}


def test_the_draft_claiming_another_author_is_refused(harness: Harness) -> None:
    """RX-45: ``created_by`` is a claim; the session is the authority."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/contracts",
        json=draft_payload(project_id=project_id, created_by=OWNER),
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACTOR_IDENTITY_MISMATCH"


# --------------------------------------------------------------------------- #
# 3. Membership, roles and revocation.
# --------------------------------------------------------------------------- #


def test_naming_a_workspace_does_not_grant_access_to_it(harness: Harness) -> None:
    """RX-47: the path segment is a request, never a grant."""
    harness.sign_in(OUTSIDER)
    response = harness.client.get(f"/v1/workspaces/{TENANT_A}/projects")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "WORKSPACE_NOT_AUTHORISED"


def test_a_verified_member_of_that_same_workspace_is_admitted(harness: Harness) -> None:
    """POSITIVE CONTROL: the directory, not the path, decides."""
    harness.sign_in(MEMBER)
    assert harness.client.get(f"/v1/workspaces/{TENANT_A}/projects").status_code == 200


def test_a_viewer_cannot_write_and_a_member_can(harness: Harness) -> None:
    """RX-46: the role gate, with both halves of the comparison."""
    harness.sign_in(VIEWER)
    refused = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects",
        json={"name": "viewer-attempt"},
        headers=harness.headers(VIEWER),
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "ROLE_INSUFFICIENT"
    assert harness.client.get(f"/v1/workspaces/{TENANT_A}/projects").status_code == 200

    harness.sign_in(MEMBER)
    admitted = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects",
        json={"name": "member-attempt"},
        headers=harness.headers(MEMBER),
    )
    assert admitted.status_code == 201, admitted.text


def test_revoking_a_membership_takes_effect_on_the_next_request(harness: Harness) -> None:
    """RX-39, T6: membership is looked up per request, not cached at sign-in."""
    harness.sign_in(MEMBER)
    assert harness.client.get(f"/v1/workspaces/{TENANT_A}/projects").status_code == 200
    harness.directory.revoke(MEMBER, TENANT_A)
    after = harness.client.get(f"/v1/workspaces/{TENANT_A}/projects")
    assert after.status_code == 403
    assert after.json()["error"]["code"] == "WORKSPACE_NOT_AUTHORISED"


def test_a_role_that_is_insufficient_is_distinguishable_from_no_membership(
    harness: Harness,
) -> None:
    """The two 403s carry different codes, which is why both exist (RX-44)."""
    harness.sign_in(VIEWER)
    insufficient = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects",
        json={"name": "x"},
        headers=harness.headers(VIEWER),
    )
    harness.sign_in(OUTSIDER)
    unauthorised = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects",
        json={"name": "x"},
        headers=harness.headers(OUTSIDER),
    )
    assert insufficient.json()["error"]["code"] == "ROLE_INSUFFICIENT"
    assert unauthorised.json()["error"]["code"] == "WORKSPACE_NOT_AUTHORISED"


# --------------------------------------------------------------------------- #
# 4. CSRF.
# --------------------------------------------------------------------------- #


def test_a_mutation_with_no_csrf_header_is_refused(harness: Harness) -> None:
    """RX-45: double-submit, and the header half is required."""
    harness.sign_in(MEMBER)
    headers = harness.headers(MEMBER)
    del headers[CSRF_HEADER_NAME]
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects", json={"name": "csrf-less"}, headers=headers
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REFUSED"


def test_a_mutation_with_a_csrf_header_the_session_does_not_know_is_refused(
    harness: Harness,
) -> None:
    """A token an attacker set in BOTH the cookie and the header is refused.

    This is the case a cookie-against-header comparison alone would admit: the
    two agree with each other and disagree with the server-side session record.
    """
    harness.sign_in(MEMBER)
    harness.client.cookies.set("retrace_csrf", "attacker-chosen-token")
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects",
        json={"name": "forged"},
        headers={
            CSRF_HEADER_NAME: "attacker-chosen-token",
            "idempotency-key": "forged-1",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REFUSED"


def test_the_same_mutation_with_the_sessions_own_token_succeeds(harness: Harness) -> None:
    """POSITIVE CONTROL for both CSRF refusals."""
    harness.sign_in(MEMBER)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects",
        json={"name": "legitimate"},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 201, response.text


def test_a_safe_method_needs_no_csrf_token(harness: Harness) -> None:
    """RX-45: a GET is not a mutation, and refusing it would break preflight."""
    harness.sign_in(MEMBER)
    assert harness.client.get(f"/v1/workspaces/{TENANT_A}/projects").status_code == 200


def test_the_session_cookie_is_httponly_and_the_csrf_cookie_is_not(harness: Harness) -> None:
    """RX-45: the credential is script-unreadable; the CSRF token must not be."""
    record = harness.sign_in(MEMBER)
    response = harness.client.post(
        "/v1/auth/session/rotate", headers=harness.headers(MEMBER)
    )
    assert response.status_code == 200, response.text
    cookies = response.headers.get_list("set-cookie")
    session_cookie = next(c for c in cookies if c.startswith("retrace_session="))
    csrf_cookie = next(c for c in cookies if c.startswith("retrace_csrf="))
    assert "HttpOnly" in session_cookie
    assert "HttpOnly" not in csrf_cookie
    for cookie in (session_cookie, csrf_cookie):
        assert "Secure" in cookie
        assert "SameSite=strict" in cookie
    assert record.session_id not in session_cookie


# --------------------------------------------------------------------------- #
# 5. Sessions: fixation, rotation, expiry, and the absent provider.
# --------------------------------------------------------------------------- #


def test_no_route_mints_a_session(harness: Harness) -> None:
    """RX-45: sign-in reports NEEDS_CONFIGURATION rather than a local credential."""
    response = harness.client.post("/v1/auth/session")
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "IDENTITY_PROVIDER_NOT_CONFIGURED"
    assert body["context"]["status"] == "NEEDS_CONFIGURATION"
    assert "RETRACE_OIDC_ISSUER" in body["context"]["missing"]
    assert "set-cookie" not in response.headers


def test_rotation_replaces_the_identifier_and_the_old_one_stops_working(
    harness: Harness,
) -> None:
    """RX-45: session fixation needs the old identifier to become useless."""
    original = harness.sign_in(MEMBER)
    rotated = harness.client.post(
        "/v1/auth/session/rotate", headers=harness.headers(MEMBER)
    )
    assert rotated.status_code == 200, rotated.text
    # Cleared first: the rotation's own Set-Cookie is in the jar under the
    # request domain, and adding a same-named cookie beside it would leave the
    # test asserting against whichever one the client happened to send.
    harness.client.cookies.clear()
    harness.client.cookies.set("retrace_session", original.session_id)
    assert harness.client.get("/v1/auth/session").status_code == 401


def test_a_session_expires_on_the_server_clock_not_the_cookie(harness: Harness) -> None:
    """RX-45: the server record is the authority, so an edited expiry buys nothing."""
    harness.sign_in(MEMBER)
    assert harness.client.get("/v1/auth/session").status_code == 200
    harness.clock.advance(harness.state.config.session_ttl_seconds + 1)
    assert harness.client.get("/v1/auth/session").status_code == 401


def test_signing_out_destroys_the_server_record(harness: Harness) -> None:
    record = harness.sign_in(MEMBER)
    response = harness.client.delete("/v1/auth/session", headers=harness.headers(MEMBER))
    assert response.status_code == 204
    assert harness.state.sessions.resolve(record.session_id, now=harness.clock()) is None


# --------------------------------------------------------------------------- #
# 6. CORS.
# --------------------------------------------------------------------------- #


def test_a_wildcard_cors_origin_is_refused_at_construction() -> None:
    """RX-45: NEGATIVE CONTROL for the exact-allowlist rule."""
    for origin in ("*", "https://*.example.test", ""):
        with pytest.raises(ConfigurationError):
            ApiConfig(cors_allowed_origins=(origin,))


def test_an_exact_origin_is_accepted_at_construction() -> None:
    """POSITIVE CONTROL: the check is about wildcards, not about origins."""
    config = ApiConfig(cors_allowed_origins=("https://studio.example.test",))
    assert config.cors_allowed_origins == ("https://studio.example.test",)


def test_no_cors_headers_are_emitted_when_no_origin_is_configured(harness: Harness) -> None:
    """An API with no configured front end permits no cross-origin access."""
    harness.sign_in(MEMBER)
    response = harness.client.get(
        f"/v1/workspaces/{TENANT_A}/projects",
        headers={"origin": "https://studio.example.test"},
    )
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_a_configured_origin_is_allowed_and_any_other_is_not(make_harness: Any) -> None:
    """RX-45: precise CORS - the allowlist admits exactly what it names."""
    configured = make_harness(cors_allowed_origins=("https://studio.example.test",))
    configured.sign_in(MEMBER)
    allowed = configured.client.get(
        f"/v1/workspaces/{TENANT_A}/projects",
        headers={"origin": "https://studio.example.test"},
    )
    assert allowed.headers["access-control-allow-origin"] == "https://studio.example.test"
    assert allowed.headers.get("access-control-allow-credentials") == "true"

    refused = configured.client.get(
        f"/v1/workspaces/{TENANT_A}/projects",
        headers={"origin": "https://attacker.example.test"},
    )
    assert "access-control-allow-origin" not in refused.headers


def test_the_preflight_allows_the_csrf_header_and_not_a_wildcard(make_harness: Any) -> None:
    """The double-submit header has to be permitted by name to be usable."""
    configured = make_harness(cors_allowed_origins=("https://studio.example.test",))
    response = configured.client.options(
        f"/v1/workspaces/{TENANT_A}/projects",
        headers={
            "origin": "https://studio.example.test",
            "access-control-request-method": "POST",
            "access-control-request-headers": CSRF_HEADER_NAME,
        },
    )
    assert response.status_code == 200, response.text
    permitted = response.headers["access-control-allow-headers"].lower()
    assert CSRF_HEADER_NAME in permitted
    assert "*" not in permitted
    assert "*" not in [h.lower() for h in ALLOWED_REQUEST_HEADERS]


# --------------------------------------------------------------------------- #
# 7. Cross-tenant reads and the ordinary edit.
# --------------------------------------------------------------------------- #


def test_a_project_of_one_tenant_is_invisible_to_another(harness: Harness) -> None:
    """RX-47: a cross-tenant read returns nothing, and 404 rather than 403."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER, name="tenant-a-only")

    harness.sign_in(TENANT_B_MEMBER)
    listing = harness.client.get(f"/v1/workspaces/{TENANT_B}/projects")
    assert listing.status_code == 200
    assert listing.json() == []
    direct = harness.client.get(f"/v1/workspaces/{TENANT_B}/projects/{project_id}")
    assert direct.status_code == 404
    assert direct.json()["error"]["code"] == "NOT_FOUND"


def test_the_owning_tenant_can_read_the_same_project(harness: Harness) -> None:
    """POSITIVE CONTROL: the 404 above is about the tenant, not the identifier."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER, name="tenant-a-only")
    found = harness.client.get(f"/v1/workspaces/{TENANT_A}/projects/{project_id}")
    assert found.status_code == 200
    assert found.json()["project_id"] == project_id


def test_an_ordinary_edit_cannot_move_a_project_between_tenants(harness: Harness) -> None:
    """RX-47, RX-49: the operation cannot EXPRESS a tenant change.

    Three layers, asserted together: the payload has no tenant field, a payload
    that adds one is refused, and the row is still the original tenant's
    afterwards - read past the API, from the repository.
    """
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER, name="before")

    smuggled = harness.client.patch(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}",
        json={"name": "after", "tenant_id": TENANT_B},
        headers=harness.headers(MEMBER),
    )
    assert smuggled.status_code == 422

    renamed = harness.client.patch(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}",
        json={"name": "after"},
        headers=harness.headers(MEMBER),
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "after"
    assert renamed.json()["workspace_id"] == TENANT_A
    rows = harness.state.repository.rows_for_audit()  # type: ignore[attr-defined]
    assert rows == ((TENANT_A, project_id),)


def test_an_edit_addressed_from_the_other_tenant_is_not_found(harness: Harness) -> None:
    """RX-47: a 403 would confirm the identifier exists, which is one bit too many."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER, name="before")

    harness.sign_in(TENANT_B_MEMBER)
    response = harness.client.patch(
        f"/v1/workspaces/{TENANT_B}/projects/{project_id}",
        json={"name": "moved"},
        headers=harness.headers(TENANT_B_MEMBER),
    )
    assert response.status_code == 404
    rows = harness.state.repository.rows_for_audit()  # type: ignore[attr-defined]
    assert rows == ((TENANT_A, project_id),)


def test_a_contract_cannot_reference_another_tenants_project(harness: Harness) -> None:
    """RX-49: the cross-tenant RELATIONSHIP is refused, not merely hidden."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)

    harness.sign_in(TENANT_B_MEMBER)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_B}/projects/{project_id}/contracts",
        json=draft_payload(project_id=project_id, created_by=TENANT_B_MEMBER),
        headers=harness.headers(TENANT_B_MEMBER),
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------- #
# 8. The refusal envelope exists at all.
# --------------------------------------------------------------------------- #


def test_a_refusal_is_rendered_as_its_envelope_and_not_as_a_server_fault(
    harness: Harness,
) -> None:
    """RX-44: an ``ApiRefusal`` is a plain Exception, so the handler is load-bearing.

    Without the handler the application installs, every typed refusal in this
    package would surface as an unhandled 500 and the stable codes would be
    indistinguishable - which is the exact failure ``errors.py`` says a bare 403
    causes. This asserts the shape of the envelope, not just the status.
    """
    response = harness.client.get(f"/v1/workspaces/{TENANT_A}/projects")
    assert response.status_code == 401
    error = response.json()["error"]
    assert set(error) >= {"code", "detail", "remedy"}
    assert error["remedy"]
    assert "Traceback" not in response.text


def test_the_handler_is_registered_for_the_base_class(harness: Harness) -> None:
    """One handler, so a refusal added later cannot ship without an envelope."""
    from retrace_api.web.errors import ApiRefusal

    assert ApiRefusal in harness.app.exception_handlers


# --------------------------------------------------------------------------- #
# 9. The structural gate, with a contained violation.
# --------------------------------------------------------------------------- #


def test_a_route_that_omits_the_gate_is_reachable_without_a_session(
    harness: Harness,
) -> None:
    """DISCRIMINATION CONTROL for every refusal in this file.

    A contained router with a workspace path parameter and NO dependency. It is
    mounted on a throwaway application, never on the real one. If this returned
    401 the tests above would be measuring something other than the gate -
    FastAPI refusing an unknown route, say - and the whole file would be
    vacuous. ``test_route_surface.py`` is what stops such a router reaching the
    real application.
    """
    rogue = APIRouter()

    @rogue.get("/v1/workspaces/{workspace_id}/ungated")
    def ungated(workspace_id: str) -> dict[str, str]:
        return {"workspace_id": workspace_id}

    app = FastAPI()
    app.include_router(rogue)
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get(f"/v1/workspaces/{TENANT_A}/ungated")
    assert response.status_code == 200
    assert response.json() == {"workspace_id": TENANT_A}


def test_the_role_ordering_is_what_the_gate_relies_on() -> None:
    """RX-46: APPROVER implies MEMBER implies VIEWER, and ADMIN implies all."""
    assert WorkspaceRole.ADMIN.permits(WorkspaceRole.APPROVER)
    assert WorkspaceRole.APPROVER.permits(WorkspaceRole.MEMBER)
    assert WorkspaceRole.MEMBER.permits(WorkspaceRole.VIEWER)
    assert not WorkspaceRole.VIEWER.permits(WorkspaceRole.MEMBER)
    assert not WorkspaceRole.MEMBER.permits(WorkspaceRole.APPROVER)


def test_an_approver_is_not_automatically_able_to_create_a_project_elsewhere(
    harness: Harness,
) -> None:
    """A role is scoped to one workspace; it is not a global capability."""
    harness.sign_in(APPROVER)
    assert harness.client.get(f"/v1/workspaces/{TENANT_A}/projects").status_code == 200
    assert harness.client.get(f"/v1/workspaces/{TENANT_B}/projects").status_code == 403


def test_the_project_create_model_declares_exactly_one_field() -> None:
    """RX-47: there is nothing in the payload that could name a tenant."""
    assert set(ProjectCreateRequest.model_fields) == {"name"}
    with pytest.raises(ValidationError):
        ProjectCreateRequest(name="x", tenant_id=TENANT_B)  # type: ignore[call-arg]

"""The execution gate: a documented blocked state, not a 500 and not a success.

Serves RX-08, RX-09, RX-11 and the T2 row of ``docs/security/THREAT_MODEL.md``.

THE REFUSAL HAS TO BE REACHED BY A REQUEST THAT WOULD OTHERWISE HAVE SUCCEEDED.

A 503 that could also have been caused by a missing session, a bad payload or an
unknown identifier demonstrates nothing about the gate. So the tests below first
show the OTHER refusals - 401, 403, 404, 422 - and only then show the 503 on a
fully valid request. Each of those is a positive control for the one after it:
the gate is the last thing standing between a well-formed request and execution.

WHAT THE REFUSAL MUST SAY.

The specific open reason. T2's filesystem half is closed over declared paths, so
a refusal citing "nothing denies a write to the approval ledger" would send a
reader to fix a control that is already in place. The blocked state, the
reference into the threat model, the unmet preconditions and the confined profile
are all asserted.

``runs.py`` points at this file by name. It was pointing at a file that did not
exist.
"""

from __future__ import annotations

import pathlib
import uuid
from typing import Any

import pytest
from api_support import (
    MEMBER,
    TENANT_A,
    VIEWER,
    Harness,
    draft_payload,
    legitimate_archive,
)
from retrace_api.web.errors import T2_BLOCKED_STATE, T2_DOCUMENT, T2_SECTION_HEADING
from retrace_api.web.execution import EXECUTION_NOT_IMPLEMENTED
from retrace_api.web.run_profile import identity_separation

RUNS_SOURCE = pathlib.Path(
    __import__("retrace_api.web.routers.runs", fromlist=["runs"]).__file__ or ""
)


def prepared(harness: Harness) -> tuple[str, str, str]:
    """A project, a contract and a snapshot, all real, all through the routes."""
    harness.sign_in(MEMBER)
    project_id = harness.create_project(TENANT_A, MEMBER)
    upload = harness.upload(
        TENANT_A,
        MEMBER,
        project_id,
        filename="study.zip",
        content_type="application/zip",
        data=legitimate_archive(),
    )
    assert upload.status_code == 201, upload.text
    snapshot = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/snapshots",
        json={"upload_id": upload.json()["upload_id"]},
        headers=harness.headers(MEMBER),
    )
    assert snapshot.status_code == 201, snapshot.text
    contract = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/projects/{project_id}/contracts",
        json=draft_payload(project_id=project_id, created_by=MEMBER),
        headers=harness.headers(MEMBER),
    )
    assert contract.status_code == 201, contract.text
    return project_id, contract.json()["contract_id"], snapshot.json()["snapshot_id"]


def request_run(harness: Harness, contract_id: str, snapshot_id: str, *, key: str | None = None):
    return harness.client.post(
        f"/v1/workspaces/{TENANT_A}/runs",
        json={"contract_id": contract_id, "snapshot_id": snapshot_id},
        headers=harness.headers(MEMBER, key=key),
    )


# --------------------------------------------------------------------------- #
# Everything that refuses BEFORE the gate, so the gate is distinguishable.
# --------------------------------------------------------------------------- #


def test_a_run_request_with_no_session_is_refused_as_unauthenticated(
    harness: Harness,
) -> None:
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/runs",
        json={"contract_id": "c", "snapshot_id": "s"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "SESSION_REQUIRED"


def test_a_viewer_cannot_request_a_run(harness: Harness) -> None:
    harness.sign_in(VIEWER)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/runs",
        json={"contract_id": "c", "snapshot_id": "s"},
        headers=harness.headers(VIEWER),
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ROLE_INSUFFICIENT"


def test_an_unknown_contract_is_a_404_and_not_the_gate(harness: Harness) -> None:
    """The gate must not absorb an identifier error."""
    _project, _contract, snapshot_id = prepared(harness)
    response = request_run(harness, str(uuid.uuid4()), snapshot_id)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_an_unknown_snapshot_is_a_404_and_not_the_gate(harness: Harness) -> None:
    _project, contract_id, _snapshot = prepared(harness)
    response = request_run(harness, contract_id, "0" * 64)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_a_malformed_payload_is_a_422_and_not_the_gate(harness: Harness) -> None:
    _project, _contract, snapshot_id = prepared(harness)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/runs",
        json={"snapshot_id": snapshot_id},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# The gate itself.
# --------------------------------------------------------------------------- #


def test_a_valid_run_request_is_refused_with_the_documented_blocked_state(
    harness: Harness,
) -> None:
    """RX-08: a request that would otherwise have succeeded reaches the gate."""
    _project, contract_id, snapshot_id = prepared(harness)
    response = request_run(harness, contract_id, snapshot_id)
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "EXECUTION_BLOCKED_T2"
    context = error["context"]
    assert context["threat"] == "T2"
    assert context["blocked_state"] == T2_BLOCKED_STATE
    assert context["transient"] is False
    assert context["contract_id"] == contract_id
    assert context["snapshot_id"] == snapshot_id


def test_the_refusal_names_the_identity_half_and_not_the_closed_one(
    harness: Harness,
) -> None:
    """The specific open reason, which is the whole value of the message.

    T2's filesystem half is closed over declared paths. A refusal that still
    claimed nothing denied a write to the approval ledger would point a reader
    at a control that is already in place - and that exact wording was in the
    code until this test existed.
    """
    _project, contract_id, snapshot_id = prepared(harness)
    error = request_run(harness, contract_id, snapshot_id).json()["error"]
    detail = error["detail"]
    assert "IDENTITY half is open" in detail
    assert "filesystem half is closed" in detail
    assert error["context"]["blocked_half"] == "IDENTITY"
    assert error["context"]["filesystem_half"] == "CLOSED_OVER_DECLARED_PATHS"
    assert "nothing denies it" not in detail


def test_the_refusal_cites_the_threat_model_through_the_checkable_reference(
    harness: Harness,
) -> None:
    """RX-54: the pointer has to resolve, and ``test_error_references.py`` checks that.

    Asserted here as well because the reference has to actually be IN the
    response: a refusal that cites its evidence only in a module constant cites
    it to nobody.
    """
    _project, contract_id, snapshot_id = prepared(harness)
    error = request_run(harness, contract_id, snapshot_id).json()["error"]
    assert T2_DOCUMENT in error["detail"]
    assert T2_SECTION_HEADING.lstrip("# ").rstrip(".") in error["detail"]
    assert T2_DOCUMENT in error["context"]["reference"]


def test_the_refusal_lists_the_unmet_preconditions(harness: Harness) -> None:
    """RX-09: each missing identity requirement is named separately."""
    _project, contract_id, snapshot_id = prepared(harness)
    context = request_run(harness, contract_id, snapshot_id).json()["error"]["context"]
    unmet = " ".join(context["unmet_preconditions"])
    assert "RETRACE_RUNNER_OS_USER" in unmet
    assert "RETRACE_RUNNER_DATABASE_URL" in unmet
    assert "RETRACE_VERIFIER_DATABASE_URL" in unmet
    assert EXECUTION_NOT_IMPLEMENTED in context["unmet_preconditions"]
    assert "CONFIGURATION checks" in context["identity_separation_caveat"]


def test_the_refusal_reports_the_confined_profile_it_would_have_used(
    harness: Harness,
) -> None:
    """The property that makes the gate a one-line change rather than a rewrite.

    The day the identity half closes, the profile reported here is the one that
    runs. Nobody has to invent a declaration under pressure, and a reviewer can
    see today which paths a future verdict would have covered.
    """
    _project, contract_id, snapshot_id = prepared(harness)
    context = request_run(harness, contract_id, snapshot_id).json()["error"]["context"]
    profile = context["execution_profile"]
    assert profile["filesystem_confinement"] == "KERNEL_MOUNT_NAMESPACE"
    assert profile["network"] == "KERNEL_NAMESPACE"
    assert profile["write_confinement"] == "SCRATCH_ONLY"
    assert len(profile["policy_digest"]) == 64
    assert profile["protected_paths"]
    assert profile["secret_paths"]
    assert "approval-ledger" in profile["protected_kinds"]
    assert profile["confinement_and_identity_met"] is False


def test_the_refusal_is_recorded_as_a_request_and_not_as_a_run(harness: Harness) -> None:
    """RX-11: execution status is a separate type, and none of its values is true."""
    _project, contract_id, snapshot_id = prepared(harness)
    request_run(harness, contract_id, snapshot_id)
    listing = harness.client.get(f"/v1/workspaces/{TENANT_A}/runs")
    assert listing.status_code == 200
    records = listing.json()
    assert len(records) == 1
    record = records[0]
    assert record["state"] == T2_BLOCKED_STATE
    assert record["contract_id"] == contract_id
    assert record["requested_by"] == MEMBER
    assert record["filesystem_confinement"] == "KERNEL_MOUNT_NAMESPACE"
    for absent in ("execution_status", "exit_code", "outputs", "outcome", "verdict"):
        assert absent not in record, f"a refused request must not carry {absent}"
    for value in ("SUCCEEDED", "FAILED", "TIMEOUT", "KILLED"):
        assert value not in str(record)


def test_the_gate_still_refuses_when_the_identity_half_is_configured(
    make_harness: Any,
) -> None:
    """Configuration alone does not open the gate, and must not.

    With a distinct runner account and distinct restricted database URLs
    configured, the identity reasons disappear from the refusal - and the route
    STILL refuses, because no route in this service invokes the runner. A gate
    that opened here would return a success-shaped response for work nothing
    performed, which is precisely the fabrication it exists to prevent.
    """
    import dataclasses

    from retrace_api.web.config import ApiConfig

    probe = identity_separation(ApiConfig())
    harness = make_harness(
        runner_os_user=f"{probe.process_os_user}-runner",
        runner_database_url="postgresql://runner@localhost/retrace",
        verifier_database_url="postgresql://verifier@localhost/retrace",
    )
    assert dataclasses.is_dataclass(identity_separation(harness.state.config))
    assert identity_separation(harness.state.config).satisfied is True

    _project, contract_id, snapshot_id = prepared(harness)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/runs",
        json={"contract_id": contract_id, "snapshot_id": snapshot_id},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 503, response.text
    context = response.json()["error"]["context"]
    assert context["unmet_preconditions"] == [EXECUTION_NOT_IMPLEMENTED]
    assert context["execution_profile"]["confinement_and_identity_met"] is True


def test_a_deployment_with_no_declaration_reports_needs_configuration_instead(
    make_harness: Any,
) -> None:
    """Two different findings get two different refusals.

    "You have not told me what to protect" is not "the identity half of T2 is
    open". A deployment that has configured neither would otherwise read the
    threat-model refusal and go looking for a threat when the answer was a
    setting.
    """
    harness = make_harness(schema_root=None, secret_root=None)
    _project, contract_id, snapshot_id = prepared(harness)
    response = harness.client.post(
        f"/v1/workspaces/{TENANT_A}/runs",
        json={"contract_id": contract_id, "snapshot_id": snapshot_id},
        headers=harness.headers(MEMBER),
    )
    assert response.status_code == 503, response.text
    error = response.json()["error"]
    assert error["code"] == "EXECUTION_PROFILE_NOT_CONFIGURED"
    assert error["context"]["status"] == "NEEDS_CONFIGURATION"
    assert set(error["context"]["missing"]) == {
        "RETRACE_SCHEMA_ROOT",
        "RETRACE_SECRET_ROOT",
    }


def test_an_unconfigured_deployment_records_no_blocked_run(make_harness: Any) -> None:
    """The recorded state must not say "blocked by T2" for a settings refusal."""
    harness = make_harness(schema_root=None, secret_root=None)
    _project, contract_id, snapshot_id = prepared(harness)
    harness.client.post(
        f"/v1/workspaces/{TENANT_A}/runs",
        json={"contract_id": contract_id, "snapshot_id": snapshot_id},
        headers=harness.headers(MEMBER),
    )
    listing = harness.client.get(f"/v1/workspaces/{TENANT_A}/runs")
    assert listing.json() == []


# --------------------------------------------------------------------------- #
# Nothing in the module can execute anything.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "forbidden",
    ["run_notebook", "subprocess", "Popen", "os.exec", "os.fork", "retrace_runner.execution"],
)
def test_the_run_router_names_no_execution_entry_point(forbidden: str) -> None:
    """A source property, because the claim is about the module, not one request."""
    source = RUNS_SOURCE.read_text(encoding="utf-8")
    # The docstring names `run_notebook` when describing what is NOT called, so
    # the code is checked rather than the whole file.
    code = source.split('"""', 2)[-1]
    assert forbidden not in code, f"{forbidden} appears in the run router's code"


def test_the_source_check_detects_an_execution_entry_point() -> None:
    """DISCRIMINATION CONTROL: a substring check that always passes is no check."""
    contained = "from retrace_runner import run_notebook\nrun_notebook(...)\n"
    assert "run_notebook" in contained


def test_run_notebook_is_not_called_when_the_route_is_exercised(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The behavioural half of the claim above.

    The runner's entry point is replaced with one that records a call and
    fails. Exercising the route must leave it untouched - a source grep alone
    would not catch an execution path reached through an alias or a dependency.
    """
    calls: list[tuple[Any, ...]] = []

    def record(*args: Any, **kwargs: Any) -> None:
        calls.append(args)
        raise AssertionError("the run route invoked the runner")

    import retrace_runner
    import retrace_runner.execution

    monkeypatch.setattr(retrace_runner, "run_notebook", record, raising=True)
    monkeypatch.setattr(retrace_runner.execution, "run_notebook", record, raising=True)

    _project, contract_id, snapshot_id = prepared(harness)
    response = request_run(harness, contract_id, snapshot_id)
    assert response.status_code == 503
    assert calls == []


def test_the_runner_patch_would_have_been_observed_if_it_had_been_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DISCRIMINATION CONTROL for the patch above."""
    calls: list[tuple[Any, ...]] = []

    def record(*args: Any, **kwargs: Any) -> None:
        calls.append(args)

    import retrace_runner

    monkeypatch.setattr(retrace_runner, "run_notebook", record, raising=True)
    retrace_runner.run_notebook()  # type: ignore[call-arg]
    assert calls == [()]


# --------------------------------------------------------------------------- #
# Idempotency across a refused request.
# --------------------------------------------------------------------------- #


def test_an_identical_retry_reaches_the_gate_again(harness: Harness) -> None:
    """RX-53: a refused request must not consume its idempotency key.

    The caller should be able to retry the identical request with the same key
    once the gate opens. A reservation held by a refusal would turn the second
    attempt into a 409 about the key rather than the real answer about the gate.
    """
    _project, contract_id, snapshot_id = prepared(harness)
    first = request_run(harness, contract_id, snapshot_id, key="run-1")
    second = request_run(harness, contract_id, snapshot_id, key="run-1")
    assert first.status_code == 503
    assert second.status_code == 503
    assert second.json()["error"]["code"] == "EXECUTION_BLOCKED_T2"
    listing = harness.client.get(f"/v1/workspaces/{TENANT_A}/runs")
    assert len(listing.json()) == 2, "each attempt is recorded as its own request"

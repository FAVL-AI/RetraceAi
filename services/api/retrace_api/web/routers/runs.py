"""The execution gate (RX-08, RX-09, threat T2).

THIS ROUTE EXISTS IN ORDER TO REFUSE.

It authenticates, enforces CSRF, verifies membership, requires the MEMBER role,
validates the payload, resolves the contract and the snapshot inside the
authorised workspace, builds the CONFINED execution profile it would have used -
and then refuses with a documented blocked state naming T2's identity half.
Every one of those steps happens first on purpose: a refusal that could also
have been caused by a missing session, a bad payload or an unknown identifier
would not demonstrate the gate. Reaching the gate requires a request that would
otherwise have succeeded.

THE PROFILE IS BUILT BEFORE THE REFUSAL, AND THAT IS THE POINT.

The threat model's third open T2 item is that nothing in the repository
requested confinement. Requesting it only on the day execution is admitted would
mean inventing a declaration under pressure, with no reviewed list to check it
against. So the profile is assembled on every request, its policy digest and
protected paths are reported in the refusal, and the gate is the single measured
condition that remains. A deployment that has not configured the declaration
gets ``EXECUTION_PROFILE_NOT_CONFIGURED`` instead - a different refusal, naming
settings rather than a threat, because "you have not told me what to protect"
and "the identity half of T2 is open" are not the same finding.

NOTHING IN THIS MODULE CAN EXECUTE ANYTHING.

It does not import ``retrace_runner.execution``, it does not import
``subprocess``, and it does not queue work. It imports the runner's POLICY types
through :mod:`retrace_api.web.run_profile`, which is a frozen record and a path
list. ``tests/api/test_run_gate.py`` asserts both: that this module's source
names no execution entry point, and that ``run_notebook`` is not called when the
route is exercised.

THE REFUSAL IS RECORDED.

A blocked request appends a run record with the blocked state, so the journey
has an auditable trace of what was asked for and refused. The record is NOT a
run: it carries no execution status, no exit code and no outputs, because none
exist. A record that looked like a queued job would be the fabrication this gate
is here to prevent.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from retrace_api.web.contract_store import resolve_contract
from retrace_api.web.dependencies import (
    Authorised,
    AuthorisedWorkspace,
    IdempotencyScope,
    idempotency_scope,
    require_role,
    service_state,
)
from retrace_api.web.errors import T2_BLOCKED_STATE
from retrace_api.web.execution import execution_refusal
from retrace_api.web.identity import WorkspaceRole
from retrace_api.web.run_profile import execution_profile
from retrace_api.web.schemas import RunRequest
from retrace_api.web.snapshots import resolve_snapshot
from retrace_api.web.state import ServiceState

__all__ = ["router"]

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["runs"])

_WRITER = require_role(WorkspaceRole.MEMBER)


@router.post("/runs", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
def request_run(
    payload: RunRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> dict[str, Any]:
    """Request execution. Refused while T2's identity half is open (RX-08, RX-09)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    # Resolved before the gate so that a 503 here cannot be confused with a 404:
    # an unknown contract or snapshot is reported as such.
    contract_record, _contract = resolve_contract(workspace, payload.contract_id)
    resolve_snapshot(workspace, snapshot_id=payload.snapshot_id)
    # Built before the record is appended, so the recorded state cannot say
    # "blocked by T2" for a request that was actually refused for want of a
    # declaration.
    profile = execution_profile(state.config, tenant_id=auth.tenant_id)
    workspace.index("runs").append(
        {
            "id": str(uuid.uuid4()),
            "project_id": str(contract_record.get("project_id", "")),
            "contract_id": payload.contract_id,
            "snapshot_id": payload.snapshot_id,
            "state": T2_BLOCKED_STATE,
            "requested_by": auth.actor,
            "requested_at": state.now().isoformat(),
            # The profile the refused request would have executed under, so the
            # trace records which declaration was in force rather than only that
            # something was refused.
            "execution_policy_digest": profile.limits.policy_digest,
            "filesystem_confinement": profile.limits.filesystem_confinement.value,
        }
    )
    # The reservation is released by the dependency when this raises, so the
    # caller may retry the identical request with the same key once the gate
    # opens.
    raise execution_refusal(
        contract_id=payload.contract_id, snapshot_id=payload.snapshot_id, profile=profile
    )


@router.get("/runs")
def list_run_requests(
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[dict[str, Any]]:
    """List run REQUESTS and the state each reached (RX-08, RX-11).

    Every record here is a refusal. The field is called ``state`` rather than
    ``execution_status`` because ``ExecutionStatus`` means something specific -
    SUCCEEDED, FAILED, TIMEOUT, KILLED - and none of those is true of a request
    that never ran.
    """
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    return [dict(record) for record in workspace.index("runs").records()]

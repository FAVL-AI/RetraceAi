"""Verification reports, read-only (RX-11, RX-12, RX-18).

THERE IS NO WRITE ROUTE HERE, AND THAT IS THE REQUIREMENT.

A verification outcome is the verifier's conclusion from independent
recomputation. If any route accepted one, the system's central claim - that a
pass was computed rather than asserted - would be false for every record that
came in that way. So this module exposes ``GET`` only, and
``tests/api/test_no_supplied_verdict.py`` greps every router in the application
for a request model carrying a verdict, an outcome, a check status or an
approval status, and fails if one appears. That test includes a contained
fixture router that DOES carry such a field, so the check is shown to detect
what it claims to detect.

WHERE A REPORT CAN COME FROM IN THIS BUILD.

Only from an imported evidence package, and such a report is labelled
``source="imported-evidence"`` with ``independently_recomputed=false``. That is
the origin's claim about its own result, carried as provenance. It is not this
workspace's verification of anything, and the response says so in a field rather
than in prose a client can ignore. Independent recomputation requires execution,
and execution is gated by T2.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from retrace_api.web.dependencies import Authorised, service_state
from retrace_api.web.errors import NotFound
from retrace_api.web.schemas import VerificationReportResponse
from retrace_api.web.state import ServiceState

__all__ = ["router"]

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["verification"])


def _render(workspace_id: str, record: dict[str, Any]) -> VerificationReportResponse:
    return VerificationReportResponse(
        workspace_id=workspace_id,
        report_id=str(record["id"]),
        contract_hash=str(record["contract_hash"]),
        outcome=str(record["outcome"]),
        reason=str(record["reason"]),
        verifier_identity=str(record["verifier_identity"]),
        verified_at=dt.datetime.fromisoformat(str(record["verified_at"])),
        independently_recomputed=bool(record.get("independently_recomputed", False)),
        source=str(record["source"]),
    )


@router.get("/reports", response_model=list[VerificationReportResponse])
def list_reports(
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[VerificationReportResponse]:
    """List the authorised workspace's verification reports (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    return [_render(auth.tenant_id, record) for record in workspace.index("reports").distinct()]


@router.get("/reports/{report_id}", response_model=VerificationReportResponse)
def read_report(
    report_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> VerificationReportResponse:
    """Read one report, or 404 outside the authorised workspace (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    record = workspace.index("reports").latest(report_id)
    if record is None:
        raise NotFound(
            f"no verification report {report_id!r} exists in the authorised workspace",
            remedy="list the workspace's reports",
        )
    return _render(auth.tenant_id, record)

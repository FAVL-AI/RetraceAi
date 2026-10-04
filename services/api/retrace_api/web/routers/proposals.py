"""Repair proposals, review, and exact approval (RX-04, RX-05, RX-06, RX-07).

A PROPOSAL IS A PATCH, NEVER A MUTATION.

The route takes the proposed CONTENT and computes the unified diff itself from
the snapshot's stored bytes, then computes the candidate digest from the
manifest plus the patched bytes. A client-supplied diff would let the recorded
patch and the recorded candidate hash describe different things - and the
candidate hash is what an approval binds, so the mismatch would be invisible
until someone tried to reproduce the result. The snapshot is untouched: it is
content-addressed and immutable, and the proposal refers to it by digest.

THREE SEPARATE AUTHORITIES, AND WHY THEY ARE NOT ONE ROUTE.

* **Proposing** needs the MEMBER role and records who proposed.
* **Reviewing** records that a human looked. It carries notes and NO decision,
  because a review that carried a verdict would be an approval under another
  name, and the approval is the step that has to bind five fields.
* **Approving** needs the APPROVER role, needs a review by someone who is not
  the proposer, and refuses an approver who is the proposer. One compromised
  account therefore cannot propose, review and approve its own change. This is
  the control RX-07 describes from the other side: the repair worker cannot
  write the ledger, and the ledger will not accept a self-reviewed candidate.

THE APPROVAL BINDS `declaration_digest`, NOT `contract_hash`.

``contract_hash`` covers ``status`` and ``approval_ref``, so it MOVES when the
contract is marked APPROVED - an approval that bound it would invalidate itself
the moment it was recorded. ``declaration_digest`` excludes the lifecycle label
and changes on any edit to the declaration, which is exactly the binding
semantics RX-05 requires.

AND THE APPROVAL IS VERIFIED AFTER IT IS RECORDED.

``verify_contract_approval`` is called on the newly APPROVED contract before the
route returns. If it refuses, the ledger entry is SUPERSEDED with a reason
rather than deleted - the ledger is append-only and hash-chained, so a mistake
is corrected by a later entry, never by editing the middle.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from retrace_api.web.contract_store import resolve_contract, store_contract
from retrace_api.web.dependencies import (
    Authorised,
    AuthorisedWorkspace,
    IdempotencyScope,
    idempotency_scope,
    require_role,
    service_state,
)
from retrace_api.web.errors import ContractApprovalRefused, NotFound, UploadRefused
from retrace_api.web.execution import ENVIRONMENT_POLICY_DIGEST
from retrace_api.web.identity import WorkspaceRole
from retrace_api.web.routers.contracts import contract_response
from retrace_api.web.schemas import (
    ApprovalRequest,
    ProposalCreateRequest,
    ProposalResponse,
    ReviewCreateRequest,
    ReviewResponse,
)
from retrace_api.web.snapshots import resolve_snapshot
from retrace_api.web.state import ServiceState
from retrace_api.web.workspace import TenantWorkspace
from retrace_contracts import (
    Approval,
    ContractStatus,
    RepairProposal,
    ResultContract,
    canonical_digest,
)
from retrace_domain import LedgerAppendRefused, build_unified_diff, candidate_digest, store_reader

__all__ = ["router"]

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["repairs"])

_WRITER = require_role(WorkspaceRole.MEMBER)
_APPROVER = require_role(WorkspaceRole.APPROVER)


def _resolve_proposal(
    workspace: TenantWorkspace, proposal_id: str
) -> tuple[dict[str, Any], RepairProposal]:
    record = workspace.index("proposals").latest(proposal_id)
    if record is None:
        raise NotFound(
            f"no proposal {proposal_id!r} exists in the authorised workspace",
            remedy="create the proposal first",
        )
    blob = record.get("document_blob")
    if not blob:
        raise NotFound(
            f"proposal {proposal_id!r} has no stored document",
            remedy="re-create the proposal",
        )
    document: Any = json.loads(workspace.store.get_bytes(str(blob)).decode("utf-8"))
    payload = document.get("payload") if isinstance(document, dict) else None
    if not isinstance(payload, dict):
        raise NotFound(
            f"proposal {proposal_id!r} has a malformed stored document",
            remedy="re-create the proposal",
        )
    return record, RepairProposal.model_validate(payload)


def _proposal_response(
    workspace_id: str, record: dict[str, Any], proposal: RepairProposal, reviews: int
) -> ProposalResponse:
    return ProposalResponse(
        workspace_id=workspace_id,
        project_id=str(record["project_id"]),
        proposal_id=proposal.proposal_id,
        snapshot_id=proposal.snapshot_id,
        target_path=proposal.target_path,
        candidate_hash=proposal.candidate_hash,
        provider=proposal.provider,
        proposed_by=str(record["proposed_by"]),
        unified_diff=proposal.unified_diff,
        review_count=reviews,
    )


def _review_count(workspace: TenantWorkspace, proposal_id: str, *, excluding: str) -> int:
    """Reviews of ``proposal_id`` by someone other than ``excluding``."""
    return sum(
        1
        for record in workspace.index("reviews").records()
        if record.get("proposal_id") == proposal_id and record.get("reviewed_by") != excluding
    )


@router.post(
    "/projects/{project_id}/proposals",
    status_code=status.HTTP_201_CREATED,
    response_model=ProposalResponse,
)
def create_proposal(
    project_id: str,
    payload: ProposalCreateRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Record a reviewable patch against a named snapshot (RX-06)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    _record, manifest = resolve_snapshot(
        workspace, snapshot_id=payload.snapshot_id, project_id=project_id
    )
    if payload.target_path not in manifest.files:
        raise NotFound(
            f"snapshot {payload.snapshot_id!r} does not contain {payload.target_path!r}",
            remedy="name a path the snapshot declares",
        )
    read = store_reader(workspace.store, manifest)
    try:
        original = read(payload.target_path).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UploadRefused(
            f"{payload.target_path!r} is not UTF-8 text, so a textual patch cannot be "
            "proposed against it",
            remedy="propose a patch against a text file",
            extra={"reason": "target-not-text"},
        ) from exc
    diff = build_unified_diff(payload.target_path, original, payload.proposed_content)
    if not diff:
        raise UploadRefused(
            "the proposed content is identical to the snapshot's content, so there is "
            "nothing to review",
            remedy="submit content that differs from the snapshot",
            extra={"reason": "empty-diff"},
        )
    proposal = RepairProposal(
        proposal_id=str(uuid.uuid4()),
        snapshot_id=payload.snapshot_id,
        target_path=payload.target_path,
        unified_diff=diff,
        candidate_hash=candidate_digest(
            manifest, payload.target_path, payload.proposed_content.encode("utf-8")
        ),
        rationale=payload.rationale,
        provider=state.proposal_provider_id,
        # Not an injected fault. RX-56 reserves `injected=True` for deliberately
        # seeded faults in fixtures; marking a real submission that way would
        # misattribute it.
        injected=False,
    )
    blob = workspace.store.put_bytes(proposal.canonical_document().encode("utf-8"))
    workspace.index("proposals").append(
        {
            "id": proposal.proposal_id,
            "project_id": project_id,
            "snapshot_id": proposal.snapshot_id,
            "document_blob": blob,
            "candidate_hash": proposal.candidate_hash,
            "proposed_by": auth.actor,
            "created_at": state.now().isoformat(),
        }
    )
    record = workspace.index("proposals").latest(proposal.proposal_id) or {}
    body = _proposal_response(auth.tenant_id, record, proposal, 0).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


@router.get("/projects/{project_id}/proposals", response_model=list[ProposalResponse])
def list_proposals(
    project_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[ProposalResponse]:
    """List this project's proposals within the authorised workspace (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    out: list[ProposalResponse] = []
    for record in workspace.index("proposals").distinct():
        if record.get("project_id") != project_id:
            continue
        found, proposal = _resolve_proposal(workspace, str(record["id"]))
        out.append(
            _proposal_response(
                auth.tenant_id,
                found,
                proposal,
                _review_count(workspace, proposal.proposal_id, excluding=""),
            )
        )
    return out


@router.post("/reviews", status_code=status.HTTP_201_CREATED, response_model=ReviewResponse)
def create_review(
    payload: ReviewCreateRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Record that a human reviewed a proposal. Carries notes, not a verdict."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    record, proposal = _resolve_proposal(workspace, payload.proposal_id)
    if record.get("proposed_by") == auth.actor:
        raise ContractApprovalRefused(
            "a proposal cannot be reviewed by the principal who proposed it",
            remedy="ask another member of the workspace to review it",
            code="SELF_REVIEW_REFUSED",
        )
    reviewed_at = state.now()
    review_id = str(uuid.uuid4())
    workspace.index("reviews").append(
        {
            "id": review_id,
            "proposal_id": proposal.proposal_id,
            "reviewed_by": auth.actor,
            "reviewed_at": reviewed_at.isoformat(),
            "notes": payload.notes,
        }
    )
    body = ReviewResponse(
        workspace_id=auth.tenant_id,
        review_id=review_id,
        proposal_id=proposal.proposal_id,
        reviewed_by=auth.actor,
        reviewed_at=reviewed_at,
        notes=payload.notes,
    ).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


@router.get("/proposals/{proposal_id}/reviews", response_model=list[ReviewResponse])
def list_reviews(
    proposal_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[ReviewResponse]:
    """List a proposal's reviews within the authorised workspace (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    _record, proposal = _resolve_proposal(workspace, proposal_id)
    out: list[ReviewResponse] = []
    for record in workspace.index("reviews").records():
        if record.get("proposal_id") != proposal.proposal_id:
            continue
        out.append(
            ReviewResponse(
                workspace_id=auth.tenant_id,
                review_id=str(record["id"]),
                proposal_id=proposal.proposal_id,
                reviewed_by=str(record["reviewed_by"]),
                reviewed_at=dt.datetime.fromisoformat(str(record["reviewed_at"])),
                notes=str(record["notes"]),
            )
        )
    return out


def _approve(
    *,
    workspace: TenantWorkspace,
    contract: ResultContract,
    proposal: RepairProposal,
    actor: str,
    now: dt.datetime,
) -> tuple[ResultContract, str]:
    """Record the approval in the ledger and return the APPROVED contract."""
    action_digest = canonical_digest(
        {
            "action": "accept-repair-candidate",
            "contract_id": contract.contract_id,
            "proposal_id": proposal.proposal_id,
            "target_path": proposal.target_path,
            "snapshot_id": proposal.snapshot_id,
        },
        type_tag="retrace.ApprovedAction",
    )
    approval = Approval(
        approval_id=str(uuid.uuid4()),
        # RX-05 and the closure's section 6: the DECLARATION digest, so marking
        # the contract APPROVED does not invalidate the approval it records.
        contract_hash=contract.declaration_digest,
        candidate_hash=proposal.candidate_hash,
        input_snapshot_id=proposal.snapshot_id,
        environment_policy_digest=ENVIRONMENT_POLICY_DIGEST,
        action_digest=action_digest,
        approved_by=actor,
        approved_at=now,
    )
    try:
        entry = workspace.ledger.record_contract_approval(approval=approval, recorded_at=now)
    except LedgerAppendRefused as refusal:
        raise ContractApprovalRefused(
            f"the approval ledger refused the entry: {refusal}",
            remedy="resolve the ledger's objection; the ledger is the authority",
        ) from refusal
    approved = ResultContract.model_validate(
        {
            **contract.model_dump(mode="python"),
            "status": ContractStatus.APPROVED,
            "approval_ref": entry.entry_id,
        }
    )
    return approved, entry.entry_id


@router.post("/approvals", status_code=status.HTTP_201_CREATED)
def approve_candidate(
    payload: ApprovalRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_APPROVER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Approve a reviewed proposal against a contract (RX-04, RX-05)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    _contract_record, contract = resolve_contract(workspace, payload.contract_id)
    proposal_record, proposal = _resolve_proposal(workspace, payload.proposal_id)
    if contract.status is not ContractStatus.DRAFT:
        raise ContractApprovalRefused(
            f"contract {payload.contract_id!r} is {contract.status.value}, not DRAFT",
            remedy="supersede the contract and approve a new revision",
            code="CONTRACT_NOT_DRAFT",
        )
    proposer = str(proposal_record.get("proposed_by", ""))
    if proposer == auth.actor:
        raise ContractApprovalRefused(
            "the principal who proposed a repair may not approve it",
            remedy="ask an approver who did not author the proposal",
            code="SEPARATION_OF_DUTIES",
        )
    if _review_count(workspace, proposal.proposal_id, excluding=proposer) == 0:
        raise ContractApprovalRefused(
            "the proposal has no review by anyone other than its author, so it cannot "
            "be approved",
            remedy="have another member review the proposal first",
            code="PROPOSAL_REVIEW_REQUIRED",
        )
    now = state.now()
    approved, entry_id = _approve(
        workspace=workspace, contract=contract, proposal=proposal, actor=auth.actor, now=now
    )
    try:
        workspace.ledger.verify_contract_approval(approved)
    except Exception as failure:
        # The ledger is append-only, so a bad entry is SUPERSEDED rather than
        # removed. The refusal names the entry so the correction is traceable.
        workspace.ledger.supersede(
            entry_id,
            reason=f"the recorded approval did not verify against the contract: {failure!r}",
            recorded_at=now,
        )
        raise ContractApprovalRefused(
            "the approval was recorded but did not verify against the contract it "
            "claims to approve; the entry has been superseded and the contract is "
            "NOT approved",
            remedy="re-check that the proposal belongs to this contract's declaration",
            code="APPROVAL_DID_NOT_VERIFY",
        ) from failure
    blob = store_contract(workspace.store, approved)
    workspace.index("contracts").append(
        {
            "id": approved.contract_id,
            "project_id": approved.project_id,
            "document_blob": blob,
            "contract_hash": approved.contract_hash,
            "declaration_digest": approved.declaration_digest,
            "status": approved.status.value,
            "approval_ref": entry_id,
            "approved_by": auth.actor,
            "created_at": now.isoformat(),
        }
    )
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        uow.mark_contract_approved(approved.contract_id)
    body = contract_response(workspace, approved).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)

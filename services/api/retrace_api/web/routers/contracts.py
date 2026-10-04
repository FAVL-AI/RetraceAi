"""Result-contract routes (RX-03, RX-04, RX-47).

THE CREATE MODEL IS `ResultContractDraft`, UNCHANGED.

It omits ``contract_id``, ``tenant_id``, ``status`` and ``approval_ref``, and it
forbids extras, so a payload carrying any of them is REFUSED by the model rather
than having the field dropped. The route then calls ``persist_contract_draft``
with the server-established values as explicit keyword arguments, which is where
a reviewer can see that the tenant came from the authorised membership and not
from the request.

THREE EXTRA CHECKS THE MODEL CANNOT MAKE.

* ``draft.project_id`` must equal the project in the path. The model cannot know
  the path, and accepting a mismatch would let a caller create a contract under
  one project while addressing another - which the tenancy check would not catch,
  because both projects can be in the same tenant.
* ``draft.created_by`` must equal the authenticated subject. The field is a
  CLAIM, and its own docstring says server-side authentication is the authority;
  this is where that is enforced.
* the project must exist in the authorised workspace. In PostgreSQL the
  composite foreign key refuses the relationship anyway (RX-49), but a 404 from
  the route is a better answer than a constraint violation, and both layers
  refuse rather than one of them trusting the other.

APPROVAL IS REPORTED FROM THE LEDGER, NEVER FROM THE STORED STATUS.

``approved_in_ledger`` on the response is the ledger's answer. A contract whose
stored document says ``APPROVED`` but whose reference resolves to nothing reads
as ``false``, which is the whole point of the field existing separately from
``status``.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from retrace_api.web.contract_store import approval_state, resolve_contract, store_contract
from retrace_api.web.dependencies import (
    Authorised,
    AuthorisedWorkspace,
    IdempotencyScope,
    idempotency_scope,
    require_role,
    service_state,
)
from retrace_api.web.errors import ActorIdentityMismatch, CrossTenantReferenceRefused, NotFound
from retrace_api.web.identity import WorkspaceRole
from retrace_api.web.schemas import ContractResponse
from retrace_api.web.state import ServiceState
from retrace_api.web.workspace import TenantWorkspace
from retrace_contracts import (
    ContractStatus,
    ResultContract,
    ResultContractDraft,
    persist_contract_draft,
)

__all__ = ["contract_response", "router"]

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["contracts"])

_WRITER = require_role(WorkspaceRole.MEMBER)


def contract_response(
    workspace: TenantWorkspace, contract: ResultContract
) -> ContractResponse:
    """Render a contract, asking the ledger about approval (RX-04)."""
    approved, _reason = approval_state(workspace.ledger, contract)
    return ContractResponse(
        workspace_id=contract.tenant_id,
        project_id=contract.project_id,
        contract_id=contract.contract_id,
        version=contract.version,
        status=contract.status.value,
        reference_kind=contract.reference_kind.value,
        contract_hash=contract.contract_hash,
        declaration_digest=contract.declaration_digest,
        approval_ref=contract.approval_ref,
        approved_in_ledger=approved,
        permits_reproduced_outcome=contract.permits_reproduced_outcome,
    )


@router.post(
    "/projects/{project_id}/contracts",
    status_code=status.HTTP_201_CREATED,
    response_model=ContractResponse,
)
def create_contract(
    project_id: str,
    draft: ResultContractDraft,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Create a DRAFT contract from an external draft payload (RX-03, RX-47)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    if draft.project_id != project_id:
        raise CrossTenantReferenceRefused(
            f"the draft names project {draft.project_id!r} but the request addresses "
            f"{project_id!r}",
            remedy="post the draft to the project it names",
            code="PROJECT_MISMATCH",
            status_code=422,
        )
    if draft.created_by != auth.actor:
        raise ActorIdentityMismatch(
            f"the draft claims author {draft.created_by!r} but the authenticated subject "
            f"is {auth.actor!r}; the claim is not believed",
            remedy="submit the draft with created_by set to your own subject",
        )
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        if uow.get_project(project_id) is None:
            raise NotFound(
                f"no project {project_id!r} exists in the authorised workspace",
                remedy="create the project first",
            )
    contract = persist_contract_draft(
        draft,
        # Server-established, every one of them, and visible as such here.
        contract_id=str(uuid.uuid4()),
        tenant_id=auth.tenant_id,
        status=ContractStatus.DRAFT,
        approval_ref=None,
    )
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    blob = store_contract(workspace.store, contract)
    # Files first, row last: a failure between the two leaves an orphan blob,
    # which is inert and identifiable by digest, rather than a row pointing at a
    # document that does not exist.
    workspace.index("contracts").append(
        {
            "id": contract.contract_id,
            "project_id": project_id,
            "document_blob": blob,
            "contract_hash": contract.contract_hash,
            "declaration_digest": contract.declaration_digest,
            "status": contract.status.value,
            "created_at": state.now().isoformat(),
        }
    )
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        uow.create_contract(
            contract_id=contract.contract_id,
            project_id=project_id,
            contract_hash=contract.contract_hash,
        )
    body = contract_response(workspace, contract).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


@router.get("/projects/{project_id}/contracts", response_model=list[ContractResponse])
def list_contracts(
    project_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[ContractResponse]:
    """List this project's contracts within the authorised workspace (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    out: list[ContractResponse] = []
    for record in workspace.index("contracts").distinct():
        if record.get("project_id") != project_id:
            continue
        _found, contract = resolve_contract(workspace, str(record["id"]))
        out.append(contract_response(workspace, contract))
    return out


@router.get("/contracts/{contract_id}", response_model=ContractResponse)
def read_contract(
    contract_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> ContractResponse:
    """Read one contract, or 404 outside the authorised workspace (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    _record, contract = resolve_contract(workspace, contract_id)
    return contract_response(workspace, contract)

"""Project routes (RX-47, RX-49, RX-53).

THE EDIT ROUTE IS THE INTERESTING ONE.

``PATCH`` carries :class:`ProjectRenameRequest`, which has exactly one field: a
name. There is no tenant field to supply, the repository's update statement has
no tenant parameter, and the row it reaches is the one the transaction-local
tenant context admits. So "an ordinary edit cannot move an object between
tenants" is not a rule somebody has to remember - the operation cannot express
it, at the payload, at the repository and at the database.

A PATCH naming another tenant's project is a 404, not a 403. The distinction
would confirm that the identifier exists, which is a cross-tenant disclosure of
one bit and exactly what an enumeration attempt is looking for.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from retrace_api.web.dependencies import (
    Authorised,
    AuthorisedWorkspace,
    IdempotencyScope,
    idempotency_scope,
    require_role,
    service_state,
)
from retrace_api.web.errors import NotFound
from retrace_api.web.identity import WorkspaceRole
from retrace_api.web.repository import ProjectRecord
from retrace_api.web.schemas import ProjectCreateRequest, ProjectRenameRequest, ProjectResponse
from retrace_api.web.state import ServiceState

__all__ = ["router"]

router = APIRouter(prefix="/v1/workspaces/{workspace_id}", tags=["projects"])


#: The role an ordinary write requires. VIEWER can read and nothing else.
_WRITER = require_role(WorkspaceRole.MEMBER)


def _response(record: ProjectRecord) -> ProjectResponse:
    return ProjectResponse(
        workspace_id=record.tenant_id,
        project_id=record.id,
        name=record.name,
        created_at=record.created_at,
    )


@router.post("/projects", status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
def create_project(
    payload: ProjectCreateRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Create a project in the AUTHORISED workspace (RX-47)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    project_id = str(uuid.uuid4())
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        record = uow.create_project(
            project_id=project_id, name=payload.name, created_at=state.now()
        )
    body = _response(record).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


@router.get("/projects", response_model=list[ProjectResponse])
def list_projects(
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[ProjectResponse]:
    """List the authorised workspace's projects, and nothing else (RX-47)."""
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        records = uow.list_projects()
    return [_response(record) for record in records]


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def read_project(
    project_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> ProjectResponse:
    """Read one project, or 404 if it is not in the authorised workspace (RX-47)."""
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        record = uow.get_project(project_id)
    if record is None:
        raise NotFound(
            f"no project {project_id!r} exists in the authorised workspace",
            remedy="list the workspace's projects and use an identifier from that listing",
        )
    return _response(record)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def rename_project(
    project_id: str,
    payload: ProjectRenameRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Rename a project. Cannot move it between tenants (RX-47, RX-49)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        record = uow.rename_project(project_id, payload.name)
    body = _response(record).model_dump(mode="json")
    scope.record(status.HTTP_200_OK, body)
    return JSONResponse(body, status_code=status.HTTP_200_OK)

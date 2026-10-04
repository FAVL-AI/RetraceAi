"""Upload admission and snapshot promotion (RX-01, RX-02, RX-42).

TWO ROUTES, BECAUSE THERE ARE TWO DECISIONS.

``POST .../uploads`` quarantines the bytes and runs admission. Nothing it
accepts is yet part of any project's content: an admitted upload is a file in a
per-tenant quarantine directory and an index record saying it passed.

``POST .../snapshots`` promotes an admitted upload into an immutable,
content-addressed snapshot. A refused upload has no promotion route - the
snapshot route looks the upload up in the index and refuses unless the recorded
admission says it passed, so a caller cannot skip admission by going straight to
promotion with an upload identifier.

WHAT THE RESPONSE DOES NOT SAY.

It reports what was detected and what was admitted. It does not say the content
is valid, parseable, scientifically meaningful or reproducible. A 200 here means
"these bytes are of a declared, known shape within declared limits", and nothing
further.
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import JSONResponse
from retrace_api.web.admission import (
    AdmittedUpload,
    DetectedKind,
    QuarantinedUpload,
    admit_bytes,
    read_capped,
)
from retrace_api.web.dependencies import (
    Authorised,
    AuthorisedWorkspace,
    IdempotencyScope,
    idempotency_scope,
    require_role,
    service_state,
)
from retrace_api.web.errors import NotFound, UploadRefused
from retrace_api.web.identity import WorkspaceRole
from retrace_api.web.promotion import promote_to_snapshot
from retrace_api.web.schemas import SnapshotCreateRequest, SnapshotResponse, UploadResponse
from retrace_api.web.snapshots import load_manifest, store_manifest
from retrace_api.web.state import ServiceState
from retrace_domain import ContentAddressedStore

__all__ = ["router"]

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/projects/{project_id}", tags=["sources"])

_WRITER = require_role(WorkspaceRole.MEMBER)


def _require_project(state: ServiceState, auth: AuthorisedWorkspace, project_id: str) -> None:
    """404 unless the project is in the authorised workspace (RX-47, RX-49)."""
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        if uow.get_project(project_id) is None:
            raise NotFound(
                f"no project {project_id!r} exists in the authorised workspace",
                remedy="create the project first, or use an identifier from the listing",
            )


@router.post("/uploads", status_code=status.HTTP_201_CREATED, response_model=UploadResponse)
def upload_source(
    project_id: str,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
    file: Annotated[UploadFile, File(description="the source document or archive")],
) -> JSONResponse:
    """Quarantine bytes, then run every admission rule over them (RX-42)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    _require_project(state, auth, project_id)
    quarantine = state.quarantine()
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    policy = state.admission_policy
    data = read_capped(file.file, policy)
    upload_id = str(uuid.uuid4())
    declared = (file.content_type or "application/octet-stream").strip()
    filename = (file.filename or "").strip()
    quarantined = quarantine.store(
        tenant_id=auth.tenant_id,
        project_id=project_id,
        upload_id=upload_id,
        filename=filename or "unnamed",
        declared_content_type=declared,
        data=data,
        received_at=state.now(),
    )
    index = workspace.index("uploads")
    try:
        detected, members = admit_bytes(
            data, filename=filename, declared_content_type=declared, policy=policy
        )
    except UploadRefused as refusal:
        # The refusal is recorded against the quarantined bytes. It is NOT
        # promoted and has no snapshot, so the record is the only thing that
        # refers to it - which is what makes the refusal auditable without the
        # payload becoming part of the project.
        index.append(
            {
                "id": upload_id,
                "project_id": project_id,
                "admitted": False,
                "reason": str(refusal.extra.get("reason", "unknown")),
                "filename": quarantined.filename,
                "declared_content_type": declared,
                "byte_count": quarantined.byte_count,
                "sha256": quarantined.sha256,
                "received_at": quarantined.received_at.isoformat(),
            }
        )
        raise
    index.append(
        {
            "id": upload_id,
            "project_id": project_id,
            # Recorded so promotion can check the stored path against the tenant
            # it claims to belong to, rather than opening whatever path the
            # record happens to carry.
            "tenant_id": auth.tenant_id,
            "admitted": True,
            "detected_kind": detected.value,
            "member_paths": list(members),
            "filename": quarantined.filename,
            "declared_content_type": declared,
            "byte_count": quarantined.byte_count,
            "sha256": quarantined.sha256,
            "path": str(quarantined.path),
            "received_at": quarantined.received_at.isoformat(),
        }
    )
    body = UploadResponse(
        workspace_id=auth.tenant_id,
        project_id=project_id,
        upload_id=upload_id,
        filename=quarantined.filename,
        byte_count=quarantined.byte_count,
        sha256=quarantined.sha256,
        detected_kind=detected.value,
        member_count=len(members),
        admitted=True,
    ).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


def _admitted_from_record(
    record: dict[str, Any], state: ServiceState, *, tenant_id: str, quarantine_root: Path
) -> AdmittedUpload:
    """Rebuild an admitted upload from its index record, checking its path.

    The recorded ``path`` is what promotion is about to open, so it is verified
    against the authorised tenant's quarantine directory before anything reads
    it. The index is server-written and tenant-scoped, so a record naming
    another tenant's file should be impossible - which is exactly why a bug that
    made it possible would otherwise be silent. The check is cheap and it is at
    the point of the read.
    """
    recorded_tenant = str(record.get("tenant_id", ""))
    if recorded_tenant and recorded_tenant != tenant_id:
        raise UploadRefused(
            "the upload record names a different tenant from the authorised workspace; "
            "it was not read",
            remedy="upload the source into this workspace",
            extra={"reason": "upload-tenant-mismatch"},
        )
    path = Path(str(record["path"])).resolve()
    permitted = (quarantine_root / tenant_id).resolve()
    if path != permitted and permitted not in path.parents:
        raise UploadRefused(
            "the upload record names a path outside the authorised workspace's "
            "quarantine directory; it was not read",
            remedy="re-upload the source",
            extra={"reason": "quarantine-path-escape"},
        )
    quarantined = QuarantinedUpload(
        upload_id=str(record["id"]),
        tenant_id=tenant_id,
        project_id=str(record["project_id"]),
        filename=str(record["filename"]),
        declared_content_type=str(record["declared_content_type"]),
        byte_count=int(record["byte_count"]),
        sha256=str(record["sha256"]),
        path=Path(str(record["path"])),
        received_at=state.now(),
    )
    return AdmittedUpload(
        quarantined=quarantined,
        detected_kind=DetectedKind(str(record["detected_kind"])),
        member_paths=tuple(str(m) for m in record.get("member_paths", ())),
    )


@router.post("/snapshots", status_code=status.HTTP_201_CREATED, response_model=SnapshotResponse)
def create_snapshot(
    project_id: str,
    payload: SnapshotCreateRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Promote an ADMITTED upload to an immutable snapshot (RX-01, RX-42)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    _require_project(state, auth, project_id)
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    record = workspace.index("uploads").latest(payload.upload_id)
    if record is None or record.get("project_id") != project_id:
        raise NotFound(
            f"no upload {payload.upload_id!r} exists in this project",
            remedy="upload the source first",
        )
    if not record.get("admitted"):
        raise UploadRefused(
            f"upload {payload.upload_id!r} did not pass admission, so it cannot be "
            "promoted to a snapshot",
            remedy="correct the payload and upload it again",
            extra={"reason": str(record.get("reason", "unknown"))},
        )
    quarantine = state.quarantine()
    admitted = _admitted_from_record(
        record, state, tenant_id=auth.tenant_id, quarantine_root=quarantine.root
    )
    data = quarantine.read(admitted.quarantined)
    staging_root = workspace.root / "_staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="snap-", dir=str(staging_root)))
    try:
        manifest = promote_to_snapshot(
            admitted,
            data,
            store=workspace.store,
            staging=staging,
            policy=state.admission_policy,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    manifest_blob = store_manifest(workspace.store, manifest)
    workspace.index("snapshots").append(
        {
            "id": manifest.manifest_digest,
            "project_id": project_id,
            "upload_id": payload.upload_id,
            "manifest_blob": manifest_blob,
            "file_count": len(manifest.paths),
            "created_at": state.now().isoformat(),
        }
    )
    body = SnapshotResponse(
        workspace_id=auth.tenant_id,
        project_id=project_id,
        snapshot_id=manifest.manifest_digest,
        manifest_digest=manifest.manifest_digest,
        file_count=len(manifest.paths),
        files=tuple(manifest.paths),
    ).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


@router.get("/snapshots", response_model=list[SnapshotResponse])
def list_snapshots(
    project_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[SnapshotResponse]:
    """List this project's snapshots within the authorised workspace (RX-47)."""
    _require_project(state, auth, project_id)
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    store = workspace.store
    out: list[SnapshotResponse] = []
    for record in workspace.index("snapshots").distinct():
        if record.get("project_id") != project_id:
            continue
        files = _files_for(store, record)
        out.append(
            SnapshotResponse(
                workspace_id=auth.tenant_id,
                project_id=project_id,
                snapshot_id=str(record["id"]),
                manifest_digest=str(record["id"]),
                file_count=len(files),
                files=files,
            )
        )
    return out


def _files_for(store: ContentAddressedStore, record: dict[str, Any]) -> tuple[str, ...]:
    blob = record.get("manifest_blob")
    if not blob:
        return ()
    return tuple(load_manifest(store, str(blob)).paths)

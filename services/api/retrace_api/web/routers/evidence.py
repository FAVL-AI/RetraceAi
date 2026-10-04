"""Evidence export and provenance-preserving import (RX-15, RX-16, RX-47).

IMPORT IS WHERE A TENANCY MISTAKE WOULD BE WORST, SO IT IS THE MOST EXPLICIT.

An evidence package is produced by someone else. It carries identifiers that
meant something where it was made: a bundle id, a contract id, a project id and
- inside the embedded result contract - a TENANT id. Every one of those is DATA
here. The import:

* records them under ``provenance``, unchanged;
* creates NEW destination records with freshly minted identifiers in the
  authorised destination tenant;
* writes an ``identifier_mapping`` from each origin identifier to what it became;
* drops the origin's ``approval_ref`` and sets the destination contract's status
  to ``DRAFT``, because an approval granted in another workspace approves nothing
  here;
* reports ``granted_from_origin`` as an EMPTY list, which is the assertion made
  explicit rather than left implicit.

The origin tenant id never reaches a membership lookup, never reaches
``set_config('retrace.tenant_id', ...)``, and never appears in a path a handler
builds. ``tests/api/test_evidence_import.py`` carries a package whose embedded
contract names a foreign tenant and shows it grants no read and no write in the
destination.

THE PACKAGE ITSELF IS NOT EDITED.

The bytes are stored in the destination's content-addressed store exactly as
received, and the response reports the package digest BEFORE and AFTER the
import so a reader can see the two agree. ``import_bundle`` extracts into a
fresh directory and verifies every recorded digest; a tampered package is
refused and leaves nothing behind.

WHAT THE EXPORTED BUNDLE CLAIMS, AND WHAT IT DOES NOT.

The outcome written into an exported bundle is ``BLOCKED_MISSING_EVIDENCE``, and
it is the SERVER's value - there is no request field for it. That is what is
true while execution is gated by T2: no run has produced outputs, so nothing has
been verified. The bundle's limitations say so, name the gate, and state that
the environment manifest describes the API process rather than an execution
environment.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import platform
import shutil
import sys
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import JSONResponse
from retrace_api.web.admission import read_capped
from retrace_api.web.contract_store import resolve_contract, store_contract
from retrace_api.web.dependencies import (
    Authorised,
    AuthorisedWorkspace,
    IdempotencyScope,
    idempotency_scope,
    require_role,
    service_state,
)
from retrace_api.web.errors import EvidenceImportRefused, NotFound
from retrace_api.web.execution import ENVIRONMENT_POLICY_DIGEST
from retrace_api.web.identity import WorkspaceRole
from retrace_api.web.schemas import (
    EvidenceExportRequest,
    EvidenceExportResponse,
    EvidenceImportResponse,
)
from retrace_api.web.snapshots import resolve_snapshot, store_manifest
from retrace_api.web.state import ServiceState
from retrace_contracts import (
    Attestation,
    ContractStatus,
    EnvironmentManifest,
    ResultContract,
    VerificationOutcome,
)
from retrace_domain import store_reader
from retrace_verifier import (
    BundleIntegrityError,
    BundleMember,
    BundleRefused,
    build_bundle,
    import_bundle,
)

__all__ = ["EXPORT_LIMITATIONS", "NON_CERTIFICATION", "router"]

router = APIRouter(prefix="/v1/workspaces/{workspace_id}/evidence", tags=["evidence"])

_WRITER = require_role(WorkspaceRole.MEMBER)

#: Every exported bundle carries these, in addition to the contract's own.
#: RX-15 requires a non-empty limitations section; these are the ones that are
#: true of every bundle this build can produce.
EXPORT_LIMITATIONS: tuple[str, ...] = (
    "No execution occurred: threat T2 is measured and OPEN, so the run endpoint "
    "refuses and no outputs were produced. The outcome is BLOCKED_MISSING_EVIDENCE.",
    "The environment manifest describes the API process that built this bundle, "
    "not an execution environment, and its package list is deliberately empty "
    "rather than a list that would imply a run.",
    "The attestation is UNSIGNED. No signing key is provisioned, so bundle "
    "authenticity is not established (threat T7).",
)

NON_CERTIFICATION: str = (
    "This bundle is a readiness artefact, not a certification. No penetration test, "
    "external review or audit has been performed, and passing a result contract "
    "establishes agreement with its declared checks only - never the correctness of "
    "the reference data, the adequacy of the methodology, or the truth of the "
    "conclusion."
)


def _environment_manifest(now: dt.datetime) -> EnvironmentManifest:
    """The API process's environment, bound to the gated execution policy."""
    return EnvironmentManifest(
        python_version=sys.version.split()[0],
        platform=platform.platform(),
        packages={},
        policy_digest=ENVIRONMENT_POLICY_DIGEST,
        captured_at=now,
    )


@router.post("/exports", status_code=status.HTTP_201_CREATED, response_model=EvidenceExportResponse)
def export_evidence(
    payload: EvidenceExportRequest,
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
) -> JSONResponse:
    """Build an evidence bundle for a contract in the authorised workspace (RX-15)."""
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    _record, contract = resolve_contract(workspace, payload.contract_id)
    _snapshot_record, manifest = resolve_snapshot(workspace, snapshot_id=payload.snapshot_id)
    now = state.now()
    read = store_reader(workspace.store, manifest)
    evidence: list[BundleMember] = [
        BundleMember(
            ref_id=f"snapshot-file-{index}",
            path=f"snapshot/files/{relative}",
            data=read(relative),
            role="input-snapshot-file",
        )
        for index, relative in enumerate(manifest.paths)
    ]
    snapshot_member = BundleMember(
        ref_id="snapshot-manifest",
        path="snapshot/manifest.json",
        data=workspace.store.get_bytes(
            store_manifest(workspace.store, manifest)
        ),
        role="input-snapshot",
        media_type="application/json",
    )
    export_id = str(uuid.uuid4())
    destination = workspace.evidence_dir / f"{export_id}.zip"
    built = build_bundle(
        destination,
        bundle_id=export_id,
        created_by=auth.actor,
        created_at=now,
        contract_hash=contract.contract_hash,
        snapshot=snapshot_member,
        environment_manifest=_environment_manifest(now),
        # Server-established. No request field carries an outcome (RX-11, RX-12).
        outcome=VerificationOutcome.BLOCKED_MISSING_EVIDENCE,
        limitations=(*contract.limitations, *EXPORT_LIMITATIONS),
        attestation=Attestation(
            attested_by=auth.actor,
            attested_at=now,
            statement=(
                "Exported from RETRACE with the execution gate engaged; the bundle "
                "records a declaration and its pinned inputs, and no verified result."
            ),
            non_certification_statement=NON_CERTIFICATION,
            method="unsigned-declaration",
        ),
        evidence=evidence,
        contract=contract,
    )
    package_bytes = destination.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    workspace.index("exports").append(
        {
            "id": export_id,
            "project_id": contract.project_id,
            "contract_id": contract.contract_id,
            "snapshot_id": payload.snapshot_id,
            "bundle_digest": built.bundle_digest,
            "package_sha256": package_sha256,
            "outcome": VerificationOutcome.BLOCKED_MISSING_EVIDENCE.value,
            "exported_by": auth.actor,
            "exported_at": now.isoformat(),
        }
    )
    body = EvidenceExportResponse(
        workspace_id=auth.tenant_id,
        export_id=export_id,
        bundle_id=built.manifest.bundle_id,
        bundle_digest=built.bundle_digest,
        package_sha256=package_sha256,
        contract_hash=contract.contract_hash,
        outcome=VerificationOutcome.BLOCKED_MISSING_EVIDENCE.value,
        member_paths=built.member_paths,
    ).model_dump(mode="json")
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


@router.get("/exports")
def list_exports(
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> list[dict[str, Any]]:
    """List the authorised workspace's exports (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    return [dict(record) for record in workspace.index("exports").distinct()]


@router.post("/imports", status_code=status.HTTP_201_CREATED, response_model=EvidenceImportResponse)
def import_evidence(
    auth: Annotated[AuthorisedWorkspace, Depends(_WRITER)],
    state: Annotated[ServiceState, Depends(service_state)],
    scope: Annotated[IdempotencyScope, Depends(idempotency_scope)],
    project_id: Annotated[str, Form(min_length=1, max_length=128)],
    package: Annotated[UploadFile, File(description="an evidence bundle zip")],
) -> JSONResponse:
    """Import an evidence package as PROVENANCE and create destination records.

    Serves RX-16 and RX-47. Nothing in the package grants anything here.
    """
    if scope.replay is not None:
        return JSONResponse(scope.replay.body, status_code=scope.replay.status_code)
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    with state.repository.unit_of_work(auth.tenant_id) as uow:
        if uow.get_project(project_id) is None:
            raise NotFound(
                f"no project {project_id!r} exists in the authorised workspace",
                remedy="create the destination project first",
            )
    data = read_capped(package.file, state.admission_policy)
    package_sha256 = hashlib.sha256(data).hexdigest()
    # Stored BEFORE extraction and never rewritten: the original package is the
    # thing whose digest is being preserved.
    stored_digest = workspace.store.put_bytes(data)
    import_id = str(uuid.uuid4())
    staging = workspace.root / "_imports" / import_id
    staging.parent.mkdir(parents=True, exist_ok=True)
    package_path = workspace.root / "_imports" / f"{import_id}.zip"
    package_path.write_bytes(data)
    try:
        imported = import_bundle(package_path, staging)
    except (BundleRefused, BundleIntegrityError) as refusal:
        shutil.rmtree(staging, ignore_errors=True)
        raise EvidenceImportRefused(
            f"the evidence package was refused: {refusal}",
            remedy="import an unmodified package produced by a compatible exporter",
            extra={"reason": type(refusal).__name__},
        ) from refusal
    try:
        origin = imported.contract
        if origin is None:
            raise EvidenceImportRefused(
                "the package carries no result contract, so there is nothing to create "
                "in the destination workspace",
                remedy="export the bundle with its contract included",
                extra={"reason": "bundle-has-no-contract"},
            )
        destination_contract_id = str(uuid.uuid4())
        destination = ResultContract.model_validate(
            {
                **origin.model_dump(mode="python"),
                # Newly authorised destination identity. The origin's tenant,
                # contract id, status and approval reference are NOT carried.
                "contract_id": destination_contract_id,
                "tenant_id": auth.tenant_id,
                "project_id": project_id,
                "status": ContractStatus.DRAFT,
                "approval_ref": None,
            }
        )
        blob = store_contract(workspace.store, destination)
        now = state.now()
        provenance: dict[str, Any] = {
            "origin_bundle_id": imported.manifest.bundle_id,
            "origin_bundle_digest": imported.bundle_digest,
            "origin_contract_id": origin.contract_id,
            "origin_tenant_id": origin.tenant_id,
            "origin_project_id": origin.project_id,
            "origin_contract_hash": origin.contract_hash,
            "origin_declaration_digest": origin.declaration_digest,
            "origin_status": origin.status.value,
            "origin_approval_ref": origin.approval_ref,
            "origin_outcome": imported.outcome.value,
            "origin_created_by": imported.manifest.created_by,
            "origin_attested_by": imported.attestation.attested_by,
            "package_sha256": package_sha256,
            "stored_package_digest": stored_digest,
        }
        mapping = {
            origin.contract_id: destination_contract_id,
            origin.project_id: project_id,
            origin.tenant_id: auth.tenant_id,
        }
        workspace.index("contracts").append(
            {
                "id": destination.contract_id,
                "project_id": project_id,
                "document_blob": blob,
                "contract_hash": destination.contract_hash,
                "declaration_digest": destination.declaration_digest,
                "status": destination.status.value,
                "imported_from": import_id,
                "created_at": now.isoformat(),
            }
        )
        with state.repository.unit_of_work(auth.tenant_id) as uow:
            uow.create_contract(
                contract_id=destination.contract_id,
                project_id=project_id,
                contract_hash=destination.contract_hash,
            )
        report_id = str(uuid.uuid4())
        workspace.index("reports").append(
            {
                "id": report_id,
                "contract_hash": imported.contract_hash,
                "outcome": imported.outcome.value,
                "reason": (
                    "outcome as recorded by the origin package; NOT independently "
                    "recomputed in this workspace, because execution is gated by T2"
                ),
                "verifier_identity": imported.attestation.attested_by,
                "verified_at": imported.manifest.created_at.isoformat(),
                "independently_recomputed": False,
                "source": "imported-evidence",
                "import_id": import_id,
            }
        )
        workspace.index("imports").append(
            {
                "id": import_id,
                "project_id": project_id,
                "destination_contract_id": destination.contract_id,
                "report_id": report_id,
                "provenance": provenance,
                "identifier_mapping": mapping,
                "granted_from_origin": [],
                "imported_by": auth.actor,
                "imported_at": now.isoformat(),
            }
        )
        after = hashlib.sha256(workspace.store.get_bytes(stored_digest)).hexdigest()
        body = EvidenceImportResponse(
            workspace_id=auth.tenant_id,
            import_id=import_id,
            package_sha256=package_sha256,
            package_sha256_after_import=after,
            bundle_digest=imported.bundle_digest,
            destination_contract_id=destination.contract_id,
            destination_project_id=project_id,
            provenance=provenance,
            identifier_mapping=mapping,
            # Explicit, and empty. An origin identifier confers no access.
            granted_from_origin=(),
        ).model_dump(mode="json")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    scope.record(status.HTTP_201_CREATED, body)
    return JSONResponse(body, status_code=status.HTTP_201_CREATED)


@router.get("/imports/{import_id}")
def read_import(
    import_id: str,
    auth: Authorised,
    state: Annotated[ServiceState, Depends(service_state)],
) -> dict[str, Any]:
    """Read one import record, or 404 outside the authorised workspace (RX-47)."""
    workspace = state.workspaces.for_tenant(auth.tenant_id)
    record = workspace.index("imports").latest(import_id)
    if record is None:
        raise NotFound(
            f"no import {import_id!r} exists in the authorised workspace",
            remedy="list the workspace's imports",
        )
    return dict(record)

"""External request and response models (RX-44, RX-47).

THE REQUEST MODELS ARE THE FIRST TENANCY CONTROL, NOT THE LAST.

Authorisation can only be got right if the request cannot express the thing
being authorised. Every model here forbids unknown fields AND is checked at
import time against :data:`REFUSED_EXTERNAL_FIELDS`: if a developer adds a
``tenant_id``, an ``actor_id``, a ``status``, an approval reference, a signature
or a verdict to a request model, the module fails to import. That is deliberately
louder than a review comment, because the mistake it prevents is the one that
does not look like a mistake - a field that "just passes through".

The guard is on REQUEST models only. A response may of course report the tenant
it was read in and the status the server established; refusing those would make
the API unusable without making it safer.

``ResultContractDraft`` from ``packages/contracts`` is the create model for a
contract and is NOT redefined here. It already omits every server-established
field and already forbids extras, and restating it would create a second place
for the boundary to drift.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "REFUSED_EXTERNAL_FIELDS",
    "ApprovalRequest",
    "ContractResponse",
    "EvidenceExportRequest",
    "EvidenceExportResponse",
    "EvidenceImportResponse",
    "ExternalModel",
    "ProjectCreateRequest",
    "ProjectRenameRequest",
    "ProjectResponse",
    "ProposalCreateRequest",
    "ProposalResponse",
    "RefusedFieldInRequestModel",
    "ReviewCreateRequest",
    "ReviewResponse",
    "RunRequest",
    "SessionResponse",
    "SnapshotCreateRequest",
    "SnapshotResponse",
    "UploadResponse",
    "VerificationReportResponse",
]

#: Names no external request model may declare (RX-47).
#:
#: Four groups, each for a different reason. **Tenancy** (`tenant_id`, `tenant`,
#: `workspace`) decides which rows row-level security reveals. **Actor**
#: (`actor_id`, `subject`, `created_by`, `role`) decides who the server believes
#: is asking. **Authority** (`status`, `approved`, `approval_ref`, `signature`)
#: is the approval claim itself. **Judgement** (`verdict`, `outcome`,
#: `check_status`) is the verifier's conclusion, which no caller may assert.
REFUSED_EXTERNAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "tenant_id",
        "tenant",
        "workspace",
        "workspace_id",
        "actor_id",
        "actor",
        "principal",
        "subject",
        "created_by",
        "role",
        "roles",
        "permissions",
        "status",
        "approved",
        "approval_ref",
        "approval_id",
        "approval_status",
        "signature",
        "signatures",
        "attestation",
        "verdict",
        "outcome",
        "check_status",
        "execution_status",
        "reproduced",
        "contract_hash",
        "declaration_digest",
        "candidate_hash",
    }
)


class RefusedFieldInRequestModel(TypeError):
    """A request model declared a field the server must establish itself."""


class ExternalModel(BaseModel):
    """Base for every request body this service accepts.

    ``extra="forbid"`` so an unexpected field is refused rather than ignored;
    ``frozen=True`` so a handler cannot mutate the validated payload and then
    reason about the mutated copy.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        # `__pydantic_init_subclass__` rather than `__init_subclass__`: pydantic
        # collects `model_fields` AFTER the class body is executed, so the plain
        # hook would inspect an empty mapping and the guard would never fire.
        super().__pydantic_init_subclass__(**kwargs)
        declared = set(getattr(cls, "model_fields", {}) or {})
        offending = sorted(declared & REFUSED_EXTERNAL_FIELDS)
        if offending:
            raise RefusedFieldInRequestModel(
                f"{cls.__name__} declares {offending}, which the server establishes from "
                "the authenticated session, the ledger or the verifier. Remove the "
                "field; do not accept it and overwrite it."
            )


class ResponseModel(BaseModel):
    """Base for responses. Frozen, but free to report server-established values."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProjectCreateRequest(ExternalModel):
    """Create a project inside the authorised workspace (RX-47)."""

    name: str = Field(min_length=1, max_length=200)


class ProjectRenameRequest(ExternalModel):
    """Rename a project.

    The ordinary edit. It carries a name and nothing else, which is why it
    cannot move the project to another tenant: there is no field for that, and
    the repository's update statement has no tenant parameter either.
    """

    name: str = Field(min_length=1, max_length=200)


class ProjectResponse(ResponseModel):
    workspace_id: str
    project_id: str
    name: str
    created_at: dt.datetime


class UploadResponse(ResponseModel):
    """What admission decided about an upload (RX-42)."""

    workspace_id: str
    project_id: str
    upload_id: str
    filename: str
    byte_count: int
    sha256: str
    detected_kind: str
    member_count: int
    admitted: bool


class SnapshotCreateRequest(ExternalModel):
    """Promote an ADMITTED upload to an immutable snapshot (RX-01, RX-42)."""

    upload_id: str = Field(min_length=1, max_length=128)


class SnapshotResponse(ResponseModel):
    workspace_id: str
    project_id: str
    snapshot_id: str
    manifest_digest: str
    file_count: int
    files: tuple[str, ...]


class ContractResponse(ResponseModel):
    """A persisted contract as the server holds it.

    ``status`` and ``approval_ref`` are reported, never accepted: the create
    model omits them and the ledger establishes them.
    """

    workspace_id: str
    project_id: str
    contract_id: str
    version: int
    status: str
    reference_kind: str
    contract_hash: str
    declaration_digest: str
    approval_ref: str | None
    approved_in_ledger: bool
    permits_reproduced_outcome: bool


class ProposalCreateRequest(ExternalModel):
    """Propose a repair as a reviewable patch against a named snapshot (RX-06).

    The proposed content is submitted; the DIFF and the candidate digest are
    computed by the server from the snapshot's stored bytes. A client-supplied
    diff would let the recorded patch disagree with the recorded candidate hash,
    and the hash is what an approval binds.
    """

    snapshot_id: str = Field(min_length=1, max_length=128)
    target_path: str = Field(min_length=1, max_length=4096)
    proposed_content: str = Field(min_length=1, max_length=1_048_576)
    rationale: str = Field(min_length=1, max_length=4096)


class ProposalResponse(ResponseModel):
    workspace_id: str
    project_id: str
    proposal_id: str
    snapshot_id: str
    target_path: str
    candidate_hash: str
    provider: str
    proposed_by: str
    unified_diff: str
    review_count: int


class ReviewCreateRequest(ExternalModel):
    """Record that a human reviewed a proposal (RX-62 in spirit).

    Carries NOTES, not a decision. A review is evidence that someone looked; the
    authority step is the separate approval route, and keeping them separate is
    what lets the approval require a reviewer who is not the proposer.
    """

    proposal_id: str = Field(min_length=1, max_length=128)
    notes: str = Field(min_length=1, max_length=4096)


class ReviewResponse(ResponseModel):
    workspace_id: str
    review_id: str
    proposal_id: str
    reviewed_by: str
    reviewed_at: dt.datetime
    notes: str


class ApprovalRequest(ExternalModel):
    """Request that a reviewed proposal be approved against a contract (RX-04, RX-05).

    Carries only the two identifiers. Every bound field of the approval -
    contract declaration digest, candidate hash, input snapshot id, environment
    policy digest, action digest - is derived server-side from the stored
    objects, so the approval binds what is actually there rather than what the
    caller says is there.
    """

    contract_id: str = Field(min_length=1, max_length=128)
    proposal_id: str = Field(min_length=1, max_length=128)


class RunRequest(ExternalModel):
    """Request execution of an approved candidate (RX-08).

    Accepted, validated, authorised - and then refused while T2 is open. The
    model exists so the refusal is reached by a well-formed request rather than
    by a validation error, which is what makes the gate demonstrable.
    """

    contract_id: str = Field(min_length=1, max_length=128)
    snapshot_id: str = Field(min_length=1, max_length=128)


class EvidenceExportRequest(ExternalModel):
    """Export an evidence bundle for a contract (RX-15).

    No outcome field. The outcome written into the bundle is the server's, and
    while execution is gated it is ``BLOCKED_MISSING_EVIDENCE`` - because that is
    what is true.
    """

    contract_id: str = Field(min_length=1, max_length=128)
    snapshot_id: str = Field(min_length=1, max_length=128)


class EvidenceExportResponse(ResponseModel):
    workspace_id: str
    export_id: str
    bundle_id: str
    bundle_digest: str
    package_sha256: str
    contract_hash: str
    outcome: str
    member_paths: tuple[str, ...]


class EvidenceImportResponse(ResponseModel):
    """What an import created, and what it merely RECORDED (RX-16, RX-47).

    ``provenance`` holds the origin package's own identifiers, including its
    tenant. They are data. ``identifier_mapping`` says which destination object
    each origin identifier became. Nothing in ``provenance`` grants anything.
    """

    workspace_id: str
    import_id: str
    package_sha256: str
    package_sha256_after_import: str
    bundle_digest: str
    destination_contract_id: str
    destination_project_id: str
    provenance: dict[str, Any]
    identifier_mapping: dict[str, str]
    granted_from_origin: tuple[str, ...]


class VerificationReportResponse(ResponseModel):
    """A verification report, read-only (RX-11, RX-12).

    There is no request model that carries any of these fields. The only way a
    report enters the system is by independent recomputation or by importing a
    signed-shaped evidence package, and in both cases the verifier wrote it.
    """

    workspace_id: str
    report_id: str
    contract_hash: str
    outcome: str
    reason: str
    verifier_identity: str
    verified_at: dt.datetime
    independently_recomputed: bool
    source: str


class SessionResponse(ResponseModel):
    """What the holder of a session may learn about it (RX-45)."""

    subject: str
    display_name: str
    expires_at: dt.datetime
    workspaces: tuple[dict[str, str], ...]

"""Typed, actionable refusals for the HTTP surface (RX-44, RX-45, RX-47).

WHY EVERY REFUSAL IS A NAMED CODE RATHER THAN A STATUS ALONE.

A bare ``403`` tells a caller it failed and nothing about which gate refused it.
Worse, it makes two very different events indistinguishable in a log: "you are
not a member of that workspace" and "your CSRF token did not match" both become
"forbidden", so an operator cannot tell a misconfigured client from an attempted
cross-tenant read. Every refusal below therefore carries a stable ``code``, the
HTTP status it maps to, a human ``detail``, and a ``remedy`` naming what the
caller can actually do about it.

WHY `NEEDS_CONFIGURATION` IS A REFUSAL AND NOT A DEGRADED MODE.

No identity provider, signing key or secret store is provisioned in this build
(see ``docs/security/THREAT_MODEL.md`` "Out of scope"). The honest response to
"sign me in" is therefore a refusal that names the missing dependency, not a
locally minted credential that would look like authentication while
establishing nothing. :class:`IdentityProviderNotConfigured` is that refusal.

WHY EXECUTION HAS ITS OWN REFUSAL CLASS.

T2 is measured and OPEN: a child process can write the approval ledger, a
reference output, verifier code or a verification verdict, and nothing denies
it. Until execution runs inside the confinement the threat model describes, an
execution endpoint that returned anything success-shaped would be a fabricated
result. :class:`ExecutionBlocked` is the documented blocked state, it names T2,
and it is distinguishable from both an authorisation failure and a server fault.
"""

from __future__ import annotations

from typing import Any, Final

__all__ = [
    "ActorIdentityMismatch",
    "ApiRefusal",
    "ContractApprovalRefused",
    "CrossTenantReferenceRefused",
    "CsrfRefused",
    "EvidenceImportRefused",
    "ExecutionBlocked",
    "IdempotencyRefused",
    "IdentityProviderNotConfigured",
    "NEEDS_CONFIGURATION",
    "NotFound",
    "ServerEstablishedFieldRefused",
    "SessionRequired",
    "T2_BLOCKED_STATE",
    "T2_REFERENCE",
    "TenantContextMissing",
    "UploadRefused",
    "WorkspaceNotAuthorised",
]

#: The single spelling of the unconfigured-dependency status, used so a caller
#: can match one token rather than parsing prose.
NEEDS_CONFIGURATION: Final = "NEEDS_CONFIGURATION"

#: The documented blocked state for execution. Named in the response body so the
#: refusal is machine-readable and cannot be mistaken for a transient outage.
T2_BLOCKED_STATE: Final = "BLOCKED_EXECUTION_NOT_CONFINED"

#: Where the measurement behind that state is recorded. A refusal that cites no
#: evidence is an assertion.
#: Where the execution refusal is justified. Deliberately a FILE plus a heading
#: TEXT rather than a generated anchor: an anchor silently rots when the heading
#: is reworded, and this one already had - the section was renamed when T2's
#: filesystem half was closed. A test asserts the heading still exists, so a
#: future rename breaks a test instead of leaving a dead pointer in an error
#: message a user is meant to follow.
T2_DOCUMENT: Final = "docs/security/THREAT_MODEL.md"
T2_SECTION_HEADING: Final = "## T2 — measured, then half closed."
T2_REFERENCE: Final = f"{T2_DOCUMENT} ({T2_SECTION_HEADING.lstrip('# ').rstrip('.')})"


class ApiRefusal(Exception):
    """Base class for every refusal the HTTP surface raises (RX-44).

    Carries the response status, a stable code, the detail and the remedy. The
    application installs one handler for this class, so a new refusal cannot be
    added without an envelope, and no refusal can leak a stack trace.
    """

    status_code: int = 400
    code: str = "REFUSED"

    def __init__(
        self,
        detail: str,
        *,
        remedy: str,
        code: str | None = None,
        status_code: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.remedy = remedy
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.extra: dict[str, Any] = dict(extra or {})

    def envelope(self) -> dict[str, Any]:
        """The JSON body for this refusal.

        Flat and stable: ``code`` is the branch key for a client, ``detail`` and
        ``remedy`` are for a human, and ``extra`` carries whatever the specific
        gate measured. No field here is derived from request input that has not
        already been validated.
        """
        body: dict[str, Any] = {
            "error": {
                "code": self.code,
                "detail": self.detail,
                "remedy": self.remedy,
            }
        }
        if self.extra:
            body["error"]["context"] = self.extra
        return body


class SessionRequired(ApiRefusal):
    """No authenticated server-managed session accompanied the request (RX-45).

    Raised before any tenant is resolved and before any query is issued. A
    header naming an actor or a tenant does NOT satisfy this: headers are
    request input, and request input cannot authenticate itself.
    """

    status_code = 401
    code = "SESSION_REQUIRED"


class CsrfRefused(ApiRefusal):
    """A mutating request arrived without a matching CSRF token (RX-45).

    Double-submit: the token must be present in both the non-HttpOnly cookie
    and the request header, the two must be equal, and both must equal the token
    the server stored in the session record. Comparing only cookie against
    header would accept a token an attacker set in both places; comparing only
    against the session record would accept a token read out of a cookie by
    script. Both comparisons are required.
    """

    status_code = 403
    code = "CSRF_REFUSED"


class WorkspaceNotAuthorised(ApiRefusal):
    """The session's principal is not a verified member of the named workspace.

    Serves RX-47. The workspace id in the path is a REQUEST, never a grant.
    Membership is resolved from the directory on every request rather than
    cached in the session, so a revoked membership stops working immediately
    instead of surviving until the session expires (RX-39).
    """

    status_code = 403
    code = "WORKSPACE_NOT_AUTHORISED"


class NotFound(ApiRefusal):
    """The object does not exist within the authorised tenant (RX-47).

    Deliberately indistinguishable from "exists, but in another tenant". A
    distinct 403 for the second case would confirm the identifier to a caller
    who must not learn it, which is a cross-tenant read of one bit.
    """

    status_code = 404
    code = "NOT_FOUND"


class ServerEstablishedFieldRefused(ApiRefusal):
    """The payload carried a field the server establishes (RX-47).

    ``tenant_id``, ``actor_id``, ``status``, an approval reference, a signature
    or a verdict. Refused rather than dropped: a client told its submission
    succeeded while the field it cared about was discarded has been misled about
    the thing that matters most.
    """

    status_code = 422
    code = "SERVER_ESTABLISHED_FIELD_REFUSED"


class ActorIdentityMismatch(ApiRefusal):
    """The payload claimed an author other than the authenticated principal.

    Serves RX-45. ``ResultContractDraft.created_by`` is a claim, and the model's
    own docstring says server-side authentication is the authority. This is
    where that is enforced; without it a member could author a contract under a
    colleague's name inside their own tenant.
    """

    status_code = 403
    code = "ACTOR_IDENTITY_MISMATCH"


class IdempotencyRefused(ApiRefusal):
    """The idempotency key is missing, or was reused for a different request.

    Serves RX-53. A reused key with a DIFFERENT request digest is refused rather
    than served the stored response: replaying the first response for a second,
    different request would silently discard the second request.
    """

    status_code = 409
    code = "IDEMPOTENCY_REFUSED"


class UploadRefused(ApiRefusal):
    """The upload failed admission (RX-42).

    ``extra['reason']`` names which admission rule refused it, so a reviewer can
    tell a declared/sniffed type disagreement from a decompression bomb from a
    traversing archive member. The bytes are never promoted out of quarantine.
    """

    status_code = 422
    code = "UPLOAD_REFUSED"


class ContractApprovalRefused(ApiRefusal):
    """A contract-approval operation was refused by the ledger (RX-04, RX-05).

    Raised when the ledger declines to record or to confirm an approval. The
    ledger stays the authority; this class only carries its refusal outward.
    """

    status_code = 409
    code = "CONTRACT_APPROVAL_REFUSED"


class CrossTenantReferenceRefused(ApiRefusal):
    """A write would have related two objects across tenants (RX-49)."""

    status_code = 409
    code = "CROSS_TENANT_REFERENCE_REFUSED"


class EvidenceImportRefused(ApiRefusal):
    """An evidence package failed import (RX-15, RX-42, RX-47)."""

    status_code = 422
    code = "EVIDENCE_IMPORT_REFUSED"


class TenantContextMissing(ApiRefusal):
    """The database tenant context was absent when a query was about to run.

    Serves RX-48. This is a fail-closed internal invariant, not caller error:
    the handler reached the data layer without a transaction-local
    ``retrace.tenant_id``, and under row-level security that would either return
    nothing or - worse, on a pooled connection - inherit whatever the previous
    transaction left behind. The query is NOT issued. Reported as 503 rather
    than 500 so it is distinguishable from an unhandled fault.
    """

    status_code = 503
    code = "TENANT_CONTEXT_MISSING"


class IdentityProviderNotConfigured(ApiRefusal):
    """Real sign-in cannot be performed: no identity provider is configured.

    Serves RX-45. OIDC is the specified mechanism and none is provisioned here,
    so this build cannot authenticate a human. It refuses with
    ``NEEDS_CONFIGURATION`` and names the settings that are absent. No password
    store, password hashing or token minting is implemented: inventing one would
    be custom cryptography, which RX-45 forbids, and it would make the refusal
    disappear without the dependency appearing.
    """

    status_code = 503
    code = "IDENTITY_PROVIDER_NOT_CONFIGURED"

    def __init__(self, detail: str, *, remedy: str, missing: tuple[str, ...] = ()) -> None:
        super().__init__(
            detail,
            remedy=remedy,
            extra={"status": NEEDS_CONFIGURATION, "missing": list(missing)},
        )


class ExecutionBlocked(ApiRefusal):
    """Execution is gated because threat T2 is open and unmitigated.

    Serves RX-08 and the T2 row of ``docs/security/THREAT_MODEL.md``. The
    endpoint exists, authenticates, authorises and validates - and then refuses,
    naming the threat and the blocked state. It is NOT a 500: nothing failed.
    It is NOT a success: nothing ran. ``context.transient`` is false so a client
    does not retry a gate that will not open without a deployment change.
    """

    status_code = 503
    code = "EXECUTION_BLOCKED_T2"

    def __init__(self, detail: str, *, remedy: str, extra: dict[str, Any] | None = None) -> None:
        context: dict[str, Any] = {
            "threat": "T2",
            "blocked_state": T2_BLOCKED_STATE,
            "reference": T2_REFERENCE,
            "transient": False,
        }
        context.update(extra or {})
        super().__init__(detail, remedy=remedy, extra=context)

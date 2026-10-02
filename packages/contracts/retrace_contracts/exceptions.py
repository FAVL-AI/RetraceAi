"""Named exceptions shared across the RETRACE scientific authority layer.

Every other RETRACE package imports these names, so they are defined here with
no dependency on any other module in this package (including ``pydantic``) to
keep the import graph acyclic and the names importable from a minimal context.

Requirement coverage:

* :class:`ContractNotApproved` -- RX-04 (a candidate repair may not be accepted
  against a contract that carries no approval).
* :class:`ApprovalInvalidated` -- RX-05 (altering any bound field invalidates
  the approval).
* :class:`SnapshotIntegrityError` -- RX-02 (a post-hoc edit to stored snapshot
  bytes must be detected).
* :class:`UIPlanRejected` -- RX-22, RX-23 (a generated layout that is not
  schema-valid, not allowlisted, carries executable payloads, or hides a
  protected region must be refused).
* :class:`VerifierAuthorityError` -- RX-07, RX-09 (the verifier runs with its
  own identity and read-only access to references; an authority breach is an
  error, never a silent downgrade).
* :class:`ContractImmutable` -- RX-03 (a hashed contract record is immutable;
  mutation is refused rather than silently re-hashed).

"""

from __future__ import annotations

__all__ = [
    "ApprovalInvalidated",
    "CanonicalisationError",
    "ContractImmutable",
    "ContractNotApproved",
    "RetraceContractError",
    "SnapshotIntegrityError",
    "UIPlanRejected",
    "VerifierAuthorityError",
]


class RetraceContractError(Exception):
    """Base class for every error raised by the RETRACE contracts layer.

    Callers that need to distinguish a contract-layer refusal from an unrelated
    runtime failure catch this type. It is deliberately **not** a subclass of
    ``ValueError`` so that a broad ``except ValueError`` in calling code cannot
    swallow an authority refusal (RX-07).
    """


class ContractNotApproved(RetraceContractError):
    """A result contract was used for acceptance without an approval (RX-04).

    Parameters
    ----------
    message:
        Optional human-readable message. A default is produced from the
        keyword fields when omitted.
    contract_hash:
        The hash of the contract that lacked an approval, when known.
    """

    def __init__(self, message: str | None = None, *, contract_hash: str | None = None) -> None:
        self.contract_hash = contract_hash
        if message is None:
            suffix = f" contract_hash={contract_hash}" if contract_hash else ""
            message = f"result contract is not approved; acceptance refused.{suffix}"
        super().__init__(message)


class ApprovalInvalidated(RetraceContractError):
    """An approval's bound evidence no longer matches what was observed (RX-05).

    The approval binds five fields: ``contract_hash``, ``candidate_hash``,
    ``input_snapshot_id``, ``environment_policy_digest`` and ``action_digest``.
    If any of them differs from the observed value, the approval is void.

    Attributes
    ----------
    field:
        The first bound field (in declaration order) that changed.
    fields:
        Every bound field that changed, in declaration order.
    expected:
        Mapping of changed field name to the value recorded in the approval.
    observed:
        Mapping of changed field name to the value actually observed.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        field: str | None = None,
        fields: tuple[str, ...] = (),
        expected: dict[str, str] | None = None,
        observed: dict[str, str] | None = None,
        approval_id: str | None = None,
    ) -> None:
        self.fields: tuple[str, ...] = tuple(fields) or ((field,) if field else ())
        self.field: str | None = field or (self.fields[0] if self.fields else None)
        self.expected: dict[str, str] = dict(expected or {})
        self.observed: dict[str, str] = dict(observed or {})
        self.approval_id = approval_id
        if message is None:
            named = ", ".join(self.fields) if self.fields else "unknown field"
            where = f" (approval_id={approval_id})" if approval_id else ""
            message = f"approval invalidated: bound field changed: {named}{where}"
        super().__init__(message)


class SnapshotIntegrityError(RetraceContractError):
    """Stored snapshot bytes do not match their recorded digest (RX-02).

    Attributes
    ----------
    path:
        The snapshot-relative path whose bytes failed verification.
    expected_sha256 / observed_sha256:
        The recorded digest and the digest recomputed from the stored bytes.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        path: str | None = None,
        expected_sha256: str | None = None,
        observed_sha256: str | None = None,
    ) -> None:
        self.path = path
        self.expected_sha256 = expected_sha256
        self.observed_sha256 = observed_sha256
        if message is None:
            message = (
                "snapshot integrity check failed"
                + (f" for {path}" if path else "")
                + (
                    f": expected sha256={expected_sha256} observed sha256={observed_sha256}"
                    if expected_sha256 or observed_sha256
                    else ""
                )
            )
        super().__init__(message)


class UIPlanRejected(RetraceContractError):
    """A prompt-generated UI plan was refused (RX-22, RX-23).

    Attributes
    ----------
    reason:
        A machine-readable rejection code. Values come from
        :class:`retrace_contracts.enums.UIPlanRejectionReason`; the attribute is
        typed as ``str`` here so that this module stays import-free.
    detail:
        Human-readable detail naming the offending value.
    path:
        A JSON-pointer-like path to the offending field within the plan, so the
        reviewer can see *where* the plan was refused rather than only *that* it
        was refused.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        reason: str | None = None,
        detail: str | None = None,
        path: str | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail
        self.path = path
        if message is None:
            message = "ui plan rejected" + (f": {reason}" if reason else "")
            if path:
                message += f" at {path}"
            if detail:
                message += f" -- {detail}"
        super().__init__(message)


class VerifierAuthorityError(RetraceContractError):
    """An actor attempted something outside its granted authority (RX-07, RX-09).

    Raised when, for example, the repair worker attempts to write a contract,
    reference output, approval record or verifier source file, or when the
    verifier identity attempts a write against a read-only reference store.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        actor: str | None = None,
        action: str | None = None,
        target: str | None = None,
    ) -> None:
        self.actor = actor
        self.action = action
        self.target = target
        if message is None:
            message = "authority refused" + (
                f": actor={actor} action={action} target={target}"
                if actor or action or target
                else ""
            )
        super().__init__(message)


class ContractImmutable(RetraceContractError):
    """An attempt was made to mutate a frozen, hashed record (RX-03).

    Hashed records (result contracts, approvals, repair proposals, verification
    reports, evidence bundle manifests) are content-addressed. In-place mutation
    would silently detach a record from its digest, so it is refused by name
    rather than by a generic validation error.
    """

    def __init__(
        self,
        message: str | None = None,
        *,
        record: str | None = None,
        field: str | None = None,
    ) -> None:
        self.record = record
        self.field = field
        if message is None:
            message = (
                f"{record or 'record'} is immutable; "
                f"cannot assign to field {field!r}. Build a new record instead."
            )
        super().__init__(message)


class CanonicalisationError(RetraceContractError):
    """A value cannot be placed in canonical form, so no stable digest exists.

    Raised for non-finite floats, timezone-naive datetimes, non-string mapping
    keys and unsupported types. Supports RX-03: rather than emit a digest over a
    non-portable serialisation, canonicalisation fails loudly.
    """

    def __init__(self, message: str, *, path: str | None = None) -> None:
        self.path = path
        super().__init__(f"{message} (at {path})" if path else message)

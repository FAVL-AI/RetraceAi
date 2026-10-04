"""Storing and reloading result contracts (RX-03, RX-04).

THE STORED DOCUMENT IS THE CANONICAL ONE, AND THE HASH IS CHECKED ON THE WAY BACK.

``ResultContract.canonical_document()`` is the exact string the contract's digest
is taken over, so storing that string means the stored bytes and the digest
cannot disagree. On reload the document is parsed, the model revalidated - every
invariant in ``packages/contracts`` runs again - and the resulting
``contract_hash`` compared against the hash the index recorded. A blob edited in
place fails the store's own digest check; a document swapped for a different,
internally consistent contract fails this comparison.

APPROVAL IS NEVER READ FROM THE STORED DOCUMENT.

The document carries ``status`` and ``approval_ref`` because they are part of the
record. Neither is believed: :func:`approval_state` asks the ledger, which
checks the reference resolves to an active approval granted against THIS
declaration digest. A stored ``"APPROVED"`` with a dangling reference therefore
reads as not approved.
"""

from __future__ import annotations

import json
from typing import Any

from retrace_api.web.errors import NotFound
from retrace_api.web.workspace import TenantWorkspace
from retrace_contracts import (
    ApprovalInvalidated,
    ContractNotApproved,
    ResultContract,
)
from retrace_domain import ApprovalLedger, ContentAddressedStore, LedgerIntegrityError

__all__ = ["approval_state", "load_contract", "resolve_contract", "store_contract"]


def store_contract(store: ContentAddressedStore, contract: ResultContract) -> str:
    """Put the canonical contract document in the store and return its digest."""
    return store.put_bytes(contract.canonical_document().encode("utf-8"))


def load_contract(
    store: ContentAddressedStore, blob_digest: str, *, expected_hash: str | None = None
) -> ResultContract:
    """Reconstruct a contract from its stored canonical document (RX-03)."""
    document: Any = json.loads(store.get_bytes(blob_digest).decode("utf-8"))
    payload = document.get("payload") if isinstance(document, dict) else None
    if not isinstance(payload, dict):
        raise ValueError("the stored contract document has no object 'payload'")
    contract = ResultContract.model_validate(payload)
    if expected_hash is not None and contract.contract_hash != expected_hash:
        raise ValueError(
            "the stored contract document's hash does not match the recorded hash"
        )
    return contract


def resolve_contract(
    workspace: TenantWorkspace, contract_id: str
) -> tuple[dict[str, Any], ResultContract]:
    """Find a contract in the authorised workspace, or 404 (RX-47)."""
    record = workspace.index("contracts").latest(contract_id)
    if record is None:
        raise NotFound(
            f"no contract {contract_id!r} exists in the authorised workspace",
            remedy="create the contract first, or use an identifier from the listing",
        )
    blob = record.get("document_blob")
    if not blob:
        raise NotFound(
            f"contract {contract_id!r} has no stored document",
            remedy="re-create the contract",
        )
    contract = load_contract(
        workspace.store, str(blob), expected_hash=str(record.get("contract_hash"))
    )
    return record, contract


def approval_state(ledger: ApprovalLedger, contract: ResultContract) -> tuple[bool, str]:
    """Ask the LEDGER whether this contract is approved (RX-04, RX-05).

    Returns ``(approved, reason)``. Every refusal path is reported as
    not-approved with the ledger's own reason; an integrity failure of the chain
    is reported too rather than being allowed to look like a plain refusal,
    because a broken chain is a far more serious finding than an unapproved
    contract.
    """
    try:
        entry = ledger.verify_contract_approval(contract)
    except ContractNotApproved as refusal:
        return False, f"not approved: {refusal}"
    except ApprovalInvalidated as refusal:
        return False, f"approval invalidated: {refusal}"
    except LedgerIntegrityError as failure:
        return False, f"ledger integrity failure: {failure}"
    return True, f"approved by ledger entry {entry.entry_id}"

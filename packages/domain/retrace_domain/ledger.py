"""Append-only, hash-chained approval ledger (RX-04, RX-05, RX-52).

What this file defends
----------------------
An approval is the only thing that turns a *proposal* into something RETRACE
will act on, so the record of approvals is the highest-value target in the
system. Three properties are enforced here, each with a negative control in
``tests/domain/test_ledger.py``:

1. **Append-only.** Nothing is ever updated or deleted in place. A changed
   decision is recorded by appending a ``SUPERSEDE`` entry that references the
   superseded entry id; the original line stays byte-identical and readable,
   and :meth:`ApprovalLedger.status` reports it as superseded (RX-52).
2. **Tamper-evident middle.** Every entry carries ``previous_digest``, the
   digest of the line before it, and ``entry_digest``, a digest over its own
   content *including* ``previous_digest``. Editing or deleting a line in the
   middle therefore breaks either that line's own digest or the next line's
   chain link, and :meth:`ApprovalLedger.verify_chain` says which line and
   which rule.
3. **Authority is read from the file, after verification.** Every
   ``require_*`` method verifies the chain before answering. A lookup that
   trusted in-memory state, or trusted an unverified file, would let an edited
   ledger grant authority -- which is the whole attack.

Honest limit, stated rather than defended
-----------------------------------------
A hash chain detects edits and deletions *within* the sequence. It cannot, on
its own, detect **truncation of the tail**: removing the last ``k`` lines leaves
a perfectly valid shorter chain, indistinguishable from "fewer approvals were
ever recorded". Detecting that needs an anchor held outside the file, so
:meth:`ApprovalLedger.head_digest` is exposed for exactly that purpose (an
evidence bundle or an external notarisation records it). Until such an anchor
is in place, tail truncation is an accepted, recorded gap -- not a solved
problem.

The clock is never read here. ``recorded_at`` is supplied by the caller, so a
ledger can be reconstructed from evidence and tested deterministically, the
same rule the contracts layer follows for ``approved_at``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import ClassVar, Final

from pydantic import AwareDatetime, Field
from retrace_contracts import (
    Approval,
    ApprovalInvalidated,
    ContractNotApproved,
    FrozenRecord,
    Identifier,
    NonEmptyStr,
    Sha256Hex,
)

from .errors import LedgerAppendRefused, LedgerIntegrityError

__all__ = [
    "GENESIS_DIGEST",
    "LEDGER_ENTRY_TYPE_TAG",
    "ApprovalLedger",
    "EntryStatus",
    "LedgerEntry",
    "LedgerEntryType",
]

GENESIS_DIGEST: Final[str] = "0" * 64
"""``previous_digest`` of the first entry.

A fixed all-zero digest rather than ``None`` so that the chain field has one
type and the genesis link takes part in the first entry's digest like every
other link.
"""

LEDGER_ENTRY_TYPE_TAG: Final[str] = "retrace.ApprovalLedgerEntry"


class LedgerEntryType(str, Enum):
    """What an appended ledger entry asserts (RX-04, RX-05, RX-52).

    ``CONTRACT_APPROVAL`` is the gate RX-04 describes: without an active one,
    no candidate may be accepted against that contract. ``CANDIDATE_APPROVAL``
    is the five-field binding of RX-05. ``SUPERSEDE`` is the only way a
    previous entry's effect is withdrawn.
    """

    CONTRACT_APPROVAL = "CONTRACT_APPROVAL"
    CANDIDATE_APPROVAL = "CANDIDATE_APPROVAL"
    SUPERSEDE = "SUPERSEDE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class EntryStatus(str, Enum):
    """Whether a recorded entry still has effect (RX-52)."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class LedgerEntry(FrozenRecord):
    """One line of the approval ledger (RX-04, RX-05, RX-52).

    Derives from the contracts layer's :class:`FrozenRecord`, so it is frozen,
    rejects unexpected keys when deserialised (the defensive-parsing posture
    RX-10 asks for) and digests through the one specified canonical form.

    ``entry_digest`` is listed in ``CANONICAL_EXCLUDE`` because it *binds to*
    the digest and so cannot take part in computing it -- the single
    legitimate use of that mechanism.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = LEDGER_ENTRY_TYPE_TAG
    CANONICAL_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"entry_digest"})

    sequence: int = Field(ge=0, description="0-based position in the ledger.")
    entry_id: Identifier = Field(description="Stable id of this ledger entry.")
    entry_type: LedgerEntryType = Field(description="What this entry asserts.")
    recorded_at: AwareDatetime = Field(
        description="When the entry was appended; supplied by the caller, never read from a clock."
    )
    previous_digest: Sha256Hex = Field(
        description="entry_digest of the preceding entry, or GENESIS_DIGEST for the first."
    )
    contract_hash: Sha256Hex | None = Field(
        default=None, description="Contract this entry concerns (RX-03)."
    )
    candidate_hash: Sha256Hex | None = Field(
        default=None, description="Candidate this entry concerns (RX-06)."
    )
    approval_id: Identifier | None = Field(
        default=None, description="Id of the embedded approval, when present."
    )
    binding_digest: Sha256Hex | None = Field(
        default=None,
        description=(
            "Digest over the Approval's five bound fields (RX-05). Stored so that a later "
            "candidate, snapshot, policy or action change is detectable against the record."
        ),
    )
    approval: Approval | None = Field(
        default=None, description="The approval record itself, for approval entries."
    )
    superseded_entry_id: Identifier | None = Field(
        default=None, description="For SUPERSEDE: the entry whose effect is withdrawn."
    )
    reason: NonEmptyStr | None = Field(
        default=None, description="Why this entry was appended (required for SUPERSEDE)."
    )
    entry_digest: Sha256Hex = Field(
        description="Digest over every other field of this entry, chaining previous_digest."
    )

    def recompute_digest(self) -> str:
        """Return the digest this entry's content implies (RX-52).

        Equal to :attr:`entry_digest` for an untampered entry. Compared by
        :meth:`ApprovalLedger.verify_chain`.
        """
        return self.content_digest()


def _seal(**payload: object) -> LedgerEntry:
    """Build a :class:`LedgerEntry` whose ``entry_digest`` covers its content.

    Constructed twice on purpose: once with a placeholder digest to obtain the
    content digest (``entry_digest`` is excluded from it), then once more with
    that digest stored. Both constructions run the model's validators, so a
    malformed entry is refused before anything reaches the file.
    """
    provisional = LedgerEntry(entry_digest=GENESIS_DIGEST, **payload)  # type: ignore[arg-type]
    return LedgerEntry(entry_digest=provisional.content_digest(), **payload)  # type: ignore[arg-type]


class ApprovalLedger:
    """An append-only hash-chained ledger of approvals on disk (RX-04, RX-05, RX-52).

    The file is the authority. Entries are re-read and re-verified on every
    query rather than cached, because a cache would answer "is this approved?"
    from memory while the question is about the record.

    Parameters
    ----------
    path:
        JSONL file holding the ledger. Created on first append; a missing file
        is an empty ledger, not an error.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """The ledger file this instance reads and appends to."""
        return self._path

    # -- reading ---------------------------------------------------------

    def entries(self) -> tuple[LedgerEntry, ...]:
        """Parse and return every entry, without chain verification.

        Raises
        ------
        LedgerIntegrityError:
            If a line is not JSON, is not an object, or does not validate as a
            :class:`LedgerEntry`. Parsing is strict: an unexpected key is a
            refusal, not a field to ignore.
        """
        if not self._path.is_file():
            return ()
        parsed: list[LedgerEntry] = []
        with self._path.open("r", encoding="utf-8") as handle:
            for index, raw in enumerate(handle, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError as error:
                    raise LedgerIntegrityError(
                        f"ledger line {index} is not valid JSON",
                        rule="MALFORMED_LINE",
                        line_number=index,
                    ) from error
                if not isinstance(payload, dict):
                    raise LedgerIntegrityError(
                        f"ledger line {index} is not a JSON object",
                        rule="MALFORMED_LINE",
                        line_number=index,
                    )
                try:
                    parsed.append(LedgerEntry.model_validate(payload))
                except Exception as error:
                    raise LedgerIntegrityError(
                        f"ledger line {index} does not validate as a ledger entry: {error}",
                        rule="MALFORMED_LINE",
                        line_number=index,
                    ) from error
        return tuple(parsed)

    def __len__(self) -> int:
        return len(self.entries())

    def __iter__(self) -> Iterator[LedgerEntry]:
        return iter(self.entries())

    def verify_chain(self) -> int:
        """Verify every entry's digest and chain link; return the entry count (RX-52).

        Checks, in order, per line:

        * ``entry_digest`` equals the digest recomputed from the entry's
          content (detects an edited field);
        * ``previous_digest`` equals the preceding entry's ``entry_digest``
          (detects a deleted, reordered or inserted line);
        * ``sequence`` equals the line's 0-based position (a second, independent
          detector for deletion and reordering).

        Raises
        ------
        LedgerIntegrityError:
            Naming the rule and the 1-based line number of the first failure.
        """
        previous = GENESIS_DIGEST
        count = 0
        for index, entry in enumerate(self.entries()):
            line_number = index + 1
            recomputed = entry.recompute_digest()
            if recomputed != entry.entry_digest:
                raise LedgerIntegrityError(
                    rule="ENTRY_DIGEST_MISMATCH",
                    line_number=line_number,
                    expected=entry.entry_digest,
                    observed=recomputed,
                )
            if entry.previous_digest != previous:
                raise LedgerIntegrityError(
                    rule="CHAIN_BREAK",
                    line_number=line_number,
                    expected=previous,
                    observed=entry.previous_digest,
                )
            if entry.sequence != index:
                raise LedgerIntegrityError(
                    rule="SEQUENCE_BREAK",
                    line_number=line_number,
                    expected=str(index),
                    observed=str(entry.sequence),
                )
            previous = entry.entry_digest
            count += 1
        return count

    def head_digest(self) -> str:
        """Return the last entry's ``entry_digest``, or :data:`GENESIS_DIGEST` if empty.

        Exposed so a caller can anchor the ledger head outside the file and
        thereby close the tail-truncation gap documented in this module's
        docstring. The ledger cannot close that gap by itself.
        """
        entries = self.entries()
        return entries[-1].entry_digest if entries else GENESIS_DIGEST

    def status(self, entry_id: str) -> EntryStatus:
        """Return whether ``entry_id`` is still in effect (RX-52).

        Raises
        ------
        LedgerAppendRefused:
            With rule ``UNKNOWN_ENTRY`` if no such entry exists. Reported as a
            refusal rather than ``ACTIVE`` so that a typo cannot read as
            approval.
        """
        entries = self.entries()
        known = {entry.entry_id for entry in entries}
        if entry_id not in known:
            raise LedgerAppendRefused(rule="UNKNOWN_ENTRY", entry_id=entry_id)
        superseded = self._superseded_ids(entries)
        return EntryStatus.SUPERSEDED if entry_id in superseded else EntryStatus.ACTIVE

    def supersession_of(self, entry_id: str) -> LedgerEntry | None:
        """Return the SUPERSEDE entry that withdrew ``entry_id``, if any (RX-52)."""
        for entry in self.entries():
            if (
                entry.entry_type is LedgerEntryType.SUPERSEDE
                and entry.superseded_entry_id == entry_id
            ):
                return entry
        return None

    # -- appending -------------------------------------------------------

    def record_contract_approval(
        self,
        *,
        approval: Approval,
        recorded_at: datetime,
        entry_id: str | None = None,
    ) -> LedgerEntry:
        """Append a contract approval, the gate RX-04 requires.

        Raises
        ------
        LedgerAppendRefused:
            ``DUPLICATE_ENTRY_ID`` if ``entry_id`` is already used.
        LedgerIntegrityError:
            If the existing ledger does not verify. Nothing is chained onto a
            ledger that has already been tampered with.
        """
        return self._append(
            entry_type=LedgerEntryType.CONTRACT_APPROVAL,
            approval=approval,
            recorded_at=recorded_at,
            entry_id=entry_id,
            reason=None,
            superseded_entry_id=None,
        )

    def record_candidate_approval(
        self,
        *,
        approval: Approval,
        recorded_at: datetime,
        entry_id: str | None = None,
    ) -> LedgerEntry:
        """Append a candidate approval carrying the five-field binding (RX-05).

        The entry stores ``binding_digest`` as well as the approval itself, so
        a later change to the candidate, the input snapshot, the environment
        policy or the authorised action is detectable against the record and
        not only against a live object.
        """
        return self._append(
            entry_type=LedgerEntryType.CANDIDATE_APPROVAL,
            approval=approval,
            recorded_at=recorded_at,
            entry_id=entry_id,
            reason=None,
            superseded_entry_id=None,
        )

    def supersede(
        self,
        entry_id: str,
        reason: str,
        *,
        recorded_at: datetime,
        new_entry_id: str | None = None,
    ) -> LedgerEntry:
        """Append an entry withdrawing ``entry_id``'s effect (RX-52).

        The superseded line is untouched and stays readable; only its
        :meth:`status` changes. This is the *only* way an approval's effect
        ends -- there is no update and no delete.

        Raises
        ------
        LedgerAppendRefused:
            ``UNKNOWN_ENTRY`` if ``entry_id`` does not exist;
            ``ALREADY_SUPERSEDED`` if it has already been withdrawn (withdraw
            the superseding entry instead, so the record stays a single chain
            of explicit decisions).
        """
        entries = self.entries()
        known = {entry.entry_id: entry for entry in entries}
        target = known.get(entry_id)
        if target is None:
            raise LedgerAppendRefused(rule="UNKNOWN_ENTRY", entry_id=entry_id)
        if entry_id in self._superseded_ids(entries):
            raise LedgerAppendRefused(rule="ALREADY_SUPERSEDED", entry_id=entry_id)
        return self._append(
            entry_type=LedgerEntryType.SUPERSEDE,
            approval=None,
            recorded_at=recorded_at,
            entry_id=new_entry_id,
            reason=reason,
            superseded_entry_id=entry_id,
            contract_hash=target.contract_hash,
            candidate_hash=target.candidate_hash,
        )

    # -- authority queries -----------------------------------------------

    def require_approved_contract(self, contract_hash: str) -> LedgerEntry:
        """Return the active contract approval for ``contract_hash`` (RX-04).

        Verifies the chain first: an unverified ledger cannot grant authority.

        Raises
        ------
        ContractNotApproved:
            If no contract approval exists for that hash, or every one of them
            has been superseded. A superseded approval is not an approval.
        LedgerIntegrityError:
            If the chain does not verify.
        """
        self.verify_chain()
        entries = self.entries()
        superseded = self._superseded_ids(entries)
        matches = [
            entry
            for entry in entries
            if entry.entry_type is LedgerEntryType.CONTRACT_APPROVAL
            and entry.contract_hash == contract_hash
            and entry.entry_id not in superseded
        ]
        if not matches:
            raise ContractNotApproved(contract_hash=contract_hash)
        return matches[-1]

    def require_approved_candidate(
        self,
        *,
        contract_hash: str,
        candidate_hash: str,
        input_snapshot_id: str,
        environment_policy_digest: str,
        action_digest: str,
    ) -> LedgerEntry:
        """Return the active candidate approval binding exactly these values (RX-05).

        Both gates are applied, in the order the authority rule states: the
        contract must be approved (RX-04), and then the candidate approval's
        five bound fields must still match what is observed (RX-05).

        Raises
        ------
        ContractNotApproved:
            If the contract is unapproved, or no candidate approval exists for
            that contract and candidate.
        ApprovalInvalidated:
            If a candidate approval exists but a bound field has moved. The
            exception names every changed field.
        LedgerIntegrityError:
            If the chain does not verify.
        """
        self.require_approved_contract(contract_hash)
        entries = self.entries()
        superseded = self._superseded_ids(entries)
        matches = [
            entry
            for entry in entries
            if entry.entry_type is LedgerEntryType.CANDIDATE_APPROVAL
            and entry.contract_hash == contract_hash
            and entry.candidate_hash == candidate_hash
            and entry.entry_id not in superseded
        ]
        if not matches:
            raise ContractNotApproved(
                "no active candidate approval binds this candidate to this contract; "
                f"contract_hash={contract_hash} candidate_hash={candidate_hash}",
                contract_hash=contract_hash,
            )
        entry = matches[-1]
        approval = entry.approval
        if approval is None:  # pragma: no cover - guarded at append time
            raise LedgerAppendRefused(rule="APPROVAL_MISSING", entry_id=entry.entry_id)
        approval.validate_binding(
            contract_hash=contract_hash,
            candidate_hash=candidate_hash,
            input_snapshot_id=input_snapshot_id,
            environment_policy_digest=environment_policy_digest,
            action_digest=action_digest,
        )
        if approval.binding_digest != entry.binding_digest:
            raise ApprovalInvalidated(
                "recorded binding_digest does not match the stored approval",
                field="binding_digest",
                fields=("binding_digest",),
                expected={"binding_digest": str(entry.binding_digest)},
                observed={"binding_digest": approval.binding_digest},
                approval_id=approval.approval_id,
            )
        return entry

    # -- internals -------------------------------------------------------

    @staticmethod
    def _superseded_ids(entries: tuple[LedgerEntry, ...]) -> frozenset[str]:
        return frozenset(
            entry.superseded_entry_id
            for entry in entries
            if entry.entry_type is LedgerEntryType.SUPERSEDE and entry.superseded_entry_id
        )

    def _append(
        self,
        *,
        entry_type: LedgerEntryType,
        approval: Approval | None,
        recorded_at: datetime,
        entry_id: str | None,
        reason: str | None,
        superseded_entry_id: str | None,
        contract_hash: str | None = None,
        candidate_hash: str | None = None,
    ) -> LedgerEntry:
        existing = self.entries()
        self.verify_chain()
        sequence = len(existing)
        chosen_id = entry_id or f"led-{sequence:06d}"
        if any(entry.entry_id == chosen_id for entry in existing):
            raise LedgerAppendRefused(rule="DUPLICATE_ENTRY_ID", entry_id=chosen_id)
        if entry_type is LedgerEntryType.SUPERSEDE and not reason:
            raise LedgerAppendRefused(rule="SUPERSEDE_REQUIRES_REASON", entry_id=chosen_id)

        entry = _seal(
            sequence=sequence,
            entry_id=chosen_id,
            entry_type=entry_type,
            recorded_at=recorded_at,
            previous_digest=existing[-1].entry_digest if existing else GENESIS_DIGEST,
            contract_hash=approval.contract_hash if approval else contract_hash,
            candidate_hash=approval.candidate_hash if approval else candidate_hash,
            approval_id=approval.approval_id if approval else None,
            binding_digest=approval.binding_digest if approval else None,
            approval=approval,
            superseded_entry_id=superseded_entry_id,
            reason=reason,
        )
        self._write_line(entry)
        return entry

    def _write_line(self, entry: LedgerEntry) -> None:
        """Append one JSONL line, flushed and fsync-ed before returning.

        ``fsync`` is not decoration: an approval that is acknowledged to a
        reviewer but lost in a page cache on power failure is an approval the
        record cannot defend.
        """
        line = json.dumps(
            entry.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())

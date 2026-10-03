"""The approval ledger: append-only, hash-chained, tamper-evident (RX-04, RX-05, RX-52).

The negative controls are the point of this file. An append-only claim that has
never been tested against an edit, a deletion, a reordering or a forged append
is a claim about intent, not about the artefact. One test deliberately records
the property the chain does **not** have (tail truncation), so that nobody
later reads a passing suite as proof of something it never checked.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import T0, T1, T2, digest
from retrace_contracts import Approval, ApprovalInvalidated, ContractNotApproved
from retrace_domain import (
    GENESIS_DIGEST,
    ApprovalLedger,
    EntryStatus,
    LedgerAppendRefused,
    LedgerEntryType,
    LedgerIntegrityError,
)

CONTRACT = digest("contract")
CANDIDATE = digest("candidate")
POLICY = digest("env-policy")
ACTION = digest("action-accept-candidate")
SNAPSHOT = "snap-0001"

OBSERVED = {
    "contract_hash": CONTRACT,
    "candidate_hash": CANDIDATE,
    "input_snapshot_id": SNAPSHOT,
    "environment_policy_digest": POLICY,
    "action_digest": ACTION,
}


@pytest.fixture
def ledger(tmp_path: Path) -> ApprovalLedger:
    """An empty ledger in the test's temporary directory."""
    return ApprovalLedger(tmp_path / "build" / "approvals.jsonl")


@pytest.fixture
def populated(
    ledger: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> ApprovalLedger:
    """A three-entry ledger: contract approval, candidate approval, second candidate."""
    ledger.record_contract_approval(
        approval=approval_factory(approval_id="ap-contract"),
        recorded_at=T0,
        entry_id="ap-contract",
    )
    ledger.record_candidate_approval(
        approval=approval_factory(approval_id="ap-candidate"),
        recorded_at=T1,
        entry_id="ap-candidate",
    )
    ledger.record_candidate_approval(
        approval=approval_factory(
            approval_id="ap-candidate-2", candidate_hash=digest("candidate-2")
        ),
        recorded_at=T2,
        entry_id="ap-candidate-2",
    )
    return ledger


def rewrite(path: Path, lines: list[str]) -> None:
    """Replace the ledger file's lines -- the hostile act the chain must detect."""
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def read_lines(path: Path) -> list[str]:
    """Return the ledger file's non-empty lines."""
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# The record itself.
# ---------------------------------------------------------------------------


def test_an_empty_ledger_is_not_an_error(ledger: ApprovalLedger) -> None:
    """A ledger with no file yet is empty, not broken."""
    assert ledger.entries() == ()
    assert ledger.verify_chain() == 0
    assert ledger.head_digest() == GENESIS_DIGEST


def test_the_first_entry_chains_to_the_genesis_digest(
    ledger: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> None:
    """RX-52: the genesis link takes part in the first digest like every other link."""
    entry = ledger.record_contract_approval(approval=approval_factory(), recorded_at=T0)
    assert entry.previous_digest == GENESIS_DIGEST
    assert entry.sequence == 0
    assert entry.entry_type is LedgerEntryType.CONTRACT_APPROVAL


def test_each_entry_chains_to_its_predecessor(populated: ApprovalLedger) -> None:
    """RX-52: the chain is the mechanism, so it is asserted link by link."""
    entries = populated.entries()
    assert len(entries) == 3
    previous = GENESIS_DIGEST
    for index, entry in enumerate(entries):
        assert entry.sequence == index
        assert entry.previous_digest == previous
        assert entry.entry_digest == entry.recompute_digest()
        previous = entry.entry_digest
    assert populated.head_digest() == entries[-1].entry_digest


def test_the_chain_verifies_when_reopened_from_disk(populated: ApprovalLedger) -> None:
    """RX-52: the file is the authority, so a fresh reader must reach the same verdict.

    This also pins digest stability across the JSON round-trip: a digest that
    changed when the record was reloaded would make every stored chain invalid.
    """
    assert ApprovalLedger(populated.path).verify_chain() == 3


def test_a_candidate_approval_stores_the_five_field_binding_digest(
    ledger: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> None:
    """RX-05: the binding is recorded, so a later change is detectable against the record."""
    approval = approval_factory()
    entry = ledger.record_candidate_approval(approval=approval, recorded_at=T0)
    assert entry.binding_digest == approval.binding_digest
    assert entry.approval is not None
    assert entry.approval.bound_values == OBSERVED


def test_entry_ids_are_deterministic_when_not_supplied(
    ledger: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> None:
    """A reconstructed ledger must be comparable, so defaults are sequence-derived."""
    first = ledger.record_contract_approval(approval=approval_factory(), recorded_at=T0)
    second = ledger.record_candidate_approval(approval=approval_factory(), recorded_at=T1)
    assert (first.entry_id, second.entry_id) == ("led-000000", "led-000001")


# ---------------------------------------------------------------------------
# Supersession: the only way an approval's effect ends (RX-52).
# ---------------------------------------------------------------------------


def test_supersede_appends_and_leaves_the_original_readable(
    populated: ApprovalLedger,
) -> None:
    """NEGATIVE CONTROL, RX-52: nothing is updated or deleted in place.

    The superseded line must still be byte-identical afterwards. An "amendment"
    that rewrote the original would be exactly the silent edit RX-52 forbids.
    """
    before = read_lines(populated.path)
    entry = populated.supersede(
        "ap-candidate", "superseded by a reviewed second candidate", recorded_at=T2
    )
    after = read_lines(populated.path)

    assert after[: len(before)] == before, "existing lines were rewritten"
    assert len(after) == len(before) + 1
    assert entry.entry_type is LedgerEntryType.SUPERSEDE
    assert entry.superseded_entry_id == "ap-candidate"
    assert entry.reason == "superseded by a reviewed second candidate"

    original = next(item for item in populated.entries() if item.entry_id == "ap-candidate")
    assert original.approval is not None
    assert original.approval.approval_id == "ap-candidate"
    assert populated.status("ap-candidate") is EntryStatus.SUPERSEDED
    assert populated.status("ap-contract") is EntryStatus.ACTIVE
    assert populated.verify_chain() == 4


def test_the_superseding_entry_is_discoverable_from_the_original(
    populated: ApprovalLedger,
) -> None:
    """RX-52: a reader of the original can find the decision that withdrew it."""
    populated.supersede("ap-candidate", "revoked after review", recorded_at=T2)
    supersession = populated.supersession_of("ap-candidate")
    assert supersession is not None
    assert supersession.reason == "revoked after review"
    assert populated.supersession_of("ap-contract") is None


def test_superseding_an_unknown_entry_is_refused(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-52: a typo cannot create a dangling withdrawal."""
    with pytest.raises(LedgerAppendRefused) as caught:
        populated.supersede("ap-does-not-exist", "typo", recorded_at=T2)
    assert caught.value.rule == "UNKNOWN_ENTRY"


def test_superseding_twice_is_refused(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-52: the record stays a single chain of explicit decisions."""
    populated.supersede("ap-candidate", "first withdrawal", recorded_at=T2)
    with pytest.raises(LedgerAppendRefused) as caught:
        populated.supersede("ap-candidate", "second withdrawal", recorded_at=T2)
    assert caught.value.rule == "ALREADY_SUPERSEDED"


def test_a_duplicate_entry_id_is_refused(
    populated: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> None:
    """NEGATIVE CONTROL: two entries cannot share an id, or status becomes ambiguous."""
    with pytest.raises(LedgerAppendRefused) as caught:
        populated.record_contract_approval(
            approval=approval_factory(), recorded_at=T2, entry_id="ap-contract"
        )
    assert caught.value.rule == "DUPLICATE_ENTRY_ID"


def test_status_of_an_unknown_entry_is_refused_not_active(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL: an unknown id must never read as approved."""
    with pytest.raises(LedgerAppendRefused) as caught:
        populated.status("ap-never-recorded")
    assert caught.value.rule == "UNKNOWN_ENTRY"


# ---------------------------------------------------------------------------
# Authority queries (RX-04, RX-05).
# ---------------------------------------------------------------------------


def test_require_approved_contract_returns_the_active_entry(
    populated: ApprovalLedger,
) -> None:
    """RX-04: an approved contract resolves to the record that approved it."""
    assert populated.require_approved_contract(CONTRACT).entry_id == "ap-contract"


def test_require_approved_contract_raises_for_an_unapproved_hash(
    populated: ApprovalLedger,
) -> None:
    """NEGATIVE CONTROL, RX-04: acceptance against an unapproved contract is refused."""
    unapproved = digest("a contract nobody approved")
    with pytest.raises(ContractNotApproved) as caught:
        populated.require_approved_contract(unapproved)
    assert caught.value.contract_hash == unapproved


def test_require_approved_contract_raises_on_an_empty_ledger(ledger: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-04: an empty record grants nothing."""
    with pytest.raises(ContractNotApproved):
        ledger.require_approved_contract(CONTRACT)


def test_a_superseded_contract_approval_no_longer_approves(
    populated: ApprovalLedger,
) -> None:
    """NEGATIVE CONTROL, RX-04, RX-52: withdrawal has to actually withdraw authority."""
    populated.supersede("ap-contract", "contract revision supersedes this approval", recorded_at=T2)
    with pytest.raises(ContractNotApproved):
        populated.require_approved_contract(CONTRACT)


def test_require_approved_candidate_accepts_the_bound_combination(
    populated: ApprovalLedger,
) -> None:
    """RX-05: the five-field binding resolves when every observed value matches."""
    entry = populated.require_approved_candidate(**OBSERVED)
    assert entry.entry_id == "ap-candidate"


@pytest.mark.parametrize(
    "field",
    ["input_snapshot_id", "environment_policy_digest", "action_digest"],
)
def test_changing_a_bound_field_invalidates_the_approval(
    populated: ApprovalLedger, field: str
) -> None:
    """NEGATIVE CONTROL, RX-05: altering a bound field voids the approval by name."""
    observed = dict(OBSERVED)
    observed[field] = digest(f"moved-{field}")
    with pytest.raises(ApprovalInvalidated) as caught:
        populated.require_approved_candidate(**observed)
    assert caught.value.field == field
    assert caught.value.observed[field] == observed[field]


def test_a_changed_candidate_finds_no_approval(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-05: a different candidate is simply not approved.

    The candidate hash takes part in the lookup, so a changed candidate cannot
    inherit the previous candidate's approval.
    """
    observed = dict(OBSERVED, candidate_hash=digest("a candidate nobody approved"))
    with pytest.raises(ContractNotApproved, match="no active candidate approval"):
        populated.require_approved_candidate(**observed)


def test_candidate_approval_requires_the_contract_to_be_approved(
    ledger: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> None:
    """NEGATIVE CONTROL, RX-04 before RX-05: both gates apply, in order."""
    ledger.record_candidate_approval(approval=approval_factory(), recorded_at=T0)
    with pytest.raises(ContractNotApproved):
        ledger.require_approved_candidate(**OBSERVED)


# ---------------------------------------------------------------------------
# Negative controls: tampering with the file.
# ---------------------------------------------------------------------------


def test_editing_a_middle_line_breaks_the_chain(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-52: an edited field no longer matches its own digest."""
    lines = read_lines(populated.path)
    payload = json.loads(lines[1])
    payload["approval"]["approved_by"] = "someone who did not approve this"
    lines[1] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    rewrite(populated.path, lines)

    with pytest.raises(LedgerIntegrityError) as caught:
        populated.verify_chain()
    assert caught.value.rule == "ENTRY_DIGEST_MISMATCH"
    assert caught.value.line_number == 2


def test_editing_a_middle_line_and_resealing_it_still_breaks_the_chain(
    populated: ApprovalLedger,
) -> None:
    """NEGATIVE CONTROL, RX-52: the chain defeats the *competent* tamper.

    Here the attacker edits the entry and recomputes its ``entry_digest``
    correctly, so the per-entry check passes. The following line's
    ``previous_digest`` still names the old digest, which is the whole reason
    the chain exists.
    """
    entries = populated.entries()
    lines = read_lines(populated.path)
    payload = json.loads(lines[1])
    payload["approval"]["approved_by"] = "someone who did not approve this"

    from retrace_domain.ledger import LedgerEntry

    resealed = LedgerEntry.model_validate({**payload, "entry_digest": GENESIS_DIGEST})
    payload["entry_digest"] = resealed.content_digest()
    lines[1] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    rewrite(populated.path, lines)

    assert payload["entry_digest"] != entries[1].entry_digest
    with pytest.raises(LedgerIntegrityError) as caught:
        populated.verify_chain()
    assert caught.value.rule == "CHAIN_BREAK"
    assert caught.value.line_number == 3


def test_deleting_a_middle_line_breaks_the_chain(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-52: a removed decision cannot be removed quietly."""
    lines = read_lines(populated.path)
    rewrite(populated.path, [lines[0], lines[2]])

    with pytest.raises(LedgerIntegrityError) as caught:
        populated.verify_chain()
    assert caught.value.rule == "CHAIN_BREAK"
    assert caught.value.line_number == 2


def test_reordering_lines_breaks_the_chain(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-52: order is part of the record."""
    lines = read_lines(populated.path)
    rewrite(populated.path, [lines[0], lines[2], lines[1]])
    with pytest.raises(LedgerIntegrityError) as caught:
        populated.verify_chain()
    assert caught.value.rule == "CHAIN_BREAK"


def test_a_forged_appended_line_breaks_the_chain(
    populated: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> None:
    """NEGATIVE CONTROL, RX-52: an approval cannot be added by writing to the file."""
    lines = read_lines(populated.path)
    forged = json.loads(lines[1])
    forged["entry_id"] = "ap-forged"
    forged["sequence"] = 3
    rewrite(populated.path, [*lines, json.dumps(forged, sort_keys=True, separators=(",", ":"))])
    with pytest.raises(LedgerIntegrityError):
        populated.verify_chain()


def test_a_malformed_line_is_refused(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL: a line that is not JSON is not an entry to skip."""
    lines = read_lines(populated.path)
    rewrite(populated.path, [lines[0], "{not json", lines[2]])
    with pytest.raises(LedgerIntegrityError) as caught:
        populated.entries()
    assert caught.value.rule == "MALFORMED_LINE"
    assert caught.value.line_number == 2


def test_an_unexpected_key_is_refused_not_absorbed(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-10: parsing is strict, so an injected field is a refusal."""
    lines = read_lines(populated.path)
    payload = json.loads(lines[0])
    payload["override_authority"] = True
    lines[0] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    rewrite(populated.path, lines)
    with pytest.raises(LedgerIntegrityError) as caught:
        populated.entries()
    assert caught.value.rule == "MALFORMED_LINE"


def test_authority_is_refused_from_a_tampered_ledger(populated: ApprovalLedger) -> None:
    """NEGATIVE CONTROL, RX-04: a tampered record grants nothing, even for an intact line.

    ``ap-contract`` is untouched here. The query is still refused, because
    authority comes from the record as a whole and the record no longer
    verifies.
    """
    lines = read_lines(populated.path)
    payload = json.loads(lines[1])
    payload["reason"] = "injected"
    lines[1] = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    rewrite(populated.path, lines)
    with pytest.raises(LedgerIntegrityError):
        populated.require_approved_contract(CONTRACT)


def test_appending_onto_a_tampered_ledger_is_refused(
    populated: ApprovalLedger, approval_factory: Callable[..., Approval]
) -> None:
    """NEGATIVE CONTROL, RX-52: a valid-looking chain is never grown onto a broken one."""
    lines = read_lines(populated.path)
    rewrite(populated.path, [lines[0], lines[2]])
    with pytest.raises(LedgerIntegrityError):
        populated.record_contract_approval(
            approval=approval_factory(approval_id="ap-later"), recorded_at=T2
        )


def test_tail_truncation_is_not_detected_by_the_chain_alone(
    populated: ApprovalLedger,
) -> None:
    """RECORDED LIMIT, RX-52: the chain does not detect removal of the last lines.

    A truncated chain is a shorter valid chain, indistinguishable from "fewer
    approvals were ever recorded". This test exists so the limit is visible in
    the suite rather than assumed away: closing it needs the head digest
    anchored outside the file, which :meth:`ApprovalLedger.head_digest` exposes
    and which the ledger cannot do for itself.
    """
    before = populated.head_digest()
    rewrite(populated.path, read_lines(populated.path)[:1])

    assert populated.verify_chain() == 1, "a truncated chain still verifies -- by design"
    assert populated.head_digest() != before, (
        "the head digest changes, which is what an external anchor would catch"
    )

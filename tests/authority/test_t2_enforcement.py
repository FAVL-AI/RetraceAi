"""T2: can the repair worker reach the evidence used to judge its own work?

The acceptance question from review:

    Can the repair worker modify a reference, change an approval, forge a
    verifier result, or write an authoritative outcome WITHOUT calling the
    path guard?

`RepairAuthority` answers only when asked. These tests never ask. Every attempt
runs in a real child process that writes directly, so the verdicts below are
about enforcement, not about cooperation.

Three groups, and the first is the uncomfortable one:

* GAP - what nothing currently denies. These assert that the bypass SUCCEEDS.
  They are expected to FAIL, and must then be inverted, once execution runs
  inside the confinement demonstrated in group 2. Until then they are the
  evidence that T2 is genuinely OPEN rather than merely unreviewed.
* MECHANISM - the same operations denied by the kernel, proving a fix is
  reachable on this host.
* ENFORCED / NOT_RUN - what already holds, and what cannot be tested yet.

Nothing here runs against the developer's real repository state: every fixture
is built inside the test's own temporary directory, and the confinement is a
mount namespace whose changes cannot escape into the host (verified by asserting
host files are unchanged afterwards).
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest
from retrace_contracts import Approval, ApprovalInvalidated

sys.path.insert(0, str(Path(__file__).parent))
import jail  # noqa: E402  - local probe helper, imported by path on purpose

pytestmark = pytest.mark.integration

FIXED = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC)


@pytest.fixture(scope="module", autouse=True)
def _require_namespaces() -> None:
    reason = jail.namespace_support()
    if reason is not None:
        pytest.skip(f"kernel confinement unavailable: {reason}")


@pytest.fixture
def protected(tmp_path: Path) -> dict[str, Path]:
    """A stand-in for the artefacts a repair worker must never reach."""
    root = tmp_path / "authoritative"
    (root / "references").mkdir(parents=True)
    (root / "secrets").mkdir(parents=True)
    files = {
        "ledger": root / "approvals.jsonl",
        "reference": root / "references" / "expected.json",
        "verifier_code": root / "verify.py",
        "verdict": root / "verification_report.json",
    }
    files["ledger"].write_text('{"entry":"approved","digest":"abc"}\n', encoding="utf-8")
    files["reference"].write_text('{"outputs":{"mean_mass":{"value":3800.0}}}\n', encoding="utf-8")
    files["verifier_code"].write_text("def verify():\n    return 'REAL'\n", encoding="utf-8")
    files["verdict"].write_text('{"outcome":"CHANGED_RESULT"}\n', encoding="utf-8")
    files["secret"] = root / "secrets" / "signing.token"
    files["secret"].write_text("CANARY-NOT-A-REAL-CREDENTIAL\n", encoding="utf-8")
    files["root"] = root
    files["secrets_dir"] = root / "secrets"
    return files


# ========================================================================== #
# GAP - no enforcement today. Invert these when execution is confined.
# ========================================================================== #
@pytest.mark.parametrize(
    "artefact",
    ["ledger", "reference", "verifier_code", "verdict"],
    ids=["approval-ledger", "reference-output", "verifier-code", "verification-verdict"],
)
def test_gap_unconfined_worker_can_overwrite_protected_artefacts(
    protected: dict[str, Path], artefact: str
) -> None:
    """RECORDS THE GAP. A write that never calls the guard is not refused.

    RepairAuthority is defence in depth and nothing more: it is in-process, so a
    caller that simply opens the file wins. That is why T2 stays OPEN and why the
    threat model must not cite the guard as the verifier boundary.
    """
    target = protected[artefact]
    before = target.read_text(encoding="utf-8")
    verdict = jail.attempt(attempt="write", target=target, confine=False)
    assert verdict["outcome"] == "ALLOWED", (
        "an unconfined write was denied by something. If execution is now "
        "confined, invert this test and close the finding in the threat model. "
        f"verdict={verdict}"
    )
    assert target.read_text(encoding="utf-8") != before, (
        "write reported allowed but changed nothing"
    )


def test_gap_unconfined_worker_can_read_a_canary_credential(
    protected: dict[str, Path]
) -> None:
    """RECORDS THE GAP. The canary is deliberately not a real credential."""
    verdict = jail.attempt(attempt="read", target=protected["secret"], confine=False)
    assert verdict["outcome"] == "ALLOWED", f"unexpectedly denied: {verdict}"


# ========================================================================== #
# MECHANISM - the kernel denies the same operations.
# ========================================================================== #
@pytest.mark.parametrize("how", ["write", "os_open_write", "unlink"])
@pytest.mark.parametrize(
    "artefact",
    ["ledger", "reference", "verifier_code", "verdict"],
    ids=["approval-ledger", "reference-output", "verifier-code", "verification-verdict"],
)
def test_mechanism_readonly_confinement_denies_every_write_path(
    protected: dict[str, Path], artefact: str, how: str
) -> None:
    """A read-only bind mount denies open(), os.open() and unlink alike.

    Parameterised over three distinct syscall paths on purpose: a guard that
    only covered `open` would be defeated by `os.open`, and the point of moving
    enforcement into the kernel is that it does not enumerate call sites.
    """
    target = protected[artefact]
    before = target.read_text(encoding="utf-8")
    verdict = jail.attempt(
        attempt=how, target=target, confine=True, readonly=[protected["root"]]
    )
    assert verdict["outcome"] == "DENIED", f"confinement did not deny {how}: {verdict}"
    assert verdict["errno"] == 30, f"expected EROFS(30), got {verdict}"
    assert target.read_text(encoding="utf-8") == before, "host artefact was modified"


def test_mechanism_hidden_mount_denies_reading_a_credential(
    protected: dict[str, Path]
) -> None:
    """Read-only is the wrong tool for a secret: a credential the worker can read
    is a credential it can use. An empty tmpfs makes it unreachable instead."""
    verdict = jail.attempt(
        attempt="read",
        target=protected["secret"],
        confine=True,
        hidden=[protected["secrets_dir"]],
    )
    assert verdict["outcome"] == "DENIED", f"credential was readable under confinement: {verdict}"
    assert verdict["errno"] == 2, f"expected ENOENT(2), got {verdict}"
    assert protected["secret"].read_text(encoding="utf-8").startswith("CANARY"), (
        "the host credential file was disturbed"
    )


def test_mechanism_confinement_cannot_escape_into_the_host(
    protected: dict[str, Path], tmp_path: Path
) -> None:
    """DISCRIMINATION CONTROL for the mechanism itself.

    A namespace that silently failed to apply would make every DENIED above a
    false reassurance. So: a path NOT listed read-only must still be writable
    inside the same confined child. If this is denied too, the child is failing
    for an unrelated reason and the other results prove nothing.
    """
    writable = tmp_path / "scratch"
    writable.mkdir()
    target = writable / "out.txt"
    target.write_text("start\n", encoding="utf-8")
    verdict = jail.attempt(
        attempt="write", target=target, confine=True, readonly=[protected["root"]]
    )
    assert verdict["outcome"] == "ALLOWED", (
        "scratch was not writable under confinement, so the DENIED results above "
        f"may be incidental rather than caused by the read-only mount: {verdict}"
    )


# ========================================================================== #
# ENFORCED today - at the record level, independent of any filesystem guard.
# ========================================================================== #
def test_enforced_post_approval_candidate_mutation_invalidates_the_approval() -> None:
    """RX-05: changing the approved candidate stops the approval applying.

    This holds regardless of filesystem enforcement, because it is a property of
    the bound digest rather than of who can write where.
    """
    bound = {
        "contract_hash": "a" * 64,
        "candidate_hash": "b" * 64,
        "input_snapshot_id": "snap-1",
        "environment_policy_digest": "c" * 64,
        "action_digest": "d" * 64,
    }
    approval = Approval(
        approval_id="ap-1", approved_by="favl", approved_at=FIXED, **bound
    )
    approval.validate_binding(**bound)
    with pytest.raises(ApprovalInvalidated) as caught:
        approval.validate_binding(**dict(bound, candidate_hash="0" * 64))
    assert "candidate_hash" in str(caught.value)


# ========================================================================== #
# NOT_RUN - blocked on components that do not exist yet. Recorded, not skipped
# silently, so the gate cannot be read as passing.
# ========================================================================== #
@pytest.mark.skip(
    reason=(
        "NOT_RUN: forging a verifier payload into the AUTHORITATIVE record needs "
        "that record to exist. services/api has no verification store yet, so "
        "there is nothing to forge into. The adjacent property that IS tested is "
        "tests/exec/test_scientific_triad.py: a notebook's self-reported verdict "
        "does not influence the outcome."
    )
)
def test_not_run_forged_verifier_payload_is_refused() -> None:  # pragma: no cover
    raise AssertionError("unimplemented gate")


@pytest.mark.skip(
    reason=(
        "NOT_RUN: an unauthorised verdict write needs an authoritative store and "
        "a broker that only admits run/digest-bound results. Neither exists yet."
    )
)
def test_not_run_unauthorised_verdict_write_is_refused() -> None:  # pragma: no cover
    raise AssertionError("unimplemented gate")


@pytest.mark.skip(
    reason=(
        "NOT_RUN: replay protection needs the action-proposal envelope and its "
        "idempotency_key, classified UNRESOLVED-WITH-DECISION and not yet "
        "implemented (SPEC_RECONCILIATION_CLOSURE.md section 2)."
    )
)
def test_not_run_replayed_action_is_applied_once() -> None:  # pragma: no cover
    raise AssertionError("unimplemented gate")

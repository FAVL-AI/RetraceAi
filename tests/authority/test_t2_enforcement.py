"""T2: can the repair worker reach the evidence used to judge its own work?

The acceptance question from review:

    Can the repair worker modify a reference, change an approval, forge a
    verifier result, or write an authoritative outcome WITHOUT calling the
    path guard?

`RepairAuthority` answers only when asked. These tests never ask. Every attempt
runs in a real process that writes directly -- and, through the runner, from
inside a notebook kernel using `ctypes` so that no Python-level patch is in the
path at all. The verdicts below are therefore about enforcement, not cooperation.

Four groups:

* ENFORCED THROUGH THE RUNNER - the filesystem half, now closed for the local
  profile. A notebook executed by `run_notebook` under
  `FilesystemConfinement.KERNEL_MOUNT_NAMESPACE` is denied by the KERNEL when it
  tries to overwrite a declared protected artefact or read a declared credential.
  These tests were the GAP tests; they asserted the bypass succeeded, and they
  have been inverted now that confinement landed.
* GAP THAT REMAINS - the same run with `FilesystemConfinement.NONE` still
  succeeds. That is not a defect to be hidden: it is the honest description of a
  run that did not request confinement, and it is what makes the group above
  attributable to the confinement rather than to something incidental.
* MECHANISM - the kernel primitives, measured directly, independently of the
  runner.
* ENFORCED / NOT_RUN - what holds at the record level, and what cannot be tested
  yet.

WHAT THIS DOES NOT ACHIEVE - quote this, not a summary of it
============================================================
* **No distinct OS execution identity.** `sudo` requires a password on this host
  and `chown` is refused, so credential separation by file ownership is
  impossible here and the confined child runs as the same uid as the runner.
  T2's *identity* half is therefore still OPEN; only its filesystem half is
  closed, and only for the local profile.
* **This confines a cooperatively launched child.** The parent chooses to hand
  the child a namespace in which the declared paths are read-only. It is not
  protection against a compromised host, and a launcher that declines to confine
  is unaffected by any of it.
* **Only declared paths are confined.** An artefact the policy does not list
  stays writable, so the declaration is part of the control and belongs under
  review with the rest of the execution policy.
* **The infrastructure-administrator trust boundary is unchanged.** Nothing here
  constrains anyone who can write the host filesystem directly.

Nothing here runs against the developer's real repository state: every fixture is
built inside the test's own temporary directory, and the confinement is a mount
namespace whose changes cannot escape into the host (verified by asserting host
files are unchanged afterwards).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from retrace_contracts import Approval, ApprovalInvalidated, ExecutionStatus
from retrace_runner import (
    ExecutionLimits,
    FilesystemConfinement,
    probe_confinement_capability,
    run_notebook,
)
from retrace_runner.mountns import EROFS

sys.path.insert(0, str(Path(__file__).parent))
import jail  # noqa: E402  - local probe helper, imported by path on purpose

pytestmark = pytest.mark.integration

FIXED = dt.datetime(2026, 10, 3, 12, 0, tzinfo=dt.UTC)

ARTEFACTS: tuple[tuple[str, str], ...] = (
    ("approval-ledger", "ledger"),
    ("reference-output", "reference"),
    ("verifier-code", "verifier_code"),
    ("verification-verdict", "verdict"),
)
"""The four artefacts a repair worker must never reach, and their fixture keys."""

#: A notebook that attacks the filesystem with NATIVE calls.
#:
#: `ctypes` is the point. The in-process guard patches `builtins.open`,
#: `os.open` and friends, so a probe written in plain Python would measure the
#: guard rather than the kernel. `libc.open` and `libc.unlink` reach the syscall
#: with nothing of the guard in the path -- exactly the bypass class the threat
#: model records -- so a denial here is the kernel's denial.
_NATIVE_PROBE = r'''
import ctypes, ctypes.util, json, os

libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.open.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
libc.open.restype = ctypes.c_int
libc.unlink.argtypes = [ctypes.c_char_p]
libc.unlink.restype = ctypes.c_int

def attempt(kind, path):
    ctypes.set_errno(0)
    if kind == "unlink":
        if libc.unlink(path.encode()) != 0:
            return {"outcome": "DENIED", "errno": ctypes.get_errno()}
        return {"outcome": "ALLOWED", "errno": None}
    if kind == "read":
        flags = os.O_RDONLY
    elif kind == "create":
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    else:
        flags = os.O_WRONLY | os.O_APPEND
    descriptor = libc.open(path.encode(), flags, 0o600)
    if descriptor < 0:
        return {"outcome": "DENIED", "errno": ctypes.get_errno()}
    try:
        if kind == "read":
            os.read(descriptor, 1)
        else:
            os.write(descriptor, b"TAMPERED\n")
    finally:
        os.close(descriptor)
    return {"outcome": "ALLOWED", "errno": None}

for label, kind, path in __TARGETS__:
    verdict = attempt(kind, path)
    print("PROBE " + json.dumps({"label": label, "kind": kind, **verdict}, sort_keys=True))
'''


def _probe_notebook(tmp_path: Path, targets: list[tuple[str, str, str]]) -> Path:
    """Write a notebook that runs ``targets`` natively and prints one verdict per line."""
    nbformat = pytest.importorskip("nbformat")
    source = _NATIVE_PROBE.replace("__TARGETS__", repr(targets))
    notebook = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell(source)])
    path = tmp_path / "native-probe.ipynb"
    nbformat.write(notebook, str(path))
    return path


def _verdicts(claims: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    """Parse the probe lines the notebook printed, keyed by label.

    The notebook's output is *quarantined claim text* (RX-18) everywhere else in
    this repository, and it is used here only because the claim is about what the
    kernel did to the notebook, and every claim is cross-checked below against
    the artefact bytes on the host.
    """
    found: dict[str, dict[str, Any]] = {}
    for claim in claims:
        if not claim.startswith("PROBE "):
            continue
        payload = json.loads(claim[len("PROBE ") :])
        found[str(payload["label"])] = payload
    return found


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module", autouse=True)
def _require_namespaces() -> None:
    reason = jail.namespace_support()
    if reason is not None:
        pytest.skip(f"kernel confinement unavailable: {reason}")


@pytest.fixture(scope="module")
def confinement_capability() -> str | None:
    """Measure the capability once per module by attempting it, not by assuming it."""
    return probe_confinement_capability()


@pytest.fixture
def confined_host(confinement_capability: str | None) -> None:
    """Skip a test that needs the capability this host was measured not to have."""
    if confinement_capability is not None:
        pytest.skip(f"kernel filesystem confinement unavailable: {confinement_capability}")


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


def _attack_targets(
    protected: dict[str, Path], scratch_marker: str
) -> list[tuple[str, str, str]]:
    """The attack list every runner-level test below uses, confined or not.

    One list for both cases is deliberate: the confined and unconfined runs must
    differ in the *policy* and in nothing else, or the comparison proves nothing.
    """
    targets = [(label, "write", str(protected[key])) for label, key in ARTEFACTS]
    # A second syscall path, so a denial cannot be an open(2)-specific accident.
    targets.append(("approval-ledger-unlink", "unlink", str(protected["ledger"])))
    targets.append(("canary-credential", "read", str(protected["secret"])))
    # DISCRIMINATION CONTROL, inside the same process as the denials above.
    targets.append(("scratch-control", "create", scratch_marker))
    return targets


# ========================================================================== #
# ENFORCED THROUGH THE RUNNER - the inverted GAP. The kernel denies the bypass.
# ========================================================================== #
def test_a_confined_run_cannot_reach_any_protected_artefact_or_credential(
    confined_host: None, protected: dict[str, Path], tmp_path: Path
) -> None:
    """THE INVERTED GAP (RX-08). Native writes are denied by the kernel, not by a guard.

    This test asserted the opposite until filesystem confinement landed: four
    artefacts overwritten, four for four ALLOWED, and a canary credential read.
    The same six attacks now run from inside a notebook kernel executed by
    :func:`~retrace_runner.execution.run_notebook` with the artefact tree
    declared protected and the credential directory declared secret.

    Every attack uses ``ctypes``, so ``RepairAuthority`` and the in-process guard
    are both out of the path: the denial is ``EROFS`` from a read-only bind mount
    and ``ENOENT``/``EACCES`` from an empty ``tmpfs``.

    Three things are asserted together, and the third is what makes the first two
    mean anything:

    1. each attack reported DENIED with an errno attributable to the mount;
    2. the artefact bytes on the host are unchanged -- a mount namespace cannot
       write back into the host's, and this proves it did not;
    3. the control write to the run's own scratch area SUCCEEDED, so the
       namespace confined rather than failing shut.
    """
    before = {key: protected[key].read_bytes() for _, key in ARTEFACTS}
    marker = str(tmp_path / "run" / "scratch" / "control-write.txt")
    notebook = _probe_notebook(tmp_path, _attack_targets(protected, marker))
    limits = ExecutionLimits(
        wall_clock_seconds=180.0,
        filesystem_confinement=FilesystemConfinement.KERNEL_MOUNT_NAMESPACE,
        protected_paths=(str(protected["root"]),),
        secret_paths=(str(protected["secrets_dir"]),),
    )

    result = run_notebook(notebook, tmp_path / "run", limits, run_id="t2-confined")

    assert result.status is ExecutionStatus.SUCCEEDED, (
        f"the probe notebook did not complete: {result.cell_error}"
    )
    assert result.isolation.filesystem_applied is FilesystemConfinement.KERNEL_MOUNT_NAMESPACE
    assert result.isolation.readonly_paths == (str(protected["root"]),)
    assert result.isolation.hidden_paths == (str(protected["secrets_dir"]),)

    verdicts = _verdicts(result.notebook_reported_claims)
    expected_labels = {label for label, _ in ARTEFACTS} | {
        "approval-ledger-unlink",
        "canary-credential",
        "scratch-control",
    }
    assert set(verdicts) == expected_labels, f"the probe did not report every attack: {verdicts}"

    # (3) first: a namespace that failed shut would deny everything, and then the
    # denials below would be a false reassurance rather than enforcement.
    control = verdicts["scratch-control"]
    assert control["outcome"] == "ALLOWED", (
        "the run's own scratch area was not writable under confinement, so every "
        f"denial in this test may be incidental: {control}"
    )
    assert Path(marker).is_file()

    for label in (*(label for label, _ in ARTEFACTS), "approval-ledger-unlink"):
        verdict = verdicts[label]
        assert verdict["outcome"] == "DENIED", f"{label} was not denied: {verdict}"
        assert verdict["errno"] == EROFS, f"{label} was denied, but not by the mount: {verdict}"
    credential = verdicts["canary-credential"]
    assert credential["outcome"] == "DENIED", f"the credential was readable: {credential}"
    assert credential["errno"] in (2, 13), f"denied, but not by the empty tmpfs: {credential}"

    # (2) the host is untouched, including the file the unlink attempt targeted.
    for _, key in ARTEFACTS:
        assert protected[key].read_bytes() == before[key], f"{key} changed on the host"
    assert protected["secret"].read_text(encoding="utf-8").startswith("CANARY")


# ========================================================================== #
# GAP THAT REMAINS - a run that did not ask for confinement is not confined.
# ========================================================================== #
def test_an_unconfined_run_still_reaches_every_protected_artefact(
    protected: dict[str, Path], tmp_path: Path
) -> None:
    """THE HONEST BASELINE, and the discrimination control for the test above.

    With ``FilesystemConfinement.NONE`` the identical attack list succeeds: four
    artefacts overwritten, the ledger unlinked, the credential read. Two things
    follow, and both matter.

    First, the denials in the confined test are attributable to the confinement
    and to nothing else -- same notebook, same artefacts, same syscalls, one
    field of the policy different.

    Second, this is the residual exposure, stated rather than hidden: the
    confinement is a declared capability, so any caller that does not request it
    is exactly as exposed as before. Nothing in the runner requests it by
    default, because the runner cannot know what a deployment must protect.
    """
    marker = str(tmp_path / "run" / "scratch" / "control-write.txt")
    notebook = _probe_notebook(tmp_path, _attack_targets(protected, marker))
    limits = ExecutionLimits(wall_clock_seconds=180.0)
    assert limits.filesystem_confinement is FilesystemConfinement.NONE

    result = run_notebook(notebook, tmp_path / "run", limits, run_id="t2-unconfined")

    assert result.status is ExecutionStatus.SUCCEEDED, (
        f"the probe notebook did not complete: {result.cell_error}"
    )
    assert result.isolation.filesystem_applied is FilesystemConfinement.NONE
    assert result.isolation.readonly_paths == ()

    verdicts = _verdicts(result.notebook_reported_claims)
    for label in (*(label for label, _ in ARTEFACTS), "approval-ledger-unlink"):
        assert verdicts[label]["outcome"] == "ALLOWED", (
            "an unconfined native write was denied by something. If the runner now "
            "confines by default, this test is no longer the honest description of "
            f"an unconfined run and must be revisited. verdict={verdicts[label]}"
        )
    assert verdicts["canary-credential"]["outcome"] == "ALLOWED"

    # The filesystem agrees with the claims: these writes really happened.
    assert b"TAMPERED" in protected["reference"].read_bytes()
    assert b"TAMPERED" in protected["verifier_code"].read_bytes()
    assert b"TAMPERED" in protected["verdict"].read_bytes()
    assert not protected["ledger"].exists(), "the unlink claimed success but left the file"


# ========================================================================== #
# MECHANISM - the kernel denies the same operations, measured without the runner.
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

    Kept after the runner-level tests above because it measures the *primitive*
    rather than the product: if the runner's confinement ever regressed, this
    group localises the failure to the runner instead of the host.
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
        "a broker that only admits run/digest-bound results. Neither exists yet. "
        "Filesystem confinement does not close this: it denies a write to a "
        "declared path, and says nothing about what an authorised writer admits."
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

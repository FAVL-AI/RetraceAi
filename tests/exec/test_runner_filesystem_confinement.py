"""Kernel filesystem confinement: policy, verification gates, refusals (RX-08).

This suite covers the *runner mechanics* of ``FilesystemConfinement``: that the
policy records the declaration, that the verification gates can be shown to
reject a mount table that does not hold the property, and that every way the
confinement can fail ends in a named refusal rather than an unconfined run.

What this suite deliberately does **not** cover is whether the confinement stops
a repair worker reaching the evidence used to judge it. That is a question about
authority, it is measured against real artefacts in
``tests/authority/test_t2_enforcement.py``, and it would be circular to answer
it here with the runner's own report.

The unit tests need no kernel and no namespace. The ones that start one carry
the ``integration`` marker and skip only when this host cannot confine at all --
measured by attempting it, never by assuming.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from retrace_contracts import ExecutionStatus
from retrace_runner import (
    ExecutionLimits,
    FilesystemConfinement,
    FilesystemConfinementUnavailable,
    IsolationReport,
    IsolationUnavailable,
    NetworkIsolation,
    probe_confinement_capability,
    run_notebook,
)
from retrace_runner.execution import _as_filesystem_confinement, _raise_isolation_refusal
from retrace_runner.mountns import (
    EROFS,
    MountConfinementUnavailable,
    apply_confinement,
    confinement_support_reason,
    interpret_probe,
    parse_mountinfo,
    unprotected_submounts,
)
from retrace_runner.policy import WriteConfinement

if TYPE_CHECKING:  # pragma: no cover - annotation only
    from .conftest import NotebookFactory


CONFINED = FilesystemConfinement.KERNEL_MOUNT_NAMESPACE

_GOOD_PROBE: dict[str, Any] = {
    "protected_write": {"outcome": "DENIED", "errno": EROFS},
    "secret_read": {"outcome": "DENIED", "errno": 2},
    "control_write": {"outcome": "ALLOWED", "errno": None},
}
"""The one payload that means the capability was demonstrated."""


# --------------------------------------------------------------------------- #
# Policy: the declaration is explicit, validated, and inside the digest
# --------------------------------------------------------------------------- #
def test_the_default_policy_claims_no_filesystem_confinement() -> None:
    """``NONE`` is the honest default: nothing declared, nothing protected (RX-08)."""
    limits = ExecutionLimits()
    assert limits.filesystem_confinement is FilesystemConfinement.NONE
    assert limits.protected_paths == ()
    assert limits.secret_paths == ()


def test_policy_digest_covers_the_filesystem_declaration() -> None:
    """A run under one confinement cannot be confused with a run under another (RX-15).

    Every variant below differs from the baseline *only* in the filesystem
    declaration, so each distinct digest is attributable to that field alone.
    """
    baseline = ExecutionLimits()
    variants = [
        ExecutionLimits(filesystem_confinement=CONFINED, protected_paths=("/etc",)),
        ExecutionLimits(filesystem_confinement=CONFINED, protected_paths=("/usr",)),
        ExecutionLimits(
            filesystem_confinement=CONFINED, protected_paths=("/etc", "/usr")
        ),
        ExecutionLimits(filesystem_confinement=CONFINED, secret_paths=("/etc",)),
    ]
    digests = {variant.policy_digest for variant in variants}
    assert baseline.policy_digest not in digests
    assert len(digests) == len(variants), "two different declarations digested alike"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"protected_paths": ("/etc",)}, "nothing would enforce them"),
        ({"filesystem_confinement": CONFINED}, "would confine nothing"),
        (
            {"filesystem_confinement": CONFINED, "protected_paths": ("etc",)},
            "is not absolute",
        ),
        (
            {"filesystem_confinement": CONFINED, "protected_paths": ("/etc/../usr",)},
            "is not normalised",
        ),
        (
            {
                "filesystem_confinement": CONFINED,
                "protected_paths": ("/etc",),
                "secret_paths": ("/etc",),
            },
            "contradictory",
        ),
    ],
    ids=["unenforced-declaration", "empty-declaration", "relative", "unnormalised", "both-lists"],
)
def test_policy_refuses_a_declaration_that_does_not_mean_what_it_says(
    kwargs: dict[str, Any], expected: str
) -> None:
    """Each refusal closes a way a policy could read as protection without being one."""
    with pytest.raises(ValueError, match=expected):
        ExecutionLimits(**kwargs)


def test_the_isolation_report_defaults_to_claiming_nothing() -> None:
    """An omitted filesystem field must not imply a confinement that was not in force.

    The negative control on the record type itself: a report built without the
    new fields says ``NONE`` and lists no protected path, so an older caller
    cannot accidentally produce a record that overstates what was enforced.
    """
    report = IsolationReport(
        network_requested=NetworkIsolation.COOPERATIVE,
        network_applied=NetworkIsolation.COOPERATIVE,
        write_confinement=WriteConfinement.SCRATCH_ONLY,
        scratch_root="/tmp/scratch",  # noqa: S108 - a record field, nothing is created
    )
    assert report.filesystem_requested is FilesystemConfinement.NONE
    assert report.filesystem_applied is FilesystemConfinement.NONE
    assert report.readonly_paths == ()
    assert report.hidden_paths == ()


# --------------------------------------------------------------------------- #
# The verification gates, shown to reject the bad case
# --------------------------------------------------------------------------- #
def test_mountinfo_parsing_extracts_flags_and_unescapes_paths() -> None:
    """Octal escapes are decoded, or a protected path with a space never matches."""
    text = (
        "36 35 8:1 /authoritative /mnt/a\\040space ro,relatime - ext4 /dev/sda1 rw\n"
        "37 36 0:42 / /mnt/secrets rw,relatime - tmpfs tmpfs rw,mode=000\n"
        "garbage line with no separator\n"
    )
    entries = parse_mountinfo(text)
    assert [entry.mount_point for entry in entries] == ["/mnt/a space", "/mnt/secrets"]
    assert entries[0].read_only is True
    assert entries[1].read_only is False
    assert entries[1].fstype == "tmpfs"


def test_the_submount_gate_detects_a_writable_filesystem_under_a_protected_path() -> None:
    """CONTAINED VIOLATING FIXTURE. A recursive bind leaves a submount writable.

    ``MS_REMOUNT|MS_RDONLY`` applies to one mount, so a separate filesystem
    mounted inside a protected tree keeps its own write permission. This mount
    table violates the property the confinement claims, and the gate must say so
    -- a gate never shown to fail is not evidence.
    """
    text = (
        "36 35 8:1 /authoritative /protected ro,relatime - ext4 /dev/sda1 rw\n"
        "37 36 8:2 / /protected/nested rw,relatime - ext4 /dev/sdb1 rw\n"
    )
    offenders = unprotected_submounts(
        parse_mountinfo(text), readonly_paths=("/protected",), hidden_paths=()
    )
    assert offenders == ("/protected/nested",)


def test_the_submount_gate_passes_a_fully_read_only_tree() -> None:
    """DISCRIMINATION CONTROL. A gate that flagged everything would be useless."""
    text = (
        "36 35 8:1 /authoritative /protected ro,relatime - ext4 /dev/sda1 rw\n"
        "37 36 8:2 / /protected/nested ro,relatime - ext4 /dev/sdb1 rw\n"
        "38 35 8:3 / /elsewhere rw,relatime - ext4 /dev/sdc1 rw\n"
    )
    assert (
        unprotected_submounts(
            parse_mountinfo(text), readonly_paths=("/protected",), hidden_paths=()
        )
        == ()
    )


def test_the_submount_gate_exempts_a_declared_hidden_tmpfs() -> None:
    """A ``mode=000`` tmpfs is writable by design and holds nothing to protect."""
    text = (
        "36 35 8:1 /authoritative /protected ro,relatime - ext4 /dev/sda1 rw\n"
        "37 36 0:42 / /protected/secrets rw,relatime - tmpfs tmpfs rw,mode=000\n"
    )
    assert (
        unprotected_submounts(
            parse_mountinfo(text),
            readonly_paths=("/protected",),
            hidden_paths=("/protected/secrets",),
        )
        == ()
    )


def test_the_capability_gate_accepts_only_a_demonstrated_probe() -> None:
    """The one payload that means the mechanism works returns no reason."""
    assert interpret_probe(dict(_GOOD_PROBE)) is None


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            {**_GOOD_PROBE, "control_write": {"outcome": "DENIED", "errno": EROFS}},
            "failed shut",
        ),
        (
            {**_GOOD_PROBE, "protected_write": {"outcome": "ALLOWED", "errno": None}},
            "was not denied",
        ),
        (
            {**_GOOD_PROBE, "protected_write": {"outcome": "DENIED", "errno": 13}},
            "not by the read-only mount",
        ),
        (
            {**_GOOD_PROBE, "secret_read": {"outcome": "ALLOWED", "errno": None}},
            "was readable",
        ),
        (
            {**_GOOD_PROBE, "secret_read": {"outcome": "DENIED", "errno": EROFS}},
            "not by the empty tmpfs",
        ),
        ({"stage": "setup", "error": "unshare refused"}, "setup failed"),
        ({"protected_write": {"outcome": "DENIED", "errno": EROFS}}, "incomplete"),
    ],
    ids=[
        "failed-shut",
        "write-allowed",
        "denied-for-another-reason",
        "credential-readable",
        "credential-denied-wrongly",
        "setup-failed",
        "incomplete",
    ],
)
def test_the_capability_gate_rejects_every_way_a_probe_can_go_wrong(
    payload: dict[str, Any], expected: str
) -> None:
    """CONTAINED VIOLATING FIXTURES, one per failure mode (RX-08).

    The first case is the one that matters most: a namespace that failed shut
    would deny the control write too, and every denial it reported would be a
    false reassurance. The gate checks that case *before* it credits any denial.
    """
    reason = interpret_probe(payload)
    assert reason is not None, f"the gate accepted a bad probe: {payload!r}"
    assert expected in reason


def test_support_reason_is_structural_and_never_claims_success() -> None:
    """The cheap pre-flight returns a reason or ``None``; it measures nothing."""
    reason = confinement_support_reason()
    assert reason is None or isinstance(reason, str)


# --------------------------------------------------------------------------- #
# apply_confinement refuses rather than confining less than was declared
# --------------------------------------------------------------------------- #
def test_confinement_cannot_succeed_by_accident_outside_a_namespace(
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL on the mechanism. No namespace, no confinement (RX-08).

    Called in this test process -- which has no private mount namespace --
    ``mount(2)`` is refused ``EPERM`` and the function raises. That is what makes
    a successful return meaningful: it cannot be produced without the namespace
    the child enters first. The host is left untouched, asserted below.
    """
    protected = tmp_path / "protected"
    protected.mkdir()
    artefact = protected / "ledger.jsonl"
    artefact.write_text("original\n", encoding="utf-8")

    with pytest.raises(MountConfinementUnavailable) as refusal:
        apply_confinement(readonly_paths=(str(protected),), hidden_paths=())

    assert "mount(2) refused" in str(refusal.value)
    assert artefact.read_text(encoding="utf-8") == "original\n"
    with artefact.open("a", encoding="utf-8") as handle:
        handle.write("still writable on the host\n")


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("absent", "does not exist"),
        ("", "confine nothing"),
    ],
    ids=["missing-path", "empty-declaration"],
)
def test_confinement_refuses_a_declaration_it_cannot_honour(
    tmp_path: Path, relative: str, expected: str
) -> None:
    """A mistyped or empty declaration must not read as protection (RX-08)."""
    paths = (str(tmp_path / relative),) if relative else ()
    with pytest.raises(MountConfinementUnavailable, match=expected):
        apply_confinement(readonly_paths=paths, hidden_paths=())


def test_confinement_refuses_a_secret_declaration_that_is_not_a_directory(
    tmp_path: Path,
) -> None:
    """An empty tmpfs can only replace a directory, so a file is refused by name."""
    token = tmp_path / "signing.token"
    token.write_text("CANARY-NOT-A-REAL-CREDENTIAL\n", encoding="utf-8")
    with pytest.raises(MountConfinementUnavailable, match="not a directory"):
        apply_confinement(readonly_paths=(), hidden_paths=(str(token),))


def test_confinement_refuses_a_path_that_resolves_through_a_symlink(
    tmp_path: Path,
) -> None:
    """The declared path and the confined path must be the same path (RX-08).

    A symlinked declaration would bind-mount somewhere else, so the artefact a
    reviewer read as protected and the artefact the kernel protected could
    differ -- the same reasoning that refuses a symlinked notebook.
    """
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(MountConfinementUnavailable, match="symlink"):
        apply_confinement(readonly_paths=(str(link),), hidden_paths=())


# --------------------------------------------------------------------------- #
# Parent-side refusals: nothing is prepared and nothing runs
# --------------------------------------------------------------------------- #
def test_a_run_root_inside_a_protected_path_is_refused_before_anything_is_created(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A run that could not write its own outputs is a misconfiguration, not science.

    The assertion that the run root was never created is what makes the refusal
    positive evidence that nothing ran.
    """
    protected = tmp_path / "protected"
    protected.mkdir()
    workdir = protected / "run"
    notebook = notebooks.write("print('never runs')\n")
    limits = ExecutionLimits(
        wall_clock_seconds=60.0,
        filesystem_confinement=CONFINED,
        protected_paths=(str(protected),),
    )

    with pytest.raises(FilesystemConfinementUnavailable) as refusal:
        run_notebook(notebook, workdir, limits, run_id="inside-protected")

    assert "lies inside declared protected path" in str(refusal.value)
    assert not workdir.exists()


def test_a_protected_path_inside_the_run_root_is_refused(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """Confining the runner's own control area would stop it recording what happened."""
    workdir = tmp_path / "run"
    notebook = notebooks.write("print('never runs')\n")
    limits = ExecutionLimits(
        wall_clock_seconds=60.0,
        filesystem_confinement=CONFINED,
        protected_paths=(str(workdir / "control"),),
    )

    with pytest.raises(FilesystemConfinementUnavailable) as refusal:
        run_notebook(notebook, workdir, limits, run_id="protected-inside")

    assert "lies inside the run root" in str(refusal.value)
    assert not workdir.exists()


def test_a_protected_path_that_does_not_exist_refuses_the_run(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """FAIL CLOSED. A declaration that cannot be honoured stops the run (RX-08).

    The refusal must be the *named* filesystem exception, so a caller cannot
    read it as an ordinary environment problem, and the run must not have
    executed a cell.
    """
    notebook = notebooks.write("print('never runs')\n")
    limits = ExecutionLimits(
        wall_clock_seconds=60.0,
        filesystem_confinement=CONFINED,
        protected_paths=(str(tmp_path / "never-created"),),
    )

    with pytest.raises(FilesystemConfinementUnavailable) as refusal:
        run_notebook(notebook, tmp_path / "run", limits, run_id="missing-path")

    assert "does not exist" in str(refusal.value)
    assert "kernel filesystem confinement" in str(refusal.value)
    assert not (tmp_path / "run" / "scratch" / "executed.ipynb").exists()


# --------------------------------------------------------------------------- #
# Established, verified, and recorded
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def confinement_capability() -> str | None:
    """Measure once per module whether this host can confine at all."""
    return probe_confinement_capability()


@pytest.fixture
def confined_host(confinement_capability: str | None) -> None:
    """Skip a test that needs the capability this host was measured not to have."""
    if confinement_capability is not None:
        pytest.skip(f"kernel filesystem confinement unavailable: {confinement_capability}")


@pytest.mark.integration
def test_the_realised_confinement_is_verified_and_recorded(
    confined_host: None, notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A confined run records what was *in force*, not what was asked for (RX-08).

    ``readonly_paths`` and ``hidden_paths`` reach the result only after the child
    has read ``/proc/self/mountinfo`` back and found the expected flags, so a
    verdict quoting them is quoting a verified observation.
    """
    protected = tmp_path / "authoritative"
    (protected / "secrets").mkdir(parents=True)
    (protected / "approvals.jsonl").write_text("{}\n", encoding="utf-8")
    secrets = protected / "secrets"

    notebook = notebooks.write("open('out.txt', 'w').write('confined')\n")
    limits = ExecutionLimits(
        wall_clock_seconds=180.0,
        filesystem_confinement=CONFINED,
        protected_paths=(str(protected),),
        secret_paths=(str(secrets),),
    )
    result = run_notebook(notebook, tmp_path / "run", limits, run_id="confined")

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.isolation.filesystem_requested is CONFINED
    assert result.isolation.filesystem_applied is CONFINED
    assert result.isolation.readonly_paths == (str(protected),)
    assert result.isolation.hidden_paths == (str(secrets),)
    assert result.policy_digest == limits.policy_digest
    assert result.environment_manifest is not None
    assert result.environment_manifest.policy_digest == limits.policy_digest
    # The confinement did not cost the run its own scratch area.
    assert (Path(result.scratch_dir) / "out.txt").read_text(encoding="utf-8") == "confined"
    # And the host artefact is untouched: a mount namespace cannot write back.
    assert (protected / "approvals.jsonl").read_text(encoding="utf-8") == "{}\n"


@pytest.mark.integration
def test_network_and_filesystem_confinement_hold_together_in_one_namespace(
    confined_host: None, notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """Both capabilities are established by a single ``unshare`` (RX-08).

    ``CLONE_NEWUSER`` cannot usefully be unshared twice -- the second namespace
    could not write an unprivileged id map -- so requesting both capabilities
    exercises a different code path from requesting either alone. If the
    combination silently dropped one, the applied fields would disagree with the
    requested ones and the runner would have refused the run.
    """
    protected = tmp_path / "authoritative"
    protected.mkdir()
    (protected / "reference.json").write_text("{}\n", encoding="utf-8")

    notebook = notebooks.write("print('both namespaces')\n")
    limits = ExecutionLimits(
        wall_clock_seconds=180.0,
        network=NetworkIsolation.KERNEL_NAMESPACE,
        filesystem_confinement=CONFINED,
        protected_paths=(str(protected),),
    )
    result = run_notebook(notebook, tmp_path / "run", limits, run_id="both")

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.isolation.network_applied is NetworkIsolation.KERNEL_NAMESPACE
    assert result.isolation.filesystem_applied is CONFINED
    assert result.isolation.loopback_available is True
    assert result.isolation.readonly_paths == (str(protected),)


# --------------------------------------------------------------------------- #
# The record never weakens, and the refusal is named
# --------------------------------------------------------------------------- #
def test_an_unreadable_child_report_never_weakens_the_recorded_confinement() -> None:
    """A value the parent cannot parse is reported as the REQUESTED mode (RX-08).

    The direction matters: falling back to ``NONE`` would turn a child's garbled
    report into a record that understates the confinement, and falling back
    silently to ``CONFINED`` on a child that honestly reported ``NONE`` would
    overstate it. The parse keeps the request; the downgrade check in
    :func:`~retrace_runner.execution.run_notebook` is what refuses a genuine
    mismatch, and it was shown to refuse one by mutating the child to report
    ``NONE`` while skipping the mounts.
    """
    assert _as_filesystem_confinement("nonsense", CONFINED) is CONFINED
    assert _as_filesystem_confinement("NONE", CONFINED) is FilesystemConfinement.NONE


def test_a_child_side_filesystem_refusal_raises_the_named_exception() -> None:
    """The capability a child names decides which refusal the parent raises (RX-08)."""
    with pytest.raises(FilesystemConfinementUnavailable):
        _raise_isolation_refusal(
            {"isolation_capability": "kernel filesystem confinement"}, detail="bind failed"
        )


def test_an_unrelated_child_side_refusal_is_not_reported_as_a_filesystem_one() -> None:
    """DISCRIMINATION CONTROL. A guard-install failure must not read as T2 evidence."""
    with pytest.raises(IsolationUnavailable) as refusal:
        _raise_isolation_refusal(
            {"isolation_capability": "address-space ceiling"}, detail="rlimit refused"
        )
    assert not isinstance(refusal.value, FilesystemConfinementUnavailable)

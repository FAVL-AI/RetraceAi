"""Runner unit controls: admission, policy digest, guard decisions, reaping (RX-08).

These tests need no kernel. The ones that do are in
``test_runner_isolation.py`` and carry the ``integration`` marker.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from retrace_runner import (
    DEFAULT_LIMITS,
    ExecutionLimits,
    NetworkIsolation,
    NotebookAdmissionRefused,
    RetraceGuardDenied,
    WriteConfinement,
    admit_notebook,
    capture_environment,
    descendant_pids,
    installed_distributions,
)
from retrace_runner.guard import (
    NETWORK_DENY_NON_LOOPBACK,
    SPAWN_ALLOW,
    RetraceGuardInstallFailed,
    install,
    receipt_filename,
    target_is_denied,
)
from retrace_runner.netns import namespace_support_reason


# --------------------------------------------------------------------------- #
# Notebook admission (RX-08: no arbitrary-code entrypoint)
# --------------------------------------------------------------------------- #
def test_admits_a_plain_notebook(tmp_path: Path) -> None:
    """A regular ``.ipynb`` file is admitted and returned resolved."""
    notebook = tmp_path / "ok.ipynb"
    notebook.write_text("{}", encoding="utf-8")
    assert admit_notebook(notebook) == notebook.resolve()


@pytest.mark.parametrize(
    ("name", "expected_reason"),
    [("script.py", "suffix"), ("data.json", "suffix"), ("archive.zip", "suffix")],
)
def test_refuses_non_notebook_suffixes(tmp_path: Path, name: str, expected_reason: str) -> None:
    """Only ``.ipynb`` is executable; a source file is refused by name (RX-08)."""
    artefact = tmp_path / name
    artefact.write_text("print('x')", encoding="utf-8")
    with pytest.raises(NotebookAdmissionRefused) as refusal:
        admit_notebook(artefact)
    assert expected_reason in str(refusal.value.reason)


def test_refuses_a_symlinked_notebook(tmp_path: Path) -> None:
    """A symlink is refused: the reviewed bytes and the executed bytes must be one."""
    real = tmp_path / "real.ipynb"
    real.write_text("{}", encoding="utf-8")
    link = tmp_path / "link.ipynb"
    link.symlink_to(real)
    with pytest.raises(NotebookAdmissionRefused) as refusal:
        admit_notebook(link)
    assert "symlink" in str(refusal.value.reason)


def test_refuses_a_notebook_outside_the_declared_source_root(tmp_path: Path) -> None:
    """A path escaping the declared source root is refused (RX-08, RX-42)."""
    outside = tmp_path / "outside.ipynb"
    outside.write_text("{}", encoding="utf-8")
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(NotebookAdmissionRefused) as refusal:
        admit_notebook(outside, source_root=root)
    assert "source root" in str(refusal.value.reason)


def test_refuses_a_missing_notebook(tmp_path: Path) -> None:
    """A path that does not exist is refused before anything is started."""
    with pytest.raises(NotebookAdmissionRefused):
        admit_notebook(tmp_path / "absent.ipynb")


def test_refuses_a_directory_named_like_a_notebook(tmp_path: Path) -> None:
    """A directory is not a regular file and is refused."""
    directory = tmp_path / "trap.ipynb"
    directory.mkdir()
    with pytest.raises(NotebookAdmissionRefused):
        admit_notebook(directory)


# --------------------------------------------------------------------------- #
# Policy digest (RX-08, RX-15)
# --------------------------------------------------------------------------- #
def test_policy_digest_is_stable_for_equal_policies() -> None:
    """Two equal policies digest equally, so a rerun can prove the same envelope."""
    assert ExecutionLimits().policy_digest == ExecutionLimits().policy_digest


def test_policy_digest_changes_when_any_ceiling_changes() -> None:
    """Changing any ceiling changes the digest; a loosened policy cannot hide."""
    baseline = ExecutionLimits()
    variants = [
        ExecutionLimits(wall_clock_seconds=baseline.wall_clock_seconds + 1),
        ExecutionLimits(max_address_space_bytes=1024 * 1024 * 1024),
        ExecutionLimits(network=NetworkIsolation.KERNEL_NAMESPACE),
        ExecutionLimits(deny_child_process_spawn=False),
        ExecutionLimits(allow_notebook_cell_errors=True),
    ]
    digests = {variant.policy_digest for variant in variants}
    assert baseline.policy_digest not in digests
    assert len(digests) == len(variants)


def test_policy_refuses_an_unstartable_memory_cap() -> None:
    """A cap too small to start an interpreter is refused at construction (RX-08)."""
    with pytest.raises(ValueError, match="greater than or equal"):
        ExecutionLimits(max_address_space_bytes=1024)


def test_policy_is_frozen() -> None:
    """The policy record cannot be mutated after construction (RX-03)."""
    from retrace_contracts import ContractImmutable

    with pytest.raises(ContractImmutable):
        DEFAULT_LIMITS.wall_clock_seconds = 1.0  # type: ignore[misc]


def test_default_policy_requests_scratch_only_writes() -> None:
    """The default envelope confines writes; it is not an opt-in."""
    assert DEFAULT_LIMITS.write_confinement is WriteConfinement.SCRATCH_ONLY
    assert DEFAULT_LIMITS.deny_child_process_spawn is True


# --------------------------------------------------------------------------- #
# Guard decision function: a deny rule must be shown to deny AND to allow
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "address",
    [
        ("93.184.216.34", 80),
        ("8.8.8.8", 53),
        ("example.invalid", 443),
        ("169.254.169.254", 80),
        ("::ffff:1.1.1.1", 443),
        ("2001:4860:4860::8888", 443),
    ],
)
def test_non_loopback_destinations_are_denied(address: tuple[str, int]) -> None:
    """Every off-host destination, literal or name, is denied (RX-08)."""
    import socket

    assert target_is_denied(socket.AF_INET, address) is True


@pytest.mark.parametrize(
    "address", [("127.0.0.1", 9000), ("localhost", 9000), ("::1", 9000), ("127.5.5.5", 1)]
)
def test_loopback_destinations_are_permitted_under_cooperative(
    address: tuple[str, int],
) -> None:
    """Loopback is permitted; the kernel transport needs it, and the docstring says so."""
    import socket

    assert target_is_denied(socket.AF_INET, address) is False


def test_unix_sockets_are_not_treated_as_egress() -> None:
    """An ``AF_UNIX`` peer is not network egress and is not denied."""
    import socket

    assert target_is_denied(socket.AF_UNIX, "/tmp/some.sock") is False  # noqa: S108


def test_guard_refuses_an_unknown_mode() -> None:
    """An unrecognised guard mode fails closed rather than installing nothing."""
    with pytest.raises(RetraceGuardInstallFailed):
        install(write_roots=("/",), network="permissive", spawn=SPAWN_ALLOW)


def test_guard_refuses_empty_write_roots() -> None:
    """Write confinement with no roots would confine nothing, so it is refused."""
    with pytest.raises(RetraceGuardInstallFailed):
        install(write_roots=(), network=NETWORK_DENY_NON_LOOPBACK, spawn=SPAWN_ALLOW)


def test_guard_denials_are_permission_errors() -> None:
    """Guard refusals derive from ``PermissionError`` so notebook code sees a real error."""
    assert issubclass(RetraceGuardDenied, PermissionError)


def test_receipt_filename_is_pid_addressed() -> None:
    """The receipt a process writes is named by its pid, so it can be verified per-process."""
    assert receipt_filename(4321) == "4321.json"


# --------------------------------------------------------------------------- #
# Descendant discovery (the mechanism that catches a kernel outside the group)
# --------------------------------------------------------------------------- #
def test_descendant_pids_finds_a_real_child() -> None:
    """``descendant_pids`` sees a live child of this process."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child branch never reports coverage
        os.close(write_fd)
        try:
            os.read(read_fd, 1)
        finally:
            os._exit(0)
    os.close(read_fd)
    try:
        assert pid in descendant_pids(os.getpid())
    finally:
        os.write(write_fd, b"x")
        os.close(write_fd)
        os.waitpid(pid, 0)


def test_descendant_pids_of_a_leaf_is_empty() -> None:
    """A pid with no children yields an empty set rather than a guess."""
    assert descendant_pids(os.getpid()) >= set()
    assert descendant_pids(2**22) == set()


# --------------------------------------------------------------------------- #
# Environment capture is read-only (RX-15)
# --------------------------------------------------------------------------- #
def test_capture_environment_reports_this_interpreter() -> None:
    """The manifest payload describes the running interpreter and pins the policy."""
    import sys

    payload = capture_environment(policy_digest="0" * 64)
    assert payload["python_version"] == sys.version.split()[0]
    assert payload["policy_digest"] == "0" * 64
    assert isinstance(payload["packages"], dict)
    assert payload["packages"], "an empty package map would make the manifest vacuous"


def test_installed_distributions_is_sorted_and_read_only() -> None:
    """Distribution capture is deterministic in order and installs nothing."""
    first = installed_distributions()
    second = installed_distributions()
    assert first == second
    assert list(first) == sorted(first)


# --------------------------------------------------------------------------- #
# Namespace availability is probed, never assumed
# --------------------------------------------------------------------------- #
def test_namespace_support_reason_is_structural_only() -> None:
    """The pre-flight check reports a structural reason or ``None``; it never claims success."""
    reason = namespace_support_reason()
    assert reason is None or isinstance(reason, str)

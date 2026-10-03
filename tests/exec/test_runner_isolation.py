"""Runner isolation controls, executed against a real notebook kernel (RX-08, RX-11).

Marked ``integration`` because every test here starts a kernel. The marker is
descriptive, not a filter: the repository's default pytest options do not
deselect it, so these tests run -- and fail -- in the ordinary suite. A marker
used to keep a failure away from the integrator would be worse than no marker.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from retrace_contracts import ExecutionStatus, VerificationOutcome
from retrace_runner import (
    ExecutionEnvironmentUnavailable,
    ExecutionLimits,
    ExecutionResult,
    NetworkIsolation,
    run_notebook,
)

if TYPE_CHECKING:  # pragma: no cover - annotation only
    # Imported for typing only. A runtime `from .conftest import ...` fails
    # (tests/exec is not a package), and a bare `from conftest import ...`
    # would collide with the other suites' conftest basenames under pytest's
    # prepend import mode. `from __future__ import annotations` makes the
    # annotation a string, so no runtime import is needed at all.
    from .conftest import NotebookFactory

pytestmark = pytest.mark.integration

FAST = ExecutionLimits(wall_clock_seconds=180.0)
"""A generous wall clock for tests that are not about the wall clock."""


def test_a_clean_notebook_runs_and_reports_operational_facts_only(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A successful run reports SUCCEEDED, a manifest, and a verified guard (RX-08, RX-11)."""
    notebook = notebooks.write(
        "import json, os\n"
        "print('cwd=' + os.getcwd())\n"
        "json.dump({'outputs': {'m': {'value': 1.0, 'unit': 'g'}}}, open('outputs.json', 'w'))\n"
    )
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="clean")

    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.exit_code == 0
    assert result.isolation.guard_receipt_verified is True
    assert result.isolation.survivors == ()
    assert result.environment_manifest is not None
    assert result.environment_manifest.policy_digest == FAST.policy_digest
    assert result.environment_manifest.packages
    assert (Path(result.scratch_dir) / "outputs.json").is_file()
    assert f"cwd={result.scratch_dir}" in result.notebook_reported_claims


def test_the_result_type_cannot_express_a_verification_outcome() -> None:
    """The runner has no field for a scientific verdict (RX-11).

    A negative control on the trust boundary itself: if someone added an outcome
    field to the runner's result type, this fails.
    """
    fields = set(ExecutionResult.model_fields)
    assert "outcome" not in fields
    assert "verification_outcome" not in fields
    for value in VerificationOutcome:
        assert value.value.lower() not in {name.lower() for name in fields}


def test_wall_clock_timeout_kills_the_process_group_and_the_escaped_kernel(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A sleeping notebook is killed at the ceiling and nothing survives (RX-08).

    This is the control that proves group-kill alone is insufficient: the kernel
    is launched by ``jupyter_client`` with ``start_new_session=True``, so it is
    reaped by the ``/proc`` descendant sweep rather than by ``killpg``. The test
    asserts both that the group is gone and that no swept pid is still alive.
    """
    notebook = notebooks.write("import time\ntime.sleep(600)\n")
    limits = ExecutionLimits(wall_clock_seconds=6.0)
    result = run_notebook(notebook, tmp_path / "run", limits, run_id="runaway")

    assert result.status is ExecutionStatus.TIMEOUT
    assert result.duration_seconds >= 6.0
    assert result.duration_seconds < 60.0
    assert result.isolation.process_group_terminated is True
    assert result.isolation.survivors == ()
    assert result.isolation.reaped_descendant_pids, (
        "no descendant was reaped, so either the kernel never started or the sweep "
        "silently missed it"
    )

    pgid = result.isolation.process_group_id
    assert pgid is not None
    with pytest.raises(ProcessLookupError):
        os.killpg(pgid, 0)
    for pid in result.isolation.reaped_descendant_pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_a_socket_connection_from_the_notebook_is_denied(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """Egress from inside the kernel is refused by the guard (RX-08).

    The address is a routable literal and the refusal happens before any syscall,
    so the test needs no network and cannot pass by being offline.
    """
    notebook = notebooks.write(
        "import socket\n"
        "socket.create_connection(('93.184.216.34', 80), timeout=5)\n"
    )
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="egress")

    assert result.status is ExecutionStatus.FAILED
    assert result.cell_error is not None
    assert "RetraceNetworkDenied" in result.cell_error


def test_dns_resolution_from_the_notebook_is_denied(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """Name resolution is egress too, and is refused (RX-08)."""
    notebook = notebooks.write("import socket\nsocket.getaddrinfo('example.invalid', 443)\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="dns")

    assert result.status is ExecutionStatus.FAILED
    assert result.cell_error is not None
    assert "RetraceNetworkDenied" in result.cell_error


def test_a_write_outside_scratch_is_refused_and_leaves_no_file(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """The notebook cannot write outside its scratch root (RX-08).

    The assertion is about the filesystem, not only about the exception: the
    escape target must not exist afterwards.
    """
    escape_target = tmp_path / "escaped.txt"
    notebook = notebooks.write(f"open({str(escape_target)!r}, 'w').write('escaped')\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="escape")

    assert result.status is ExecutionStatus.FAILED
    assert result.cell_error is not None
    assert "RetraceWriteDenied" in result.cell_error
    assert not escape_target.exists()


def test_a_write_inside_scratch_succeeds(notebooks: NotebookFactory, tmp_path: Path) -> None:
    """The confinement permits the writes a real notebook needs.

    Paired with the previous test: a confinement that refused everything would
    pass that one while being useless.
    """
    notebook = notebooks.write("open('result.txt', 'w').write('kept')\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="inside")

    assert result.status is ExecutionStatus.SUCCEEDED
    assert (Path(result.scratch_dir) / "result.txt").read_text(encoding="utf-8") == "kept"


def test_the_notebook_cannot_write_into_the_runner_control_directory(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """The run record cannot be forged by the code being recorded (RX-08, RX-18)."""
    control = tmp_path / "run" / ".retrace-control" / "result.json"
    notebook = notebooks.write(f"open({str(control)!r}, 'w').write('{{\"status\": \"ok\"}}')\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="forge")

    assert result.status is ExecutionStatus.FAILED
    assert result.cell_error is not None
    assert "RetraceWriteDenied" in result.cell_error
    assert result.isolation.guard_receipt_verified is True


def test_spawning_a_process_from_the_notebook_is_denied(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """Spawn denial closes the hole that would bypass every cooperative layer (RX-08)."""
    notebook = notebooks.write("import subprocess\nsubprocess.Popen(['/bin/true'])\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="spawn")

    assert result.status is ExecutionStatus.FAILED
    assert result.cell_error is not None
    assert "RetraceSpawnDenied" in result.cell_error


def test_the_address_space_ceiling_is_in_force_inside_the_kernel(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """The kernel inherits ``RLIMIT_AS``, reported from inside the kernel itself (RX-08)."""
    limits = ExecutionLimits(wall_clock_seconds=180.0, max_address_space_bytes=1_500_000_000)
    notebook = notebooks.write(
        "import resource\nprint('as=' + str(resource.getrlimit(resource.RLIMIT_AS)[0]))\n"
    )
    result = run_notebook(notebook, tmp_path / "run", limits, run_id="rlimit")

    assert result.status is ExecutionStatus.SUCCEEDED
    assert "as=1500000000" in result.notebook_reported_claims
    assert result.isolation.address_space_limit_bytes == 1_500_000_000


def test_an_allocation_beyond_the_ceiling_fails_rather_than_exhausting_the_host(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A request beyond the address-space ceiling raises inside the kernel (RX-08)."""
    notebook = notebooks.write("buffer = bytearray(6 * 1024 * 1024 * 1024)\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="memory")

    assert result.status is ExecutionStatus.FAILED
    assert result.cell_error is not None
    assert "MemoryError" in result.cell_error or "Cannot allocate" in result.cell_error


def test_a_cell_exception_is_a_failed_run_not_a_verified_one(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A raising notebook is ``FAILED``; the runner states nothing about the science."""
    notebook = notebooks.write("raise ValueError('the analysis is wrong')\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="raise")

    assert result.status is ExecutionStatus.FAILED
    assert result.exit_code == 2
    assert "the analysis is wrong" in (result.cell_error or "")


def test_an_unavailable_kernel_raises_before_anything_is_started(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """No kernel means a named exception and *no execution at all* (RX-08).

    The assertion that the run directory was never created is what makes the
    exception positive evidence that nothing ran, rather than a report about
    something that already had.
    """
    notebook = notebooks.write("print('never runs')\n")
    workdir = tmp_path / "run"
    limits = ExecutionLimits(wall_clock_seconds=30.0, kernel_name="no-such-kernel-exists")

    with pytest.raises(ExecutionEnvironmentUnavailable) as refusal:
        run_notebook(notebook, workdir, limits, run_id="nokernel")

    assert "no-such-kernel-exists" in str(refusal.value)
    assert not workdir.exists()


def test_notebook_self_reported_claims_are_captured_but_quarantined(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A notebook printing a verdict gets it recorded as a claim, nothing more (RX-18)."""
    notebook = notebooks.write("print('VERIFICATION PASSED: everything reproduced')\n")
    result = run_notebook(notebook, tmp_path / "run", FAST, run_id="claims")

    assert result.status is ExecutionStatus.SUCCEEDED
    assert "VERIFICATION PASSED: everything reproduced" in result.notebook_reported_claims
    assert not hasattr(result, "outcome")


def test_kernel_namespace_isolation_is_established_or_refused_never_downgraded(
    notebooks: NotebookFactory, tmp_path: Path
) -> None:
    """A stronger isolation request is honoured or refused -- never silently weakened (RX-08).

    Unprivileged user-namespace creation is a kernel policy decision, so this
    test asserts the *property that must hold either way*: if the run happened,
    the applied mode is the requested one; if it could not, the run was refused
    with a named exception. There is no third outcome in which the run proceeded
    under ``COOPERATIVE``.
    """
    from retrace_runner import IsolationUnavailable

    notebook = notebooks.write("print('ran in a namespace')\n")
    limits = ExecutionLimits(
        wall_clock_seconds=180.0, network=NetworkIsolation.KERNEL_NAMESPACE
    )
    try:
        result = run_notebook(notebook, tmp_path / "run", limits, run_id="netns")
    except IsolationUnavailable as refusal:
        assert "namespace" in str(refusal).lower()
        return
    assert result.isolation.network_requested is NetworkIsolation.KERNEL_NAMESPACE
    assert result.isolation.network_applied is NetworkIsolation.KERNEL_NAMESPACE
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.isolation.loopback_available is True

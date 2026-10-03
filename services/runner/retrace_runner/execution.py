"""Isolated notebook execution: the runner's public entrypoint (RX-08).

:func:`run_notebook` executes a declared notebook in a **subprocess**, never in
this process, under a bounded wall clock, a bounded address space, writes
confined to a scratch root, and egress denied. It returns an
:class:`~retrace_runner.results.ExecutionResult` carrying an
:class:`~retrace_contracts.ExecutionStatus` and an
:class:`~retrace_contracts.EnvironmentManifest`.

THE ISOLATION, AND WHAT IT IS NOT (read this before quoting it as a boundary)
=============================================================================
Three layers, with genuinely different strengths:

**1. Process containment -- a real OS mechanism.** The child is started with
``start_new_session=True``, so it leads its own session and process group, and
the wall-clock ceiling is enforced by ``killpg(2)`` on that whole group rather
than on the direct child. That alone is not sufficient, and the reason is a
concrete fact about the toolchain rather than a theoretical worry:
``jupyter_client.launcher.launch_kernel`` launches the kernel with
``start_new_session=True`` itself, so **the notebook kernel leaves the child's
process group and session**. A group kill would reap the driver and orphan the
kernel. The runner therefore reaps by three independent mechanisms -- group kill,
a ``/proc`` descendant snapshot taken *before* the kill (afterwards the parent
links are gone), and the kernel pid the child records -- and then *verifies*
that nothing survived, reporting survivors in
:attr:`~retrace_runner.results.IsolationReport.survivors` instead of assuming
success.

**2. Resource ceilings -- a real OS mechanism.** ``RLIMIT_AS``, ``RLIMIT_FSIZE``
and ``RLIMIT_CORE`` are set inside the child before any thread or kernel exists,
so the kernel inherits them. ``RLIMIT_AS`` bounds address space, which is not the
same thing as resident memory: a process can be killed by the host OOM killer
below its ``RLIMIT_AS``, and a process that reserves without touching may stay
under a resident budget while exceeding this one.

**3. Egress denial and write confinement -- cooperative, NOT a boundary.** With
``NetworkIsolation.COOPERATIVE`` these are in-process Python monkeypatches
installed in both the driver and the kernel interpreter (see
:mod:`retrace_runner.guard`, whose docstring lists the limits in full).
Same-interpreter code can rebind them or ``reload`` the module to recover the
originals; native code -- ``ctypes``, a C extension, a compiled numerical
library -- never passes through them at all and is wholly unaffected. The proof
is visible in this very design: the kernel's own ZeroMQ transport keeps working
under total egress denial *because libzmq opens its sockets in C*. Loopback also
stays reachable under ``COOPERATIVE``.
``NetworkIsolation.KERNEL_NAMESPACE`` replaces that one layer with a real kernel
network boundary (``unshare(CLONE_NEWUSER|CLONE_NEWNET)``), but the filesystem,
``/proc`` and the PID namespace remain shared with the host.

**Conclusion, to be quoted as written:** this runner is appropriate for
*authorised but untrusted* scientific code -- code a reviewer has read and
admitted, where the risk being managed is runaway loops, accidental egress,
accidental writes and non-determinism. It is **not** a sandbox for hostile code.
Hostile code requires a kernel or hypervisor boundary (a VM, gVisor, a seccomp
profile, a locked-down container), and this build does not provide one.

**Arbitrary code execution stays refused.** There is no public entrypoint in
this package that accepts source code, a command line, or a module name to run.
:func:`run_notebook` accepts a *path to an admitted notebook artefact* and
refuses anything else: wrong suffix, symlink, non-regular file, or -- when a
``source_root`` is declared -- a path resolving outside it. The package contains
no ``eval``, ``exec`` or ``compile`` call, which
``tests/exec/test_runner_surface.py`` asserts over the module AST.

**The runner never judges science.** It records how a process terminated and
what the notebook printed; it does not import :mod:`retrace_verifier`, has no
comparison logic, and has no representation for a verification outcome (RX-11).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess  # noqa: S404 - the subprocess IS the isolation boundary here
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from retrace_contracts import EnvironmentManifest, ExecutionStatus

from . import guard
from .errors import (
    ExecutionEnvironmentUnavailable,
    IsolationUnavailable,
    NotebookAdmissionRefused,
    ScratchConfinementError,
)
from .netns import namespace_support_reason
from .policy import DEFAULT_LIMITS, ExecutionLimits, NetworkIsolation
from .protocol import EXIT_ENVIRONMENT_UNAVAILABLE, EXIT_ISOLATION_UNAVAILABLE, EXIT_OK
from .results import ExecutionResult, IsolationReport

__all__ = [
    "ARBITRARY_CODE_REFUSAL",
    "CONTROL_DIR_NAME",
    "GUARD_DIR_NAME",
    "HOME_DIR_NAME",
    "ISOLATION_LIMITS",
    "SCRATCH_DIR_NAME",
    "admit_notebook",
    "descendant_pids",
    "run_notebook",
]

SCRATCH_DIR_NAME: Final[str] = "scratch"
CONTROL_DIR_NAME: Final[str] = ".retrace-control"
GUARD_DIR_NAME: Final[str] = ".retrace-guard"
HOME_DIR_NAME: Final[str] = ".retrace-home"

NOTEBOOK_SUFFIX: Final[str] = ".ipynb"
# Not a secret: the substring a kernel command line must still contain before the
# runner will signal a recorded pid, so a recycled pid is left alone.
_KERNEL_PROCESS_TOKEN: Final[str] = "ipykernel"  # noqa: S105
_REAP_GRACE_SECONDS: Final[float] = 2.0
_REAP_POLL_SECONDS: Final[float] = 0.02

ARBITRARY_CODE_REFUSAL: Final[str] = (
    "This package exposes no entrypoint that accepts source code, a command "
    "line or a module name. Execution is only ever of a notebook artefact that "
    "passed admit_notebook(). Arbitrary code execution is refused, not gated."
)

ISOLATION_LIMITS: Final[tuple[str, ...]] = (
    "Process containment and resource ceilings are real OS mechanisms; egress "
    "denial and write confinement under COOPERATIVE are cooperative in-process "
    "restrictions that native code bypasses entirely.",
    "RLIMIT_AS bounds address space, not resident memory. The host OOM killer "
    "can still terminate a run below the configured cap.",
    "KERNEL_NAMESPACE isolates the network only: the filesystem, /proc and the "
    "PID namespace stay shared with the host.",
    "This is not a sandbox for hostile code. Hostile code needs a kernel or "
    "hypervisor boundary, which this build does not provide.",
)


def admit_notebook(notebook_path: Path, *, source_root: Path | None = None) -> Path:
    """Return the resolved notebook path, or refuse it by name (RX-08, RX-42).

    Admission rules, each refused with a named reason in
    :class:`~retrace_runner.errors.NotebookAdmissionRefused`: the suffix must be
    ``.ipynb``; the path must exist and be a regular file; it must not be a
    symlink (a symlink lets the artefact that was reviewed differ from the
    artefact that runs); and when ``source_root`` is declared the resolved path
    must lie within it.
    """
    raw = Path(notebook_path)
    if raw.suffix != NOTEBOOK_SUFFIX:
        raise NotebookAdmissionRefused(
            reason=f"suffix {raw.suffix!r} is not {NOTEBOOK_SUFFIX!r}", path=str(raw)
        )
    if raw.is_symlink():
        raise NotebookAdmissionRefused(
            reason="path is a symlink; the reviewed artefact and the executed artefact "
            "must be the same bytes",
            path=str(raw),
        )
    if not raw.exists():
        raise NotebookAdmissionRefused(reason="path does not exist", path=str(raw))
    if not raw.is_file():
        raise NotebookAdmissionRefused(reason="path is not a regular file", path=str(raw))
    resolved = raw.resolve()
    if source_root is not None:
        root = Path(source_root).resolve()
        if root != resolved and root not in resolved.parents:
            raise NotebookAdmissionRefused(
                reason=f"resolved path escapes the declared source root {root}",
                path=str(resolved),
            )
    return resolved


def descendant_pids(root_pid: int) -> set[int]:
    """Return every live descendant of ``root_pid`` by walking ``/proc`` (RX-08).

    Must be called *before* the root is killed: once the root dies its children
    are reparented and the link that identifies them as ours is gone. Returns an
    empty set where ``/proc`` is unavailable, which is reported as "nothing
    found", never as "nothing there".
    """
    children: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:  # pragma: no cover - /proc is present on every supported host
        return set()
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            stat_bytes = Path("/proc", entry, "stat").read_bytes()
        except OSError:
            continue
        fields = stat_bytes.rpartition(b")")[2].split()
        if len(fields) < 2:
            continue
        try:
            children.setdefault(int(fields[1]), []).append(int(entry))
        except ValueError:  # pragma: no cover - /proc field shape is stable
            continue
    found: set[int] = set()
    stack = [root_pid]
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def _process_is_alive(pid: int) -> bool:
    """Return whether ``pid`` currently exists."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_is_alive(pgid: int) -> bool:
    """Return whether any process remains in process group ``pgid``."""
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - same-uid groups do not raise this
        return True
    return True


def _kill_pids(pids: set[int]) -> tuple[int, ...]:
    """SIGKILL each pid that is still alive and return those actually signalled."""
    killed: list[int] = []
    for pid in sorted(pids):
        if pid <= 1:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue
        killed.append(pid)
    return tuple(killed)


def _read_kernel_pid(control_dir: Path) -> int | None:
    """Return the kernel pid the child recorded, if it recorded one.

    The child records it because ``jupyter_client`` puts the kernel in its own
    session, where a group kill cannot reach it.
    """
    try:
        text = (control_dir / "kernel.pid").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid > 1 else None


def _kernel_pid_still_ours(pid: int) -> bool:
    """Return whether ``pid`` still looks like the notebook kernel we started.

    Guards against pid reuse: a recorded pid is only signalled when its current
    command line still names the kernel. A pid that has been recycled into an
    unrelated process is left alone and reported as not reaped.
    """
    try:
        cmdline = Path("/proc", str(pid), "cmdline").read_bytes()
    except OSError:
        return False
    return _KERNEL_PROCESS_TOKEN.encode() in cmdline


def _materialise_guard(guard_dir: Path) -> Path:
    """Copy the guard module's source into ``guard_dir`` as ``sitecustomize.py``.

    The kernel's ``PYTHONPATH`` is set to this directory *alone*, so the guard
    is the only thing the kernel's import system gains -- in particular the
    kernel cannot import :mod:`retrace_runner` and reach the runner's own
    machinery. The file is a byte copy of a module that is linted and tested in
    place, not a generated string.
    """
    guard_dir.mkdir(parents=True, exist_ok=True)
    target = guard_dir / "sitecustomize.py"
    target.write_bytes(Path(guard.__file__).read_bytes())
    return target


def _preflight_environment(limits: ExecutionLimits) -> None:
    """Refuse the run now if the execution environment is unusable (RX-08).

    Checked in the parent so that an unavailable kernel raises
    :class:`~retrace_runner.errors.ExecutionEnvironmentUnavailable` *before any
    subprocess starts*. The exception is therefore positive evidence that
    nothing was executed, which is the property RX-08 needs and which a
    post-hoc failure status could not provide.
    """
    try:
        import nbformat  # noqa: F401 - availability probe only
        from jupyter_client.kernelspec import KernelSpecManager
        from nbclient import NotebookClient  # noqa: F401 - availability probe only
    except ImportError as error:
        raise ExecutionEnvironmentUnavailable(
            component="notebook machinery", detail=repr(error)
        ) from error
    try:
        KernelSpecManager().get_kernel_spec(limits.kernel_name)
    except Exception as error:
        raise ExecutionEnvironmentUnavailable(
            component=f"kernel spec {limits.kernel_name!r}", detail=repr(error)
        ) from error


def _preflight_isolation(limits: ExecutionLimits) -> None:
    """Refuse the run now if a requested isolation capability is structurally absent.

    Fail closed (RX-08): an isolation request that cannot be honoured is a
    reason not to run. There is no code path in this module that downgrades
    ``KERNEL_NAMESPACE`` to ``COOPERATIVE``.
    """
    if os.name != "posix":
        raise IsolationUnavailable(
            capability="process-group containment",
            detail=f"os.name={os.name!r}; start_new_session/killpg are POSIX-only",
        )
    if not hasattr(os, "killpg") or not hasattr(os, "setsid"):  # pragma: no cover - POSIX always
        raise IsolationUnavailable(capability="process-group containment", detail="no killpg")
    if limits.max_address_space_bytes is not None:
        try:
            import resource  # noqa: F401 - availability probe only
        except ImportError as error:  # pragma: no cover - POSIX always has resource
            raise IsolationUnavailable(
                capability="address-space ceiling", detail=repr(error)
            ) from error
    if limits.network is NetworkIsolation.KERNEL_NAMESPACE:
        reason = namespace_support_reason()
        if reason is not None:
            raise IsolationUnavailable(capability="kernel network namespace", detail=reason)


def _prepare_directories(workdir: Path) -> dict[str, Path]:
    """Create the scratch/control/guard/home layout and return it (RX-08)."""
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise ScratchConfinementError(path=str(workdir)) from error
    if not workdir.is_dir():
        raise ScratchConfinementError("workdir is not a directory", path=str(workdir))
    layout = {
        "workdir": workdir,
        "scratch": workdir / SCRATCH_DIR_NAME,
        "control": workdir / CONTROL_DIR_NAME,
        "guard": workdir / GUARD_DIR_NAME,
        "home": workdir / HOME_DIR_NAME,
    }
    layout["receipts"] = layout["control"] / "receipts"
    layout["tmp"] = layout["home"] / "tmp"
    for key in ("scratch", "control", "guard", "home", "receipts", "tmp"):
        try:
            layout[key].mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ScratchConfinementError(path=str(layout[key])) from error
    return layout


def _child_environment(runner_root: Path) -> dict[str, str]:
    """Return the child's environment: runner importable, guard variables cleared."""
    env = dict(os.environ)
    for name in (
        guard.ENV_ACTIVE,
        guard.ENV_WRITE_ROOTS,
        guard.ENV_NETWORK,
        guard.ENV_SPAWN,
        guard.ENV_RECEIPT_DIR,
    ):
        env.pop(name, None)
    env["PYTHONPATH"] = str(runner_root)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _read_capped(path: Path, cap: int) -> tuple[str, bool]:
    """Read at most ``cap`` bytes from ``path``; report whether more existed.

    Truncation keeps the head of the stream and is always reported. A silently
    truncated log is a log that lies about what happened.
    """
    try:
        with path.open("rb") as handle:
            data = handle.read(cap + 1)
    except OSError:
        return "", False
    if len(data) > cap:
        return data[:cap].decode("utf-8", "replace"), True
    return data.decode("utf-8", "replace"), False


def _read_child_report(control_dir: Path) -> dict[str, Any]:
    """Return the child's JSON report, or an empty mapping if it wrote none."""
    try:
        text = (control_dir / "result.json").read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        payload = json.loads(text)
    except ValueError:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _read_environment_manifest(
    control_dir: Path, *, policy_digest: str
) -> EnvironmentManifest | None:
    """Build the :class:`~retrace_contracts.EnvironmentManifest` the child captured.

    Returns ``None`` when the child wrote none. The policy digest is taken from
    the parent's own policy record rather than from the child's report, so a
    child that misreported it cannot change what the manifest claims was applied.
    """
    try:
        payload = json.loads((control_dir / "environment.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return EnvironmentManifest(
            python_version=str(payload["python_version"]),
            platform=str(payload["platform"]),
            packages={str(k): str(v) for k, v in dict(payload.get("packages", {})).items()},
            policy_digest=policy_digest,
            image_digest=payload.get("image_digest"),
            captured_at=datetime.fromisoformat(str(payload["captured_at"])),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _as_network_isolation(value: str, fallback: NetworkIsolation) -> NetworkIsolation:
    """Parse a child-reported isolation mode, defaulting to the requested one.

    A value the parent does not recognise never becomes a *weaker* mode: the
    requested mode is reported instead, and the mismatch check above has already
    refused the run if the child reported anything other than what was asked for.
    """
    try:
        return NetworkIsolation(value)
    except ValueError:
        return fallback


def run_notebook(
    notebook_path: str | os.PathLike[str],
    workdir: str | os.PathLike[str],
    limits: ExecutionLimits = DEFAULT_LIMITS,
    *,
    run_id: str = "run",
    source_root: str | os.PathLike[str] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ExecutionResult:
    """Execute ``notebook_path`` in an isolated subprocess and report (RX-08, RX-11).

    Parameters
    ----------
    notebook_path:
        Path to an admitted ``.ipynb`` artefact. See :func:`admit_notebook`.
    workdir:
        Run root. The runner creates ``scratch/`` (the notebook's cwd and only
        writable root), ``.retrace-control/`` (the run record and the executed
        notebook -- deliberately *not* writable by the notebook, so the record
        cannot be forged), ``.retrace-guard/`` and ``.retrace-home/``.
    limits:
        The policy envelope. Every ceiling in it is enforced or the run is
        refused.
    clock:
        Injectable clock for the two timestamps, so a caller can make a result
        reproducible. Defaults to UTC now, because a run's start and end are
        measurements.

    Raises
    ------
    NotebookAdmissionRefused:
        The artefact is not an admissible notebook.
    ExecutionEnvironmentUnavailable:
        No notebook machinery or no kernel spec. Raised before anything is
        started, so nothing executed.
    IsolationUnavailable:
        A requested isolation capability could not be established, including the
        case where the kernel process could not be shown to have installed the
        in-process guard. The run is refused; there is no unsandboxed fallback.
    ScratchConfinementError:
        The scratch layout could not be created.
    """
    now = clock or (lambda: datetime.now(UTC))
    notebook = admit_notebook(
        Path(notebook_path), source_root=Path(source_root) if source_root else None
    )
    _preflight_isolation(limits)
    _preflight_environment(limits)
    layout = _prepare_directories(Path(workdir).resolve())
    _materialise_guard(layout["guard"])

    admitted_copy = layout["control"] / "notebook.ipynb"
    shutil.copyfile(notebook, admitted_copy)

    # Both NetworkIsolation members include the cooperative layer; KERNEL_NAMESPACE
    # adds a kernel boundary underneath it rather than replacing it.
    guard_network = guard.NETWORK_DENY_NON_LOOPBACK
    spec = {
        "notebook_path": str(admitted_copy),
        "scratch_dir": str(layout["scratch"]),
        "control_dir": str(layout["control"]),
        "guard_dir": str(layout["guard"]),
        "home_dir": str(layout["home"]),
        "tmp_dir": str(layout["tmp"]),
        "receipt_dir": str(layout["receipts"]),
        "kernel_write_roots": [str(layout["scratch"]), str(layout["home"])],
        "child_write_roots": [
            str(layout["scratch"]),
            str(layout["home"]),
            str(layout["control"]),
        ],
        "guard_network": guard_network,
        "network": limits.network.value,
        "deny_child_process_spawn": limits.deny_child_process_spawn,
        "max_address_space_bytes": limits.max_address_space_bytes,
        "max_file_size_bytes": limits.max_file_size_bytes,
        "max_core_dump_bytes": limits.max_core_dump_bytes,
        "kernel_name": limits.kernel_name,
        "cell_timeout_seconds": limits.cell_timeout_seconds,
        "allow_notebook_cell_errors": limits.allow_notebook_cell_errors,
        "policy_digest": limits.policy_digest,
    }
    spec_path = layout["control"] / "spec.json"
    spec_path.write_text(
        json.dumps(spec, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )

    runner_root = Path(__file__).resolve().parents[1]
    stdout_path = layout["control"] / "stdout.log"
    stderr_path = layout["control"] / "stderr.log"
    started_at = now()
    started_monotonic = time.monotonic()

    with stdout_path.open("wb") as out_handle, stderr_path.open("wb") as err_handle:
        process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell, isolated child
            [sys.executable, "-m", "retrace_runner.child_main", str(spec_path)],
            cwd=str(layout["scratch"]),
            env=_child_environment(runner_root),
            stdin=subprocess.DEVNULL,
            stdout=out_handle,
            stderr=err_handle,
            start_new_session=True,
        )
        try:
            pgid = os.getpgid(process.pid)
        except ProcessLookupError:  # pragma: no cover - the child has only just started
            pgid = process.pid
        timed_out = False
        reaped: tuple[int, ...] = ()
        survivors: tuple[int, ...] = ()
        group_terminated = False
        try:
            process.wait(timeout=limits.wall_clock_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Snapshot first: after the kill the parent links that identify
            # these processes as ours no longer exist.
            targets = descendant_pids(process.pid)
            recorded_kernel = _read_kernel_pid(layout["control"])
            if recorded_kernel is not None and _kernel_pid_still_ours(recorded_kernel):
                targets.add(recorded_kernel)
            try:
                os.killpg(pgid, signal.SIGKILL)
                group_terminated = True
            except ProcessLookupError:  # pragma: no cover - group already empty
                group_terminated = True
            reaped = _kill_pids(targets)
            process.wait(timeout=_REAP_GRACE_SECONDS)
            deadline = time.monotonic() + _REAP_GRACE_SECONDS
            while time.monotonic() < deadline:
                if not _group_is_alive(pgid) and not any(
                    _process_is_alive(pid) for pid in targets
                ):
                    break
                time.sleep(_REAP_POLL_SECONDS)
            survivors = tuple(sorted(pid for pid in targets if _process_is_alive(pid)))

    duration = time.monotonic() - started_monotonic
    finished_at = now()
    returncode = process.returncode

    if not timed_out:
        leaked = _read_kernel_pid(layout["control"])
        if leaked is not None and _process_is_alive(leaked) and _kernel_pid_still_ours(leaked):
            reaped = _kill_pids({leaked})
            survivors = tuple(pid for pid in reaped if _process_is_alive(pid))

    report = _read_child_report(layout["control"])
    stdout, stdout_truncated = _read_capped(stdout_path, limits.max_captured_stream_bytes)
    stderr, stderr_truncated = _read_capped(stderr_path, limits.max_captured_stream_bytes)

    isolation_error = report.get("isolation_error")
    if returncode == EXIT_ISOLATION_UNAVAILABLE or returncode == guard.GUARD_INSTALL_FAILURE_EXIT:
        raise IsolationUnavailable(
            capability="child-side isolation",
            detail=str(isolation_error or f"child exit {returncode}; stderr: {stderr[-800:]}"),
        )
    if returncode == EXIT_ENVIRONMENT_UNAVAILABLE:
        raise ExecutionEnvironmentUnavailable(
            component="child-side notebook environment",
            detail=str(report.get("environment_error") or f"child exit {returncode}"),
        )
    if isolation_error:
        raise IsolationUnavailable(capability="child-side isolation", detail=str(isolation_error))

    applied_network = str(report.get("network_applied") or limits.network.value)
    if not timed_out and returncode is not None and returncode >= 0:
        if applied_network != limits.network.value:
            raise IsolationUnavailable(
                capability="network isolation",
                detail=f"requested {limits.network.value} but the child applied "
                f"{applied_network}; a downgrade is never accepted",
            )

    if timed_out:
        status = ExecutionStatus.TIMEOUT
    elif returncode is None:  # pragma: no cover - wait() always sets a returncode
        status = ExecutionStatus.FAILED
    elif returncode < 0:
        status = ExecutionStatus.KILLED
    elif returncode == EXIT_OK:
        status = ExecutionStatus.SUCCEEDED
    else:
        status = ExecutionStatus.FAILED

    isolation = IsolationReport(
        network_requested=limits.network,
        network_applied=_as_network_isolation(applied_network, limits.network),
        write_confinement=limits.write_confinement,
        scratch_root=str(layout["scratch"]),
        address_space_limit_bytes=report.get("address_space_limit_bytes"),
        guard_receipt_verified=bool(report.get("guard_receipt")),
        loopback_available=report.get("loopback_available"),
        process_group_id=pgid,
        process_group_terminated=group_terminated,
        reaped_descendant_pids=reaped,
        survivors=survivors,
    )
    claims = tuple(str(line) for line in report.get("notebook_reported_claims") or ())
    cell_error = report.get("cell_error")
    return ExecutionResult(
        run_id=run_id,
        status=status,
        exit_code=returncode if returncode is not None and returncode >= 0 else None,
        terminating_signal=-returncode if returncode is not None and returncode < 0 else None,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=max(duration, 0.0),
        stdout=stdout,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        environment_manifest=_read_environment_manifest(
            layout["control"], policy_digest=limits.policy_digest
        ),
        policy_digest=limits.policy_digest,
        isolation=isolation,
        scratch_dir=str(layout["scratch"]),
        control_dir=str(layout["control"]),
        executed_notebook_path=report.get("executed_notebook_path"),
        cell_error=str(cell_error) if cell_error else None,
        notebook_reported_claims=claims,
    )

"""The isolated child entrypoint: the only place a notebook is ever executed (RX-08).

Run as ``python -m retrace_runner.child_main <spec.json>`` by
:func:`retrace_runner.execution.run_notebook`. Nothing in the parent process
executes notebook code, and nothing in this module decides whether a result is
scientifically correct -- that judgement belongs to a different trust domain
(:mod:`retrace_verifier`), which this package does not import.

Order of operations is load-bearing and fail-closed:

1. resource ceilings (``RLIMIT_AS``/``FSIZE``/``CORE``) -- applied *before* any
   thread or kernel exists so the kernel inherits them;
2. the private network namespace when one was requested -- ``CLONE_NEWUSER``
   fails in a multi-threaded process, so this must precede everything;
3. the kernel's environment, including a ``PYTHONPATH`` containing *only* the
   guard directory, a redirected ``HOME``/``TMPDIR``/Jupyter dirs, and the
   ``RETRACE_GUARD_*`` variables;
4. the environment manifest, written before execution so that even a killed run
   carries one;
5. the in-process guard in this process (spawn permitted here, because starting
   the kernel is itself a spawn);
6. ``chdir`` into scratch;
7. kernel start, then **verification that the kernel wrote its guard receipt**;
8. cell execution.

Step 7 exists because ``site.execsitecustomize`` catches and discards exceptions
raised by ``sitecustomize``: without a positive receipt, "the guard is installed
in the kernel" would be an assumption. If the receipt is absent the child exits
:data:`EXIT_ISOLATION_UNAVAILABLE` without executing a single cell.

Exit statuses are the child's whole protocol with the parent:

=====  ========================================================================
``0``  the notebook ran to completion
``2``  a cell raised and cell errors are not allowed
``3``  no usable execution environment (no notebook machinery, no kernel spec)
``4``  a requested isolation capability could not be established
``5``  an internal child failure, reported rather than hidden
=====  ========================================================================
"""

from __future__ import annotations

import json
import os
import resource
import sys
import time
from typing import Any, Final

from . import environment, guard, netns
from .protocol import (
    EXIT_CELL_ERROR,
    EXIT_ENVIRONMENT_UNAVAILABLE,
    EXIT_INTERNAL_ERROR,
    EXIT_ISOLATION_UNAVAILABLE,
    EXIT_OK,
)

__all__ = ["main"]

RECEIPT_WAIT_SECONDS: Final[float] = 10.0
MAX_CLAIM_LINES: Final[int] = 200
MAX_CLAIM_LENGTH: Final[int] = 1000


def _write_json(path: str, payload: dict[str, Any]) -> None:
    """Write ``payload`` as UTF-8 JSON to ``path`` inside the control directory."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))


def _apply_resource_ceilings(spec: dict[str, Any]) -> dict[str, Any]:
    """Apply ``RLIMIT_*`` ceilings in this process so the kernel inherits them (RX-08)."""
    applied: dict[str, Any] = {}
    address_space = spec.get("max_address_space_bytes")
    if address_space is not None:
        resource.setrlimit(resource.RLIMIT_AS, (int(address_space), int(address_space)))
    file_size = spec.get("max_file_size_bytes")
    if file_size is not None:
        resource.setrlimit(resource.RLIMIT_FSIZE, (int(file_size), int(file_size)))
    core = spec.get("max_core_dump_bytes")
    if core is not None:
        resource.setrlimit(resource.RLIMIT_CORE, (int(core), int(core)))
    soft, _hard = resource.getrlimit(resource.RLIMIT_AS)
    applied["address_space_limit_bytes"] = None if soft == resource.RLIM_INFINITY else soft
    return applied


def _prepare_kernel_environment(spec: dict[str, Any]) -> None:
    """Point the kernel at the guard and at confined HOME/TMP/Jupyter directories (RX-08)."""
    home = spec["home_dir"]
    tmp = spec["tmp_dir"]
    os.environ["PYTHONPATH"] = spec["guard_dir"]
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["HOME"] = home
    os.environ["TMPDIR"] = tmp
    os.environ["TEMP"] = tmp
    os.environ["TMP"] = tmp
    os.environ["XDG_CACHE_HOME"] = os.path.join(home, ".cache")
    os.environ["XDG_CONFIG_HOME"] = os.path.join(home, ".config")
    os.environ["XDG_DATA_HOME"] = os.path.join(home, ".local", "share")
    os.environ["XDG_RUNTIME_DIR"] = os.path.join(home, ".runtime")
    os.environ["IPYTHONDIR"] = os.path.join(home, ".ipython")
    os.environ["JUPYTER_CONFIG_DIR"] = os.path.join(home, ".jupyter")
    os.environ["JUPYTER_DATA_DIR"] = os.path.join(home, ".jupyter-data")
    os.environ["JUPYTER_RUNTIME_DIR"] = os.path.join(home, ".jupyter-runtime")
    os.environ["MPLCONFIGDIR"] = os.path.join(home, ".matplotlib")
    os.environ[guard.ENV_ACTIVE] = "1"
    os.environ[guard.ENV_WRITE_ROOTS] = os.pathsep.join(spec["kernel_write_roots"])
    os.environ[guard.ENV_NETWORK] = spec["guard_network"]
    os.environ[guard.ENV_SPAWN] = (
        guard.SPAWN_DENY if spec["deny_child_process_spawn"] else guard.SPAWN_ALLOW
    )
    os.environ[guard.ENV_RECEIPT_DIR] = spec["receipt_dir"]
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ.pop(name, None)


def _kernel_pid(kernel_manager: Any) -> int | None:
    """Return the kernel's OS pid, trying the known provisioner shapes.

    ``jupyter_client`` launches the kernel with ``start_new_session=True``, so the
    kernel leaves this process's session and process group entirely. The parent
    cannot reap it by group, which makes this pid the runner's only reliable
    handle on it -- see :func:`retrace_runner.execution.run_notebook`.
    """
    for path in (("provisioner", "process", "pid"), ("kernel", "pid"), ("provisioner", "pid")):
        target: Any = kernel_manager
        for attribute in path:
            target = getattr(target, attribute, None)
            if target is None:
                break
        if isinstance(target, int):
            return target
    return None


def _await_guard_receipt(receipt_dir: str, pid: int | None) -> dict[str, Any] | None:
    """Return the kernel's guard receipt, or ``None`` if it never appeared (RX-08)."""
    if pid is None:
        return None
    path = os.path.join(receipt_dir, guard.receipt_filename(pid))
    deadline = time.monotonic() + RECEIPT_WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            with open(path, encoding="utf-8") as handle:
                return dict(json.load(handle))
        except (OSError, ValueError):
            time.sleep(0.05)
    return None


def _collect_reported_claims(notebook: Any) -> list[str]:
    """Collect what the notebook printed about itself -- quarantined, never trusted (RX-18)."""
    claims: list[str] = []
    for cell in getattr(notebook, "cells", []):
        for output in cell.get("outputs", []) or []:
            text = output.get("text")
            if not text:
                continue
            if isinstance(text, list):
                text = "".join(str(part) for part in text)
            for line in str(text).splitlines():
                stripped = line.strip()
                if stripped:
                    claims.append(stripped[:MAX_CLAIM_LENGTH])
                if len(claims) >= MAX_CLAIM_LINES:
                    return claims
    return claims


def main(argv: list[str]) -> int:
    """Execute one notebook under the declared isolation and report (RX-08, RX-11)."""
    if len(argv) != 2:
        sys.stderr.write("usage: python -m retrace_runner.child_main <spec.json>\n")
        return EXIT_INTERNAL_ERROR
    with open(argv[1], encoding="utf-8") as handle:
        spec = json.load(handle)

    control_dir = spec["control_dir"]
    report: dict[str, Any] = {
        "network_applied": "COOPERATIVE",
        "loopback_available": None,
        "guard_receipt": None,
        "cell_error": None,
        "notebook_reported_claims": [],
        "isolation_error": None,
        "environment_error": None,
    }
    result_path = os.path.join(control_dir, "result.json")

    try:
        report.update(_apply_resource_ceilings(spec))
    except (OSError, ValueError) as error:
        report["isolation_error"] = f"resource ceiling refused: {error!r}"
        _write_json(result_path, report)
        return EXIT_ISOLATION_UNAVAILABLE

    if spec["network"] == "KERNEL_NAMESPACE":
        try:
            netns.enter_private_network_namespace()
        except netns.NetworkNamespaceUnavailable as error:
            report["isolation_error"] = f"kernel network namespace unavailable: {error}"
            _write_json(result_path, report)
            return EXIT_ISOLATION_UNAVAILABLE
        report["network_applied"] = "KERNEL_NAMESPACE"
        report["loopback_available"] = netns.bring_loopback_up()

    _prepare_kernel_environment(spec)

    try:
        _write_json(
            os.path.join(control_dir, "environment.json"),
            dict(environment.capture_environment(policy_digest=spec["policy_digest"])),
        )
    except Exception as error:  # noqa: BLE001 - a missing manifest is reported, not faked
        report["environment_error"] = repr(error)

    guard.install(
        write_roots=tuple(spec["child_write_roots"]),
        network=spec["guard_network"],
        # The child must be allowed to spawn: starting the kernel is a spawn.
        # The kernel itself is given SPAWN_DENY through the environment above.
        spawn=guard.SPAWN_ALLOW,
        receipt_dir=None,
    )
    os.chdir(spec["scratch_dir"])

    try:
        import nbformat
        from jupyter_client.kernelspec import KernelSpecManager
        from nbclient import NotebookClient
        from nbclient.exceptions import CellExecutionError
    except ImportError as error:
        report["environment_error"] = f"notebook machinery unavailable: {error!r}"
        _write_json(result_path, report)
        return EXIT_ENVIRONMENT_UNAVAILABLE

    try:
        KernelSpecManager().get_kernel_spec(spec["kernel_name"])
    except Exception as error:  # noqa: BLE001 - any kernelspec failure means unavailable
        report["environment_error"] = f"kernel spec {spec['kernel_name']!r} unavailable: {error!r}"
        _write_json(result_path, report)
        return EXIT_ENVIRONMENT_UNAVAILABLE

    notebook = nbformat.read(spec["notebook_path"], as_version=4)
    client = NotebookClient(
        notebook,
        kernel_name=spec["kernel_name"],
        timeout=spec.get("cell_timeout_seconds"),
        allow_errors=bool(spec["allow_notebook_cell_errors"]),
        record_timing=False,
        resources={"metadata": {"path": spec["scratch_dir"]}},
    )

    exit_status = EXIT_OK
    try:
        with client.setup_kernel():
            kernel_pid = _kernel_pid(client.km)
            if kernel_pid is not None:
                with open(os.path.join(control_dir, "kernel.pid"), "w", encoding="utf-8") as fh:
                    fh.write(str(kernel_pid))
            receipt = _await_guard_receipt(spec["receipt_dir"], kernel_pid)
            report["guard_receipt"] = receipt
            if receipt is None:
                report["isolation_error"] = (
                    "the kernel process did not write a guard install receipt, so the "
                    "in-process guard cannot be shown to be active; refusing to execute"
                )
                _write_json(result_path, report)
                return EXIT_ISOLATION_UNAVAILABLE
            for index, cell in enumerate(notebook.cells):
                client.execute_cell(cell, index)
    except CellExecutionError as error:
        report["cell_error"] = str(error)[:4000]
        exit_status = EXIT_CELL_ERROR
    except Exception as error:  # noqa: BLE001 - reported to the parent, never swallowed
        report["cell_error"] = f"{type(error).__name__}: {error}"[:4000]
        exit_status = EXIT_INTERNAL_ERROR

    report["notebook_reported_claims"] = _collect_reported_claims(notebook)
    executed_path = os.path.join(control_dir, "executed.ipynb")
    try:
        nbformat.write(notebook, executed_path)
        report["executed_notebook_path"] = executed_path
    except Exception as error:  # noqa: BLE001 - recorded, not hidden
        report["environment_error"] = f"could not write executed notebook: {error!r}"
    _write_json(result_path, report)
    return exit_status


def _main_guarded(argv: list[str]) -> int:
    """Run :func:`main`, reporting an unexpected child failure instead of only crashing.

    A bare traceback reaches the parent through stderr, but without a
    ``result.json`` the parent cannot distinguish an internal child fault from a
    notebook failure. This wrapper guarantees the distinction is recorded.
    """
    try:
        return main(argv)
    except Exception as error:  # noqa: BLE001 - the child's last chance to report
        sys.stderr.write(f"retrace runner child failed: {type(error).__name__}: {error}\n")
        if len(argv) == 2:
            try:
                with open(argv[1], encoding="utf-8") as handle:
                    control = json.load(handle)["control_dir"]
                _write_json(
                    os.path.join(control, "result.json"),
                    {"child_error": f"{type(error).__name__}: {error}"},
                )
            except Exception as nested:  # noqa: BLE001 - last resort before exiting
                sys.stderr.write(f"retrace runner child could not record the failure: {nested!r}\n")
        return EXIT_INTERNAL_ERROR


if __name__ == "__main__":
    sys.exit(_main_guarded(sys.argv))

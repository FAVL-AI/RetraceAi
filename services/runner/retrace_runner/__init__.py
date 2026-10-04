"""RETRACE isolated runner -- untrusted execution, and nothing else (RX-08, RX-11).

This service runs a declared notebook in a subprocess under a bounded wall
clock, a bounded address space, writes confined to a scratch root, egress
denied, and -- when the policy declares it -- a kernel mount namespace in which
the declared protected paths are read-only and the declared secret directories
are empty. Read :mod:`retrace_runner.execution` before relying on any of that as a
boundary: the process and resource layers are real OS mechanisms, the egress and
write layers under ``COOPERATIVE`` are cooperative in-process restrictions that
native code bypasses, and none of it is a sandbox for hostile code.

**Trust-domain rule, enforced by test.** This package must never decide whether
a result is scientifically correct. It does not import :mod:`retrace_verifier`,
contains no comparison or tolerance logic, and has no type that can represent a
:class:`~retrace_contracts.VerificationOutcome`.
``tests/exec/test_runner_surface.py`` walks this package's import graph and
fails if that changes.

=========================================  =============================
Unit                                       Requirement
=========================================  =============================
:func:`~retrace_runner.execution.run_notebook`     RX-08, RX-11
:class:`~retrace_runner.policy.ExecutionLimits`    RX-08, RX-15
:mod:`retrace_runner.guard`                        RX-08
:mod:`retrace_runner.netns`                        RX-08
:mod:`retrace_runner.mountns`                      RX-08
:func:`~retrace_runner.environment.capture_environment`  RX-15, RX-16
:class:`~retrace_runner.results.ExecutionResult`   RX-08, RX-11, RX-18
=========================================  =============================
"""

from __future__ import annotations

from .environment import capture_environment, installed_distributions
from .errors import (
    ExecutionEnvironmentUnavailable,
    FilesystemConfinementUnavailable,
    IsolationUnavailable,
    NotebookAdmissionRefused,
    RunnerError,
    ScratchConfinementError,
)
from .execution import (
    ARBITRARY_CODE_REFUSAL,
    ISOLATION_LIMITS,
    admit_notebook,
    descendant_pids,
    run_notebook,
)
from .guard import (
    GUARD_LIMITS,
    RetraceGuardDenied,
    RetraceNetworkDenied,
    RetraceSpawnDenied,
    RetraceWriteDenied,
)
from .mountns import (
    FILESYSTEM_LIMITS,
    MountConfinementUnavailable,
    RealisedConfinement,
    probe_confinement_capability,
)
from .netns import NAMESPACE_LIMITS, NamespaceUnavailable, NetworkNamespaceUnavailable
from .policy import (
    DEFAULT_LIMITS,
    ExecutionLimits,
    FilesystemConfinement,
    NetworkIsolation,
    WriteConfinement,
)
from .protocol import (
    EXIT_CELL_ERROR,
    EXIT_ENVIRONMENT_UNAVAILABLE,
    EXIT_INTERNAL_ERROR,
    EXIT_ISOLATION_UNAVAILABLE,
    EXIT_OK,
)
from .results import ExecutionResult, IsolationReport
from .seams import SnapshotMaterialiser, SnapshotMember

__version__ = "0.0.0"

__all__ = [
    "ARBITRARY_CODE_REFUSAL",
    "DEFAULT_LIMITS",
    "EXIT_CELL_ERROR",
    "EXIT_ENVIRONMENT_UNAVAILABLE",
    "EXIT_INTERNAL_ERROR",
    "EXIT_ISOLATION_UNAVAILABLE",
    "EXIT_OK",
    "FILESYSTEM_LIMITS",
    "GUARD_LIMITS",
    "ISOLATION_LIMITS",
    "NAMESPACE_LIMITS",
    "ExecutionEnvironmentUnavailable",
    "ExecutionLimits",
    "ExecutionResult",
    "FilesystemConfinement",
    "FilesystemConfinementUnavailable",
    "IsolationReport",
    "IsolationUnavailable",
    "MountConfinementUnavailable",
    "NamespaceUnavailable",
    "NetworkIsolation",
    "NetworkNamespaceUnavailable",
    "NotebookAdmissionRefused",
    "RealisedConfinement",
    "RetraceGuardDenied",
    "RetraceNetworkDenied",
    "RetraceSpawnDenied",
    "RetraceWriteDenied",
    "RunnerError",
    "ScratchConfinementError",
    "SnapshotMaterialiser",
    "SnapshotMember",
    "WriteConfinement",
    "__version__",
    "admit_notebook",
    "capture_environment",
    "descendant_pids",
    "installed_distributions",
    "probe_confinement_capability",
    "run_notebook",
]

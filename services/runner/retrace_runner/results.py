"""What one isolated run produced -- operational facts only (RX-08, RX-11).

:class:`ExecutionResult` is the runner's entire output type, and it deliberately
carries no verification vocabulary. It holds an
:class:`~retrace_contracts.ExecutionStatus`, never a
:class:`~retrace_contracts.VerificationOutcome`, because a process that exited
``0`` has told us only that it exited ``0`` (RX-11).

:attr:`ExecutionResult.notebook_reported_claims` exists so that what the
notebook *said about itself* is preserved and visibly quarantined (RX-18). The
runner records those lines; it never acts on them, and it is not the component
that decides whether they were true.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import AwareDatetime, Field
from retrace_contracts import (
    EnvironmentManifest,
    ExecutionStatus,
    FrozenRecord,
    Identifier,
    NonEmptyStr,
    Sha256Hex,
)

from .policy import NetworkIsolation, WriteConfinement

__all__ = ["ExecutionResult", "IsolationReport"]


class IsolationReport(FrozenRecord):
    """What isolation was actually established for a run (RX-08).

    Every field records an *observation*, not a request. ``network_requested``
    and ``network_applied`` are both present precisely so that a downgrade would
    be visible in the record; the runner refuses to run rather than produce a
    result in which they disagree, and
    ``tests/exec/test_runner_isolation.py`` asserts that.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.IsolationReport"

    network_requested: NetworkIsolation = Field(description="Egress denial that was requested.")
    network_applied: NetworkIsolation = Field(description="Egress denial actually established.")
    write_confinement: WriteConfinement = Field(description="Write confinement established.")
    scratch_root: NonEmptyStr = Field(description="Absolute path the notebook was confined to.")
    address_space_limit_bytes: int | None = Field(
        default=None, ge=0, description="RLIMIT_AS observed inside the kernel, when reported."
    )
    guard_receipt_verified: bool = Field(
        default=False,
        description="True only when the kernel process wrote an install receipt. False means "
        "the in-process guard was not proven to be active.",
    )
    loopback_available: bool | None = Field(
        default=None, description="Whether loopback was up inside a private namespace."
    )
    process_group_id: int | None = Field(
        default=None, description="Process group the child led, for audit of the kill path."
    )
    process_group_terminated: bool = Field(
        default=False, description="True when the runner had to terminate the group."
    )
    reaped_descendant_pids: tuple[int, ...] = Field(
        default=(),
        description="Descendants the runner had to kill individually because the notebook "
        "kernel is launched into its own session and leaves the child's process group.",
    )
    survivors: tuple[int, ...] = Field(
        default=(),
        description="Processes still alive after the kill sweep. Non-empty is a reported "
        "containment failure, never a silent one.",
    )


class ExecutionResult(FrozenRecord):
    """The complete record of one isolated notebook execution (RX-08, RX-11).

    ``environment_manifest`` is ``None`` only when the child died before it could
    report one -- that is an honest gap, not a placeholder. The child captures the
    environment *before* executing the notebook so that even a ``TIMEOUT`` run
    carries its manifest.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ExecutionResult"

    run_id: Identifier = Field(description="Stable id of this run.")
    status: ExecutionStatus = Field(
        description="How the process terminated. Not a statement about the science (RX-11)."
    )
    exit_code: int | None = Field(default=None, description="Child exit status, when it exited.")
    terminating_signal: int | None = Field(
        default=None, ge=0, description="Signal number that killed the child, when one did."
    )
    started_at: AwareDatetime = Field(description="When the child was started.")
    finished_at: AwareDatetime = Field(description="When the child was reaped.")
    duration_seconds: float = Field(ge=0.0, description="Measured wall-clock duration.")
    stdout: str = Field(default="", description="Captured child stdout, possibly truncated.")
    stderr: str = Field(default="", description="Captured child stderr, possibly truncated.")
    stdout_truncated: bool = Field(default=False, description="Whether stdout was truncated.")
    stderr_truncated: bool = Field(default=False, description="Whether stderr was truncated.")
    environment_manifest: EnvironmentManifest | None = Field(
        default=None, description="Environment observed in the child, or None if never reported."
    )
    policy_digest: Sha256Hex = Field(description="Digest of the execution policy applied.")
    isolation: IsolationReport = Field(description="Isolation actually established (RX-08).")
    scratch_dir: NonEmptyStr = Field(description="Absolute path of the notebook's scratch root.")
    control_dir: NonEmptyStr = Field(
        description="Absolute path of the runner's control directory. Outside the notebook's "
        "writable roots, so the notebook cannot forge the run record."
    )
    executed_notebook_path: str | None = Field(
        default=None, description="Executed notebook with outputs, when one was written."
    )
    cell_error: str | None = Field(
        default=None, description="Cell exception summary, when a cell raised."
    )
    notebook_reported_claims: tuple[str, ...] = Field(
        default=(),
        description="Lines the notebook printed about itself. Quarantined, untrusted, and "
        "never used by anything in this package to decide anything (RX-18).",
    )

    @property
    def succeeded(self) -> bool:
        """Whether the *process* completed. Says nothing about the result (RX-11)."""
        return self.status is ExecutionStatus.SUCCEEDED

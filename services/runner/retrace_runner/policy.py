"""The execution policy the runner applies, and its digest (RX-08, RX-15).

The policy is a frozen, hashed record for one reason: RX-15 requires an
:class:`~retrace_contracts.EnvironmentManifest` carrying a ``policy_digest``, so
a second researcher can prove they re-ran under the same envelope rather than
under a differently-configured runner. Changing any ceiling changes the digest.

Requirement coverage:

* :class:`ExecutionLimits` -- RX-08 (bounded wall clock, bounded memory,
  scratch-only writes, network denial), RX-15 (``policy_digest``).
* :class:`NetworkIsolation` -- RX-08. The two members are *not* equivalent and
  the weaker one is never substituted for the stronger: see
  :mod:`retrace_runner.execution` for the fail-closed rule.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, ClassVar, Final

from pydantic import Field
from retrace_contracts import FrozenRecord, Sha256Hex

__all__ = [
    "DEFAULT_LIMITS",
    "ExecutionLimits",
    "NetworkIsolation",
    "WriteConfinement",
]

PositiveFloat = Annotated[float, Field(gt=0.0, allow_inf_nan=False)]
PositiveInt = Annotated[int, Field(gt=0)]

MIN_ADDRESS_SPACE_BYTES: Final[int] = 256 * 1024 * 1024
"""Floor on an address-space cap.

A cap below this cannot start a CPython kernel at all, so accepting one would
produce an :class:`~retrace_contracts.ExecutionStatus` of ``FAILED`` that looks
like a scientific failure and is actually a misconfigured ceiling.
"""


class NetworkIsolation(str, Enum):
    """How egress is denied inside the child (RX-08).

    Members
    -------
    COOPERATIVE:
        In-process denial installed in both the driver and the kernel
        interpreter: Python-level ``connect``/``create_connection``/name
        resolution to any non-loopback address is refused. This is defence in
        depth and **not** a boundary -- see
        :mod:`retrace_runner.guard` for the exact, honest limits.
    KERNEL_NAMESPACE:
        The child enters a new user+network namespace (``unshare(2)``) before
        any notebook machinery starts, so the kernel has no route off the host
        at the kernel level. The cooperative layer is applied *as well*. If the
        namespace cannot be created the run is refused; it is never downgraded
        to ``COOPERATIVE``.
    """

    COOPERATIVE = "COOPERATIVE"
    KERNEL_NAMESPACE = "KERNEL_NAMESPACE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class WriteConfinement(str, Enum):
    """How writes are confined (RX-08).

    ``SCRATCH_ONLY`` is the only supported value. It exists as a closed enum
    rather than a boolean so that a future kernel-enforced confinement can be
    added as a distinct, non-substitutable member -- the same fail-closed shape
    as :class:`NetworkIsolation`.
    """

    SCRATCH_ONLY = "SCRATCH_ONLY"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ExecutionLimits(FrozenRecord):
    """The resource and isolation envelope for one run (RX-08, RX-15).

    Every field is a ceiling or a capability request. None of them is advisory:
    :func:`retrace_runner.execution.run_notebook` refuses the run if a requested
    capability cannot be established.

    Notes on individual ceilings:

    ``wall_clock_seconds``
        Enforced by the parent, which kills the child's whole process group and
        then sweeps surviving descendants (RX-08). The kernel is launched by
        ``jupyter_client`` with ``start_new_session=True`` and therefore leaves
        the child's group, so group-kill alone would orphan it -- see
        :func:`retrace_runner.execution.run_notebook`.
    ``max_address_space_bytes``
        ``RLIMIT_AS``, set inside the child before any kernel starts, so the
        kernel inherits it. A cap below :data:`MIN_ADDRESS_SPACE_BYTES` is
        refused at construction.
    ``cell_timeout_seconds``
        Passed to the notebook client. Secondary to ``wall_clock_seconds``,
        which is the ceiling that is actually enforced by signal.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ExecutionLimits"

    wall_clock_seconds: PositiveFloat = Field(
        default=600.0, description="Hard wall-clock ceiling for the whole child process group."
    )
    cell_timeout_seconds: PositiveFloat | None = Field(
        default=None, description="Per-cell ceiling handed to the notebook client, or None."
    )
    max_address_space_bytes: int | None = Field(
        default=2 * 1024 * 1024 * 1024,
        ge=MIN_ADDRESS_SPACE_BYTES,
        description="RLIMIT_AS applied in the child and inherited by the kernel.",
    )
    max_file_size_bytes: int | None = Field(
        default=512 * 1024 * 1024, gt=0, description="RLIMIT_FSIZE applied in the child."
    )
    max_core_dump_bytes: int = Field(
        default=0, ge=0, description="RLIMIT_CORE; zero so a crash cannot write a core image."
    )
    max_captured_stream_bytes: PositiveInt = Field(
        default=1024 * 1024,
        description="Bytes of stdout/stderr retained in the result; the rest is dropped "
        "and the truncation is reported, never hidden.",
    )
    network: NetworkIsolation = Field(
        default=NetworkIsolation.COOPERATIVE,
        description="Requested egress denial. Never downgraded silently (RX-08).",
    )
    write_confinement: WriteConfinement = Field(
        default=WriteConfinement.SCRATCH_ONLY,
        description="Requested write confinement (RX-08).",
    )
    deny_child_process_spawn: bool = Field(
        default=True,
        description="Refuse process spawning inside the kernel interpreter. Spawning would "
        "defeat both the cooperative egress denial and the write confinement.",
    )
    kernel_name: str = Field(
        default="python3", min_length=1, max_length=128, description="Kernel spec name."
    )
    allow_notebook_cell_errors: bool = Field(
        default=False,
        description="When False a cell exception ends the run and the status is FAILED. "
        "A notebook that raised has not reproduced anything.",
    )

    @property
    def policy_digest(self) -> Sha256Hex:
        """SHA-256 over the canonical form of this policy (RX-08, RX-15)."""
        return self.content_digest()


DEFAULT_LIMITS: Final[ExecutionLimits] = ExecutionLimits()
"""The default envelope: 600 s, 2 GiB address space, cooperative egress denial."""

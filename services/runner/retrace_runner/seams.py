"""Narrow protocols the runner needs from the domain layer (RX-01, RX-06, RX-08).

``packages/domain`` owns the snapshot store, the approval ledger and the repair
authority. This service does not import it. Instead it declares the *smallest*
interface it actually needs, as :class:`typing.Protocol` classes, so the
integrator can wire the real implementations in without either side depending on
the other's internals -- and so the runner's tests can run against a fixture
that implements four methods rather than against a half-built package.

Both protocols are **read-only by construction**: neither declares a write,
because the runner has no authority to mutate a snapshot. A notebook is
materialised into the run's own scratch root, never executed in place against
the snapshot store (RX-06: a repair is a reviewable patch, not an in-place
mutation).
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

__all__ = ["SnapshotMaterialiser", "SnapshotMember"]


@runtime_checkable
class SnapshotMember(Protocol):
    """One file inside an immutable snapshot, pinned by digest (RX-01)."""

    @property
    def path(self) -> str:
        """Snapshot-relative POSIX path."""

    @property
    def sha256(self) -> str:
        """Lowercase hex SHA-256 of the member's exact bytes."""


@runtime_checkable
class SnapshotMaterialiser(Protocol):
    """Materialise an immutable snapshot into a run's scratch root (RX-01, RX-08).

    The runner needs exactly three things from the domain layer: the snapshot's
    identity (which goes into the run record), the ability to copy its bytes
    into a scratch directory the runner owns, and the digest-verified member
    list so the caller can prove what was materialised.

    Implementations must verify each member's digest while materialising and
    raise :class:`~retrace_contracts.SnapshotIntegrityError` on a mismatch
    (RX-02). This protocol cannot enforce that; the integrator must.
    """

    @property
    def snapshot_id(self) -> str:
        """Stable identifier of the snapshot being executed against."""

    def members(self) -> tuple[SnapshotMember, ...]:
        """Return the snapshot's members with their recorded digests."""

    def materialise(self, destination: Path) -> tuple[str, ...]:
        """Copy the snapshot into ``destination`` and return the paths written."""

"""Per-tenant durable areas: quarantine, content store, ledger, indexes (RX-47).

WHY FILESYSTEM AREAS AND NOT DATABASE TABLES.

The migration suite asserts the realised schema is exactly ``projects``,
``result_contracts`` and ``alembic_version``, and that assertion is an executed
proof, not a preference. Adding tables for snapshots, proposals, runs, reports
and evidence would break it. So the objects whose authority is already
content-addressed live where that authority already is: the content-addressed
store from ``retrace_domain`` for bytes, the hash-chained approval ledger for
approvals, and an append-only JSON-lines index per object kind for listings.

WHAT THAT COSTS, STATED PLAINLY.

* A write that spans PostgreSQL and these files is NOT one transaction. A crash
  between the two leaves a contract row with no stored document, or a stored
  document with no row. The ordering is chosen so the recoverable direction is
  the one that happens: files first, row last, so a failure leaves an orphan
  file (inert, and identifiable by digest) rather than a row pointing at nothing.
* Indexes are append-only files, so concurrent appends from multiple processes
  are not serialised by anything stronger than the filesystem's append
  behaviour. Single-process use is safe; a multi-process deployment needs a real
  table.

Both are listed as blockers rather than described as a design.

TENANT SEPARATION IS BY DIRECTORY.

Each tenant gets ``<root>/<tenant uuid>/``, and every path is constructed from
the authorised tenant. The tenant segment is validated as a UUID before it is
joined, so a crafted identifier cannot climb out of the root.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from retrace_api.web.errors import NEEDS_CONFIGURATION, ApiRefusal
from retrace_domain import ApprovalLedger, ContentAddressedStore

__all__ = [
    "INDEX_KINDS",
    "ObjectIndex",
    "StorageNotConfigured",
    "TenantWorkspace",
    "WorkspaceFactory",
]

#: The object kinds that get an append-only index. A closed list so a typo
#: creates an error rather than a silently empty new index.
INDEX_KINDS: Final[tuple[str, ...]] = (
    "uploads",
    "snapshots",
    "contracts",
    "proposals",
    "reviews",
    "runs",
    "reports",
    "exports",
    "imports",
)


class StorageNotConfigured(ApiRefusal):
    """No durable area is configured, so the route cannot proceed (RX-40).

    Reported as ``NEEDS_CONFIGURATION`` rather than served from a temporary
    directory. A route that quietly wrote evidence somewhere ephemeral would
    hand back identifiers that resolve until the process restarts, which is a
    success-shaped answer to a missing dependency.
    """

    status_code = 503
    code = "STORAGE_NOT_CONFIGURED"

    def __init__(self) -> None:
        super().__init__(
            "no storage root is configured, so quarantine, snapshots, the approval "
            "ledger and evidence have nowhere durable to live",
            remedy="set RETRACE_STORAGE_ROOT to a writable directory",
            extra={"status": NEEDS_CONFIGURATION, "missing": ["RETRACE_STORAGE_ROOT"]},
        )


@dataclass(frozen=True)
class ObjectIndex:
    """An append-only JSON-lines index of one object kind for one tenant.

    Append-only on purpose: an index that could be rewritten in place could also
    lose a record without trace. A correction is a new record with a later
    sequence, and :meth:`latest` resolves an identifier to its most recent
    record, so a correction is visible as a correction.
    """

    path: Path

    def append(self, record: dict[str, Any]) -> None:
        if "id" not in record:
            raise ValueError("an index record must carry an 'id'")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if "\n" in line:
            raise ValueError("a serialised index record must not contain a newline")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def records(self) -> tuple[dict[str, Any], ...]:
        if not self.path.is_file():
            return ()
        out: list[dict[str, Any]] = []
        for raw in self.path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                out.append(parsed)
        return tuple(out)

    def latest(self, object_id: str) -> dict[str, Any] | None:
        """The most recent record for ``object_id``, or ``None``."""
        found: dict[str, Any] | None = None
        for record in self.records():
            if record.get("id") == object_id:
                found = record
        return found

    def distinct(self) -> tuple[dict[str, Any], ...]:
        """One record per identifier, the most recent of each, in insertion order."""
        order: list[str] = []
        latest: dict[str, dict[str, Any]] = {}
        for record in self.records():
            object_id = str(record.get("id"))
            if object_id not in latest:
                order.append(object_id)
            latest[object_id] = record
        return tuple(latest[object_id] for object_id in order)


class TenantWorkspace:
    """One tenant's durable area (RX-47)."""

    def __init__(self, root: Path, tenant_id: str) -> None:
        self._tenant_id = str(uuid.UUID(tenant_id))
        self._root = root / self._tenant_id
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    @property
    def root(self) -> Path:
        return self._root

    @property
    def quarantine_root(self) -> Path:
        return self._root.parent / "_quarantine"

    @property
    def store(self) -> ContentAddressedStore:
        """The tenant's content-addressed blob store."""
        return ContentAddressedStore(self._root / "objects")

    @property
    def ledger(self) -> ApprovalLedger:
        """The tenant's append-only, hash-chained approval ledger (RX-05)."""
        return ApprovalLedger(self._root / "approvals.jsonl")

    @property
    def evidence_dir(self) -> Path:
        path = self._root / "evidence"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def index(self, kind: str) -> ObjectIndex:
        if kind not in INDEX_KINDS:
            raise ValueError(f"unknown index kind {kind!r}; expected one of {INDEX_KINDS}")
        return ObjectIndex(self._root / "index" / f"{kind}.jsonl")

    def documents(self) -> Iterator[Path]:
        """Every stored blob path. Diagnostics and tests only."""
        objects = self._root / "objects"
        return objects.rglob("*") if objects.is_dir() else iter(())


class WorkspaceFactory:
    """Builds :class:`TenantWorkspace` objects, or refuses when unconfigured."""

    def __init__(self, root: Path | None) -> None:
        self._root = root

    @property
    def configured(self) -> bool:
        return self._root is not None

    @property
    def root(self) -> Path:
        if self._root is None:
            raise StorageNotConfigured
        return self._root

    def for_tenant(self, tenant_id: str) -> TenantWorkspace:
        if self._root is None:
            raise StorageNotConfigured
        return TenantWorkspace(self._root, tenant_id)

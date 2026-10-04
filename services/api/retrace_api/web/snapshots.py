"""Storing and reloading snapshot manifests (RX-01, RX-02).

A MANIFEST IS STORED AS A BLOB IN THE SAME CONTENT-ADDRESSED STORE AS ITS FILES.

That keeps one authority for bytes. The index record carries the manifest's blob
digest, so reading a snapshot back is: read the index record, fetch the blob by
digest (which the store verifies), and reconstruct the manifest - whose own
``__post_init__`` re-validates every path and digest. A manifest tampered with
in place therefore fails the store's digest check, and a manifest carrying a
traversal path fails reconstruction. Neither failure can be reached by a caller
supplying a path.
"""

from __future__ import annotations

import json
from typing import Any

from retrace_api.web.errors import NotFound
from retrace_api.web.workspace import TenantWorkspace
from retrace_domain import ContentAddressedStore, SnapshotManifest

__all__ = ["load_manifest", "resolve_snapshot", "store_manifest"]


def store_manifest(store: ContentAddressedStore, manifest: SnapshotManifest) -> str:
    """Put the manifest document in the store and return its digest."""
    payload = json.dumps(manifest.to_json_dict(), sort_keys=True, separators=(",", ":"))
    return store.put_bytes(payload.encode("utf-8"))


def load_manifest(store: ContentAddressedStore, blob_digest: str) -> SnapshotManifest:
    """Reconstruct a manifest from its stored blob (RX-02)."""
    document: Any = json.loads(store.get_bytes(blob_digest).decode("utf-8"))
    files = document.get("files", {})
    if not isinstance(files, dict):
        raise ValueError("the stored manifest document has no 'files' mapping")
    manifest = SnapshotManifest.from_mapping(files)
    recorded = document.get("manifest_digest")
    if recorded != manifest.manifest_digest:
        # The store already verified the BYTES. This catches a document whose
        # recorded digest disagrees with the digest its own file map produces,
        # which would mean the two were written from different content.
        raise ValueError(
            "the stored manifest's recorded digest does not match its file map"
        )
    return manifest


def resolve_snapshot(
    workspace: TenantWorkspace, *, snapshot_id: str, project_id: str | None = None
) -> tuple[dict[str, Any], SnapshotManifest]:
    """Find a snapshot in the authorised workspace, or 404 (RX-47).

    Scoped to the workspace by construction: the index being read belongs to the
    tenant's own directory, so a snapshot identifier from another tenant resolves
    to nothing here rather than to that tenant's content.
    """
    record = workspace.index("snapshots").latest(snapshot_id)
    if record is None or (project_id is not None and record.get("project_id") != project_id):
        raise NotFound(
            f"no snapshot {snapshot_id!r} exists in the authorised workspace",
            remedy="create a snapshot from an admitted upload first",
        )
    blob = record.get("manifest_blob")
    if not blob:
        raise NotFound(
            f"snapshot {snapshot_id!r} has no stored manifest document",
            remedy="re-create the snapshot",
        )
    return record, load_manifest(workspace.store, str(blob))

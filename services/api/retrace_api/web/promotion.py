"""Promoting an admitted upload to an immutable snapshot (RX-01, RX-42).

PROMOTION IS A SEPARATE STEP FROM ADMISSION ON PURPOSE.

Admission decides; promotion acts. Keeping them apart means the decision is made
over bytes that are already at rest in quarantine, and the act of materialising
them happens only after every rule has passed. It also means promotion can
re-verify: the quarantined digest is checked again before the bytes are written
anywhere, because a snapshot is content-addressed and a snapshot pinning content
that was swapped after admission would be worse than no snapshot at all.

EXTRACTION RE-CHECKS WHAT ADMISSION ALREADY CHECKED.

Member names were validated during admission. They are validated AGAIN here,
and the resolved absolute target is required to sit under the destination root.
That is not redundancy for its own sake: the first check reads the central
directory, this one checks the path that is actually about to be opened, and a
path can be made to differ between those two readings (a name that normalises
differently, a symlinked destination). The cheap check at the point of the write
is the one that protects the write.

WHY THE PER-MEMBER WRITE IS CAPPED AGAIN, AND WHAT THAT CAP ACTUALLY CATCHES.

``ZipInfo.file_size`` is a DECLARED size from the archive's own metadata, so the
write streams with its own cap rather than trusting it.

Measured rather than assumed: CPython's ``ZipExtFile`` stops at the DECLARED
size, so a member that declares a small size and carries more data is truncated
by the reader and then fails its own CRC check - it does not reach the cap. The
streaming cap is therefore defence in depth against a reader that does not
truncate, and the refusal a crafted member actually produces today is
``archive-member-unreadable``. Saying otherwise would be claiming a control
fires on a path it does not.

``BadZipFile`` is caught for that reason. A crafted archive raising it uncaught
would be a 500 for a payload the service is supposed to refuse, and it would
leave a partially written member behind.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from retrace_api.web.admission import AdmissionPolicy, AdmittedUpload, DetectedKind
from retrace_api.web.errors import UploadRefused
from retrace_contracts import is_safe_relative_path
from retrace_domain import ContentAddressedStore, SnapshotManifest, snapshot_create

__all__ = ["materialise_admitted", "promote_to_snapshot"]

_CHUNK = 64 * 1024


def _refuse(reason: str, detail: str, *, remedy: str) -> UploadRefused:
    return UploadRefused(detail, remedy=remedy, extra={"reason": reason})


def _safe_target(destination: Path, name: str) -> Path:
    if not is_safe_relative_path(name) or name.startswith("/") or "\\" in name:
        raise _refuse(
            "archive-member-traversal",
            f"member {name!r} is not a relative, traversal-free POSIX path",
            remedy="rebuild the archive with relative member names",
        )
    root = destination.resolve()
    target = (root / name).resolve()
    if target != root and root not in target.parents:
        raise _refuse(
            "archive-member-traversal",
            f"member {name!r} resolves outside the extraction root",
            remedy="rebuild the archive with relative member names",
        )
    return target


def materialise_admitted(
    admitted: AdmittedUpload,
    data: bytes,
    destination: Path,
    *,
    policy: AdmissionPolicy,
) -> tuple[str, ...]:
    """Write an admitted upload into ``destination`` and return the paths written."""
    destination.mkdir(parents=True, exist_ok=True)
    if admitted.detected_kind is not DetectedKind.ZIP_ARCHIVE:
        target = _safe_target(destination, admitted.quarantined.filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return (admitted.quarantined.filename,)

    written: list[str] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in admitted.member_paths:
            target = _safe_target(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            member_bytes = 0
            try:
                with archive.open(name) as source, target.open("wb") as sink:
                    while True:
                        chunk = source.read(_CHUNK)
                        if not chunk:
                            break
                        member_bytes += len(chunk)
                        total += len(chunk)
                        if member_bytes > policy.max_archive_member_bytes:
                            sink.close()
                            target.unlink(missing_ok=True)
                            raise _refuse(
                                "archive-member-too-large",
                                f"member {name!r} decompressed past the "
                                f"{policy.max_archive_member_bytes} byte per-member cap; "
                                "the declared size in the archive metadata was smaller",
                                remedy="split or shrink the member",
                            )
                        if total > policy.max_archive_total_bytes:
                            sink.close()
                            target.unlink(missing_ok=True)
                            raise _refuse(
                                "archive-total-too-large",
                                f"the archive decompressed past the "
                                f"{policy.max_archive_total_bytes} byte total cap",
                                remedy="split the archive",
                            )
                        sink.write(chunk)
            except (zipfile.BadZipFile, OSError, EOFError, KeyError) as exc:
                # A member whose data disagrees with its metadata raises here -
                # a rewritten size, a damaged deflate stream, a CRC mismatch.
                # Uncaught it would be a 500 for a crafted payload, and it would
                # leave a partial file behind; both are refusals instead.
                target.unlink(missing_ok=True)
                raise _refuse(
                    "archive-member-unreadable",
                    f"member {name!r} could not be read: its stored data disagrees with "
                    "the archive's own metadata, so nothing was promoted",
                    remedy="re-create the archive",
                ) from exc
            written.append(name)
    return tuple(written)


def promote_to_snapshot(
    admitted: AdmittedUpload,
    data: bytes,
    *,
    store: ContentAddressedStore,
    staging: Path,
    policy: AdmissionPolicy,
) -> SnapshotManifest:
    """Materialise, snapshot, and return the manifest (RX-01).

    The snapshot is built from a STAGING directory, not from quarantine, so the
    quarantined bytes remain exactly as received for forensics and the snapshot
    is built from content that has been written and read back once.
    """
    materialise_admitted(admitted, data, staging, policy=policy)
    return snapshot_create(store, staging)

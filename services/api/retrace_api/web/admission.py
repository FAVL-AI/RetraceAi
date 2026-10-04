"""Upload admission and quarantine (RX-42).

THE ORDER OF OPERATIONS IS THE SECURITY PROPERTY.

Bytes are written to a per-tenant quarantine area FIRST, inspected there, and
promoted to a snapshot only if every rule passes. Inspecting a stream on its way
to its final location means a refusal happens after the bytes have already
arrived somewhere that is treated as trusted; a refused payload then has to be
*removed*, and a removal that fails leaves a trusted-looking artefact nobody
admitted. Quarantining first makes the failure mode "an unpromoted file in a
quarantine directory", which is inert.

WHAT IS CHECKED, AND WHY EACH CHECK IS NOT IMPLIED BY ANOTHER.

* **Size cap, enforced while reading.** Checking ``len(body)`` after reading it
  has already allocated the body. The cap is applied to the stream so an
  oversized upload is abandoned part way.
* **Declared type against sniffed bytes.** The declared ``Content-Type`` and the
  filename are both attacker-controlled. Sniffing the leading bytes and
  requiring agreement is what refuses a pickle stream posted as
  ``application/json`` - a check neither the extension nor the header can make.
* **Pickle, by signature, never by deserialisation.** No module in this package
  imports :mod:`pickle`. A pickle stream is detected by its opcode prefix and
  refused; it is never loaded to "see what it is", because loading it is the
  whole attack.
* **Macro-bearing documents.** A legacy OLE2 compound document is refused
  outright - deciding whether it carries a macro requires parsing it, and that
  parser would be the attack surface. An OOXML container is refused when it
  carries a ``vbaProject`` part or a macro-enabled extension.
* **Archive members: traversal, count, member size, total size, ratio.** These
  are four independent limits, and a bomb defeats any three of them alone. A
  single 10 GB member passes a ratio check if it is stored uncompressed; a
  million tiny members passes a total-size check; a 42 KB archive expanding to
  4 GB passes a member-count check. Member names are checked with the shared
  path validator so "``..``" and absolute names are refused by the same rule the
  evidence bundler uses.
* **Member type allowlist.** Members are admitted by extension from a closed
  list rather than refused from an open one: an unknown extension is refused,
  so a format added to the world does not silently become admissible here.
* **Nested archives are refused.** Recursive inspection would need a depth
  budget and a ratio budget per level; refusing the nesting is a smaller, more
  defensible rule than a recursive walk that has to be correct at every depth.

WHAT THIS DOES NOT DO.

It does not virus-scan, it does not validate that a notebook is executable, and
it does not establish that admitted content is scientifically meaningful.
Admission is a gate on SHAPE. Passing it says the bytes are of a declared, known
form within declared limits - nothing more.
"""

from __future__ import annotations

import codecs
import datetime as dt
import hashlib
import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, Final

from retrace_api.web.errors import UploadRefused
from retrace_contracts import is_safe_relative_path

__all__ = [
    "ADMITTED_ARCHIVE_SUFFIXES",
    "DEFAULT_ADMISSION_POLICY",
    "AdmissionPolicy",
    "AdmittedUpload",
    "DetectedKind",
    "MACRO_ENABLED_SUFFIXES",
    "NOTEBOOK_MARKER",
    "OLE2_MAGIC",
    "PICKLE_MAGIC",
    "QuarantineArea",
    "QuarantinedUpload",
    "admit_bytes",
    "read_capped",
    "sniff",
]

#: Pickle opcode prefixes. Held here rather than imported from the verifier
#: because the verifier refuses archives too (it reads JSON and CSV only) and
#: this surface must ADMIT archives in order to inspect them. The two cannot be
#: allowed to drift: `tests/api/test_admission.py` asserts that every
#: pickle-labelled signature in `retrace_verifier.REFUSED_MAGIC` is covered by
#: this tuple, so a signature added there fails this module's test.
PICKLE_MAGIC: Final[tuple[bytes, ...]] = (
    b"\x80\x01",
    b"\x80\x02",
    b"\x80\x03",
    b"\x80\x04",
    b"\x80\x05",
    b"(lp",
    b"(dp",
    b"}q",
    b"]q",
    b"ccopy_reg\n",
    b"cos\n",
    b"c__builtin__\n",
    b"c__main__\n",
)

#: The key that distinguishes a notebook from any other JSON document. Searched
#: for across the whole payload, never only in the sniff prefix: every notebook
#: writer emits `nbformat` after `cells`, so in a real notebook it is nowhere
#: near the first 512 bytes.
NOTEBOOK_MARKER: Final[bytes] = b'"nbformat"'

#: Legacy OLE2 compound-document signature. Covers the pre-2007 Office formats
#: and any other compound document; refused without further parsing.
OLE2_MAGIC: Final = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

#: Extensions whose whole purpose is to carry executable project code.
MACRO_ENABLED_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".docm", ".dotm", ".xlsm", ".xltm", ".xlam", ".pptm", ".potm", ".ppam", ".xlm", ".slk"}
)

#: Archive member extensions admitted into a snapshot. A closed list.
ADMITTED_ARCHIVE_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".json", ".csv", ".tsv", ".ipynb", ".txt", ".md", ".py", ".toml", ".cfg", ".ini", ".rst"}
)

#: Signatures that indicate a member is itself a compressed container.
_NESTED_ARCHIVE_MAGIC: Final[tuple[bytes, ...]] = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"ustar",
)

_VBA_PART_NAMES: Final[tuple[str, ...]] = ("vbaproject.bin", "vbadata.xml", "vbaproject.bin.rels")

#: Bytes of each payload inspected for a signature. Long enough for every
#: signature above with room to spare, short enough that it is a prefix read.
_SNIFF_BYTES: Final = 512

_S_IFMT: Final = 0o170000
_S_IFREG: Final = 0o100000
_S_IFLNK: Final = 0o120000


class DetectedKind(str, Enum):
    """What the leading bytes actually look like (RX-42)."""

    JSON = "JSON"
    NOTEBOOK = "NOTEBOOK"
    CSV = "CSV"
    PLAIN_TEXT = "PLAIN_TEXT"
    ZIP_ARCHIVE = "ZIP_ARCHIVE"


#: Declared media type -> the kinds whose bytes may legitimately accompany it.
#: A notebook is JSON, so ``application/json`` admits either; ``text/csv`` does
#: not admit JSON, because a JSON document posted as CSV means the client is
#: mistaken about its own payload and the downstream parser would be too.
_DECLARED_TYPES: Final[dict[str, frozenset[DetectedKind]]] = {
    "application/json": frozenset({DetectedKind.JSON, DetectedKind.NOTEBOOK}),
    "application/x-ipynb+json": frozenset({DetectedKind.NOTEBOOK}),
    "text/csv": frozenset({DetectedKind.CSV}),
    "text/tab-separated-values": frozenset({DetectedKind.CSV}),
    "text/plain": frozenset({DetectedKind.PLAIN_TEXT, DetectedKind.CSV}),
    "text/markdown": frozenset({DetectedKind.PLAIN_TEXT}),
    "application/zip": frozenset({DetectedKind.ZIP_ARCHIVE}),
}


@dataclass(frozen=True)
class AdmissionPolicy:
    """The admission limits (RX-42).

    Every bound is explicit and none is unlimited. Defaults are deliberately
    modest: a limit that is too generous to ever trip is documentation, not a
    control.
    """

    max_upload_bytes: int = 32 * 1024 * 1024
    max_archive_members: int = 2048
    max_archive_member_bytes: int = 16 * 1024 * 1024
    max_archive_total_bytes: int = 64 * 1024 * 1024
    max_compression_ratio: float = 100.0

    def __post_init__(self) -> None:
        for name in (
            "max_upload_bytes",
            "max_archive_members",
            "max_archive_member_bytes",
            "max_archive_total_bytes",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_compression_ratio <= 1.0:
            raise ValueError("max_compression_ratio must exceed 1.0")


DEFAULT_ADMISSION_POLICY: Final = AdmissionPolicy()


@dataclass(frozen=True)
class QuarantinedUpload:
    """Bytes that have landed in quarantine but have NOT been admitted (RX-42)."""

    upload_id: str
    tenant_id: str
    project_id: str
    filename: str
    declared_content_type: str
    byte_count: int
    sha256: str
    path: Path
    received_at: dt.datetime


@dataclass(frozen=True)
class AdmittedUpload:
    """A quarantined upload that passed every admission rule (RX-42)."""

    quarantined: QuarantinedUpload
    detected_kind: DetectedKind
    member_paths: tuple[str, ...]

    @property
    def upload_id(self) -> str:
        return self.quarantined.upload_id

    @property
    def sha256(self) -> str:
        return self.quarantined.sha256


def _refuse(reason: str, detail: str, *, remedy: str, status_code: int = 422) -> UploadRefused:
    return UploadRefused(
        detail, remedy=remedy, status_code=status_code, extra={"reason": reason}
    )


def read_capped(stream: BinaryIO, policy: AdmissionPolicy) -> bytes:
    """Read at most ``max_upload_bytes`` and refuse anything longer (RX-42).

    Reads one byte past the cap on purpose: without it, a payload of exactly the
    cap and a payload that was truncated at the cap are indistinguishable, and
    the second would be admitted as a complete document.
    """
    limit = policy.max_upload_bytes
    data = stream.read(limit + 1)
    if len(data) > limit:
        raise _refuse(
            "size-cap-exceeded",
            f"the upload exceeds the {limit} byte cap and was not read to completion",
            remedy=f"split the payload or raise max_upload_bytes above {limit}",
            status_code=413,
        )
    return data


def sniff(data: bytes) -> DetectedKind:
    """Classify ``data`` by its leading bytes, or refuse it (RX-42).

    Signature checks come first and the text heuristics last, so a payload that
    *starts* like text but matches a refused signature is still refused.

    TWO THINGS ARE DELIBERATELY NOT DECIDED FROM THE PREFIX ALONE.

    The prefix is decoded with an INCREMENTAL decoder. A fixed 512-byte slice of
    valid UTF-8 can end in the middle of a multi-byte character, and a strict
    ``bytes.decode`` would raise on that - refusing a perfectly good document for
    the position of one character. ``final=False`` tolerates the truncated tail
    and still raises on bytes that are genuinely not UTF-8.

    The notebook marker is searched for across the WHOLE payload. ``nbformat``
    and ``nbformat_minor`` are written AFTER ``cells`` by every notebook writer,
    so in any real notebook they sit far beyond 512 bytes. Deciding notebook-ness
    from the prefix therefore classified every real notebook as plain ``JSON``,
    and a notebook correctly declared ``application/x-ipynb+json`` was refused as
    a content-type mismatch - a legitimate upload refused by the rule meant to
    catch a lying one. The payload is already fully in memory and bounded by
    ``max_upload_bytes``, so the wider search costs one scan of a capped buffer.
    """
    if not data:
        raise _refuse(
            "empty-payload",
            "the upload carried no bytes",
            remedy="post the document body",
        )
    prefix = data[:_SNIFF_BYTES]
    for signature in PICKLE_MAGIC:
        if prefix.startswith(signature):
            raise _refuse(
                "pickle-stream",
                "the payload begins with a pickle opcode stream; it is refused by "
                "signature and is never deserialised",
                remedy="export the data as JSON or CSV",
                status_code=415,
            )
    if prefix.startswith(OLE2_MAGIC):
        raise _refuse(
            "macro-bearing-document",
            "the payload is an OLE2 compound document; deciding whether it carries a "
            "macro would require parsing it, and that parser would itself be the "
            "attack surface, so the format is refused",
            remedy="export the sheet or document as CSV or JSON",
            status_code=415,
        )
    if prefix.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        return DetectedKind.ZIP_ARCHIVE
    if b"\x00" in prefix:
        raise _refuse(
            "nul-byte",
            "the payload contains a NUL byte within its leading bytes, so it is not "
            "the text document it claims to be",
            remedy="post a text, JSON or CSV document, or a zip archive",
            status_code=415,
        )
    try:
        text = codecs.getincrementaldecoder("utf-8")().decode(prefix, False)
    except UnicodeDecodeError as exc:
        raise _refuse(
            "unrecognised-bytes",
            "the payload is neither a recognised archive nor valid UTF-8 text",
            remedy="post UTF-8 JSON, CSV, plain text, or a zip archive",
            status_code=415,
        ) from exc
    stripped = text.lstrip("﻿ \t\r\n")
    if stripped.startswith(("{", "[")):
        return DetectedKind.NOTEBOOK if NOTEBOOK_MARKER in data else DetectedKind.JSON
    first_line = stripped.split("\n", 1)[0]
    if ("," in first_line or "\t" in first_line) and first_line.strip():
        return DetectedKind.CSV
    return DetectedKind.PLAIN_TEXT


def _check_declared(declared_content_type: str, detected: DetectedKind) -> None:
    declared = declared_content_type.split(";", 1)[0].strip().lower()
    permitted = _DECLARED_TYPES.get(declared)
    if permitted is None:
        raise _refuse(
            "declared-type-unsupported",
            f"content type {declared!r} is not in the admission allowlist "
            f"{sorted(_DECLARED_TYPES)}",
            remedy="declare one of the supported content types",
            status_code=415,
        )
    if detected not in permitted:
        raise _refuse(
            "content-type-mismatch",
            f"the payload's bytes look like {detected.value} but it was declared as "
            f"{declared!r}; the declared type and the filename are both caller-supplied, "
            "so the bytes decide",
            remedy="declare the content type that matches the bytes being sent",
            status_code=415,
        )


def _check_filename(filename: str) -> str:
    name = filename.strip()
    if not name:
        raise _refuse(
            "filename-missing",
            "the upload declared no filename",
            remedy="send a filename with the part",
        )
    if not is_safe_relative_path(name) or "/" in name or "\\" in name:
        raise _refuse(
            "filename-unsafe",
            f"filename {name!r} is not a single traversal-free path segment",
            remedy="send a plain filename with no directory component",
        )
    suffix = Path(name).suffix.lower()
    if suffix in MACRO_ENABLED_SUFFIXES:
        raise _refuse(
            "macro-bearing-document",
            f"{suffix!r} is a macro-enabled document format and is refused by extension "
            "as well as by content",
            remedy="export the content as CSV or JSON",
            status_code=415,
        )
    return name


def _inspect_archive(data: bytes, policy: AdmissionPolicy) -> tuple[str, ...]:
    """Refuse an unsafe archive and return its admitted member names (RX-42).

    Nothing is extracted. Every decision is made from the central directory and
    from a bounded prefix read of each member, so a refusal here leaves no file
    anywhere.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise _refuse(
            "archive-unreadable",
            "the payload declares a zip signature but its central directory could not "
            "be read",
            remedy="re-create the archive",
        ) from exc
    with archive:
        infos = [info for info in archive.infolist() if not info.is_dir()]
        if len(infos) > policy.max_archive_members:
            raise _refuse(
                "archive-member-count",
                f"{len(infos)} members exceeds the {policy.max_archive_members} member cap",
                remedy="split the archive",
            )
        declared_total = 0
        compressed_total = 0
        names: list[str] = []
        for info in infos:
            name = info.filename
            mode = (info.external_attr >> 16) & _S_IFMT
            if mode == _S_IFLNK:
                raise _refuse(
                    "archive-non-regular-member",
                    f"member {name!r} is a symbolic link, which could redirect a later "
                    "write outside the extraction root",
                    remedy="store regular files only",
                )
            if mode not in (0, _S_IFREG):
                raise _refuse(
                    "archive-non-regular-member",
                    f"member {name!r} has unsupported mode {oct(mode)}",
                    remedy="store regular files only",
                )
            if name.startswith("/") or "\\" in name or not is_safe_relative_path(name):
                raise _refuse(
                    "archive-member-traversal",
                    f"member {name!r} is absolute, uses backslashes, or traverses out of "
                    "the archive root",
                    remedy="store members under relative, traversal-free POSIX paths",
                )
            suffix = Path(name).suffix.lower()
            if suffix in MACRO_ENABLED_SUFFIXES:
                raise _refuse(
                    "macro-bearing-document",
                    f"member {name!r} is a macro-enabled document format",
                    remedy="remove the macro-enabled member",
                    status_code=415,
                )
            if Path(name).name.lower() in _VBA_PART_NAMES or "/vbaproject." in name.lower():
                raise _refuse(
                    "macro-bearing-document",
                    f"member {name!r} is a VBA project part, so this container carries "
                    "executable document code",
                    remedy="save the document without macros, or export it as CSV or JSON",
                    status_code=415,
                )
            if suffix not in ADMITTED_ARCHIVE_SUFFIXES:
                raise _refuse(
                    "archive-member-type-refused",
                    f"member {name!r} has extension {suffix!r}, which is not in the "
                    f"admitted set {sorted(ADMITTED_ARCHIVE_SUFFIXES)}",
                    remedy="remove the member, or export it in an admitted format",
                    status_code=415,
                )
            if info.file_size > policy.max_archive_member_bytes:
                raise _refuse(
                    "archive-member-too-large",
                    f"member {name!r} declares {info.file_size} bytes, over the "
                    f"{policy.max_archive_member_bytes} per-member cap",
                    remedy="split or shrink the member",
                    status_code=413,
                )
            declared_total += info.file_size
            compressed_total += info.compress_size
            if declared_total > policy.max_archive_total_bytes:
                raise _refuse(
                    "archive-total-too-large",
                    f"the archive declares at least {declared_total} uncompressed bytes, "
                    f"over the {policy.max_archive_total_bytes} total cap",
                    remedy="split the archive",
                    status_code=413,
                )
            names.append(name)
        ratio = declared_total / compressed_total if compressed_total else float(declared_total)
        if compressed_total and ratio > policy.max_compression_ratio:
            raise _refuse(
                "archive-compression-ratio",
                f"the archive expands {ratio:.1f}x, over the "
                f"{policy.max_compression_ratio:.1f}x cap",
                remedy="store the data uncompressed, or split it",
                status_code=413,
            )
        for info in infos:
            # A bounded prefix read, not an extraction: enough to see a nested
            # container's signature or a pickle stream hiding behind an admitted
            # extension. `open` on a ZipInfo decompresses lazily, and only this
            # prefix is ever produced.
            #
            # BadZipFile is CAUGHT, not allowed to propagate. A member whose
            # central-directory metadata disagrees with its data - a rewritten
            # size, a damaged deflate stream, a CRC that does not match - raises
            # here, and an uncaught raise would leave the route reporting a 500
            # for a crafted payload. That is a refusal, not a server fault, and
            # a 500 on a crafted payload is also an availability finding.
            try:
                with archive.open(info) as member:
                    prefix = member.read(_SNIFF_BYTES)
            except (zipfile.BadZipFile, OSError, EOFError) as exc:
                raise _refuse(
                    "archive-member-unreadable",
                    f"member {info.filename!r} could not be read: its stored data "
                    "disagrees with the archive's own metadata",
                    remedy="re-create the archive",
                ) from exc
            for signature in PICKLE_MAGIC:
                if prefix.startswith(signature):
                    raise _refuse(
                        "pickle-stream",
                        f"member {info.filename!r} begins with a pickle opcode stream",
                        remedy="export the member as JSON or CSV",
                        status_code=415,
                    )
            if prefix.startswith(OLE2_MAGIC):
                raise _refuse(
                    "macro-bearing-document",
                    f"member {info.filename!r} is an OLE2 compound document",
                    remedy="export the member as CSV or JSON",
                    status_code=415,
                )
            for signature in _NESTED_ARCHIVE_MAGIC:
                if prefix.startswith(signature):
                    raise _refuse(
                        "archive-nested-archive",
                        f"member {info.filename!r} is itself a compressed container; "
                        "nested archives are refused rather than inspected recursively",
                        remedy="flatten the archive",
                        status_code=415,
                    )
        return tuple(names)


def admit_bytes(
    data: bytes,
    *,
    filename: str,
    declared_content_type: str,
    policy: AdmissionPolicy = DEFAULT_ADMISSION_POLICY,
) -> tuple[DetectedKind, tuple[str, ...]]:
    """Run every admission rule against ``data`` (RX-42).

    Returns the detected kind and, for an archive, its admitted member names.
    Raises :class:`~retrace_api.web.errors.UploadRefused` naming the rule that
    refused it. Pure: it reads no filesystem and writes nothing, so it can be
    exercised without a quarantine area.
    """
    if len(data) > policy.max_upload_bytes:
        raise _refuse(
            "size-cap-exceeded",
            f"{len(data)} bytes exceeds the {policy.max_upload_bytes} byte cap",
            remedy="split the payload",
            status_code=413,
        )
    _check_filename(filename)
    detected = sniff(data)
    _check_declared(declared_content_type, detected)
    members: tuple[str, ...] = ()
    if detected is DetectedKind.ZIP_ARCHIVE:
        members = _inspect_archive(data, policy)
    return detected, members


class QuarantineArea:
    """Per-tenant quarantine storage (RX-42, RX-47).

    Each tenant gets its own directory under the area root, so an upload cannot
    be read or overwritten through another tenant's path even if an identifier
    leaked. The tenant segment is validated as a UUID by the caller before it
    reaches here; this class additionally refuses any segment that is not a
    single safe path component, so a crafted identifier cannot escape the root.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        return self._root

    def _tenant_dir(self, tenant_id: str) -> Path:
        segment = tenant_id.strip()
        if not segment or not is_safe_relative_path(segment) or "/" in segment:
            raise _refuse(
                "quarantine-path-unsafe",
                f"tenant segment {tenant_id!r} is not a single safe path component",
                remedy="resolve the tenant from an authorised membership",
            )
        path = self._root / segment
        path.mkdir(parents=True, exist_ok=True)
        return path

    def store(
        self,
        *,
        tenant_id: str,
        project_id: str,
        upload_id: str,
        filename: str,
        declared_content_type: str,
        data: bytes,
        received_at: dt.datetime,
    ) -> QuarantinedUpload:
        """Write ``data`` into quarantine BEFORE any admission decision (RX-42)."""
        if not is_safe_relative_path(upload_id) or "/" in upload_id:
            raise _refuse(
                "quarantine-path-unsafe",
                f"upload id {upload_id!r} is not a single safe path component",
                remedy="let the server mint the upload identifier",
            )
        target = self._tenant_dir(tenant_id) / f"{upload_id}.bin"
        target.write_bytes(data)
        return QuarantinedUpload(
            upload_id=upload_id,
            tenant_id=tenant_id,
            project_id=project_id,
            filename=filename,
            declared_content_type=declared_content_type,
            byte_count=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            path=target,
            received_at=received_at,
        )

    def read(self, quarantined: QuarantinedUpload) -> bytes:
        """Read quarantined bytes back, verifying the digest they were stored under.

        The verification is not ceremony: promotion builds a snapshot from these
        bytes, and a snapshot is content-addressed, so if the quarantined file
        changed between admission and promotion the snapshot would pin content
        that was never admitted.
        """
        data = quarantined.path.read_bytes()
        observed = hashlib.sha256(data).hexdigest()
        if observed != quarantined.sha256:
            raise _refuse(
                "quarantine-digest-changed",
                "the quarantined bytes no longer match the digest recorded at admission",
                remedy="re-upload the payload",
            )
        return data

    def discard(self, quarantined: QuarantinedUpload) -> None:
        quarantined.path.unlink(missing_ok=True)

    def paths(self, tenant_id: str) -> Iterable[Path]:
        """Quarantined files for one tenant. Diagnostics only."""
        directory = self._root / tenant_id
        return sorted(directory.glob("*.bin")) if directory.is_dir() else ()

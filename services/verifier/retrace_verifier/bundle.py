"""Portable evidence bundles: build, and import for a second-person rerun (RX-15, RX-16).

A bundle is the handover artefact: snapshot, patch, environment manifest, logs,
check results, a **non-empty** limitations section, an attestation, and a digest
over the whole manifest. :func:`build_bundle` writes one; :func:`import_bundle`
reads one back with every digest verified and every structural safety rule
enforced.

DETERMINISM (RX-15)
===================
:func:`build_bundle` reads no clock, no environment variable, no random source
and no filesystem metadata. Every timestamp is a parameter. Zip members are
written in sorted path order with a fixed modification time derived from
``created_at``, fixed permissions and a fixed compression method, so identical
inputs produce a byte-identical archive -- and therefore an identical
``bundle_digest``. ``tests/exec/test_bundle.py`` asserts both the digest and the
archive bytes.

IMPORT SAFETY (RX-16, RX-42)
============================
Validation happens in two passes, and the first pass writes nothing:

#. **Structural pass.** Member count, member name safety (no absolute paths, no
   ``..``, no backslashes, no control characters), symlink and non-regular
   entries, per-member declared size, total declared size, and the compression
   ratio of each member. A bundle that fails here has had *nothing* extracted.
#. **Extraction pass.** Members are decompressed in bounded chunks with the
   per-member and total caps enforced **while reading**, so a header that lies
   about ``file_size`` is caught by the bytes actually produced rather than
   trusted. If this pass refuses, the destination is removed again.

Then every digest is verified: the manifest against the digest recorded
alongside it, the manifest bytes against their own canonical form, each
referenced file against the ``sha256`` in the manifest, and the RO-Crate
rendering against the one the manifest generates. **A bundle whose recorded
digest disagrees with its bytes is refused, never repaired** -- recomputing the
digest to match altered bytes would convert tampering into a silent success.

Unreferenced members are refused too: a file inside the archive that no manifest
reference covers could not be digest-verified, so it would be unverified payload
travelling inside an evidence artefact.
"""

from __future__ import annotations

import shutil
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Final

from pydantic import Field
from retrace_contracts import (
    RO_CRATE_1_1_PROFILE,
    Attestation,
    CheckResult,
    EnvironmentManifest,
    EvidenceBundleManifest,
    FrozenRecord,
    ResourceRef,
    ResultContract,
    VerificationOutcome,
    canonical_json,
    is_safe_relative_path,
    sha256_hex,
)

from .errors import BundleIntegrityError, BundleRefused
from .safe_read import ParseLimits, load_json_document

__all__ = [
    "BUNDLE_LIMITS_NOTE",
    "CONTRACT_MEMBER_PATH",
    "CONTRACT_ROLE",
    "MANIFEST_MEMBER_PATH",
    "RECORDED_DIGEST_MEMBER_PATH",
    "RO_CRATE_MEMBER_PATH",
    "BuiltBundle",
    "BundleLimits",
    "BundleMember",
    "DEFAULT_BUNDLE_LIMITS",
    "ImportedBundle",
    "build_bundle",
    "import_bundle",
]

MANIFEST_MEMBER_PATH: Final[str] = "manifest.json"
"""The manifest, stored as the exact canonical document its digest is taken over."""

RECORDED_DIGEST_MEMBER_PATH: Final[str] = "bundle.json"
"""The recorded ``bundle_digest``, kept separate so it can *disagree* and be caught."""

RO_CRATE_MEMBER_PATH: Final[str] = "ro-crate-metadata.json"
"""The RO-Crate-shaped rendering. Shape only; profile conformance is not validated."""

CONTRACT_MEMBER_PATH: Final[str] = "evidence/result-contract.json"
"""Where the contract travels, so a second researcher can re-verify, not just re-run."""

CONTRACT_ROLE: Final[str] = "result-contract"

_GENERATED_MEMBERS: Final[frozenset[str]] = frozenset(
    {MANIFEST_MEMBER_PATH, RECORDED_DIGEST_MEMBER_PATH, RO_CRATE_MEMBER_PATH}
)
_CHUNK_BYTES: Final[int] = 64 * 1024
_MIN_ZIP_YEAR: Final[int] = 1980
_UNIX_FILE_MODE: Final[int] = (0o100644 << 16)
_S_IFMT: Final[int] = 0o170000
_S_IFLNK: Final[int] = 0o120000
_S_IFREG: Final[int] = 0o100000

BUNDLE_LIMITS_NOTE: Final[str] = (
    "A bundle proves internal consistency: the manifest matches its digest, each "
    "referenced file matches the digest the manifest records, and nothing "
    "unreferenced travels inside. It does not prove that the recorded run "
    "happened, that the environment manifest describes the machine that ran it, "
    "or that the attestation is anything more than a declaration -- unless the "
    "attestation carries a signature that is independently verified, which this "
    "package does not do."
)


class BundleLimits(FrozenRecord):
    """Ceilings enforced when importing an untrusted bundle (RX-42)."""

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.BundleLimits"

    max_members: int = Field(default=10_000, gt=0, description="Member-count ceiling.")
    max_member_bytes: int = Field(
        default=64 * 1024 * 1024, gt=0, description="Per-member uncompressed ceiling."
    )
    max_total_bytes: int = Field(
        default=256 * 1024 * 1024, gt=0, description="Total uncompressed ceiling."
    )
    max_compression_ratio: float = Field(
        default=200.0,
        gt=1.0,
        description="Per-member uncompressed:compressed ratio ceiling. A deflate bomb of "
        "zeros reaches ~1000:1, so this refuses one while leaving real text "
        "(typically under 20:1) comfortable.",
    )


DEFAULT_BUNDLE_LIMITS: Final[BundleLimits] = BundleLimits()


@dataclass(frozen=True)
class BundleMember:
    """One file to place in a bundle.

    A plain frozen dataclass rather than a :class:`~retrace_contracts.FrozenRecord`
    because it carries raw ``bytes``, which the canonical form deliberately
    refuses to digest directly -- bytes are digested and the hex recorded instead.
    """

    ref_id: str
    path: str
    data: bytes
    role: str
    media_type: str | None = None


@dataclass(frozen=True)
class BuiltBundle:
    """The result of :func:`build_bundle`."""

    path: Path
    manifest: EvidenceBundleManifest
    bundle_digest: str
    member_paths: tuple[str, ...]


@dataclass(frozen=True)
class ImportedBundle:
    """A verified bundle, extracted and ready for an independent rerun (RX-16).

    Everything needed to re-execute and re-verify without talking to the first
    researcher: the snapshot archive, the patch under review, the environment
    manifest that was applied, the contract that was judged against (when the
    producer included it), and the check results the first verification reached.

    :meth:`missing_for_rerun` names what is *not* sufficient, rather than leaving
    a consumer to discover it.
    """

    root: Path
    manifest: EvidenceBundleManifest
    bundle_digest: str
    snapshot_path: Path
    patch_path: Path | None
    evidence_paths: dict[str, Path]
    environment_manifest: EnvironmentManifest
    check_results: tuple[CheckResult, ...]
    limitations: tuple[str, ...]
    attestation: Attestation
    outcome: VerificationOutcome
    contract_hash: str
    member_paths: tuple[str, ...]
    contract: ResultContract | None = None
    verified_digests: tuple[str, ...] = field(default_factory=tuple)

    def missing_for_rerun(self) -> tuple[str, ...]:
        """Return what this bundle does not supply for an independent rerun (RX-16).

        Honest by construction: a consumer that gets an empty tuple has the
        contract, the snapshot and the environment manifest in hand. Anything
        else is named rather than assumed.
        """
        gaps: list[str] = []
        if self.contract is None:
            gaps.append(
                "the result contract itself is absent (only its hash is recorded), so the "
                "bundle can be re-executed but not re-verified against the same declaration"
            )
        if self.patch_path is None:
            gaps.append(
                "no patch is included, so this bundle describes a baseline run rather than "
                "a reviewed repair"
            )
        if not self.check_results:
            gaps.append("no check results are included, so the first verification's "
                        "findings cannot be compared with a second one's")
        if self.attestation.signature is None:
            gaps.append(
                "the attestation is unsigned, so authorship of the bundle is a declaration "
                "rather than a verified fact"
            )
        return tuple(gaps)


def _resource_ref(member: BundleMember) -> ResourceRef:
    """Build the manifest reference for ``member``, pinning its exact bytes (RX-01)."""
    return ResourceRef(
        ref_id=member.ref_id,
        path=member.path,
        sha256=sha256_hex(member.data),
        role=member.role,
        media_type=member.media_type,
        bytes_count=len(member.data),
    )


def _zip_date_time(moment: datetime) -> tuple[int, int, int, int, int, int]:
    """Return a deterministic zip timestamp from ``moment`` (RX-15).

    Taken from the supplied ``created_at`` and never from the clock or from file
    metadata, because a bundle whose bytes depend on when it was written cannot
    have a stable digest. Zip cannot represent a year before 1980, so an earlier
    timestamp is refused rather than silently moved.
    """
    if moment.year < _MIN_ZIP_YEAR:
        raise BundleRefused(
            reason="timestamp-unrepresentable",
            detail=f"the zip format cannot store year {moment.year}; "
            f"created_at must be {_MIN_ZIP_YEAR} or later",
        )
    return (moment.year, moment.month, moment.day, moment.hour, moment.minute, moment.second)


def build_bundle(
    destination: Path | str,
    *,
    bundle_id: str,
    created_by: str,
    created_at: datetime,
    contract_hash: str,
    snapshot: BundleMember,
    environment_manifest: EnvironmentManifest,
    outcome: VerificationOutcome,
    limitations: Sequence[str],
    attestation: Attestation,
    patch: BundleMember | None = None,
    evidence: Sequence[BundleMember] = (),
    check_results: Sequence[CheckResult] = (),
    contract: ResultContract | None = None,
    bundle_version: int = 1,
    conforms_to: str = RO_CRATE_1_1_PROFILE,
) -> BuiltBundle:
    """Write a deterministic evidence bundle and return its manifest (RX-15, RX-16).

    ``limitations`` must be non-empty; the frozen manifest refuses an empty
    limitations section, because a bundle claiming no limitations is not
    reviewable.

    ``evidence`` carries auxiliary files -- the verification report, the outputs
    artefact, runner and verifier logs. The manifest exposes exactly three
    reference slots (snapshot, patch, logs), so auxiliary evidence travels in the
    logs slot with its own ``role``, which is the field that says what a file
    actually is.

    ``contract``, when supplied, is serialised into the bundle so a second
    researcher can re-*verify* rather than merely re-execute (RX-16). When it is
    omitted, :meth:`ImportedBundle.missing_for_rerun` says so.

    Determinism: nothing here reads a clock, a random source or filesystem
    metadata. Members are stored in sorted path order with one fixed timestamp,
    one fixed mode and one fixed compression method.
    """
    members: list[BundleMember] = [snapshot]
    if patch is not None:
        members.append(patch)
    log_members = list(evidence)
    if contract is not None:
        log_members.append(
            BundleMember(
                ref_id="result-contract",
                path=CONTRACT_MEMBER_PATH,
                data=contract.canonical_document().encode("utf-8"),
                role=CONTRACT_ROLE,
                media_type="application/json",
            )
        )
    members.extend(log_members)

    for member in members:
        if not is_safe_relative_path(member.path):
            raise BundleRefused(
                reason="unsafe-member-path",
                member=member.path,
                detail="bundle member paths must be relative, traversal-free POSIX paths",
            )
        if member.path in _GENERATED_MEMBERS:
            raise BundleRefused(
                reason="reserved-member-path",
                member=member.path,
                detail=f"{member.path!r} is generated by the bundler and cannot be supplied",
            )

    manifest = EvidenceBundleManifest(
        bundle_id=bundle_id,
        bundle_version=bundle_version,
        conforms_to=conforms_to,
        created_at=created_at,
        created_by=created_by,
        contract_hash=contract_hash,
        snapshot_ref=_resource_ref(snapshot),
        patch_ref=_resource_ref(patch) if patch is not None else None,
        environment_manifest=environment_manifest,
        logs_refs=tuple(_resource_ref(member) for member in log_members),
        check_results=tuple(check_results),
        outcome=outcome,
        limitations=tuple(limitations),
        attestation=attestation,
    )
    digest = manifest.bundle_digest

    payload: dict[str, bytes] = {member.path: member.data for member in members}
    payload[MANIFEST_MEMBER_PATH] = manifest.canonical_document().encode("utf-8")
    payload[RECORDED_DIGEST_MEMBER_PATH] = canonical_json(
        {
            "bundle_id": manifest.bundle_id,
            "bundle_digest": digest,
            "manifest_member": MANIFEST_MEMBER_PATH,
        },
        type_tag="retrace.BundleDigestRecord",
    ).encode("utf-8")
    payload[RO_CRATE_MEMBER_PATH] = canonical_json(
        manifest.to_ro_crate_metadata(), type_tag="retrace.RoCrateMetadata"
    ).encode("utf-8")

    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _zip_date_time(created_at)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(payload):
            info = zipfile.ZipInfo(filename=path, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = _UNIX_FILE_MODE
            info.create_system = 3
            archive.writestr(info, payload[path])
    return BuiltBundle(
        path=target,
        manifest=manifest,
        bundle_digest=digest,
        member_paths=tuple(sorted(payload)),
    )


def _validate_structure(
    archive: zipfile.ZipFile, destination: Path, limits: BundleLimits
) -> list[zipfile.ZipInfo]:
    """Refuse an unsafe archive before extracting anything (RX-42).

    Nothing is written by this pass, so a bundle refused here leaves the
    destination untouched -- which is what makes "zip-slip refused" a claim about
    the filesystem and not only about an exception type.
    """
    infos = archive.infolist()
    if len(infos) > limits.max_members:
        raise BundleRefused(
            reason="too-many-members",
            detail=f"{len(infos)} members exceeds max_members={limits.max_members}",
        )
    root = destination.resolve()
    declared_total = 0
    regular: list[zipfile.ZipInfo] = []
    for info in infos:
        name = info.filename
        if info.is_dir():
            continue
        mode = (info.external_attr >> 16) & _S_IFMT
        if mode == _S_IFLNK:
            raise BundleRefused(
                reason="non-regular-member",
                member=name,
                detail="the member is a symbolic link; a link could redirect a later write "
                "outside the extraction root",
            )
        if mode not in (0, _S_IFREG):
            raise BundleRefused(
                reason="non-regular-member",
                member=name,
                detail=f"unsupported member mode {oct(mode)}",
            )
        if name.startswith("/") or "\\" in name or not is_safe_relative_path(name):
            raise BundleRefused(
                reason="zip-slip",
                member=name,
                detail="member name is absolute, uses backslashes, or contains a traversal "
                "segment",
            )
        target = (root / name).resolve()
        if target != root and root not in target.parents:
            raise BundleRefused(
                reason="zip-slip",
                member=name,
                detail=f"member resolves to {target}, outside the extraction root {root}",
            )
        if info.file_size > limits.max_member_bytes:
            raise BundleRefused(
                reason="member-too-large",
                member=name,
                detail=f"declared {info.file_size} bytes exceeds max_member_bytes="
                f"{limits.max_member_bytes}",
            )
        declared_total += info.file_size
        if declared_total > limits.max_total_bytes:
            raise BundleRefused(
                reason="bundle-too-large",
                member=name,
                detail=f"declared total {declared_total} bytes exceeds max_total_bytes="
                f"{limits.max_total_bytes}",
            )
        if info.compress_size > 0:
            ratio = info.file_size / info.compress_size
            if ratio > limits.max_compression_ratio:
                raise BundleRefused(
                    reason="compression-ratio",
                    member=name,
                    detail=f"uncompressed:compressed ratio {ratio:.1f} exceeds "
                    f"max_compression_ratio={limits.max_compression_ratio}; this is the "
                    "shape of a decompression bomb",
                )
        regular.append(info)
    return regular


def _extract_capped(
    archive: zipfile.ZipFile,
    infos: Sequence[zipfile.ZipInfo],
    destination: Path,
    limits: BundleLimits,
) -> dict[str, bytes]:
    """Decompress every member under caps enforced *while reading* (RX-42).

    The structural pass trusted the central directory; this pass does not. Bytes
    are counted as they are produced, so a header that under-reports
    ``file_size`` is caught here.
    """
    contents: dict[str, bytes] = {}
    total = 0
    for info in infos:
        target = destination / info.filename
        target.parent.mkdir(parents=True, exist_ok=True)
        produced = bytearray()
        with archive.open(info, "r") as source:
            while True:
                chunk = source.read(_CHUNK_BYTES)
                if not chunk:
                    break
                produced.extend(chunk)
                total += len(chunk)
                if len(produced) > limits.max_member_bytes:
                    raise BundleRefused(
                        reason="member-too-large",
                        member=info.filename,
                        detail=f"produced more than max_member_bytes="
                        f"{limits.max_member_bytes} bytes while decompressing",
                    )
                if total > limits.max_total_bytes:
                    raise BundleRefused(
                        reason="bundle-too-large",
                        member=info.filename,
                        detail=f"produced more than max_total_bytes="
                        f"{limits.max_total_bytes} bytes while decompressing",
                    )
        data = bytes(produced)
        target.write_bytes(data)
        contents[info.filename] = data
    return contents


def _require_member(contents: Mapping[str, bytes], path: str) -> bytes:
    """Return a required member's bytes, or refuse the bundle."""
    if path not in contents:
        raise BundleRefused(
            reason="missing-member",
            member=path,
            detail="a bundle without this member is not an evidence bundle",
        )
    return contents[path]


def _load_manifest(contents: Mapping[str, bytes], limits: ParseLimits) -> EvidenceBundleManifest:
    """Parse the manifest defensively and confirm it is its own canonical form."""
    raw = _require_member(contents, MANIFEST_MEMBER_PATH)
    document = load_json_document(raw, limits=limits, path=MANIFEST_MEMBER_PATH)
    body = document.get("payload")
    if not isinstance(body, dict):
        raise BundleRefused(
            reason="manifest-malformed",
            member=MANIFEST_MEMBER_PATH,
            detail="the canonical document has no object 'payload'",
        )
    try:
        manifest = EvidenceBundleManifest.model_validate(body)
    except Exception as error:
        raise BundleRefused(
            reason="manifest-malformed", member=MANIFEST_MEMBER_PATH, detail=repr(error)
        ) from error
    rebuilt = manifest.canonical_document().encode("utf-8")
    if rebuilt != raw:
        raise BundleIntegrityError(
            subject=f"{MANIFEST_MEMBER_PATH} canonical form",
            expected=sha256_hex(raw),
            observed=sha256_hex(rebuilt),
        )
    return manifest


def _verify_recorded_digest(
    contents: Mapping[str, bytes], manifest: EvidenceBundleManifest, limits: ParseLimits
) -> str:
    """Verify the recorded ``bundle_digest`` against the manifest's own digest (RX-15)."""
    raw = _require_member(contents, RECORDED_DIGEST_MEMBER_PATH)
    document = load_json_document(raw, limits=limits, path=RECORDED_DIGEST_MEMBER_PATH)
    body = document.get("payload")
    recorded = body.get("bundle_digest") if isinstance(body, dict) else None
    if not isinstance(recorded, str):
        raise BundleRefused(
            reason="digest-record-malformed",
            member=RECORDED_DIGEST_MEMBER_PATH,
            detail="no 'bundle_digest' string is recorded",
        )
    computed = manifest.bundle_digest
    if recorded != computed:
        raise BundleIntegrityError(subject="bundle_digest", expected=recorded, observed=computed)
    return computed


def _verify_references(
    contents: Mapping[str, bytes], manifest: EvidenceBundleManifest
) -> tuple[str, ...]:
    """Verify every referenced file against the digest the manifest records (RX-01, RX-02)."""
    verified: list[str] = []
    for ref in manifest.resource_refs:
        if ref.path not in contents:
            raise BundleRefused(
                reason="missing-member",
                member=ref.path,
                detail=f"the manifest references {ref.ref_id!r} but the archive has no such "
                "member",
            )
        data = contents[ref.path]
        observed = sha256_hex(data)
        if observed != ref.sha256:
            raise BundleIntegrityError(
                subject=f"member {ref.path}", expected=ref.sha256, observed=observed
            )
        if ref.bytes_count is not None and ref.bytes_count != len(data):
            raise BundleIntegrityError(
                subject=f"member {ref.path} size",
                expected=str(ref.bytes_count),
                observed=str(len(data)),
            )
        verified.append(ref.path)
    return tuple(verified)


def _verify_ro_crate(contents: Mapping[str, bytes], manifest: EvidenceBundleManifest) -> None:
    """Verify the stored RO-Crate rendering matches the one the manifest generates."""
    raw = _require_member(contents, RO_CRATE_MEMBER_PATH)
    rebuilt = canonical_json(
        manifest.to_ro_crate_metadata(), type_tag="retrace.RoCrateMetadata"
    ).encode("utf-8")
    if raw != rebuilt:
        raise BundleIntegrityError(
            subject=RO_CRATE_MEMBER_PATH,
            expected=sha256_hex(raw),
            observed=sha256_hex(rebuilt),
        )


def _refuse_unreferenced(
    contents: Mapping[str, bytes], manifest: EvidenceBundleManifest
) -> None:
    """Refuse any archive member no manifest reference covers (RX-15)."""
    referenced = {ref.path for ref in manifest.resource_refs} | set(_GENERATED_MEMBERS)
    extra = sorted(set(contents) - referenced)
    if extra:
        raise BundleRefused(
            reason="unreferenced-member",
            member=extra[0],
            detail=f"{len(extra)} member(s) are not covered by any manifest reference and "
            "therefore could not be digest-verified: " + ", ".join(extra[:5]),
        )


def _load_contract(
    contents: Mapping[str, bytes], manifest: EvidenceBundleManifest, limits: ParseLimits
) -> ResultContract | None:
    """Rebuild the bundled result contract, if the producer included one (RX-16)."""
    reference = next(
        (ref for ref in manifest.logs_refs if ref.role == CONTRACT_ROLE), None
    )
    if reference is None:
        return None
    document = load_json_document(
        contents[reference.path], limits=limits, path=reference.path
    )
    body = document.get("payload")
    if not isinstance(body, dict):
        raise BundleRefused(
            reason="contract-malformed",
            member=reference.path,
            detail="the canonical document has no object 'payload'",
        )
    try:
        contract = ResultContract.model_validate(body)
    except Exception as error:
        raise BundleRefused(
            reason="contract-malformed", member=reference.path, detail=repr(error)
        ) from error
    if contract.contract_hash != manifest.contract_hash:
        raise BundleIntegrityError(
            subject="bundled result contract",
            expected=manifest.contract_hash,
            observed=contract.contract_hash,
        )
    return contract


def import_bundle(
    bundle_path: Path | str,
    destination: Path | str,
    *,
    limits: BundleLimits = DEFAULT_BUNDLE_LIMITS,
    parse_limits: ParseLimits | None = None,
) -> ImportedBundle:
    """Import and fully verify a bundle for an independent rerun (RX-16, RX-42).

    ``destination`` must not already contain anything: the import is
    all-or-nothing, and on any refusal the destination is removed again so a
    rejected bundle leaves no partially-extracted payload behind.

    Raises
    ------
    BundleRefused:
        A structural safety rule was broken -- zip-slip, a symlink member, a size
        or ratio cap, a missing required member, or an unreferenced member.
    BundleIntegrityError:
        A recorded digest disagrees with the bytes. The bundle is refused and
        **not** repaired.
    """
    source = Path(bundle_path)
    root = Path(destination)
    if root.exists() and any(root.iterdir()):
        raise BundleRefused(
            reason="destination-not-empty",
            detail=f"{root} already contains files; import is all-or-nothing and will not "
            "merge into an existing tree",
        )
    effective_parse_limits = parse_limits or ParseLimits(max_bytes=limits.max_member_bytes)
    root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(source, "r") as archive:
            infos = _validate_structure(archive, root, limits)
            contents = _extract_capped(archive, infos, root, limits)
        manifest = _load_manifest(contents, effective_parse_limits)
        digest = _verify_recorded_digest(contents, manifest, effective_parse_limits)
        verified = _verify_references(contents, manifest)
        _verify_ro_crate(contents, manifest)
        _refuse_unreferenced(contents, manifest)
        contract = _load_contract(contents, manifest, effective_parse_limits)
    except (BundleRefused, BundleIntegrityError, zipfile.BadZipFile, OSError):
        shutil.rmtree(root, ignore_errors=True)
        raise
    evidence_paths = {ref.ref_id: root / ref.path for ref in manifest.logs_refs}
    return ImportedBundle(
        root=root,
        manifest=manifest,
        bundle_digest=digest,
        snapshot_path=root / manifest.snapshot_ref.path,
        patch_path=(root / manifest.patch_ref.path) if manifest.patch_ref else None,
        evidence_paths=evidence_paths,
        environment_manifest=manifest.environment_manifest,
        check_results=manifest.check_results,
        limitations=manifest.limitations,
        attestation=manifest.attestation,
        outcome=manifest.outcome,
        contract_hash=manifest.contract_hash,
        member_paths=tuple(sorted(contents)),
        contract=contract,
        verified_digests=verified,
    )

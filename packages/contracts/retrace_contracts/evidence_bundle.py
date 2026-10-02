"""The portable evidence bundle manifest (RX-15, RX-16, RX-54).

The bundle is the handover artefact: everything a second researcher needs to
re-import, re-execute and re-verify the work without talking to the first
(RX-16). The manifest is RO-Crate *shaped* -- :meth:`
EvidenceBundleManifest.to_ro_crate_metadata` emits a JSON-LD graph with the
RO-Crate 1.1 context, a metadata descriptor and a root ``Dataset`` whose
``hasPart`` lists the bundled files.

Honest scope note, carried in code rather than only in prose: this module
constructs and digests the manifest. It does **not** validate conformance to the
RO-Crate 1.1 profile, because that requires the published profile and a
validator, neither of which is available in this build. ``conforms_to`` is a
declaration by the producer, not a verified property, and
:attr:`EvidenceBundleManifest.VALIDATION_LIMITS` says so.

"""

from __future__ import annotations

from typing import Any, ClassVar, Final

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .base import FrozenRecord, Identifier, NonEmptyStr, Sha256Hex
from .canonical import canonical_timestamp
from .enums import VerificationOutcome
from .paths import validate_relative_path
from .verification import CheckResult

__all__ = [
    "Attestation",
    "EnvironmentManifest",
    "EvidenceBundleManifest",
    "ResourceRef",
    "RO_CRATE_1_1_CONTEXT",
    "RO_CRATE_1_1_PROFILE",
]

RO_CRATE_1_1_CONTEXT: Final[str] = "https://w3id.org/ro/crate/1.1/context"
RO_CRATE_1_1_PROFILE: Final[str] = "https://w3id.org/ro/crate/1.1"


class ResourceRef(FrozenRecord):
    """A reference to one file inside the bundle, pinned by digest (RX-15, RX-01).

    ``path`` is bundle-relative and traversal-free, so importing a bundle cannot
    be made to write outside its own extraction root (RX-42).
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.ResourceRef"

    ref_id: Identifier = Field(description="Id unique within the bundle manifest.")
    path: NonEmptyStr = Field(description="Bundle-relative path to the file.")
    sha256: Sha256Hex = Field(description="SHA-256 of the referenced bytes.")
    role: NonEmptyStr = Field(description="Role of this file, e.g. 'snapshot' or 'runner-log'.")
    media_type: NonEmptyStr | None = Field(default=None, description="IANA media type, if known.")
    bytes_count: int | None = Field(
        default=None, ge=0, description="Size in bytes, when recorded."
    )

    @field_validator("path")
    @classmethod
    def _path_is_bundle_relative(cls, value: str) -> str:
        """Refuse an absolute or traversing bundle path (RX-42)."""
        return validate_relative_path(value, field="ResourceRef.path")


class EnvironmentManifest(FrozenRecord):
    """The environment a run was executed in (RX-15, RX-16).

    ``policy_digest`` is the digest of the execution policy -- network denial,
    wall-clock and memory ceilings, scratch-only write root (RX-08). The policy
    itself is the runner's record; the manifest pins its digest so a second
    researcher can prove they re-ran under the same envelope.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.EnvironmentManifest"

    python_version: NonEmptyStr = Field(description="Interpreter version string.")
    platform: NonEmptyStr = Field(description="Platform/OS identification string.")
    packages: dict[str, str] = Field(
        default_factory=dict, description="Installed package name -> exact version."
    )
    policy_digest: Sha256Hex = Field(description="Digest of the execution policy applied (RX-08).")
    image_digest: Sha256Hex | None = Field(
        default=None, description="Container image digest, when a container was used."
    )
    captured_at: AwareDatetime = Field(description="When the environment was captured.")


class Attestation(FrozenRecord):
    """Who stands behind this bundle, and what they are not claiming (RX-15, RX-54).

    ``non_certification_statement`` is required and non-empty. A readiness
    artefact that does not say it is readiness rather than certification invites
    exactly the misreading RX-54 exists to prevent.

    A half-signed attestation is refused: ``signature`` and
    ``signature_algorithm`` must be supplied together, so a signature whose
    algorithm is unknown cannot be presented as verified.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.Attestation"

    attested_by: NonEmptyStr = Field(description="Identity making the attestation.")
    attested_at: AwareDatetime = Field(description="When the attestation was made.")
    statement: NonEmptyStr = Field(description="What is being attested, explicitly.")
    non_certification_statement: NonEmptyStr = Field(
        description="Explicit statement that this is readiness evidence, not certification."
    )
    method: NonEmptyStr = Field(
        default="unsigned-declaration",
        description="How the attestation is made, e.g. 'unsigned-declaration'.",
    )
    signature: NonEmptyStr | None = Field(
        default=None, description="Detached signature, when one exists."
    )
    signature_algorithm: NonEmptyStr | None = Field(
        default=None, description="Algorithm of the signature, required when signed."
    )

    @model_validator(mode="after")
    def _signature_is_complete(self) -> Attestation:
        """Refuse a signature without its algorithm, or an algorithm without a signature."""
        if (self.signature is None) != (self.signature_algorithm is None):
            raise ValueError(
                "signature and signature_algorithm must be supplied together; "
                "a signature of unknown algorithm cannot be verified"
            )
        return self


class EvidenceBundleManifest(FrozenRecord):
    """The RO-Crate-shaped portable handover descriptor (RX-15, RX-16).

    Invariants enforced at construction:

    * ``limitations`` is non-empty (RX-15 requires a non-empty limitations
      section; a bundle that claims no limitations is not reviewable).
    * every ``ref_id`` is unique across the snapshot, patch and log references,
      and every referenced ``path`` is unique.
    * ``check_results`` have unique check ids.
    * when ``outcome`` is ``REPRODUCED_WITHIN_CONTRACT`` there is at least one
      check result, because a bundle whose headline is a reproduction must carry
      the evidence of it.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.EvidenceBundleManifest"

    VALIDATION_LIMITS: ClassVar[tuple[str, ...]] = (
        "`conforms_to` is a producer declaration. This build does not validate "
        "the manifest against the published RO-Crate 1.1 profile; no profile "
        "validator is available here.",
        "`bundle_digest` covers the manifest only. It proves the manifest has "
        "not changed; it proves nothing about the referenced files beyond the "
        "sha256 values the manifest records for them.",
        "The attestation is a declaration. Unless `signature` is present and "
        "independently verified, it carries no cryptographic authority.",
    )

    bundle_id: Identifier = Field(description="Stable id of this bundle.")
    bundle_version: int = Field(default=1, ge=1, description="Manifest version.")
    conforms_to: NonEmptyStr = Field(
        default=RO_CRATE_1_1_PROFILE,
        description="Profile the producer declares conformance to. Not validated here.",
    )
    created_at: AwareDatetime = Field(description="When the bundle was assembled.")
    created_by: NonEmptyStr = Field(description="Identity that assembled the bundle.")
    contract_hash: Sha256Hex = Field(
        description="Hash of the contract the bundled work was judged against (RX-03)."
    )
    snapshot_ref: ResourceRef = Field(description="The immutable input snapshot (RX-01).")
    patch_ref: ResourceRef | None = Field(
        default=None, description="The reviewed patch, when a repair was proposed (RX-06)."
    )
    environment_manifest: EnvironmentManifest = Field(
        description="The environment the run executed in (RX-08)."
    )
    logs_refs: tuple[ResourceRef, ...] = Field(
        default=(), description="Runner and verifier logs."
    )
    check_results: tuple[CheckResult, ...] = Field(
        default=(), description="The numerical and structural checks performed."
    )
    outcome: VerificationOutcome = Field(
        description="The verification outcome this bundle carries (RX-12)."
    )
    limitations: tuple[NonEmptyStr, ...] = Field(
        min_length=1, description="What this bundle does not establish. Must be non-empty."
    )
    attestation: Attestation = Field(description="Who stands behind the bundle (RX-54).")

    @property
    def resource_refs(self) -> tuple[ResourceRef, ...]:
        """Every file reference in the manifest, in a deterministic order."""
        refs: list[ResourceRef] = [self.snapshot_ref]
        if self.patch_ref is not None:
            refs.append(self.patch_ref)
        refs.extend(self.logs_refs)
        return tuple(refs)

    @model_validator(mode="after")
    def _check_bundle_consistency(self) -> EvidenceBundleManifest:
        """Enforce reference uniqueness and evidence-bearing invariants (RX-15)."""
        refs = self.resource_refs
        ref_ids = [ref.ref_id for ref in refs]
        duplicate_ids = sorted({rid for rid in ref_ids if ref_ids.count(rid) > 1})
        if duplicate_ids:
            raise ValueError(f"duplicate ref_id(s): {', '.join(duplicate_ids)}")
        paths = [ref.path for ref in refs]
        duplicate_paths = sorted({path for path in paths if paths.count(path) > 1})
        if duplicate_paths:
            raise ValueError(f"duplicate bundle path(s): {', '.join(duplicate_paths)}")

        check_ids = [check.check_id for check in self.check_results]
        duplicate_checks = sorted({cid for cid in check_ids if check_ids.count(cid) > 1})
        if duplicate_checks:
            raise ValueError(f"duplicate check_id(s): {', '.join(duplicate_checks)}")

        if (
            self.outcome is VerificationOutcome.REPRODUCED_WITHIN_CONTRACT
            and not self.check_results
        ):
            raise ValueError(
                "a bundle whose outcome is REPRODUCED_WITHIN_CONTRACT must carry at "
                "least one check result as evidence (RX-15)"
            )
        return self

    @property
    def bundle_digest(self) -> str:
        """SHA-256 over the canonical form of the whole manifest (RX-15).

        Recomputed on access and never stored, so the manifest cannot carry a
        digest that disagrees with its own content.
        """
        return self.content_digest()

    def to_ro_crate_metadata(self) -> dict[str, Any]:
        """Return an RO-Crate-shaped JSON-LD graph for this manifest (RX-15).

        Shape only: a metadata descriptor entity, a root ``Dataset`` whose
        ``hasPart`` lists the bundle's files in :attr:`resource_refs` order, and
        one ``File`` entity per reference carrying its digest. Entity order is
        deterministic so the rendered crate is byte-stable.

        This method does **not** assert profile conformance -- see
        :attr:`VALIDATION_LIMITS`.
        """
        parts = [{"@id": ref.path} for ref in self.resource_refs]
        graph: list[dict[str, Any]] = [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": self.conforms_to},
                "about": {"@id": "./"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "identifier": self.bundle_id,
                "name": f"RETRACE evidence bundle {self.bundle_id}",
                "datePublished": canonical_timestamp(self.created_at),
                "author": {"@id": f"#author-{self.created_by}"},
                "hasPart": parts,
                "retrace:contractHash": self.contract_hash,
                "retrace:outcome": self.outcome.value,
                "retrace:bundleDigest": self.bundle_digest,
                "retrace:limitations": list(self.limitations),
            },
            {
                "@id": f"#author-{self.created_by}",
                "@type": "Person",
                "name": self.created_by,
            },
            {
                "@id": "#attestation",
                "@type": "CreativeWork",
                "name": "attestation",
                "author": {"@id": f"#attestor-{self.attestation.attested_by}"},
                "dateCreated": canonical_timestamp(self.attestation.attested_at),
                "description": self.attestation.statement,
                "disclaimer": self.attestation.non_certification_statement,
            },
        ]
        for ref in self.resource_refs:
            entity: dict[str, Any] = {
                "@id": ref.path,
                "@type": "File",
                "name": ref.ref_id,
                "retrace:role": ref.role,
                "retrace:sha256": ref.sha256,
            }
            if ref.media_type is not None:
                entity["encodingFormat"] = ref.media_type
            if ref.bytes_count is not None:
                entity["contentSize"] = str(ref.bytes_count)
            graph.append(entity)
        return {"@context": RO_CRATE_1_1_CONTEXT, "@graph": graph}

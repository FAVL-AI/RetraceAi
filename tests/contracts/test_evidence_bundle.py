"""The portable evidence bundle manifest (RX-15, RX-16, RX-54).

"""

from __future__ import annotations

from typing import Any

import pytest
from contracts_support import AUTHOR, T0, T2, build_bundle, build_check, digest
from pydantic import ValidationError
from retrace_contracts import (
    RO_CRATE_1_1_CONTEXT,
    Attestation,
    ContractImmutable,
    EvidenceBundleManifest,
    ResourceRef,
    VerificationOutcome,
)

MUTATIONS: dict[str, Any] = {
    "bundle_id": "bundle-0002",
    "bundle_version": 2,
    "conforms_to": "https://w3id.org/ro/crate/1.2",
    "created_at": T0,
    "created_by": "F. A. Van Laarhoven",
    "contract_hash": digest("other-contract"),
    "limitations": ("A single stated limitation.",),
}


def test_bundle_digest_is_stable_for_equal_manifests() -> None:
    """RX-15: the bundle digest is a pure function of the manifest."""
    assert build_bundle().bundle_digest == build_bundle().bundle_digest


@pytest.mark.parametrize("field", sorted(MUTATIONS))
def test_bundle_digest_changes_when_a_field_changes(field: str) -> None:
    """RX-15 negative control: the digest detects any manifest change."""
    baseline = build_bundle()
    mutated = build_bundle(**{field: MUTATIONS[field]})
    assert mutated.bundle_digest != baseline.bundle_digest


def test_bundle_digest_is_not_a_stored_field() -> None:
    """RX-15: the digest is computed, so a manifest cannot misreport it."""
    assert "bundle_digest" not in EvidenceBundleManifest.model_fields


def test_limitations_must_be_non_empty() -> None:
    """RX-15 negative control: a bundle claiming no limitations is refused."""
    with pytest.raises(ValidationError):
        build_bundle(limitations=())


def test_whitespace_only_limitation_is_refused() -> None:
    """RX-15 negative control: a blank limitation is not a stated limitation."""
    with pytest.raises(ValidationError):
        build_bundle(limitations=("  ",))


def test_attestation_requires_a_non_certification_statement() -> None:
    """RX-54 negative control: readiness evidence must say it is not certification."""
    with pytest.raises(ValidationError):
        Attestation(
            attested_by=AUTHOR,
            attested_at=T2,
            statement="the checks were executed",
            non_certification_statement="   ",
        )


def test_half_signed_attestation_is_refused() -> None:
    """RX-54 negative control: a signature of unknown algorithm is not verifiable."""
    with pytest.raises(ValidationError, match="must be supplied together"):
        Attestation(
            attested_by=AUTHOR,
            attested_at=T2,
            statement="the checks were executed",
            non_certification_statement="Readiness evidence, not certification.",
            signature="deadbeef",
        )
    with pytest.raises(ValidationError, match="must be supplied together"):
        Attestation(
            attested_by=AUTHOR,
            attested_at=T2,
            statement="the checks were executed",
            non_certification_statement="Readiness evidence, not certification.",
            signature_algorithm="ed25519",
        )


def test_duplicate_reference_ids_are_refused() -> None:
    """RX-15 negative control: two bundle entries cannot share an id."""
    clash = ResourceRef(
        ref_id="snapshot", path="logs/other.jsonl", sha256=digest("other"), role="runner-log"
    )
    with pytest.raises(ValidationError, match="duplicate ref_id"):
        build_bundle(logs_refs=(clash,))


def test_duplicate_reference_paths_are_refused() -> None:
    """RX-15 negative control: two entries cannot claim the same bundle path."""
    clash = ResourceRef(
        ref_id="dup-path",
        path="snapshot/manifest.json",
        sha256=digest("other"),
        role="runner-log",
    )
    with pytest.raises(ValidationError, match="duplicate bundle path"):
        build_bundle(logs_refs=(clash,))


def test_reproduced_bundle_without_check_results_is_refused() -> None:
    """RX-15 negative control: a reproduction headline needs its evidence."""
    with pytest.raises(ValidationError, match="must carry at least one check result"):
        build_bundle(check_results=())


def test_blocked_bundle_may_carry_no_check_results() -> None:
    """RX-17 positive control: an abstaining bundle is still a valid bundle."""
    bundle = build_bundle(
        outcome=VerificationOutcome.BLOCKED_MISSING_EVIDENCE, check_results=()
    )
    assert bundle.check_results == ()


def test_duplicate_check_ids_are_refused() -> None:
    """RX-15 negative control: repeated check ids double-count evidence."""
    with pytest.raises(ValidationError, match="duplicate check_id"):
        build_bundle(check_results=(build_check(), build_check()))


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../../outside.json", "logs/../../escape.json", "logs/"]
)
def test_resource_paths_must_be_bundle_relative(path: str) -> None:
    """RX-42 negative control: importing a bundle cannot write outside its root."""
    with pytest.raises(ValidationError):
        ResourceRef(ref_id="x", path=path, sha256=digest("x"), role="runner-log")


def test_bundle_is_immutable() -> None:
    """RX-52: a frozen evidence record is not silently edited."""
    bundle = build_bundle()
    with pytest.raises(ContractImmutable):
        bundle.contract_hash = digest("other")


def test_ro_crate_metadata_has_the_expected_shape() -> None:
    """RX-15: the manifest renders an RO-Crate-shaped JSON-LD graph.

    Shape only -- profile conformance is not validated here, as recorded in
    `EvidenceBundleManifest.VALIDATION_LIMITS`.
    """
    bundle = build_bundle()
    crate = bundle.to_ro_crate_metadata()
    assert crate["@context"] == RO_CRATE_1_1_CONTEXT

    graph = crate["@graph"]
    descriptor = next(item for item in graph if item["@id"] == "ro-crate-metadata.json")
    assert descriptor["conformsTo"] == {"@id": bundle.conforms_to}
    assert descriptor["about"] == {"@id": "./"}

    root = next(item for item in graph if item["@id"] == "./")
    assert root["@type"] == "Dataset"
    assert root["identifier"] == bundle.bundle_id
    assert root["retrace:contractHash"] == bundle.contract_hash
    assert root["retrace:bundleDigest"] == bundle.bundle_digest
    assert root["retrace:limitations"] == list(bundle.limitations)

    expected_paths = [ref.path for ref in bundle.resource_refs]
    assert root["hasPart"] == [{"@id": path} for path in expected_paths]
    file_entities = [item for item in graph if item.get("@type") == "File"]
    assert [entity["@id"] for entity in file_entities] == expected_paths
    assert all(entity["retrace:sha256"] for entity in file_entities)


def test_ro_crate_metadata_carries_the_non_certification_statement() -> None:
    """RX-54: the disclaimer travels with the bundle, not just in the repo docs."""
    crate = build_bundle().to_ro_crate_metadata()
    attestation = next(item for item in crate["@graph"] if item["@id"] == "#attestation")
    assert "not a certification" in attestation["disclaimer"]


def test_ro_crate_metadata_is_deterministic() -> None:
    """RX-15: two renders of the same manifest are identical."""
    assert build_bundle().to_ro_crate_metadata() == build_bundle().to_ro_crate_metadata()


def test_patch_ref_is_optional_for_a_bundle_with_no_repair() -> None:
    """RX-15: a reproduction attempt with no proposed repair still bundles."""
    bundle = build_bundle(patch_ref=None)
    assert bundle.patch_ref is None
    assert [ref.ref_id for ref in bundle.resource_refs] == ["snapshot", "runner-log"]


def test_bundle_round_trips_through_json_preserving_its_digest() -> None:
    """RX-16: a second researcher importing the manifest gets the same digest."""
    original = build_bundle()
    restored = EvidenceBundleManifest.model_validate_json(original.model_dump_json())
    assert restored.bundle_digest == original.bundle_digest

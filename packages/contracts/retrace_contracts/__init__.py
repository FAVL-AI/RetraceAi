"""RETRACE AI data contracts -- the scientific authority layer.

This package is the stable, importable foundation the rest of RETRACE builds
on. It contains no I/O, no network access, no clock reads and no model calls:
every record is constructed from values the caller supplies, so every record is
reproducible from evidence and testable without a fixture harness.

What lives here, and the reconstructed requirement each unit serves:

=================================  ==========================================
Unit                               Requirement
=================================  ==========================================
:class:`VerificationOutcome`       RX-12 -- exactly five outcomes
:class:`ExecutionStatus`           RX-11 -- execution status is a separate type
:class:`ResultContract`            RX-03 -- versioned, hashed declaration
:class:`Approval`                  RX-05 -- five-field binding
:class:`RepairProposal`            RX-06, RX-56 -- a diff, never file content
:class:`CheckResult`               RX-12, RX-13 -- per-check evidence
:class:`RunRecord`                 RX-11, RX-33 -- what executed, model pinned
:class:`VerificationReport`        RX-11, RX-12, RX-14 -- the judgement
:class:`EvidenceBundleManifest`    RX-15 -- portable handover descriptor
:class:`UIPlan`, :func:`validate_ui_plan`  RX-22, RX-23 -- generated layouts
=================================  ==========================================

"""

from __future__ import annotations

from .approval import Approval
from .base import FrozenRecord, Identifier, LongText, NonEmptyStr, Sha256Hex
from .canonical import (
    CANONICAL_FORM_LIMITS,
    CANONICAL_FORM_VERSION,
    canonical_digest,
    canonical_json,
    canonical_timestamp,
    canonicalise,
    sha256_hex,
)
from .enums import (
    CheckStatus,
    ExecutionStatus,
    MethodologyAspect,
    OutputKind,
    UIPlanRejectionReason,
    VerificationOutcome,
)
from .evidence_bundle import (
    RO_CRATE_1_1_CONTEXT,
    RO_CRATE_1_1_PROFILE,
    Attestation,
    EnvironmentManifest,
    EvidenceBundleManifest,
    ResourceRef,
)
from .exceptions import (
    ApprovalInvalidated,
    CanonicalisationError,
    ContractImmutable,
    ContractNotApproved,
    RetraceContractError,
    SnapshotIntegrityError,
    UIPlanRejected,
    VerifierAuthorityError,
)
from .paths import is_safe_relative_path, validate_relative_path
from .repair import MAX_DIFF_BYTES, RepairProposal, parse_unified_diff_targets
from .result_contract import (
    ComparisonSpec,
    ExclusionRule,
    OutputDefinition,
    Population,
    ReferenceInput,
    ResultContract,
    SplitSpec,
    Tolerance,
)
from .ui_plan import PROTECTED_REGION_IDS, UIAllowlists, UIComponent, UIPlan, validate_ui_plan
from .verification import CheckResult, MethodologyDelta, RunRecord, VerificationReport

__version__ = "0.0.0"

__all__ = [
    "Approval",
    "ApprovalInvalidated",
    "Attestation",
    "CANONICAL_FORM_LIMITS",
    "CANONICAL_FORM_VERSION",
    "CanonicalisationError",
    "CheckResult",
    "CheckStatus",
    "ComparisonSpec",
    "ContractImmutable",
    "ContractNotApproved",
    "EnvironmentManifest",
    "EvidenceBundleManifest",
    "ExclusionRule",
    "ExecutionStatus",
    "FrozenRecord",
    "Identifier",
    "LongText",
    "MAX_DIFF_BYTES",
    "MethodologyAspect",
    "MethodologyDelta",
    "NonEmptyStr",
    "OutputDefinition",
    "OutputKind",
    "PROTECTED_REGION_IDS",
    "Population",
    "RO_CRATE_1_1_CONTEXT",
    "RO_CRATE_1_1_PROFILE",
    "ReferenceInput",
    "RepairProposal",
    "ResourceRef",
    "ResultContract",
    "RetraceContractError",
    "RunRecord",
    "Sha256Hex",
    "SnapshotIntegrityError",
    "SplitSpec",
    "Tolerance",
    "UIAllowlists",
    "UIComponent",
    "UIPlan",
    "UIPlanRejected",
    "UIPlanRejectionReason",
    "VerificationOutcome",
    "VerificationReport",
    "VerifierAuthorityError",
    "__version__",
    "canonical_digest",
    "canonical_json",
    "canonical_timestamp",
    "canonicalise",
    "is_safe_relative_path",
    "parse_unified_diff_targets",
    "sha256_hex",
    "validate_relative_path",
    "validate_ui_plan",
]

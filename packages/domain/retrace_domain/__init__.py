"""RETRACE AI domain layer -- preservation, authority and restraint.

This package is where RETRACE's scientific integrity is mechanical rather than
aspirational. It holds the four things that must be true before any repair,
run or verification means anything, and it holds nothing else: no HTTP, no
database, no network, no clock reads, no model calls.

=========================================  ==================================
Unit                                       Requirement
=========================================  ==================================
:class:`ContentAddressedStore`             RX-01, RX-02 -- immutable, tamper-evident bytes
:func:`snapshot_create`                    RX-01 -- a digest that is a function of content
:func:`snapshot_materialise`               RX-01, RX-02 -- verified on the way back out
:class:`ApprovalLedger`                    RX-04, RX-05, RX-52 -- append-only, hash-chained
:class:`RepairAuthority`                   RX-07 -- the write guard the worker cannot pass
:class:`DeterministicRepairProvider`       RX-06, RX-14 -- real repairs, and abstention
:class:`GovernedModelRepairProvider`       RX-06, RX-40 -- refuses when unconfigured
=========================================  ==================================

The authority rule in ``docs/ARCHITECTURE.md`` is enforced here by
:class:`RepairAuthority` (path allowlist, resolving symlinks and ``..`` before
deciding) and by :class:`ApprovalLedger` (a chain whose middle cannot be edited
undetectably). Nothing in this package imports the verifier or the runner.
"""

from __future__ import annotations

from .authority import PROTECTED_PREFIXES, REFERENCE_DIRECTORY_NAMES, RepairAuthority
from .errors import (
    AuthorityRule,
    LedgerAppendRefused,
    LedgerIntegrityError,
    PathRefusalRule,
    ProviderNotConfigured,
    RetraceDomainError,
    UnsafeSourcePath,
    WriteRefused,
)
from .ledger import (
    GENESIS_DIGEST,
    ApprovalLedger,
    EntryStatus,
    LedgerEntry,
    LedgerEntryType,
)
from .providers import (
    PROTECTED_CONSTRUCTS,
    SCIENTIFIC_MEANING_REASONS,
    Abstention,
    AbstentionReason,
    DeterministicRepairProvider,
    Diagnosis,
    FaultClass,
    GovernedModelRepairProvider,
    ModelRepairRequest,
    ModelTransport,
    ProtectedConstruct,
    RepairProvider,
    build_unified_diff,
    candidate_digest,
    changed_lines,
    detect_delimiter,
    first_protected_construct,
    protected_construct_in_line,
)
from .snapshot import (
    MANIFEST_TYPE_TAG,
    SnapshotManifest,
    SnapshotReader,
    snapshot_create,
    snapshot_materialise,
    store_reader,
)
from .store import BLOB_MODE, ContentAddressedStore, hash_file, is_sha256_hex

__version__ = "0.0.0"

__all__ = [
    "Abstention",
    "AbstentionReason",
    "ApprovalLedger",
    "AuthorityRule",
    "BLOB_MODE",
    "ContentAddressedStore",
    "DeterministicRepairProvider",
    "Diagnosis",
    "EntryStatus",
    "FaultClass",
    "GENESIS_DIGEST",
    "GovernedModelRepairProvider",
    "LedgerAppendRefused",
    "LedgerEntry",
    "LedgerEntryType",
    "LedgerIntegrityError",
    "MANIFEST_TYPE_TAG",
    "ModelRepairRequest",
    "ModelTransport",
    "PROTECTED_CONSTRUCTS",
    "PROTECTED_PREFIXES",
    "PathRefusalRule",
    "ProtectedConstruct",
    "ProviderNotConfigured",
    "REFERENCE_DIRECTORY_NAMES",
    "RepairAuthority",
    "RepairProvider",
    "RetraceDomainError",
    "SCIENTIFIC_MEANING_REASONS",
    "SnapshotManifest",
    "SnapshotReader",
    "UnsafeSourcePath",
    "WriteRefused",
    "__version__",
    "build_unified_diff",
    "candidate_digest",
    "changed_lines",
    "detect_delimiter",
    "first_protected_construct",
    "hash_file",
    "is_sha256_hex",
    "protected_construct_in_line",
    "snapshot_create",
    "snapshot_materialise",
    "store_reader",
]

"""Repair providers: the interface, the rule-based route and the governed route.

Requirement coverage:

=========================================  ==================================
Unit                                       Requirement
=========================================  ==================================
:class:`RepairProvider`                    RX-06 -- a proposal, never a mutation
:class:`Diagnosis`                         RX-06 -- the question, as evidence
:class:`DeterministicRepairProvider`       RX-06, RX-14 -- real rules, real restraint
:class:`GovernedModelRepairProvider`       RX-06, RX-40, PRECHECK B6 -- refuses when unconfigured
:class:`AbstentionReason`                  RX-14 -- machine-readable restraint
:data:`PROTECTED_CONSTRUCTS`               RX-14 -- what a repair may never touch
=========================================  ==================================
"""

from __future__ import annotations

from .base import (
    CANDIDATE_TYPE_TAG,
    MEANING_CHANGING_FAULT_CLASSES,
    Abstention,
    Diagnosis,
    FaultClass,
    RepairProvider,
    build_unified_diff,
    candidate_digest,
    changed_lines,
)
from .deterministic import (
    DATA_SUFFIXES,
    DELIMITER_CANDIDATES,
    DeterministicRepairProvider,
    detect_delimiter,
)
from .governed import (
    MAX_RESPONSE_BYTES,
    GovernedModelRepairProvider,
    ModelRepairRequest,
    ModelTransport,
)
from .restraint import (
    PROTECTED_CONSTRUCTS,
    SCIENTIFIC_MEANING_REASONS,
    AbstentionReason,
    ProtectedConstruct,
    first_protected_construct,
    protected_construct_in_line,
)

__all__ = [
    "CANDIDATE_TYPE_TAG",
    "DATA_SUFFIXES",
    "DELIMITER_CANDIDATES",
    "MAX_RESPONSE_BYTES",
    "MEANING_CHANGING_FAULT_CLASSES",
    "PROTECTED_CONSTRUCTS",
    "SCIENTIFIC_MEANING_REASONS",
    "Abstention",
    "AbstentionReason",
    "DeterministicRepairProvider",
    "Diagnosis",
    "FaultClass",
    "GovernedModelRepairProvider",
    "ModelRepairRequest",
    "ModelTransport",
    "ProtectedConstruct",
    "RepairProvider",
    "build_unified_diff",
    "candidate_digest",
    "changed_lines",
    "detect_delimiter",
    "first_protected_construct",
    "protected_construct_in_line",
]

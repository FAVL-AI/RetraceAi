"""RETRACE independent verifier -- judgement, in its own trust domain (RX-09..RX-18).

This service decides whether a run reproduced a result within an approved
contract, and it is the only component permitted to decide that. It is kept
structurally incapable of the things that would compromise the judgement:

* **It cannot run anything.** It does not import the runner, ``subprocess``,
  ``nbclient`` or ``nbformat``.
* **It cannot propose a repair.** It does not import any repair provider or
  model client, so no generated text can influence an outcome.
* **It cannot write to references.** Every write-shaped method on a reference
  reader raises :class:`~retrace_contracts.VerifierAuthorityError` (RX-09).
* **It cannot deserialise an object.** Run outputs are read as JSON or CSV only,
  with ``pickle`` refused by both extension and magic bytes, and no ``eval``,
  ``exec``, ``compile``, ``pickle``, ``marshal`` or ``yaml`` anywhere in the
  package (RX-10).
* **It cannot be persuaded by the notebook.** What a run printed about its own
  success is recorded and read by nothing (RX-18).

``tests/exec/test_verifier_surface.py`` walks the AST and import graph of every
module here and fails if any of the first four change.

=================================================  ============================
Unit                                               Requirement
=================================================  ============================
:func:`~retrace_verifier.verify.verify`            RX-11, RX-12, RX-17, RX-18
:class:`~retrace_verifier.seams.ReadOnlyReferenceReader`  RX-07, RX-09
:mod:`retrace_verifier.safe_read`                  RX-10, RX-42
:func:`~retrace_verifier.comparison.compare_output`       RX-13
:func:`~retrace_verifier.methodology.detect_methodology_deltas`  RX-14
:func:`~retrace_verifier.bundle.build_bundle`      RX-15
:func:`~retrace_verifier.bundle.import_bundle`     RX-16, RX-42
=================================================  ============================
"""

from __future__ import annotations

from .bundle import (
    BUNDLE_LIMITS_NOTE,
    CONTRACT_MEMBER_PATH,
    CONTRACT_ROLE,
    DEFAULT_BUNDLE_LIMITS,
    MANIFEST_MEMBER_PATH,
    RECORDED_DIGEST_MEMBER_PATH,
    RO_CRATE_MEMBER_PATH,
    BuiltBundle,
    BundleLimits,
    BundleMember,
    ImportedBundle,
    build_bundle,
    import_bundle,
)
from .comparison import (
    CHECK_ID_PREFIX,
    UNCOMPARABLE_KINDS,
    check_id_for_output,
    compare_output,
    output_name_from_check_id,
    within_tolerance,
)
from .document import (
    CandidateMethodology,
    CandidatePopulation,
    CandidateSplit,
    OutputDocument,
    OutputValue,
    parse_output_document,
)
from .errors import (
    BundleIntegrityError,
    BundleRefused,
    OutputParseRefused,
    ReferenceUnavailable,
    VerifierError,
)
from .methodology import (
    METHODOLOGY_DECLARATION_CHECK_ID,
    detect_methodology_deltas,
    methodology_declaration_check,
)
from .safe_read import (
    ALLOWED_SUFFIXES,
    DEFAULT_PARSE_LIMITS,
    REFUSED_MAGIC,
    REFUSED_SUFFIXES,
    ParseLimits,
    load_csv_document,
    load_json_document,
    read_payload,
    read_payload_bytes,
    refuse_by_magic,
    refuse_by_suffix,
    scan_json_shape,
)
from .seams import (
    VERIFIER_IDENTITY_NOTE,
    FilesystemReferenceReader,
    ReadOnlyReferenceReader,
    ReferenceReader,
)
from .verify import (
    DEFAULT_VERIFIER_IDENTITY,
    INDEPENDENT_RECOMPUTATION_SCOPE,
    OUTCOME_PRECEDENCE,
    REFERENCE_OUTPUT_ROLE,
    VERIFICATION_LIMITS,
    verify,
)

__version__ = "0.0.0"

__all__ = [
    "ALLOWED_SUFFIXES",
    "BUNDLE_LIMITS_NOTE",
    "CHECK_ID_PREFIX",
    "CONTRACT_MEMBER_PATH",
    "CONTRACT_ROLE",
    "DEFAULT_BUNDLE_LIMITS",
    "DEFAULT_PARSE_LIMITS",
    "DEFAULT_VERIFIER_IDENTITY",
    "INDEPENDENT_RECOMPUTATION_SCOPE",
    "MANIFEST_MEMBER_PATH",
    "METHODOLOGY_DECLARATION_CHECK_ID",
    "OUTCOME_PRECEDENCE",
    "RECORDED_DIGEST_MEMBER_PATH",
    "REFERENCE_OUTPUT_ROLE",
    "REFUSED_MAGIC",
    "REFUSED_SUFFIXES",
    "RO_CRATE_MEMBER_PATH",
    "UNCOMPARABLE_KINDS",
    "VERIFICATION_LIMITS",
    "VERIFIER_IDENTITY_NOTE",
    "BuiltBundle",
    "BundleIntegrityError",
    "BundleLimits",
    "BundleMember",
    "BundleRefused",
    "CandidateMethodology",
    "CandidatePopulation",
    "CandidateSplit",
    "FilesystemReferenceReader",
    "ImportedBundle",
    "OutputDocument",
    "OutputParseRefused",
    "OutputValue",
    "ParseLimits",
    "ReadOnlyReferenceReader",
    "ReferenceReader",
    "ReferenceUnavailable",
    "VerifierError",
    "__version__",
    "build_bundle",
    "check_id_for_output",
    "compare_output",
    "detect_methodology_deltas",
    "import_bundle",
    "load_csv_document",
    "load_json_document",
    "methodology_declaration_check",
    "output_name_from_check_id",
    "parse_output_document",
    "read_payload",
    "read_payload_bytes",
    "refuse_by_magic",
    "refuse_by_suffix",
    "scan_json_shape",
    "verify",
    "within_tolerance",
]

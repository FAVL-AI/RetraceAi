"""The repair provider interface and the shared pieces every provider needs (RX-06).

A repair in RETRACE is a *proposal against a named snapshot*, never an in-place
edit, so a provider is a pure-ish function from

    (diagnosis, snapshot manifest, snapshot reader, scratch directory)

to either a :class:`~retrace_contracts.RepairProposal` or ``None`` with a
recorded :class:`~retrace_domain.providers.restraint.AbstentionReason`.

Three shared pieces live here because every provider needs exactly the same
semantics for them, and two providers that computed a candidate hash
differently would produce approvals that cannot be compared:

* :class:`Diagnosis` -- what is believed to be wrong, as a frozen record. A
  diagnosis is evidence, so it is immutable and digestible like every other
  RETRACE record.
* :func:`candidate_digest` -- the identity of the patched snapshot. Computed
  over the *content*, by replacing the target's digest in the manifest with the
  digest of the patched bytes. An approval binds this value (RX-05), so it must
  change whenever any byte of the candidate changes.
* :func:`build_unified_diff` -- the reviewable patch, produced by
  :mod:`difflib` from the snapshot's own bytes. The header paths are written
  ``a/<path>`` and ``b/<path>``, which is what ``RepairProposal`` expects.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import ClassVar, Final, Protocol, runtime_checkable

from pydantic import Field, field_validator
from retrace_contracts import (
    FrozenRecord,
    Identifier,
    NonEmptyStr,
    RepairProposal,
    canonical_digest,
    sha256_hex,
    validate_relative_path,
)

from ..snapshot import SnapshotManifest, SnapshotReader
from .restraint import AbstentionReason

__all__ = [
    "CANDIDATE_TYPE_TAG",
    "MEANING_CHANGING_FAULT_CLASSES",
    "Abstention",
    "Diagnosis",
    "FaultClass",
    "RepairProvider",
    "build_unified_diff",
    "candidate_digest",
    "changed_lines",
]

CANDIDATE_TYPE_TAG: Final[str] = "retrace.Candidate"
"""Domain-separation tag for a candidate snapshot digest (RX-05, RX-06)."""


class FaultClass(str, Enum):
    """What a diagnosis believes is wrong with the run (RX-06, RX-14).

    The members divide into two groups, and the division is the whole point.
    ``MISSING_INPUT_PATH`` and ``WRONG_CSV_DELIMITER`` are *mechanical* faults:
    the code cannot read its input, and fixing it changes no measurement. The
    rest name a change to the scientific method itself, and a provider must
    abstain on them rather than reconcile them -- see
    :data:`MEANING_CHANGING_FAULT_CLASSES`.
    """

    MISSING_INPUT_PATH = "MISSING_INPUT_PATH"
    WRONG_CSV_DELIMITER = "WRONG_CSV_DELIMITER"

    EXCLUSION_RULE_CHANGED = "EXCLUSION_RULE_CHANGED"
    RANDOM_SEED_CHANGED = "RANDOM_SEED_CHANGED"
    TRAIN_TEST_SPLIT_CHANGED = "TRAIN_TEST_SPLIT_CHANGED"
    UNIT_CONVERSION_CHANGED = "UNIT_CONVERSION_CHANGED"
    ROW_FILTER_CHANGED = "ROW_FILTER_CHANGED"
    ROW_COUNT_CHANGED = "ROW_COUNT_CHANGED"

    UNKNOWN = "UNKNOWN"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


MEANING_CHANGING_FAULT_CLASSES: Final[dict[FaultClass, AbstentionReason]] = {
    FaultClass.EXCLUSION_RULE_CHANGED: AbstentionReason.EXCLUSION_RULE,
    FaultClass.RANDOM_SEED_CHANGED: AbstentionReason.RANDOM_SEED,
    FaultClass.TRAIN_TEST_SPLIT_CHANGED: AbstentionReason.TRAIN_TEST_SPLIT,
    FaultClass.UNIT_CONVERSION_CHANGED: AbstentionReason.UNIT_CONVERSION,
    FaultClass.ROW_FILTER_CHANGED: AbstentionReason.ROW_FILTER,
    FaultClass.ROW_COUNT_CHANGED: AbstentionReason.ROW_COUNT_CHANGE,
}
"""Fault classes a provider must never repair, mapped to their abstention reason.

Reaching one of these is not a provider failure. The scientifically correct
repair for "the seed changed" is a human decision about the experiment, and the
provider's contribution is to say so and stop (RX-14).
"""


class Diagnosis(FrozenRecord):
    """What is believed to be wrong, stated against a named snapshot (RX-06).

    Frozen and digestible like every other RETRACE record, because a diagnosis
    is the evidence a proposal answers and a proposal whose question can be
    edited afterwards is not reviewable.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.Diagnosis"

    diagnosis_id: Identifier = Field(description="Stable id of this diagnosis.")
    snapshot_id: Identifier = Field(description="Snapshot the diagnosis was made against (RX-01).")
    target_path: NonEmptyStr = Field(
        description="Snapshot-relative path believed to carry the fault."
    )
    fault_class: FaultClass = Field(description="The believed fault class.")
    detail: NonEmptyStr = Field(description="What was observed, in the diagnoser's own words.")
    observed_exception: NonEmptyStr | None = Field(
        default=None,
        description="Exception text observed during the baseline run, when there was one.",
    )
    missing_path: NonEmptyStr | None = Field(
        default=None,
        description=(
            "For MISSING_INPUT_PATH: the path the source asked for and did not find. "
            "A hint only -- the provider re-derives candidates from the snapshot."
        ),
    )
    declared_delimiter: NonEmptyStr | None = Field(
        default=None,
        description="For WRONG_CSV_DELIMITER: the delimiter the source currently declares.",
    )

    @field_validator("target_path")
    @classmethod
    def _target_is_snapshot_relative(cls, value: str) -> str:
        """Refuse an absolute or traversing target path (RX-06)."""
        return validate_relative_path(value, field="Diagnosis.target_path")


@dataclass(frozen=True, slots=True)
class Abstention:
    """A recorded decision not to propose a repair (RX-06, RX-14).

    Abstention is a success state. The record exists so that the decision is
    auditable and countable: a run that produced no proposal must be
    distinguishable from a run that produced no proposal *because changing the
    seed was the only way through*.

    Attributes
    ----------
    reason:
        Closed-set, machine-readable reason.
    detail:
        Human-readable detail naming the construct, path or missing evidence.
    diagnosis_id / target_path:
        What the abstention was about.
    construct_label:
        The protected construct's label when the reason is a
        scientific-meaning refusal; ``None`` otherwise.
    """

    reason: AbstentionReason
    detail: str
    diagnosis_id: str
    target_path: str
    construct_label: str | None = None

    @property
    def is_scientific_restraint(self) -> bool:
        """Whether this abstention protected the science rather than reporting a limit."""
        from .restraint import SCIENTIFIC_MEANING_REASONS

        return self.reason in SCIENTIFIC_MEANING_REASONS


@runtime_checkable
class RepairProvider(Protocol):
    """The interface every repair provider implements (RX-06).

    Implementations must honour three rules, each checked by a test:

    1. They never mutate the snapshot. The only output is a proposal carrying a
       diff, plus optional writes inside a *granted* scratch directory.
    2. They return ``None`` -- never a best-effort patch -- when no rule
       applies or when the only route through would change scientific meaning,
       and they record an :class:`Abstention`.
    3. They raise rather than invent when a dependency is absent. See
       :class:`~retrace_domain.errors.ProviderNotConfigured`.
    """

    @property
    def provider_id(self) -> str:
        """Stable id recorded on every proposal this provider produces (RX-33)."""
        ...

    @property
    def abstention_log(self) -> tuple[Abstention, ...]:
        """Abstentions recorded by this instance, oldest first (RX-06)."""
        ...

    def propose(
        self,
        diagnosis: Diagnosis,
        snapshot_manifest: SnapshotManifest,
        snapshot_reader: SnapshotReader,
        scratch: Path | None,
    ) -> RepairProposal | None:
        """Propose a reviewable patch, or abstain by returning ``None`` (RX-06)."""
        ...


def candidate_digest(
    manifest: SnapshotManifest, target_path: str, patched_bytes: bytes
) -> str:
    """Return the digest of the candidate snapshot (RX-05, RX-06).

    The candidate is the whole snapshot with ``target_path`` replaced by
    ``patched_bytes``, so the digest is taken over the full sorted
    ``(path, sha256)`` map with that one entry swapped. Computing it over the
    patched file alone would make two candidates with identical patched files
    but different surrounding inputs indistinguishable -- and an approval binds
    this value (RX-05).

    Raises
    ------
    KeyError:
        If ``target_path`` is not declared by ``manifest``. A candidate that
        patches a file the snapshot does not contain has no identity.
    """
    if target_path not in manifest:
        raise KeyError(f"snapshot does not contain {target_path!r}")
    entries = {
        path: (sha256_hex(patched_bytes) if path == target_path else digest)
        for path, digest in manifest.entries
    }
    return canonical_digest(
        {"entries": [[path, entries[path]] for path in sorted(entries)]},
        type_tag=CANDIDATE_TYPE_TAG,
    )


def build_unified_diff(target_path: str, original: str, patched: str) -> str:
    """Return a unified diff from ``original`` to ``patched`` (RX-06).

    Header paths are written ``a/<target_path>`` and ``b/<target_path>``, the
    form :class:`~retrace_contracts.RepairProposal` parses and cross-checks
    against its declared target. The diff is produced by :mod:`difflib` from
    real content on both sides; nothing about it is templated.

    Returns an empty string when the two texts are identical, which the caller
    must treat as an abstention rather than as an empty patch.
    """
    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)
    if original_lines == patched_lines:
        return ""
    diff = "".join(
        difflib.unified_diff(
            original_lines,
            patched_lines,
            fromfile=f"a/{target_path}",
            tofile=f"b/{target_path}",
            n=3,
        )
    )
    return diff if diff.endswith("\n") else diff + "\n"


def changed_lines(unified_diff: str) -> tuple[str, ...]:
    """Return every line a diff adds or removes, without its ``+``/``-`` marker (RX-14).

    This is what the scientific-restraint guard is applied to, so it lives here
    and is shared by every provider: two providers that disagreed about which
    lines a patch changes would disagree about what the guard protects.

    Header lines (``---``, ``+++``) and hunk headers (``@@``) are excluded. They
    name files and offsets, not code, and including them would make every patch
    look like it touches whatever the filename happens to contain.
    """
    collected: list[str] = []
    for line in unified_diff.splitlines():
        if line.startswith(("---", "+++", "@@")):
            continue
        if line.startswith(("+", "-")):
            collected.append(line[1:])
    return tuple(collected)

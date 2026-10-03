"""A real rule-based repair provider, and the restraint that limits it (RX-06, RX-14).

What it actually does
---------------------
Two mechanical faults are genuinely handled, both by reading the snapshot's own
bytes and producing a :mod:`difflib` patch against them:

1. **A wrong relative data path whose file exists elsewhere in the snapshot.**
   Quoted path-shaped literals in the target source are collected; any literal
   the snapshot does not contain is looked up by its basename. Exactly one
   match becomes the replacement. Several matches abstain
   (``AMBIGUOUS_CANDIDATE_PATH``) rather than guess, because picking one of two
   candidate inputs is choosing the dataset -- a scientific decision.

2. **A wrong CSV delimiter argument.** The referenced file is read from the
   snapshot and its delimiter inferred from consistent field counts across the
   first few lines. If the declared ``sep=``/``delimiter=`` disagrees it is
   rewritten; if none is declared one is inserted. If the delimiter cannot be
   determined unambiguously the provider abstains
   (``DELIMITER_UNDETERMINED``) -- it never picks the most likely one.

What it refuses to do, and why that is the point
------------------------------------------------
Before any proposal is returned, every line the patch would add or remove is
scanned by :mod:`retrace_domain.providers.restraint`. If a changed line carries
an exclusion rule, a seed, a train/test split, a unit conversion, a row filter
or a row-count-changing call, the provider abstains with the matching reason
even though it *could* emit a patch. The same refusal applies up front when the
diagnosis itself names a meaning-changing fault class.

Determinism
-----------
Nothing here reads a clock, a random source, the network or the filesystem
outside the snapshot reader and (when granted) the scratch directory. The same
diagnosis and snapshot always produce the same diff, the same candidate digest
and the same proposal id, which is what makes a proposal reviewable and a
rerun comparable.
"""

from __future__ import annotations

import codecs
import re
from pathlib import Path
from typing import Final

from retrace_contracts import RepairProposal

from ..authority import RepairAuthority
from ..errors import AuthorityRule, WriteRefused
from ..snapshot import SnapshotManifest, SnapshotReader
from .base import (
    MEANING_CHANGING_FAULT_CLASSES,
    Abstention,
    Diagnosis,
    FaultClass,
    build_unified_diff,
    candidate_digest,
    changed_lines,
)
from .restraint import AbstentionReason, first_protected_construct

__all__ = [
    "DATA_SUFFIXES",
    "DELIMITER_CANDIDATES",
    "DeterministicRepairProvider",
    "detect_delimiter",
]

DELIMITER_CANDIDATES: Final[tuple[str, ...]] = (",", ";", "\t", "|")
"""Delimiters :func:`detect_delimiter` will consider, in no priority order.

Scoring decides between them, and a tie abstains. A hard-coded preference for
``,`` would be exactly the "most likely guess" this provider must not make.
"""

DATA_SUFFIXES: Final[frozenset[str]] = frozenset(
    {".csv", ".tsv", ".psv", ".txt", ".dat", ".json", ".jsonl", ".parquet", ".xlsx", ".xls"}
)
"""Suffixes that make a quoted literal plausibly a data path (RX-06)."""

_MAX_SNIFF_LINES: Final[int] = 5
_MAX_SNIFF_BYTES: Final[int] = 1 << 16

_QUOTED = re.compile(r"(?P<quote>['\"])(?P<value>[^'\"\n]{1,512})(?P=quote)")
_READER_CALL = re.compile(r"\b(read_csv|read_table|reader)\s*\(")
_SEP_ARGUMENT = re.compile(
    r"(?P<key>sep|delimiter)\s*=\s*(?P<quote>['\"])(?P<value>(?:\\.|[^'\"\\]){0,8})(?P=quote)"
)


def _looks_like_path(value: str) -> bool:
    """Return whether a quoted literal is plausibly a relative data path (RX-06)."""
    if not value or value.startswith(("http://", "https://", "/")) or "\\" in value:
        return False
    suffix = value[value.rfind(".") :].lower() if "." in value else ""
    return "/" in value or suffix in DATA_SUFFIXES


def detect_delimiter(data: bytes) -> str | None:
    """Infer a CSV delimiter from ``data``, or return ``None`` if ambiguous.

    A candidate qualifies only if it yields the *same* field count of at least
    two on every sampled line, which rejects a character that merely appears
    inside one field. The qualifying candidate with the highest field count
    wins; a tie returns ``None`` so the caller abstains instead of guessing.

    Known limit: field counting is lexical and does not honour RFC 4180
    quoting, so a delimiter inside a quoted field can defeat it. The
    consistency requirement across several lines makes that unlikely rather
    than impossible, and the failure direction is a refusal, not a wrong fix.
    """
    text = data[:_MAX_SNIFF_BYTES].decode("utf-8", errors="replace")
    lines = [line for line in text.splitlines() if line.strip()][:_MAX_SNIFF_LINES]
    if not lines:
        return None
    scores: dict[str, int] = {}
    for candidate in DELIMITER_CANDIDATES:
        counts = {line.count(candidate) for line in lines}
        if len(counts) == 1:
            count = counts.pop()
            if count >= 1:
                scores[candidate] = count
    if not scores:
        return None
    best = max(scores.values())
    winners = [candidate for candidate, score in scores.items() if score == best]
    return winners[0] if len(winners) == 1 else None


def _escape_for_source(delimiter: str) -> str:
    """Render ``delimiter`` as it must appear inside a double-quoted literal."""
    return delimiter.encode("unicode_escape").decode("ascii")


class DeterministicRepairProvider:
    """Rule-based repair provider with scientific restraint (RX-06, RX-14).

    Parameters
    ----------
    authority:
        The write guard (RX-07). Required only if ``propose`` is called with a
        scratch directory: a provider that wrote to disk without passing the
        guard would be the exact authority bypass RX-07 forbids, so an
        unguarded write raises rather than proceeding.
    provider_id:
        Recorded on every proposal (RX-33). Defaults to ``deterministic-local``.
    """

    def __init__(
        self,
        *,
        authority: RepairAuthority | None = None,
        provider_id: str = "deterministic-local",
    ) -> None:
        self._authority = authority
        self._provider_id = provider_id
        self._abstentions: list[Abstention] = []

    @property
    def provider_id(self) -> str:
        """Stable id recorded on every proposal this provider produces (RX-33)."""
        return self._provider_id

    @property
    def abstention_log(self) -> tuple[Abstention, ...]:
        """Abstentions recorded by this instance, oldest first (RX-06)."""
        return tuple(self._abstentions)

    # -- the interface ---------------------------------------------------

    def propose(
        self,
        diagnosis: Diagnosis,
        snapshot_manifest: SnapshotManifest,
        snapshot_reader: SnapshotReader,
        scratch: Path | None,
    ) -> RepairProposal | None:
        """Propose a patch for ``diagnosis``, or abstain by returning ``None`` (RX-06).

        Raises
        ------
        WriteRefused:
            If ``scratch`` is given and either no authority guard was supplied
            or the guard refuses the destination (RX-07). An authority refusal
            is never converted into an abstention: abstention means "I chose
            not to", and being refused is not a choice.
        """
        restraint = MEANING_CHANGING_FAULT_CLASSES.get(diagnosis.fault_class)
        if restraint is not None:
            return self._abstain(
                diagnosis,
                restraint,
                detail=(
                    f"fault class {diagnosis.fault_class.value} names a change to the "
                    "declared method; repairing it would make the run a reanalysis (RX-14)"
                ),
                construct_label=diagnosis.fault_class.value,
            )

        if diagnosis.target_path not in snapshot_manifest:
            return self._abstain(
                diagnosis,
                AbstentionReason.TARGET_NOT_IN_SNAPSHOT,
                detail=f"snapshot does not contain {diagnosis.target_path!r}",
            )

        raw = snapshot_reader(diagnosis.target_path)
        try:
            original = raw.decode("utf-8")
        except UnicodeDecodeError:
            return self._abstain(
                diagnosis,
                AbstentionReason.NO_RULE_MATCHED,
                detail=f"{diagnosis.target_path!r} is not UTF-8 text; no textual rule applies",
            )

        if diagnosis.fault_class is FaultClass.MISSING_INPUT_PATH:
            outcome = self._repair_missing_path(diagnosis, snapshot_manifest, original)
        elif diagnosis.fault_class is FaultClass.WRONG_CSV_DELIMITER:
            outcome = self._repair_delimiter(
                diagnosis, snapshot_manifest, snapshot_reader, original
            )
        else:
            return self._abstain(
                diagnosis,
                AbstentionReason.UNSUPPORTED_FAULT_CLASS,
                detail=(
                    f"no deterministic rule handles fault class {diagnosis.fault_class.value}"
                ),
            )

        if isinstance(outcome, Abstention):
            self._abstentions.append(outcome)
            return None
        patched, rationale = outcome

        unified_diff = build_unified_diff(diagnosis.target_path, original, patched)
        if not unified_diff:
            return self._abstain(
                diagnosis,
                AbstentionReason.DIFF_WOULD_BE_EMPTY,
                detail="the rule produced no change; there is nothing to review",
            )

        construct = first_protected_construct(changed_lines(unified_diff))
        if construct is not None:
            return self._abstain(
                diagnosis,
                construct.reason,
                detail=(
                    f"the patch would change a line carrying {construct.label}; "
                    "that changes scientific meaning, so no proposal is made (RX-14)"
                ),
                construct_label=construct.label,
            )

        patched_bytes = patched.encode("utf-8")
        candidate_hash = candidate_digest(
            snapshot_manifest, diagnosis.target_path, patched_bytes
        )
        proposal = RepairProposal(
            proposal_id=f"prop-{candidate_hash[:16]}",
            snapshot_id=diagnosis.snapshot_id,
            target_path=diagnosis.target_path,
            unified_diff=unified_diff,
            candidate_hash=candidate_hash,
            rationale=rationale,
            provider=self._provider_id,
        )
        if scratch is not None:
            self._write_candidate(scratch, diagnosis.target_path, patched_bytes)
        return proposal

    # -- rules -----------------------------------------------------------

    def _repair_missing_path(
        self, diagnosis: Diagnosis, manifest: SnapshotManifest, original: str
    ) -> tuple[str, str] | Abstention:
        """Rewrite one wrong relative data path to the file the snapshot holds (RX-06)."""
        literals = _path_literals(original)
        hinted = diagnosis.missing_path
        if hinted:
            literals = sorted(literals, key=lambda item: item[1] != hinted)

        considered: list[str] = []
        for quote, value in literals:
            if value in manifest:
                continue
            considered.append(value)
            basename = value.rsplit("/", 1)[-1]
            matches = tuple(path for path in manifest.paths_with_basename(basename))
            if len(matches) > 1:
                return Abstention(
                    reason=AbstentionReason.AMBIGUOUS_CANDIDATE_PATH,
                    detail=(
                        f"{value!r} could be any of {matches}; choosing between candidate "
                        "inputs is a decision about the dataset, not a repair"
                    ),
                    diagnosis_id=diagnosis.diagnosis_id,
                    target_path=diagnosis.target_path,
                )
            if len(matches) == 1:
                replacement = matches[0]
                patched = original.replace(
                    f"{quote}{value}{quote}", f"{quote}{replacement}{quote}"
                )
                rationale = (
                    f"the source reads {value!r}, which the snapshot does not contain; "
                    f"the snapshot holds exactly one file named {basename!r} at "
                    f"{replacement!r}, so the relative path is corrected. No measurement, "
                    "filter, seed, split or unit is touched."
                )
                return patched, rationale

        if not considered:
            return Abstention(
                reason=AbstentionReason.NO_RULE_MATCHED,
                detail=(
                    "every path-shaped literal in the target already resolves inside the "
                    "snapshot; the missing input is not a path typo this rule can fix"
                ),
                diagnosis_id=diagnosis.diagnosis_id,
                target_path=diagnosis.target_path,
            )
        return Abstention(
            reason=AbstentionReason.CANDIDATE_PATH_NOT_FOUND,
            detail=(
                f"none of {tuple(considered)} has a basename match in the snapshot; the "
                "input is absent, which is missing evidence rather than a path typo"
            ),
            diagnosis_id=diagnosis.diagnosis_id,
            target_path=diagnosis.target_path,
        )

    def _repair_delimiter(
        self,
        diagnosis: Diagnosis,
        manifest: SnapshotManifest,
        reader: SnapshotReader,
        original: str,
    ) -> tuple[str, str] | Abstention:
        """Correct a wrong CSV delimiter argument against the real file bytes (RX-06)."""
        lines = original.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if not _READER_CALL.search(line):
                continue
            literal = next((item for item in _path_literals(line)), None)
            if literal is None:
                continue
            data_path = _resolve_in_snapshot(manifest, literal[1])
            if data_path is None:
                return Abstention(
                    reason=AbstentionReason.TARGET_NOT_IN_SNAPSHOT,
                    detail=(
                        f"the reader call references {literal[1]!r}, which the snapshot "
                        "does not contain, so its real delimiter cannot be observed"
                    ),
                    diagnosis_id=diagnosis.diagnosis_id,
                    target_path=diagnosis.target_path,
                )
            observed = detect_delimiter(reader(data_path))
            if observed is None:
                return Abstention(
                    reason=AbstentionReason.DELIMITER_UNDETERMINED,
                    detail=(
                        f"no single delimiter gives consistent field counts in {data_path!r}; "
                        "the provider does not pick the most likely one"
                    ),
                    diagnosis_id=diagnosis.diagnosis_id,
                    target_path=diagnosis.target_path,
                )
            escaped = _escape_for_source(observed)
            declared = _SEP_ARGUMENT.search(line)
            if declared is not None:
                current = codecs.decode(declared.group("value"), "unicode_escape")
                if current == observed:
                    return Abstention(
                        reason=AbstentionReason.DELIMITER_ALREADY_CORRECT,
                        detail=(
                            f"the declared delimiter already matches {data_path!r}; "
                            "the failure has another cause"
                        ),
                        diagnosis_id=diagnosis.diagnosis_id,
                        target_path=diagnosis.target_path,
                    )
                replaced = (
                    line[: declared.start()]
                    + f'{declared.group("key")}="{escaped}"'
                    + line[declared.end() :]
                )
                rationale = (
                    f"{data_path!r} is delimited by {escaped!r}, but the reader call "
                    f"declares {declared.group('value')!r}; the parsing argument is "
                    "corrected. The file's rows, columns and values are unchanged."
                )
            else:
                quote, value = literal
                anchor = line.find(f"{quote}{value}{quote}")
                insert_at = anchor + len(value) + 2
                replaced = line[:insert_at] + f', sep="{escaped}"' + line[insert_at:]
                rationale = (
                    f"{data_path!r} is delimited by {escaped!r} and the reader call "
                    "declares no delimiter, so the default would mis-parse every row; "
                    "an explicit parsing argument is added and no value is altered."
                )
            patched_lines = list(lines)
            patched_lines[index] = replaced
            return "".join(patched_lines), rationale

        return Abstention(
            reason=AbstentionReason.NO_RULE_MATCHED,
            detail=(
                f"{diagnosis.target_path!r} contains no reader call with a path literal, "
                "so there is no delimiter argument to correct"
            ),
            diagnosis_id=diagnosis.diagnosis_id,
            target_path=diagnosis.target_path,
        )

    # -- internals -------------------------------------------------------

    def _abstain(
        self,
        diagnosis: Diagnosis,
        reason: AbstentionReason,
        *,
        detail: str,
        construct_label: str | None = None,
    ) -> RepairProposal | None:
        """Record an abstention and return the abstention result (RX-06).

        Returns ``None`` always: in the proposal domain, ``None`` IS the
        abstention. Typed ``RepairProposal | None`` rather than ``None`` so that
        ``return self._abstain(...)`` at each call site reads as returning a
        result, which is what it means, instead of tripping mypy's
        func-returns-value on a bare None-returning call.

        Returning ``None`` *and* recording the reason is the contract: the
        caller sees no proposal, and the evidence record says why there is none.
        """
        self._abstentions.append(
            Abstention(
                reason=reason,
                detail=detail,
                diagnosis_id=diagnosis.diagnosis_id,
                target_path=diagnosis.target_path,
                construct_label=construct_label,
            )
        )
        return None

    def _write_candidate(self, scratch: Path, target_path: str, payload: bytes) -> Path:
        """Write candidate bytes into the granted scratch directory (RX-07).

        Every write passes :meth:`RepairAuthority.assert_writable` first. With
        no guard configured the write is refused outright rather than performed
        unchecked -- "nobody told me not to" is not an authority.
        """
        if self._authority is None:
            raise WriteRefused(
                "a repair provider may not write without an authority guard (RX-07)",
                rule=AuthorityRule.UNGUARDED_WRITE,
                target=str(Path(scratch) / target_path),
                actor=self._provider_id,
            )
        destination = Path(scratch) / target_path
        resolved = self._authority.assert_writable(destination)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_bytes(payload)
        return resolved


def _path_literals(text: str) -> list[tuple[str, str]]:
    """Return ``(quote, value)`` for every path-shaped quoted literal in ``text``."""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in _QUOTED.finditer(text):
        item = (match.group("quote"), match.group("value"))
        if item in seen or not _looks_like_path(item[1]):
            continue
        seen.add(item)
        found.append(item)
    return found


def _resolve_in_snapshot(manifest: SnapshotManifest, value: str) -> str | None:
    """Return the snapshot path ``value`` refers to, or ``None`` if not unique."""
    if value in manifest:
        return value
    matches = manifest.paths_with_basename(value.rsplit("/", 1)[-1])
    return matches[0] if len(matches) == 1 else None

"""Scientific restraint: the constructs a repair may never touch (RX-06, RX-14).

The point of this module
------------------------
A repair worker's easiest path to "the notebook runs now" is to change what the
notebook *measures*. Drop the rows that fail, widen the filter, re-seed the
split, convert the units -- each makes the error go away and each turns a
reproduction into a different experiment. RX-14 says a changed methodology is a
reanalysis even when the result looks plausible; this module is how a provider
refuses to be the thing that changes it.

Abstention is a first-class success here. A provider that returns ``None`` with
:class:`AbstentionReason.RANDOM_SEED` has done its job correctly -- the right
answer to "make this run by changing the seed" is no.

Why the reason is an enum
-------------------------
A free-text reason cannot be asserted on, counted, aggregated into an evidence
bundle, or shown to a reviewer as a category. :class:`AbstentionReason` is
closed, so a new abstention path has to declare itself by editing this file.

Scope and honest limits
-----------------------
Detection is **lexical**, applied to the exact source lines a patch would
change. It is deliberately conservative: it fires on the presence of a
construct, not on proof that the construct's meaning changed. Consequences,
stated rather than hidden:

* It over-refuses. A path fix that happens to share a line with ``dropna(``
  will be abstained from. For a scientific-integrity guard that is the correct
  direction to err, and the reviewer is told exactly which construct refused.
* It is not a parser. An obfuscated or dynamically constructed call
  (``getattr(frame, "dro" + "pna")()``) is not detected. A provider is not the
  last line of defence for that case -- the independent verifier's methodology
  delta (RX-14) is, because it compares the declared contract against what the
  run actually did.
* Patterns are matched per line. A construct split across a continuation line
  is detected only if the changed line itself carries the matching text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final

__all__ = [
    "PROTECTED_CONSTRUCTS",
    "AbstentionReason",
    "ProtectedConstruct",
    "first_protected_construct",
    "protected_construct_in_line",
]


class AbstentionReason(str, Enum):
    """Machine-readable reason a provider declined to propose a repair (RX-06).

    The first six members are the scientific-meaning refusals: each names a
    construct whose change would make the run a different experiment. The
    remainder are capability limits -- the provider has no rule that applies,
    or the evidence needed to apply one is absent.
    """

    EXCLUSION_RULE = "EXCLUSION_RULE"
    RANDOM_SEED = "RANDOM_SEED"
    TRAIN_TEST_SPLIT = "TRAIN_TEST_SPLIT"
    UNIT_CONVERSION = "UNIT_CONVERSION"
    ROW_FILTER = "ROW_FILTER"
    ROW_COUNT_CHANGE = "ROW_COUNT_CHANGE"

    NO_RULE_MATCHED = "NO_RULE_MATCHED"
    UNSUPPORTED_FAULT_CLASS = "UNSUPPORTED_FAULT_CLASS"
    TARGET_NOT_IN_SNAPSHOT = "TARGET_NOT_IN_SNAPSHOT"
    CANDIDATE_PATH_NOT_FOUND = "CANDIDATE_PATH_NOT_FOUND"
    AMBIGUOUS_CANDIDATE_PATH = "AMBIGUOUS_CANDIDATE_PATH"
    DELIMITER_UNDETERMINED = "DELIMITER_UNDETERMINED"
    DELIMITER_ALREADY_CORRECT = "DELIMITER_ALREADY_CORRECT"
    DIFF_WOULD_BE_EMPTY = "DIFF_WOULD_BE_EMPTY"
    PROVIDER_RESPONSE_UNUSABLE = "PROVIDER_RESPONSE_UNUSABLE"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


SCIENTIFIC_MEANING_REASONS: Final[tuple[AbstentionReason, ...]] = (
    AbstentionReason.EXCLUSION_RULE,
    AbstentionReason.RANDOM_SEED,
    AbstentionReason.TRAIN_TEST_SPLIT,
    AbstentionReason.UNIT_CONVERSION,
    AbstentionReason.ROW_FILTER,
    AbstentionReason.ROW_COUNT_CHANGE,
)
"""The abstentions that mean "changing this would change the science" (RX-14)."""


@dataclass(frozen=True, slots=True)
class ProtectedConstruct:
    """One lexical construct a repair may not modify (RX-06, RX-14).

    Attributes
    ----------
    reason:
        The abstention reason reported when this construct is found.
    label:
        Short human-readable name of the construct, for the reviewer.
    pattern:
        Compiled regular expression matched against a single source line.
    """

    reason: AbstentionReason
    label: str
    pattern: re.Pattern[str]


def _construct(
    reason: AbstentionReason,
    label: str,
    pattern: str,
    *,
    ignore_case: bool = False,
) -> ProtectedConstruct:
    """Compile one protected construct. Keeps the table below readable."""
    flags = re.IGNORECASE if ignore_case else 0
    return ProtectedConstruct(reason=reason, label=label, pattern=re.compile(pattern, flags))


_EXCLUSION = AbstentionReason.EXCLUSION_RULE
_SEED = AbstentionReason.RANDOM_SEED
_SPLIT = AbstentionReason.TRAIN_TEST_SPLIT
_UNITS = AbstentionReason.UNIT_CONVERSION
_FILTER = AbstentionReason.ROW_FILTER
_ROWS = AbstentionReason.ROW_COUNT_CHANGE

PROTECTED_CONSTRUCTS: Final[tuple[ProtectedConstruct, ...]] = (
    # exclusion rules -- RX-03's `exclusions`, RX-14's EXCLUSIONS aspect
    _construct(_EXCLUSION, "an exclusion rule", r"\bexclusion", ignore_case=True),
    _construct(_EXCLUSION, "an exclude argument", r"\bexclude\w*\s*=", ignore_case=True),
    _construct(_EXCLUSION, "an excluded selection", r"\bexcluded\b", ignore_case=True),
    # random seeds -- RX-14's SEED aspect
    _construct(_SEED, "a seed argument", r"\b(random_state|random_seed|seed)\s*="),
    _construct(
        _SEED,
        "a seed call",
        r"\b(np\.random\.seed|random\.seed|manual_seed|set_seed)\s*\(",
    ),
    # train/test splits -- RX-14's SPLIT aspect
    _construct(_SPLIT, "a train/test split", r"\btrain_test_split\s*\("),
    _construct(
        _SPLIT,
        "a split-size argument",
        r"\b(test_size|train_size|train_fraction|stratify)\s*=",
    ),
    _construct(
        _SPLIT,
        "a cross-validation splitter",
        r"\b(StratifiedKFold|GroupKFold|KFold|ShuffleSplit|TimeSeriesSplit)\s*\(",
    ),
    # unit conversions -- RX-13 makes a unit mismatch a failure, never a conversion
    _construct(_UNITS, "a unit argument", r"\bunits?\s*="),
    _construct(_UNITS, "a unit-conversion call", r"\bconvert_units?\s*\("),
    _construct(_UNITS, "a scale factor", r"[*/]\s*(1_?000(\.0)?|0\.001|2\.20462|1e-?3)\b"),
    _construct(_UNITS, "a unit-suffix conversion", r"\bto_(kg|g|mg|lb|lbs|m|cm|mm)\b"),
    # row filters -- RX-14's POPULATION aspect
    _construct(
        _FILTER,
        "missing-value handling",
        r"\.(dropna|fillna|notna|isna|interpolate)\s*\(",
    ),
    _construct(_FILTER, "a row selection", r"\.(query|filter|where|mask|isin)\s*\("),
    # row-count changing operations -- RX-14's POPULATION aspect
    _construct(_ROWS, "a row removal", r"\.(drop|drop_duplicates|truncate)\s*\("),
    _construct(_ROWS, "a row subsetting call", r"\.(sample|head|tail|nlargest|nsmallest)\s*\("),
    _construct(_ROWS, "a change of aggregation level", r"\.(groupby|resample|pivot_table)\s*\("),
)
"""Every construct a repair must refuse to touch, in stable priority order (RX-14).

Declaration order is the priority order used by
:func:`protected_construct_in_line`, so a line carrying two constructs always
reports the same one. The order follows RX-14's methodology aspects:
exclusions, seed, split, units, then population.
"""


def protected_construct_in_line(line: str) -> ProtectedConstruct | None:
    """Return the first protected construct found in ``line``, else ``None`` (RX-14)."""
    for construct in PROTECTED_CONSTRUCTS:
        if construct.pattern.search(line):
            return construct
    return None


def first_protected_construct(lines: Iterable[str]) -> ProtectedConstruct | None:
    """Return the first protected construct found across ``lines``, else ``None``.

    Applied by a provider to **every line a patch would add or remove**, both
    sides of the change. Checking only the removed lines would miss a patch
    that *introduces* a filter; checking only the added lines would miss one
    that deletes an exclusion rule.
    """
    for line in lines:
        found = protected_construct_in_line(line)
        if found is not None:
            return found
    return None

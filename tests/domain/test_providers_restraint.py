"""The scientific-restraint guard (RX-06, RX-14).

The guard decides what a repair may never touch, so it is tested directly as
well as through the providers. Two properties matter equally:

* it **fires** on each construct whose change would alter what the analysis
  measures, and
* it **does not fire** on an ordinary parsing fix, because a guard that refuses
  everything protects nothing and would simply be removed by the next person.
"""

from __future__ import annotations

import pytest
from retrace_domain import (
    PROTECTED_CONSTRUCTS,
    SCIENTIFIC_MEANING_REASONS,
    AbstentionReason,
    first_protected_construct,
    protected_construct_in_line,
)

MEANING_CHANGING_LINES = [
    ("    frame = frame[frame.site.isin(EXCLUSIONS)]", AbstentionReason.EXCLUSION_RULE),
    ("    rows = load(exclude_incomplete=True)", AbstentionReason.EXCLUSION_RULE),
    ("    sample = frame.sample(frac=0.5, random_state=20261002)", AbstentionReason.RANDOM_SEED),
    ("    np.random.seed(7)", AbstentionReason.RANDOM_SEED),
    ("    a, b = train_test_split(frame)", AbstentionReason.TRAIN_TEST_SPLIT),
    ("    a, b = split_frame(frame, test_size=0.3)", AbstentionReason.TRAIN_TEST_SPLIT),
    ("    folds = StratifiedKFold(n_splits=5)", AbstentionReason.TRAIN_TEST_SPLIT),
    ("    mass = frame['mass_g'] / 1000", AbstentionReason.UNIT_CONVERSION),
    ("    frame = read_measurements(unit='kg')", AbstentionReason.UNIT_CONVERSION),
    ("    frame = frame.dropna()", AbstentionReason.ROW_FILTER),
    ("    frame = frame.query('mass_g > 3000')", AbstentionReason.ROW_FILTER),
    ("    frame = frame.drop_duplicates()", AbstentionReason.ROW_COUNT_CHANGE),
    ("    frame = frame.head(100)", AbstentionReason.ROW_COUNT_CHANGE),
    ("    summary = frame.groupby('site').mean()", AbstentionReason.ROW_COUNT_CHANGE),
]

MECHANICAL_LINES = [
    '    return pd.read_csv("inputs/data/measurements.csv", sep=";")',
    '    return pd.read_csv("inputs/data/measurements.csv")',
    "    import pandas as pd",
    "    path = Path(__file__).parent / 'data'",
    '    frame.to_csv(out / "summary.csv", index=False)',
    "    return float(frame['mass_g'].mean())",
]


@pytest.mark.parametrize(("line", "reason"), MEANING_CHANGING_LINES)
def test_each_meaning_changing_construct_is_detected(line: str, reason: AbstentionReason) -> None:
    """NEGATIVE CONTROL, RX-14: the guard fires, and names the right category."""
    found = protected_construct_in_line(line)
    assert found is not None, f"the guard missed {line!r}"
    assert found.reason is reason


@pytest.mark.parametrize("line", MECHANICAL_LINES)
def test_an_ordinary_parsing_line_is_not_protected(line: str) -> None:
    """A guard that refuses every line is a guard nobody can use."""
    assert protected_construct_in_line(line) is None


def test_every_scientific_reason_has_at_least_one_detector() -> None:
    """RX-14: each methodology aspect the guard claims to cover really is covered."""
    covered = {construct.reason for construct in PROTECTED_CONSTRUCTS}
    assert covered == set(SCIENTIFIC_MEANING_REASONS)


def test_every_scientific_reason_has_a_demonstrated_detection() -> None:
    """Each reason is exercised by a real line above, not merely declared."""
    exercised = {reason for _, reason in MEANING_CHANGING_LINES}
    assert exercised == set(SCIENTIFIC_MEANING_REASONS)


def test_the_first_match_wins_in_declaration_order() -> None:
    """Priority is stable, so a two-construct line always reports the same reason."""
    line = "    frame = frame.dropna().sample(frac=0.5, random_state=1)"
    found = protected_construct_in_line(line)
    assert found is not None
    assert found.reason is AbstentionReason.RANDOM_SEED


def test_scanning_several_lines_returns_the_first_hit() -> None:
    """A patch is judged on every line it changes, not only the first."""
    lines = ["    import pandas as pd", "    frame = frame.dropna()"]
    found = first_protected_construct(lines)
    assert found is not None
    assert found.reason is AbstentionReason.ROW_FILTER


def test_scanning_clean_lines_returns_none() -> None:
    """The negative side of the scan, so the function is known to be able to pass."""
    assert first_protected_construct(MECHANICAL_LINES) is None


def test_a_dynamically_constructed_call_is_not_detected() -> None:
    """RECORDED LIMIT, RX-14: detection is lexical, so an obfuscated call escapes it.

    Stated as a passing test so the limit is visible in the suite rather than
    assumed away. A guard like this is a first filter; the last line of defence
    is the independent verifier's methodology delta (RX-14), which compares the
    declared contract against what the run actually did and so does not depend
    on how the call was spelled.
    """
    lines = ['    frame = getattr(frame, "drop" + "na")()']
    assert first_protected_construct(lines) is None

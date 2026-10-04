"""The deterministic repair provider: real repairs and real restraint (RX-06, RX-14).

The file is organised around one question: can this provider fix a mechanical
fault without ever being the thing that changed the science?

* The first group proves it genuinely repairs the two mechanical faults, by
  computing the expected patched content *independently in the test* and
  requiring the proposal to match it.
* The second group proves the snapshot is untouched by a proposal (RX-06).
* The third group is the restraint evidence: abstention on every
  meaning-changing fault class, and on every protected construct reachable
  through a patched line.
* The fourth group proves the provider's writes go through the authority guard
  (RX-07) and cannot be redirected by its own ``scratch`` argument.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from domain_support import (
    COMMA_CSV,
    NO_DELIMITER_SOURCE,
    SEMICOLON_CSV,
    WRONG_DELIMITER_SOURCE,
    WRONG_PATH_SOURCE,
    write_tree,
)
from retrace_contracts import RepairProposal, is_safe_relative_path
from retrace_domain import (
    PROTECTED_PREFIXES,
    AbstentionReason,
    AuthorityRule,
    ContentAddressedStore,
    DeterministicRepairProvider,
    Diagnosis,
    FaultClass,
    RepairAuthority,
    RepairProvider,
    SnapshotManifest,
    SnapshotReader,
    WriteRefused,
    build_unified_diff,
    candidate_digest,
    snapshot_create,
    store_reader,
)
from retrace_domain.providers.base import MEANING_CHANGING_FAULT_CLASSES

Snapshot = tuple[SnapshotManifest, SnapshotReader]
TARGET = "analysis/load.py"


@pytest.fixture
def provider() -> DeterministicRepairProvider:
    """A provider with no authority guard; it is never asked to write."""
    return DeterministicRepairProvider()


@pytest.fixture
def build_snapshot(
    store: ContentAddressedStore, tmp_path: Path
) -> Callable[[dict[str, str]], Snapshot]:
    """Factory: write a SYNTHETIC tree, snapshot it, return its manifest and reader."""
    counter = {"n": 0}

    def build(files: dict[str, str]) -> Snapshot:
        counter["n"] += 1
        root = write_tree(tmp_path / f"tree{counter['n']}", files)
        manifest = snapshot_create(store, root)
        return manifest, store_reader(store, manifest)

    return build


def diagnose(fault_class: FaultClass, **overrides: object) -> Diagnosis:
    """Build a diagnosis against the standard fixture target."""
    fields: dict[str, object] = {
        "diagnosis_id": "diag-0001",
        "snapshot_id": "snap-0001",
        "target_path": TARGET,
        "fault_class": fault_class,
        "detail": "the baseline run raised while loading its declared input",
    }
    fields.update(overrides)
    return Diagnosis(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# It really repairs: (a) a wrong relative path, (b) a wrong CSV delimiter.
# ---------------------------------------------------------------------------


def test_a_wrong_relative_path_is_repaired(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-06: the path is corrected to the one file in the snapshot that matches.

    The expected patched content is computed here, independently of the
    provider, so the assertion states what the patch must say rather than
    echoing what the provider produced.
    """
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    expected = WRONG_PATH_SOURCE.replace(
        '"data/measurements.csv"', '"inputs/data/measurements.csv"'
    )
    assert expected != WRONG_PATH_SOURCE, "the fixture no longer carries the injected fault"

    proposal = provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None)

    assert isinstance(proposal, RepairProposal)
    assert proposal.target_path == TARGET
    assert proposal.provider == "deterministic-local"
    assert proposal.unified_diff == build_unified_diff(TARGET, WRONG_PATH_SOURCE, expected)
    assert proposal.candidate_hash == candidate_digest(manifest, TARGET, expected.encode("utf-8"))
    assert provider.abstention_log == ()


def test_the_repair_diff_is_a_real_unified_diff(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-06: a proposal carries a reviewable patch, not file content."""
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    proposal = provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None)
    assert proposal is not None
    lines = proposal.unified_diff.splitlines()
    assert lines[0] == f"--- a/{TARGET}"
    assert lines[1] == f"+++ b/{TARGET}"
    assert any(line.startswith("@@") for line in lines)
    removed = [line for line in lines if line.startswith("-") and not line.startswith("---")]
    added = [line for line in lines if line.startswith("+") and not line.startswith("+++")]
    assert removed == ['-    return pd.read_csv("data/measurements.csv", sep=";")']
    assert added == ['+    return pd.read_csv("inputs/data/measurements.csv", sep=";")']


def test_the_rationale_states_what_was_changed_and_what_was_not(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-06: a reviewer is told the reasoning, in the proposer's own words."""
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    proposal = provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None)
    assert proposal is not None
    assert "inputs/data/measurements.csv" in proposal.rationale
    assert "seed" in proposal.rationale


def test_a_wrong_csv_delimiter_is_repaired(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-06: the declared delimiter is corrected from the file's real bytes."""
    manifest, reader = build_snapshot(
        {TARGET: WRONG_DELIMITER_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    expected = WRONG_DELIMITER_SOURCE.replace('sep=","', 'sep=";"')

    proposal = provider.propose(diagnose(FaultClass.WRONG_CSV_DELIMITER), manifest, reader, None)

    assert proposal is not None
    assert proposal.unified_diff == build_unified_diff(TARGET, WRONG_DELIMITER_SOURCE, expected)
    assert proposal.candidate_hash == candidate_digest(manifest, TARGET, expected.encode("utf-8"))


def test_a_missing_delimiter_argument_is_inserted(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-06: a reader call with no delimiter would mis-parse every row."""
    manifest, reader = build_snapshot(
        {TARGET: NO_DELIMITER_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    expected = NO_DELIMITER_SOURCE.replace(
        '"inputs/data/measurements.csv")', '"inputs/data/measurements.csv", sep=";")'
    )
    proposal = provider.propose(diagnose(FaultClass.WRONG_CSV_DELIMITER), manifest, reader, None)
    assert proposal is not None
    assert proposal.unified_diff == build_unified_diff(TARGET, NO_DELIMITER_SOURCE, expected)


def test_a_tab_delimiter_is_written_as_an_escape(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-06: the patched source must be valid Python, so a tab is escaped."""
    tab_csv = SEMICOLON_CSV.replace(";", "\t")
    manifest, reader = build_snapshot(
        {TARGET: WRONG_DELIMITER_SOURCE, "inputs/data/measurements.csv": tab_csv}
    )
    proposal = provider.propose(diagnose(FaultClass.WRONG_CSV_DELIMITER), manifest, reader, None)
    assert proposal is not None
    assert r'sep="\t"' in proposal.unified_diff
    assert "\t" not in proposal.unified_diff


def test_the_candidate_digest_tracks_the_content(
    build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-05, RX-06: the value an approval binds changes when the candidate changes."""
    manifest, _ = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    first = candidate_digest(manifest, TARGET, b"one")
    assert first == candidate_digest(manifest, TARGET, b"one")
    assert first != candidate_digest(manifest, TARGET, b"two")
    assert first != manifest.manifest_digest
    with pytest.raises(KeyError):
        candidate_digest(manifest, "analysis/absent.py", b"one")


def test_the_provider_satisfies_the_protocol(provider: DeterministicRepairProvider) -> None:
    """RX-06: the interface is the contract, so conformance is asserted."""
    assert isinstance(provider, RepairProvider)


# ---------------------------------------------------------------------------
# The snapshot is never mutated by a proposal (RX-06).
# ---------------------------------------------------------------------------


def test_the_snapshot_is_unchanged_after_a_proposal(
    store: ContentAddressedStore,
    provider: DeterministicRepairProvider,
    build_snapshot: Callable[[dict[str, str]], Snapshot],
) -> None:
    """RX-06: a proposal is a patch *against* a snapshot, never an edit *of* one."""
    files = {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    manifest, reader = build_snapshot(files)
    before = manifest.manifest_digest

    assert provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None)

    assert manifest.manifest_digest == before
    assert store.verify_all(), "the store sweep must still have blobs to check"
    assert reader(TARGET).decode("utf-8") == WRONG_PATH_SOURCE


# ---------------------------------------------------------------------------
# Restraint: abstention is a first-class success (RX-14).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fault_class", "reason"), sorted(MEANING_CHANGING_FAULT_CLASSES.items(), key=str)
)
def test_abstains_on_every_meaning_changing_fault_class(
    provider: DeterministicRepairProvider,
    build_snapshot: Callable[[dict[str, str]], Snapshot],
    fault_class: FaultClass,
    reason: AbstentionReason,
) -> None:
    """NEGATIVE CONTROL, RX-14: a diagnosis that names a method change is refused.

    One parametrisation per class, so losing a class from the table fails this
    test rather than quietly shrinking the guard.
    """
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    assert provider.propose(diagnose(fault_class), manifest, reader, None) is None
    recorded = provider.abstention_log[-1]
    assert recorded.reason is reason
    assert recorded.is_scientific_restraint
    assert recorded.diagnosis_id == "diag-0001"


def test_every_meaning_changing_fault_class_is_covered() -> None:
    """RX-14: the table covers each methodology aspect a repair could reach."""
    assert set(MEANING_CHANGING_FAULT_CLASSES) == {
        FaultClass.EXCLUSION_RULE_CHANGED,
        FaultClass.RANDOM_SEED_CHANGED,
        FaultClass.TRAIN_TEST_SPLIT_CHANGED,
        FaultClass.UNIT_CONVERSION_CHANGED,
        FaultClass.ROW_FILTER_CHANGED,
        FaultClass.ROW_COUNT_CHANGED,
    }


#: A mechanically repairable fault (the input path is wrong) placed on a line
#: that also carries a protected construct. The provider *could* emit a patch;
#: it must not, because the patch would touch the construct.
LOADER = '''"""SYNTHETIC fixture. injected: true -- the input path is wrong."""
import pandas as pd
from sklearn.model_selection import StratifiedKFold, train_test_split


def load():
    {statement}
'''

ENTANGLED_STATEMENTS = [
    (
        'return pd.read_csv("data/measurements.csv")  # exclusion rule: site-b only',
        AbstentionReason.EXCLUSION_RULE,
    ),
    (
        'return pd.read_csv("data/measurements.csv").sample(frac=0.5, random_state=7)',
        AbstentionReason.RANDOM_SEED,
    ),
    (
        'return train_test_split(pd.read_csv("data/measurements.csv"), test_size=0.3)',
        AbstentionReason.TRAIN_TEST_SPLIT,
    ),
    (
        'return pd.read_csv("data/measurements.csv")["mass_g"] / 1000',
        AbstentionReason.UNIT_CONVERSION,
    ),
    (
        'return pd.read_csv("data/measurements.csv").dropna()',
        AbstentionReason.ROW_FILTER,
    ),
    (
        'return pd.read_csv("data/measurements.csv").drop_duplicates()',
        AbstentionReason.ROW_COUNT_CHANGE,
    ),
]


@pytest.mark.parametrize(("statement", "reason"), ENTANGLED_STATEMENTS)
def test_abstains_when_the_patched_line_carries_a_protected_construct(
    provider: DeterministicRepairProvider,
    build_snapshot: Callable[[dict[str, str]], Snapshot],
    statement: str,
    reason: AbstentionReason,
) -> None:
    """NEGATIVE CONTROL, RX-14: restraint is applied to the lines the patch changes.

    This is the harder half of the property. The fault is mechanical and the
    rule applies, so the provider has a working repair in hand -- and still
    declines, because emitting it would modify a line that decides what the
    analysis measures.
    """
    source = LOADER.format(statement=statement)
    manifest, reader = build_snapshot(
        {TARGET: source, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )

    assert provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None) is None

    recorded = provider.abstention_log[-1]
    assert recorded.reason is reason
    assert recorded.is_scientific_restraint
    assert recorded.construct_label is not None


def test_the_entangled_fixtures_would_otherwise_be_repairable(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """The restraint tests above would be vacuous if the rule could not fire at all.

    Same fixture shape, same fault, with the protected construct removed: a
    proposal is produced. That makes the abstentions evidence of restraint
    rather than evidence of an inapplicable rule.
    """
    source = LOADER.format(statement='return pd.read_csv("data/measurements.csv")')
    manifest, reader = build_snapshot(
        {TARGET: source, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    assert provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None)


def test_abstains_when_two_snapshot_files_could_be_the_intended_input(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """NEGATIVE CONTROL, RX-06: choosing between candidate inputs is choosing the dataset."""
    manifest, reader = build_snapshot(
        {
            TARGET: WRONG_PATH_SOURCE,
            "inputs/data/measurements.csv": SEMICOLON_CSV,
            "archive/2024/measurements.csv": COMMA_CSV,
        }
    )
    assert provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None) is None
    assert provider.abstention_log[-1].reason is AbstentionReason.AMBIGUOUS_CANDIDATE_PATH


def test_abstains_when_the_input_is_simply_absent(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """NEGATIVE CONTROL, RX-17: absent evidence is not a path typo to invent a fix for."""
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/other.csv": SEMICOLON_CSV}
    )
    assert provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, None) is None
    assert provider.abstention_log[-1].reason is AbstentionReason.CANDIDATE_PATH_NOT_FOUND


def test_abstains_when_the_declared_delimiter_is_already_correct(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """NEGATIVE CONTROL: the provider does not invent a change to look useful."""
    manifest, reader = build_snapshot(
        {TARGET: WRONG_DELIMITER_SOURCE, "inputs/data/measurements.csv": COMMA_CSV}
    )
    outcome = provider.propose(diagnose(FaultClass.WRONG_CSV_DELIMITER), manifest, reader, None)
    assert outcome is None
    assert provider.abstention_log[-1].reason is AbstentionReason.DELIMITER_ALREADY_CORRECT


def test_abstains_when_the_delimiter_cannot_be_determined(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """NEGATIVE CONTROL, RX-06: an ambiguous file gets a refusal, not a best guess."""
    manifest, reader = build_snapshot(
        {TARGET: WRONG_DELIMITER_SOURCE, "inputs/data/measurements.csv": "mass_g\n3750\n3800\n"}
    )
    outcome = provider.propose(diagnose(FaultClass.WRONG_CSV_DELIMITER), manifest, reader, None)
    assert outcome is None
    assert provider.abstention_log[-1].reason is AbstentionReason.DELIMITER_UNDETERMINED


def test_abstains_when_the_target_is_not_in_the_snapshot(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """NEGATIVE CONTROL, RX-01: a proposal is always against a named snapshot."""
    manifest, reader = build_snapshot({TARGET: WRONG_PATH_SOURCE})
    diagnosis = diagnose(FaultClass.MISSING_INPUT_PATH, target_path="analysis/absent.py")
    assert provider.propose(diagnosis, manifest, reader, None) is None
    assert provider.abstention_log[-1].reason is AbstentionReason.TARGET_NOT_IN_SNAPSHOT


def test_abstains_on_an_unknown_fault_class(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """NEGATIVE CONTROL, RX-06: no rule means no proposal, stated as such."""
    manifest, reader = build_snapshot({TARGET: WRONG_PATH_SOURCE})
    assert provider.propose(diagnose(FaultClass.UNKNOWN), manifest, reader, None) is None
    assert provider.abstention_log[-1].reason is AbstentionReason.UNSUPPORTED_FAULT_CLASS


def test_abstains_on_a_non_text_target(
    provider: DeterministicRepairProvider,
    build_snapshot: Callable[[dict[str, str]], Snapshot],
    store: ContentAddressedStore,
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL: a textual rule does not pretend to understand binary content."""
    root = tmp_path / "binary-tree"
    (root / "analysis").mkdir(parents=True)
    (root / "analysis" / "load.py").write_bytes(b"\xfe\xff\x00binary")
    manifest = snapshot_create(store, root)
    assert (
        provider.propose(
            diagnose(FaultClass.MISSING_INPUT_PATH), manifest, store_reader(store, manifest), None
        )
        is None
    )
    assert provider.abstention_log[-1].reason is AbstentionReason.NO_RULE_MATCHED


def test_the_abstention_log_accumulates_in_order(
    provider: DeterministicRepairProvider, build_snapshot: Callable[[dict[str, str]], Snapshot]
) -> None:
    """RX-06: abstentions are a record, not a transient flag."""
    manifest, reader = build_snapshot({TARGET: WRONG_PATH_SOURCE})
    provider.propose(diagnose(FaultClass.RANDOM_SEED_CHANGED), manifest, reader, None)
    provider.propose(diagnose(FaultClass.UNKNOWN), manifest, reader, None)
    assert [item.reason for item in provider.abstention_log] == [
        AbstentionReason.RANDOM_SEED,
        AbstentionReason.UNSUPPORTED_FAULT_CLASS,
    ]


# ---------------------------------------------------------------------------
# Writes go through the authority guard (RX-07).
# ---------------------------------------------------------------------------


def test_the_candidate_is_written_into_a_granted_scratch(
    build_snapshot: Callable[[dict[str, str]], Snapshot], tmp_path: Path
) -> None:
    """RX-07: the one writable area is the granted candidate scratch directory."""
    scratch = tmp_path / "scratch" / "candidate-0001"
    scratch.mkdir(parents=True)
    authority = RepairAuthority(repo_root=tmp_path, scratch_dirs=(scratch,))
    provider = DeterministicRepairProvider(authority=authority)
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )

    proposal = provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, scratch)

    assert proposal is not None
    written = scratch / TARGET
    assert is_safe_relative_path(TARGET)
    assert written.read_text(encoding="utf-8") == WRONG_PATH_SOURCE.replace(
        '"data/measurements.csv"', '"inputs/data/measurements.csv"'
    )
    assert proposal.candidate_hash == candidate_digest(manifest, TARGET, written.read_bytes())


def test_an_unguarded_write_is_refused(
    provider: DeterministicRepairProvider,
    build_snapshot: Callable[[dict[str, str]], Snapshot],
    tmp_path: Path,
) -> None:
    """NEGATIVE CONTROL, RX-07: no guard configured means no write, not a free write."""
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )
    scratch = tmp_path / "ungoverned"
    scratch.mkdir()
    with pytest.raises(WriteRefused) as caught:
        provider.propose(diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, scratch)
    assert caught.value.rule is AuthorityRule.UNGUARDED_WRITE
    assert not (scratch / TARGET).exists()


@pytest.mark.parametrize("prefix", PROTECTED_PREFIXES)
def test_a_scratch_argument_cannot_redirect_the_write_into_a_protected_area(
    build_snapshot: Callable[[dict[str, str]], Snapshot], tmp_path: Path, prefix: str
) -> None:
    """NEGATIVE CONTROL, RX-07: the guard decides, not the caller's argument.

    A compromised or buggy caller passing a protected directory as ``scratch``
    is refused for every protected prefix individually.
    """
    granted = tmp_path / "scratch" / "candidate-0001"
    granted.mkdir(parents=True)
    (tmp_path / prefix).mkdir(parents=True, exist_ok=True)
    authority = RepairAuthority(repo_root=tmp_path, scratch_dirs=(granted,))
    provider = DeterministicRepairProvider(authority=authority)
    manifest, reader = build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )

    with pytest.raises(WriteRefused) as caught:
        provider.propose(
            diagnose(FaultClass.MISSING_INPUT_PATH), manifest, reader, tmp_path / prefix
        )
    assert caught.value.rule is AuthorityRule.PROTECTED_PREFIX
    assert not (tmp_path / prefix / TARGET).exists()

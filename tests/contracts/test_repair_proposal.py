"""The repair proposal: a diff, never file content (RX-06, RX-56).

"""

from __future__ import annotations

import pytest
from contracts_support import VALID_DIFF, build_proposal
from pydantic import ValidationError
from retrace_contracts import (
    MAX_DIFF_BYTES,
    ContractImmutable,
    RepairProposal,
    parse_unified_diff_targets,
)

RAW_FILE_CONTENT = """def clean(frame):
    frame = frame.dropna(subset=["mass_g"])
    return frame
"""

NEW_FILE_DIFF = """--- /dev/null
+++ b/analysis/new_check.py
@@ -0,0 +1,2 @@
+def check():
+    return True
"""


def test_valid_proposal_carries_a_diff_and_defaults_to_not_injected() -> None:
    """RX-06/RX-56: a well-formed proposal; injected is False unless declared."""
    proposal = build_proposal()
    assert proposal.unified_diff == VALID_DIFF
    assert proposal.injected is False


def test_injected_must_be_declared_explicitly() -> None:
    """RX-56: a fixture fault labels itself; nothing infers the label."""
    assert build_proposal(injected=True).injected is True
    assert RepairProposal.model_fields["injected"].default is False


def test_raw_file_content_is_refused() -> None:
    """RX-06 negative control: a replacement body is not a reviewable patch."""
    with pytest.raises(ValidationError, match="no '@@' hunk header"):
        build_proposal(unified_diff=RAW_FILE_CONTENT)


def test_diff_without_a_hunk_header_is_refused() -> None:
    """RX-06 negative control: headers alone describe no change."""
    headers_only = "--- a/analysis/clean.py\n+++ b/analysis/clean.py\n"
    with pytest.raises(ValidationError, match="no '@@' hunk header"):
        build_proposal(unified_diff=headers_only)


def test_diff_without_file_headers_is_refused() -> None:
    """RX-06 negative control: a hunk with no named file states no target."""
    hunk_only = '@@ -1,2 +1,2 @@\n-old\n+new\n'
    with pytest.raises(ValidationError, match="names no file"):
        build_proposal(unified_diff=hunk_only)


def test_diff_targeting_another_file_is_refused() -> None:
    """RX-06/RX-07 negative control: declaring one target and patching another.

    This is the shape an authority bypass takes when it is dressed as a typo:
    the proposal passes a target-path allowlist while the diff edits the
    verifier.
    """
    sneaky = VALID_DIFF.replace("analysis/clean.py", "services/verifier/compare.py")
    with pytest.raises(ValidationError, match="may not declare one target"):
        build_proposal(unified_diff=sneaky)


def test_new_file_diff_against_dev_null_is_accepted() -> None:
    """RX-06 positive control: adding a file is a legitimate patch shape."""
    proposal = build_proposal(
        target_path="analysis/new_check.py", unified_diff=NEW_FILE_DIFF
    )
    assert proposal.target_path == "analysis/new_check.py"


@pytest.mark.parametrize(
    "path",
    [
        "/etc/cron.d/retrace",
        "../../services/verifier/compare.py",
        "analysis/../../escape.py",
        "C:/windows/system32/x.py",
        "analysis\\clean.py",
        "analysis/",
        "   ",
    ],
)
def test_unsafe_target_paths_are_refused(path: str) -> None:
    """RX-06/RX-42 negative control: a target path may not escape the snapshot."""
    with pytest.raises(ValidationError):
        build_proposal(target_path=path)


def test_oversize_diff_is_refused() -> None:
    """RX-06 negative control: an unreviewable patch is not a reviewable patch."""
    padding = "+" + ("x" * 80) + "\n"
    repeats = (MAX_DIFF_BYTES // len(padding)) + 2
    with pytest.raises(ValidationError, match="exceeds"):
        build_proposal(unified_diff=VALID_DIFF + padding * repeats)


def test_candidate_hash_must_be_a_real_digest() -> None:
    """RX-05 negative control: the approval binds this value, so it must be valid."""
    with pytest.raises(ValidationError):
        build_proposal(candidate_hash="candidate-1")


def test_rationale_and_provider_are_required() -> None:
    """RX-06/RX-33: an unexplained or unattributed proposal is refused."""
    with pytest.raises(ValidationError):
        build_proposal(rationale="  ")
    with pytest.raises(ValidationError):
        build_proposal(provider="")


def test_proposal_is_immutable() -> None:
    """RX-06: the diff a reviewer read cannot be swapped afterwards."""
    proposal = build_proposal()
    with pytest.raises(ContractImmutable):
        proposal.unified_diff = NEW_FILE_DIFF


def test_proposal_digest_changes_with_the_diff() -> None:
    """RX-06: the proposal digest follows its content."""
    first = build_proposal()
    second = build_proposal(
        target_path="analysis/new_check.py", unified_diff=NEW_FILE_DIFF
    )
    assert first.content_digest() != second.content_digest()


def test_parse_unified_diff_targets_strips_prefixes_and_counts_hunks() -> None:
    """RX-06: the structural diff parse reports paths and hunk count."""
    paths, hunks = parse_unified_diff_targets(VALID_DIFF)
    assert paths == frozenset({"analysis/clean.py"})
    assert hunks == 1


def test_parse_unified_diff_targets_ignores_dev_null() -> None:
    """RX-06: /dev/null is not a patch target."""
    paths, hunks = parse_unified_diff_targets(NEW_FILE_DIFF)
    assert paths == frozenset({"analysis/new_check.py"})
    assert hunks == 1


def test_parse_unified_diff_targets_handles_timestamp_suffixes() -> None:
    """RX-06: diff metadata after a tab is not part of the path."""
    with_timestamps = (
        "--- a/analysis/clean.py\t2026-10-02 09:00:00.000000000 +0000\n"
        "+++ b/analysis/clean.py\t2026-10-02 09:05:00.000000000 +0000\n"
        "@@ -1 +1 @@\n-old\n+new\n"
    )
    paths, hunks = parse_unified_diff_targets(with_timestamps)
    assert paths == frozenset({"analysis/clean.py"})
    assert hunks == 1


def test_parse_unified_diff_targets_finds_nothing_in_plain_content() -> None:
    """RX-06 negative control: the parse does not invent a target."""
    assert parse_unified_diff_targets(RAW_FILE_CONTENT) == (frozenset(), 0)


def test_proposal_carries_no_field_for_file_content() -> None:
    """RX-06: there is nowhere to put replacement content, by construction."""
    forbidden = {"content", "new_content", "file_content", "body", "replacement"}
    assert forbidden.isdisjoint(RepairProposal.model_fields)

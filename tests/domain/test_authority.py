"""The repair worker's write guard (RX-07).

This is the authority boundary from ``docs/ARCHITECTURE.md``:

    repair worker ──proposes diff──▶ candidate
          │ CANNOT WRITE: contracts/, verifier/, references/, approval ledger,
          ▼                docs/evidence/
     VerifierAuthorityError

Every protected prefix is asserted **individually**. A guard proved only in
aggregate can quietly lose one entry without a single test turning red, and the
whole value of the guard is that a reviewer can enumerate what it defends.

The two escape routes an attacker actually uses -- a symlink whose target is
inside a protected tree, and a ``..`` chain -- are tested against the resolved
real path, because judging the spelling is the bypass.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from retrace_contracts import VerifierAuthorityError
from retrace_domain import (
    PROTECTED_PREFIXES,
    REFERENCE_DIRECTORY_NAMES,
    AuthorityRule,
    RepairAuthority,
    WriteRefused,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A repository-shaped tree with every protected area really present.

    The protected areas exist on disk so that a symlink can genuinely point
    into one; a test that linked to a non-existent directory would prove
    nothing about resolution.
    """
    for prefix in PROTECTED_PREFIXES:
        (tmp_path / prefix).mkdir(parents=True, exist_ok=True)
    (tmp_path / "scratch" / "candidate-0001").mkdir(parents=True)
    return tmp_path


@pytest.fixture
def authority(workspace: Path) -> RepairAuthority:
    """A guard rooted at the workspace with one granted scratch directory."""
    return RepairAuthority(
        repo_root=workspace,
        scratch_dirs=(workspace / "scratch" / "candidate-0001",),
        ledger_path=workspace / "build" / "approvals.jsonl",
    )


# ---------------------------------------------------------------------------
# What the guard permits. Without this, every refusal below could be a guard
# that refuses everything, which would also be useless.
# ---------------------------------------------------------------------------


def test_a_write_inside_the_granted_scratch_is_permitted(
    authority: RepairAuthority, workspace: Path
) -> None:
    """RX-07: the candidate scratch directory is the one writable area."""
    target = workspace / "scratch" / "candidate-0001" / "analysis" / "load.py"
    assert authority.assert_writable(target) == target.resolve()
    assert authority.is_writable(target)


def test_the_scratch_directory_itself_is_permitted(
    authority: RepairAuthority, workspace: Path
) -> None:
    """RX-07: containment includes the granted root, not only its children."""
    assert authority.is_writable(workspace / "scratch" / "candidate-0001")


# ---------------------------------------------------------------------------
# Negative controls: each protected prefix, individually.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", PROTECTED_PREFIXES)
def test_each_protected_prefix_is_refused_individually(
    authority: RepairAuthority, workspace: Path, prefix: str
) -> None:
    """NEGATIVE CONTROL, RX-07: one assertion per protected area."""
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(workspace / prefix / "injected.py")
    assert caught.value.rule is AuthorityRule.PROTECTED_PREFIX
    assert caught.value.protected_prefix == prefix


@pytest.mark.parametrize("prefix", PROTECTED_PREFIXES)
def test_each_protected_prefix_is_refused_when_declared_relatively(
    authority: RepairAuthority, prefix: str
) -> None:
    """NEGATIVE CONTROL, RX-07: the textual prefix route refuses too.

    A relative path is interpreted against the repository root, never the
    process working directory, so the verdict does not depend on where the
    worker was invoked from.
    """
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(f"{prefix}injected.py")
    assert caught.value.rule is AuthorityRule.PROTECTED_PREFIX


@pytest.mark.parametrize("prefix", PROTECTED_PREFIXES)
def test_each_protected_directory_itself_is_refused(
    authority: RepairAuthority, workspace: Path, prefix: str
) -> None:
    """NEGATIVE CONTROL, RX-07: the directory, not only files beneath it."""
    with pytest.raises(WriteRefused):
        authority.assert_writable(workspace / prefix.rstrip("/"))


def test_the_default_prefixes_cover_the_four_named_areas() -> None:
    """RX-07 names contracts, verifier code, reference outputs and approvals."""
    assert "packages/contracts/" in PROTECTED_PREFIXES
    assert "services/verifier/" in PROTECTED_PREFIXES
    assert "docs/evidence/" in PROTECTED_PREFIXES
    assert REFERENCE_DIRECTORY_NAMES == frozenset({"references", "reference_outputs"})


# ---------------------------------------------------------------------------
# Negative controls: the escape routes.
# ---------------------------------------------------------------------------


def test_a_symlink_into_a_protected_tree_is_refused(
    authority: RepairAuthority, workspace: Path
) -> None:
    """NEGATIVE CONTROL, RX-07: resolution happens before the decision.

    The declared path looks entirely local -- it is inside the granted scratch
    directory. Only its real path is protected.
    """
    scratch = workspace / "scratch" / "candidate-0001"
    (scratch / "innocent").symlink_to(workspace / "packages" / "contracts", True)
    declared = scratch / "innocent" / "result_contract.py"
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(declared)
    assert caught.value.rule is AuthorityRule.PROTECTED_PREFIX
    assert caught.value.protected_prefix == "packages/contracts/"
    assert caught.value.resolved_target is not None
    assert "packages/contracts" in caught.value.resolved_target


def test_a_symlink_into_the_verifier_tree_is_refused(
    authority: RepairAuthority, workspace: Path
) -> None:
    """NEGATIVE CONTROL, RX-07, RX-09: the independent judge's code is unreachable."""
    scratch = workspace / "scratch" / "candidate-0001"
    (scratch / "helper").symlink_to(workspace / "services" / "verifier", True)
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(scratch / "helper" / "compare.py")
    assert caught.value.protected_prefix == "services/verifier/"


def test_a_traversal_chain_into_a_protected_tree_is_refused(
    authority: RepairAuthority, workspace: Path
) -> None:
    """NEGATIVE CONTROL, RX-07: ``..`` is collapsed before the decision."""
    scratch = workspace / "scratch" / "candidate-0001"
    declared = scratch / ".." / ".." / "packages" / "contracts" / "approval.py"
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(declared)
    assert caught.value.rule is AuthorityRule.PROTECTED_PREFIX


def test_a_traversal_chain_out_of_the_scratch_is_refused(
    authority: RepairAuthority, workspace: Path
) -> None:
    """NEGATIVE CONTROL, RX-07: deny-by-default catches what no prefix names."""
    scratch = workspace / "scratch" / "candidate-0001"
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(scratch / ".." / ".." / "unlisted.txt")
    assert caught.value.rule is AuthorityRule.OUTSIDE_GRANTED_SCRATCH


def test_a_symlink_out_of_the_scratch_is_refused(
    authority: RepairAuthority, workspace: Path
) -> None:
    """NEGATIVE CONTROL, RX-07: an unprotected-but-ungranted target is still refused."""
    elsewhere = workspace.parent / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    scratch = workspace / "scratch" / "candidate-0001"
    (scratch / "away").symlink_to(elsewhere, True)
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(scratch / "away" / "note.txt")
    assert caught.value.rule is AuthorityRule.OUTSIDE_GRANTED_SCRATCH


@pytest.mark.parametrize("name", sorted(REFERENCE_DIRECTORY_NAMES))
def test_a_reference_output_directory_is_refused_anywhere(
    authority: RepairAuthority, workspace: Path, name: str
) -> None:
    """NEGATIVE CONTROL, RX-07: reference outputs are the scientific baseline.

    Refused by directory name wherever it appears -- including *inside* the
    granted scratch directory, which is the case a prefix list would miss.
    """
    target = workspace / "scratch" / "candidate-0001" / name / "expected.csv"
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(target)
    assert caught.value.rule is AuthorityRule.REFERENCE_OUTPUT_DIRECTORY


def test_the_approval_ledger_file_is_refused(
    authority: RepairAuthority, workspace: Path
) -> None:
    """NEGATIVE CONTROL, RX-07, RX-52: the ledger is append-only through its own class."""
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(workspace / "build" / "approvals.jsonl")
    assert caught.value.rule is AuthorityRule.APPROVAL_LEDGER


def test_nothing_is_writable_before_a_scratch_is_granted(workspace: Path) -> None:
    """NEGATIVE CONTROL, RX-07: the guard fails closed by default."""
    bare = RepairAuthority(repo_root=workspace)
    with pytest.raises(WriteRefused) as caught:
        bare.assert_writable(workspace / "scratch" / "candidate-0001" / "load.py")
    assert caught.value.rule is AuthorityRule.NO_SCRATCH_GRANTED
    assert bare.granted_scratch_dirs == ()


@pytest.mark.parametrize("prefix", PROTECTED_PREFIXES)
def test_granting_a_scratch_inside_a_protected_tree_is_refused(
    workspace: Path, prefix: str
) -> None:
    """NEGATIVE CONTROL, RX-07: the guard cannot be disarmed by granting its own target.

    This is the simplest possible bypass -- ask for write access to the
    protected area -- so the grant is checked by the same rules as a write.
    """
    guard = RepairAuthority(repo_root=workspace)
    with pytest.raises(WriteRefused) as caught:
        guard.grant_scratch(workspace / prefix / "candidate")
    assert caught.value.rule is AuthorityRule.PROTECTED_PREFIX
    assert guard.granted_scratch_dirs == ()


def test_granting_a_scratch_through_a_symlink_into_a_protected_tree_is_refused(
    workspace: Path,
) -> None:
    """NEGATIVE CONTROL, RX-07: a grant resolves its path too."""
    guard = RepairAuthority(repo_root=workspace)
    link = workspace / "scratch" / "looks-fine"
    link.symlink_to(workspace / "specs" / "schemas", True)
    with pytest.raises(WriteRefused):
        guard.grant_scratch(link)


@pytest.mark.parametrize("candidate", ["", "   ", "scratch/\x00name"])
def test_a_malformed_path_is_refused(authority: RepairAuthority, candidate: str) -> None:
    """NEGATIVE CONTROL, RX-07: an empty or NUL-bearing path never reaches the filesystem."""
    with pytest.raises(WriteRefused) as caught:
        authority.assert_writable(candidate)
    assert caught.value.rule is AuthorityRule.UNSAFE_PATH


def test_refusal_is_a_contract_layer_authority_error(
    authority: RepairAuthority, workspace: Path
) -> None:
    """RX-07: the refusal keeps the contract layer's type, so callers catch one thing."""
    with pytest.raises(VerifierAuthorityError) as caught:
        authority.assert_writable(workspace / "packages" / "contracts" / "base.py")
    assert isinstance(caught.value, WriteRefused)
    assert caught.value.actor == "repair-worker"
    assert caught.value.action == "write"


def test_a_sibling_directory_sharing_a_prefix_string_is_not_protected(
    workspace: Path,
) -> None:
    """A guard must refuse the right things: ``tests/contracts-draft/`` is not protected.

    Containment is decided with path semantics, not string prefixing, so a
    directory whose *name* starts with a protected directory's name is judged
    on its own.
    """
    scratch = workspace / "tests" / "contracts-draft"
    scratch.mkdir(parents=True)
    guard = RepairAuthority(repo_root=workspace, scratch_dirs=(scratch,))
    assert guard.is_writable(scratch / "note.txt")


def test_a_reference_named_ancestor_above_the_repository_does_not_refuse_everything(
    tmp_path: Path,
) -> None:
    """A guard must refuse the right things: scope matters, not raw path segments.

    A repository checked out beneath a directory called ``references`` is a
    plausible accident. If the reference-output rule scanned every absolute
    segment, that repository would refuse every write -- and a guard that
    refuses everything is a guard the next person removes. The rule is scoped
    to the path below the repository root or a granted scratch directory, and
    the refusal inside that scope is asserted here too so the fix cannot have
    simply disabled the rule.
    """
    repo = tmp_path / "references" / "retrace-ai"
    scratch = repo / "scratch" / "candidate-0001"
    scratch.mkdir(parents=True)
    guard = RepairAuthority(repo_root=repo, scratch_dirs=(scratch,))

    assert guard.is_writable(scratch / "analysis" / "load.py")
    with pytest.raises(WriteRefused) as caught:
        guard.assert_writable(scratch / "references" / "expected.csv")
    assert caught.value.rule is AuthorityRule.REFERENCE_OUTPUT_DIRECTORY

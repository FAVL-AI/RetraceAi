"""Snapshots: reproducible digests and an untrusted source tree (RX-01, RX-02).

The digest tests state the property RX-01 asks for directly -- same tree, same
digest; one byte different, different digest -- and the refusal tests prove the
walk cannot be walked out of its root.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from domain_support import SEMICOLON_CSV, corrupt_blob, write_tree
from retrace_contracts import SnapshotIntegrityError, sha256_hex
from retrace_domain import (
    ContentAddressedStore,
    PathRefusalRule,
    SnapshotManifest,
    UnsafeSourcePath,
    snapshot_create,
    snapshot_materialise,
    store_reader,
)

TREE = {
    "analysis/load.py": "import pandas as pd\n",
    "inputs/data/measurements.csv": SEMICOLON_CSV,
    "notes/README.md": "SYNTHETIC fixture tree.\n",
}


def test_manifest_maps_every_file_to_its_digest(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-01: one entry per file, each entry the file's own SHA-256."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    assert dict(manifest.files) == {
        path: sha256_hex(text.encode("utf-8")) for path, text in TREE.items()
    }


def test_same_tree_twice_gives_the_same_manifest_digest(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-01: the digest is a function of content, not of walk order or time."""
    first = snapshot_create(store, write_tree(tmp_path / "a", TREE))
    second = snapshot_create(store, write_tree(tmp_path / "b", TREE))
    assert first.manifest_digest == second.manifest_digest


def test_one_changed_byte_changes_the_manifest_digest(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-01: a mutated tree cannot present the previous identity."""
    mutated = dict(TREE)
    mutated["notes/README.md"] = "SYNTHETIC fixture tree?\n"
    first = snapshot_create(store, write_tree(tmp_path / "a", TREE))
    second = snapshot_create(store, write_tree(tmp_path / "b", mutated))
    assert first.manifest_digest != second.manifest_digest


def test_a_renamed_file_changes_the_manifest_digest(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-01: the digest covers paths as well as bytes."""
    renamed = {("notes/READNE.md" if path == "notes/README.md" else path): text
               for path, text in TREE.items()}
    first = snapshot_create(store, write_tree(tmp_path / "a", TREE))
    second = snapshot_create(store, write_tree(tmp_path / "b", renamed))
    assert first.manifest_digest != second.manifest_digest


def test_manifest_entries_are_sorted(store: ContentAddressedStore, tmp_path: Path) -> None:
    """RX-01: canonical order is structural, not a convention of the writer."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    assert list(manifest.paths) == sorted(TREE)


def test_exclusion_prunes_paths_and_changes_the_digest(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-01: an excluded file is absent from the manifest, visibly."""
    root = write_tree(tmp_path / "t", {**TREE, ".git/config": "[core]\n"})
    full = snapshot_create(store, root)
    pruned = snapshot_create(store, root, exclude=(".git",))
    assert ".git/config" in full.files
    assert ".git/config" not in pruned.files
    assert full.manifest_digest != pruned.manifest_digest


def test_store_reader_returns_verified_bytes(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-02: a consumer reads through verification, never around it."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    read = store_reader(store, manifest)
    assert read("inputs/data/measurements.csv").decode("utf-8") == SEMICOLON_CSV


def test_store_reader_refuses_a_path_the_snapshot_does_not_declare(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-01: a reader cannot reach content outside the snapshot it was built for."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    with pytest.raises(KeyError):
        store_reader(store, manifest)("inputs/data/absent.csv")


def test_materialise_writes_the_tree_back(store: ContentAddressedStore, tmp_path: Path) -> None:
    """RX-01: a snapshot round-trips to a working directory."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    written = snapshot_materialise(store, manifest, tmp_path / "out")
    assert [path.relative_to(tmp_path / "out").as_posix() for path in written] == sorted(TREE)
    for relative, text in TREE.items():
        assert (tmp_path / "out" / relative).read_text(encoding="utf-8") == text


def test_materialised_tree_reproduces_the_same_digest(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """RX-01, RX-16: the round-trip is identity, which is what a rerun depends on."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    snapshot_materialise(store, manifest, tmp_path / "out")
    again = snapshot_create(
        ContentAddressedStore(tmp_path / "store2"), tmp_path / "out"
    )
    assert again.manifest_digest == manifest.manifest_digest


def test_materialise_refuses_to_clobber_an_existing_file(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """A researcher's working file is never silently overwritten."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    snapshot_materialise(store, manifest, tmp_path / "out")
    with pytest.raises(UnsafeSourcePath) as caught:
        snapshot_materialise(store, manifest, tmp_path / "out")
    assert caught.value.rule is PathRefusalRule.DESTINATION_OCCUPIED


# ---------------------------------------------------------------------------
# Negative controls: the source tree and the manifest are untrusted input.
# ---------------------------------------------------------------------------


def test_symlink_escaping_the_root_is_refused(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL, RX-01: a file symlink out of the root is refused."""
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the snapshot\n", encoding="utf-8")
    root = write_tree(tmp_path / "t", TREE)
    (root / "analysis" / "leak.txt").symlink_to(outside)
    with pytest.raises(UnsafeSourcePath) as caught:
        snapshot_create(store, root)
    assert caught.value.rule is PathRefusalRule.SYMLINK_ESCAPE


def test_symlink_escaping_through_a_traversal_chain_is_refused(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL, RX-01: a ``..`` chain inside the link target is resolved first."""
    outside = tmp_path / "outside.txt"
    outside.write_text("not part of the snapshot\n", encoding="utf-8")
    root = write_tree(tmp_path / "t", TREE)
    (root / "analysis" / "leak.txt").symlink_to(Path("../../outside.txt"))
    with pytest.raises(UnsafeSourcePath) as caught:
        snapshot_create(store, root)
    assert caught.value.rule is PathRefusalRule.SYMLINK_ESCAPE


def test_directory_symlink_is_refused_rather_than_skipped(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL, RX-01: silently omitting a directory is not an option.

    Skipping it would produce a manifest that claims to describe the whole tree
    while omitting part of it, which is worse than a refusal.
    """
    elsewhere = write_tree(tmp_path / "elsewhere", {"secret.csv": "a;b\n"})
    root = write_tree(tmp_path / "t", TREE)
    (root / "linked").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(UnsafeSourcePath) as caught:
        snapshot_create(store, root)
    assert caught.value.rule is PathRefusalRule.SYMLINK_DIRECTORY


def test_broken_symlink_is_refused(store: ContentAddressedStore, tmp_path: Path) -> None:
    """NEGATIVE CONTROL, RX-01: a dangling link is not an empty file."""
    root = write_tree(tmp_path / "t", TREE)
    (root / "analysis" / "gone.csv").symlink_to(tmp_path / "never-existed.csv")
    with pytest.raises(UnsafeSourcePath) as caught:
        snapshot_create(store, root)
    assert caught.value.rule is PathRefusalRule.SYMLINK_BROKEN


def test_fifo_is_refused_as_a_non_regular_file(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL, RX-01: a snapshot stores files, not devices or pipes."""
    root = write_tree(tmp_path / "t", TREE)
    os.mkfifo(root / "analysis" / "pipe")
    with pytest.raises(UnsafeSourcePath) as caught:
        snapshot_create(store, root)
    assert caught.value.rule is PathRefusalRule.NON_REGULAR_FILE


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("../escape.txt", PathRefusalRule.TRAVERSAL),
        ("analysis/../../escape.txt", PathRefusalRule.TRAVERSAL),
        ("/etc/passwd", PathRefusalRule.ABSOLUTE_PATH),
        ("analysis\\load.py", PathRefusalRule.UNSAFE_RELATIVE_PATH),
        ("analysis/", PathRefusalRule.UNSAFE_RELATIVE_PATH),
    ],
)
def test_manifest_refuses_an_unsafe_path(path: str, rule: PathRefusalRule) -> None:
    """NEGATIVE CONTROL, RX-01: a manifest from an imported bundle is untrusted.

    This is the ``..`` route for the snapshot layer: a crafted manifest is how
    traversal arrives, because a filesystem walk never produces a ``..``
    segment itself.
    """
    with pytest.raises(UnsafeSourcePath) as caught:
        SnapshotManifest(entries=((path, sha256_hex(b"x")),))
    assert caught.value.rule is rule


def test_manifest_refuses_unsorted_entries() -> None:
    """NEGATIVE CONTROL, RX-01: order cannot vary, or the digest is not canonical."""
    with pytest.raises(ValueError, match="sorted by path"):
        SnapshotManifest(entries=(("b.txt", sha256_hex(b"b")), ("a.txt", sha256_hex(b"a"))))


def test_manifest_refuses_a_duplicate_path() -> None:
    """NEGATIVE CONTROL, RX-01: one path cannot carry two digests."""
    with pytest.raises(ValueError, match="more than once"):
        SnapshotManifest(entries=(("a.txt", sha256_hex(b"a")), ("a.txt", sha256_hex(b"b"))))


def test_manifest_refuses_a_malformed_digest() -> None:
    """NEGATIVE CONTROL, RX-01: a digest that nothing could have produced is refused."""
    with pytest.raises(ValueError, match="lowercase hex SHA-256"):
        SnapshotManifest(entries=(("a.txt", "not-a-digest"),))


def test_materialise_detects_a_corrupted_blob(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL, RX-02: a tampered store cannot write out silently wrong science."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    corrupt_blob(store, manifest.digest_for("notes/README.md"), b"tampered\n")
    with pytest.raises(SnapshotIntegrityError):
        snapshot_materialise(store, manifest, tmp_path / "out")


def test_materialise_refuses_a_destination_escape_through_a_symlink(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL, RX-01: a symlinked destination subdirectory cannot redirect a write."""
    manifest = snapshot_create(store, write_tree(tmp_path / "t", TREE))
    destination = tmp_path / "out"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (destination / "notes").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnsafeSourcePath) as caught:
        snapshot_materialise(store, manifest, destination)
    assert caught.value.rule is PathRefusalRule.DESTINATION_ESCAPE
    assert not (outside / "README.md").exists(), "the write must not have landed outside"

"""Content-addressed store: immutability and tamper evidence (RX-01, RX-02).

Every positive property here has a negative control next to it. A store that
has never been shown to *detect* corruption is a store whose verification has
never been exercised, and an unexercised check is not evidence.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from conftest import corrupt_blob
from retrace_contracts import SnapshotIntegrityError, sha256_hex
from retrace_domain import BLOB_MODE, ContentAddressedStore, hash_file, is_sha256_hex

PAYLOAD = b"specimen_id;mass_g\nS-001;3750\n"
OTHER = b"specimen_id;mass_g\nS-001;9999\n"


def test_put_bytes_returns_the_sha256_of_the_content(store: ContentAddressedStore) -> None:
    """RX-01: identity is the content digest, computed the standard way."""
    assert store.put_bytes(PAYLOAD) == sha256_hex(PAYLOAD)


def test_put_bytes_is_idempotent_for_identical_content(store: ContentAddressedStore) -> None:
    """RX-01: re-putting identical bytes is a no-op returning the same digest."""
    first = store.put_bytes(PAYLOAD)
    before = store.path_for(first).stat()
    second = store.put_bytes(PAYLOAD)
    after = store.path_for(first).stat()
    assert first == second
    assert (before.st_ino, before.st_mtime_ns) == (after.st_ino, after.st_mtime_ns), (
        "an idempotent put must not rewrite the blob"
    )


def test_distinct_content_gets_distinct_digests(store: ContentAddressedStore) -> None:
    """RX-01: one changed byte changes the identity."""
    assert store.put_bytes(PAYLOAD) != store.put_bytes(OTHER)


def test_blob_is_written_read_only(store: ContentAddressedStore) -> None:
    """RX-01: stored bytes are not casually editable."""
    mode = stat.S_IMODE(store.path_for(store.put_bytes(PAYLOAD)).stat().st_mode)
    assert mode == BLOB_MODE


def test_path_is_sharded_under_the_blobs_root(store: ContentAddressedStore) -> None:
    """RX-01: the layout is a pure function of the digest."""
    value = store.put_bytes(PAYLOAD)
    relative = store.path_for(value).relative_to(store.blobs_root)
    assert relative.parts == (value[0:2], value[2:4], value)


def test_put_file_matches_put_bytes(store: ContentAddressedStore, tmp_path: Path) -> None:
    """RX-01: the streaming path and the in-memory path agree."""
    source = tmp_path / "input.csv"
    source.write_bytes(PAYLOAD)
    assert store.put_file(source) == store.put_bytes(PAYLOAD)


def test_hash_file_reports_digest_and_size(tmp_path: Path) -> None:
    """RX-01: size is returned with the digest, from one read."""
    source = tmp_path / "input.csv"
    source.write_bytes(PAYLOAD)
    assert hash_file(source) == (sha256_hex(PAYLOAD), len(PAYLOAD))


def test_get_bytes_round_trips(store: ContentAddressedStore) -> None:
    """RX-01: what goes in comes back out."""
    assert store.get_bytes(store.put_bytes(PAYLOAD)) == PAYLOAD


def test_read_does_not_depend_on_mtime(store: ContentAddressedStore) -> None:
    """RX-02: only content decides a read; metadata is not consulted."""
    value = store.put_bytes(PAYLOAD)
    path = store.path_for(value)
    os.utime(path, (0, 0))
    assert store.get_bytes(value) == PAYLOAD
    assert store.verify(value) == value


def test_read_does_not_depend_on_the_path(store: ContentAddressedStore, tmp_path: Path) -> None:
    """RX-02: two stores holding the same bytes answer identically.

    The second store is at a different absolute path with a different
    directory mtime, so a read that silently depended on location would differ.
    """
    other = ContentAddressedStore(tmp_path / "elsewhere")
    assert other.put_bytes(PAYLOAD) == store.put_bytes(PAYLOAD)
    assert other.get_bytes(other.put_bytes(PAYLOAD)) == store.get_bytes(store.put_bytes(PAYLOAD))


def test_verify_all_reports_every_digest(store: ContentAddressedStore) -> None:
    """RX-02: the sweep covers the whole store, in deterministic order."""
    digests = sorted({store.put_bytes(PAYLOAD), store.put_bytes(OTHER)})
    assert list(store.verify_all()) == digests


def test_missing_digest_raises_key_error(store: ContentAddressedStore) -> None:
    """A read for content that was never stored is not an empty success."""
    with pytest.raises(KeyError):
        store.get_bytes(sha256_hex(b"never stored"))


def test_put_bytes_refuses_text(store: ContentAddressedStore) -> None:
    """A digest must not depend on an implicit encoding."""
    with pytest.raises(TypeError):
        store.put_bytes("already text")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "candidate",
    ["", "zz", "A" * 64, sha256_hex(b"x").upper(), sha256_hex(b"x")[:63], "../../etc/passwd"],
)
def test_malformed_digest_is_refused_before_becoming_a_path(
    store: ContentAddressedStore, candidate: str
) -> None:
    """A digest is untrusted input: it selects a file, so it is validated first."""
    assert not is_sha256_hex(candidate)
    with pytest.raises(ValueError, match="lowercase hex SHA-256"):
        store.path_for(candidate)


# ---------------------------------------------------------------------------
# Negative controls. Each proves the store detects a specific hostile act.
# ---------------------------------------------------------------------------


def test_corrupting_a_stored_blob_is_detected_on_read(store: ContentAddressedStore) -> None:
    """NEGATIVE CONTROL, RX-02: a post-hoc edit to stored bytes is detected."""
    value = store.put_bytes(PAYLOAD)
    corrupt_blob(store, value, OTHER)
    with pytest.raises(SnapshotIntegrityError) as caught:
        store.get_bytes(value)
    assert caught.value.expected_sha256 == value
    assert caught.value.observed_sha256 == sha256_hex(OTHER)


def test_corrupting_a_stored_blob_is_detected_by_verify(store: ContentAddressedStore) -> None:
    """NEGATIVE CONTROL, RX-02: the explicit integrity check fails too."""
    value = store.put_bytes(PAYLOAD)
    corrupt_blob(store, value, OTHER)
    with pytest.raises(SnapshotIntegrityError):
        store.verify(value)


def test_corruption_is_detected_by_the_whole_store_sweep(store: ContentAddressedStore) -> None:
    """NEGATIVE CONTROL, RX-02: verify_all does not pass over a corrupt blob."""
    value = store.put_bytes(PAYLOAD)
    store.put_bytes(OTHER)
    corrupt_blob(store, value, b"")
    with pytest.raises(SnapshotIntegrityError):
        store.verify_all()


def test_overwriting_a_digest_with_different_bytes_is_refused(
    store: ContentAddressedStore,
) -> None:
    """NEGATIVE CONTROL, RX-01: a put never rewrites a blob that disagrees.

    The only way the bytes under a digest can differ from the incoming bytes is
    that the store is already corrupt. Rewriting would destroy the evidence, so
    the put raises instead -- and the corrupt bytes are still there afterwards.
    """
    value = store.put_bytes(PAYLOAD)
    corrupt_blob(store, value, OTHER)
    with pytest.raises(SnapshotIntegrityError, match="refusing to overwrite"):
        store.put_bytes(PAYLOAD)
    assert store.path_for(value).read_bytes() == OTHER, (
        "the refused put must not have repaired the blob, which would hide the corruption"
    )


def test_overwriting_a_digest_with_different_bytes_is_refused_for_files(
    store: ContentAddressedStore, tmp_path: Path
) -> None:
    """NEGATIVE CONTROL, RX-01: the streaming put applies the same refusal."""
    source = tmp_path / "input.csv"
    source.write_bytes(PAYLOAD)
    value = store.put_file(source)
    corrupt_blob(store, value, OTHER)
    with pytest.raises(SnapshotIntegrityError, match="refusing to overwrite"):
        store.put_file(source)

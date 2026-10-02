"""The canonical form that makes contract hashes meaningful (RX-03).

"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone

import pytest
from retrace_contracts import (
    CanonicalisationError,
    canonical_digest,
    canonical_json,
    canonical_timestamp,
    canonicalise,
    sha256_hex,
)


def test_canonical_json_is_the_documented_literal_form() -> None:
    """RX-03: the canonical document is exactly as specified, byte for byte.

    The expected string is derived from the documented rules (sorted keys,
    compact separators, explicit null, form version and type tag), not copied
    from an implementation run.
    """
    rendered = canonical_json({"b": 1, "a": None}, type_tag="retrace.Test")
    assert rendered == '{"@canonical_form":1,"@type":"retrace.Test","payload":{"a":null,"b":1}}'


def test_sha256_hex_agrees_with_hashlib() -> None:
    """RX-03: the digest primitive is plain SHA-256, verified against hashlib."""
    assert sha256_hex(b"retrace") == hashlib.sha256(b"retrace").hexdigest()


def test_mapping_key_order_is_not_semantic() -> None:
    """RX-03: two mappings differing only in insertion order hash equal."""
    first = canonical_digest({"a": 1, "b": 2}, type_tag="t")
    second = canonical_digest({"b": 2, "a": 1}, type_tag="t")
    assert first == second


def test_sequence_order_is_semantic() -> None:
    """RX-03 negative control: reordering a list changes the digest.

    Sequence order is authored information (reference inputs, known limits), so
    it must not be normalised away.
    """
    first = canonical_digest({"items": ["x", "y"]}, type_tag="t")
    second = canonical_digest({"items": ["y", "x"]}, type_tag="t")
    assert first != second


def test_set_order_is_not_semantic() -> None:
    """RX-03: set membership carries no order, so order is removed."""
    first = canonical_digest({"items": {"x", "y"}}, type_tag="t")
    second = canonical_digest({"items": {"y", "x"}}, type_tag="t")
    assert first == second


def test_explicit_null_is_retained_not_dropped() -> None:
    """RX-03: an explicitly null field is serialised, so it cannot be elided."""
    assert '"a":null' in canonical_json({"a": None}, type_tag="t")
    assert canonical_digest({"a": None}, type_tag="t") != canonical_digest({}, type_tag="t")


def test_type_tag_provides_domain_separation() -> None:
    """RX-03 negative control: identical payloads under different tags differ."""
    payload = {"value": 1}
    assert canonical_digest(payload, type_tag="retrace.A") != canonical_digest(
        payload, type_tag="retrace.B"
    )


def test_empty_type_tag_is_refused() -> None:
    """RX-03: a canonical document without domain separation is not produced."""
    with pytest.raises(CanonicalisationError):
        canonical_json({"a": 1}, type_tag="")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_have_no_canonical_form(value: float) -> None:
    """RX-03: NaN/Inf are refused rather than emitted as invalid JSON."""
    with pytest.raises(CanonicalisationError):
        canonical_json({"tolerance": value}, type_tag="t")


def test_naive_datetime_is_refused() -> None:
    """RX-03/RX-31: a datetime with no zone has no determinate instant."""
    with pytest.raises(CanonicalisationError):
        canonical_timestamp(datetime(2026, 10, 2, 9, 0, 0))


def test_equal_instants_in_different_zones_canonicalise_identically() -> None:
    """RX-03/RX-31: the same instant renders identically whatever the offset."""
    utc = datetime(2026, 10, 2, 9, 0, 0, tzinfo=UTC)
    plus_two = datetime(2026, 10, 2, 11, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    assert canonical_timestamp(utc) == canonical_timestamp(plus_two)
    assert canonical_timestamp(utc) == "2026-10-02T09:00:00.000000Z"


def test_microsecond_padding_is_fixed_width() -> None:
    """RX-03: a zero-microsecond instant and its padded form are one string."""
    moment = datetime(2026, 10, 2, 9, 0, 0, 1, tzinfo=UTC)
    assert canonical_timestamp(moment) == "2026-10-02T09:00:00.000001Z"


def test_bytes_are_refused() -> None:
    """RX-03: raw bytes must be digested by the caller, not guessed at here."""
    with pytest.raises(CanonicalisationError):
        canonicalise({"blob": b"\x00\x01"})


def test_non_string_mapping_key_is_refused() -> None:
    """RX-03: a non-string key has no canonical JSON form."""
    with pytest.raises(CanonicalisationError):
        canonicalise({1: "one"})


def test_unsupported_type_is_refused_not_stringified() -> None:
    """RX-03 negative control: an unknown object does not silently become repr()."""

    class Opaque:
        pass

    with pytest.raises(CanonicalisationError):
        canonicalise({"thing": Opaque()})


def test_decimal_precision_is_preserved_as_declared() -> None:
    """RX-03: 1.10 and 1.1 are different declarations of precision."""
    from decimal import Decimal

    assert canonical_digest({"v": Decimal("1.10")}, type_tag="t") != canonical_digest(
        {"v": Decimal("1.1")}, type_tag="t"
    )


def test_digest_is_stable_across_repeated_calls() -> None:
    """RX-03: the digest is a pure function of the payload."""
    payload = {"a": [1, 2, {"b": None}], "c": "text"}
    assert canonical_digest(payload, type_tag="t") == canonical_digest(payload, type_tag="t")

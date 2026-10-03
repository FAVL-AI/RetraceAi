"""The governed model route (RX-06, RX-40, PRECHECK B6).

Scope of this file, stated plainly
----------------------------------
PRECHECK B6 records that no model-provider credential and no execution budget
exist on this host. Nothing here contacts any provider, and **no test in this
file is evidence that the governed route works end to end**. What is tested is:

1. the configuration gate -- an unconfigured route raises
   :class:`ProviderNotConfigured` and produces nothing (the headline property);
2. this module's own response handling and restraint, exercised through an
   injected test double.

The test double is a stub that returns canned text. It demonstrates that *our*
parsing and *our* guard behave correctly on a given input. It demonstrates
nothing about any provider's behaviour, and it is not a mock success: the
assertions are about refusals and about diffs this package computes itself.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import SEMICOLON_CSV, WRONG_PATH_SOURCE, write_tree
from retrace_domain import (
    AbstentionReason,
    AuthorityRule,
    ContentAddressedStore,
    Diagnosis,
    FaultClass,
    GovernedModelRepairProvider,
    ModelRepairRequest,
    ModelTransport,
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
from retrace_domain.errors import ProviderNotConfigured
from retrace_domain.providers.governed import MAX_RESPONSE_BYTES

Snapshot = tuple[SnapshotManifest, SnapshotReader]
TARGET = "analysis/load.py"

CONFIGURED = {
    "credential": "stub-credential-value",
    "model_id": "model-v1",
    "endpoint": "https://governed.invalid/v1",
}

REPAIRED_SOURCE = WRONG_PATH_SOURCE.replace(
    '"data/measurements.csv"', '"inputs/data/measurements.csv"'
)
RESEEDED_SOURCE = WRONG_PATH_SOURCE.replace(
    '    return pd.read_csv("data/measurements.csv", sep=";")',
    '    return pd.read_csv("inputs/data/measurements.csv", sep=";").sample(random_state=1)',
)


class StubTransport:
    """Test double returning canned text, and recording the requests it received.

    Exists to exercise this package's response handling and restraint. It is
    not a provider, it does not model one, and a passing test using it says
    nothing about any provider's output.
    """

    def __init__(self, reply: object) -> None:
        self._reply = reply
        self.requests: list[ModelRepairRequest] = []

    def complete(self, request: ModelRepairRequest) -> str:
        self.requests.append(request)
        return self._reply  # type: ignore[return-value]


@pytest.fixture
def build_snapshot(
    store: ContentAddressedStore, tmp_path: Path
) -> Callable[[dict[str, str]], Snapshot]:
    """Factory: write a SYNTHETIC tree, snapshot it, return its manifest and reader."""

    def build(files: dict[str, str]) -> Snapshot:
        manifest = snapshot_create(store, write_tree(tmp_path / "tree", files))
        return manifest, store_reader(store, manifest)

    return build


@pytest.fixture
def snapshot_with_fault(build_snapshot: Callable[[dict[str, str]], Snapshot]) -> Snapshot:
    """The standard SYNTHETIC fixture: a wrong input path, and the real input."""
    return build_snapshot(
        {TARGET: WRONG_PATH_SOURCE, "inputs/data/measurements.csv": SEMICOLON_CSV}
    )


def diagnose(fault_class: FaultClass = FaultClass.MISSING_INPUT_PATH) -> Diagnosis:
    """Build a diagnosis against the standard fixture target."""
    return Diagnosis(
        diagnosis_id="diag-0001",
        snapshot_id="snap-0001",
        target_path=TARGET,
        fault_class=fault_class,
        detail="the baseline run raised while loading its declared input",
    )


# ---------------------------------------------------------------------------
# The configuration gate. This is the property that holds on this host.
# ---------------------------------------------------------------------------


def test_an_unconfigured_route_raises_and_produces_nothing(
    snapshot_with_fault: Snapshot,
) -> None:
    """RX-40, PRECHECK B6: absence is reported, never simulated.

    This is the state of the governed route on this machine. The refusal names
    every missing field, so a status surface can say what is needed rather than
    only that something is.
    """
    provider = GovernedModelRepairProvider()
    manifest, reader = snapshot_with_fault

    assert not provider.is_configured
    with pytest.raises(ProviderNotConfigured) as caught:
        provider.propose(diagnose(), manifest, reader, None)

    assert caught.value.provider_id == "governed-model-route"
    assert caught.value.missing == ("credential", "model_id", "endpoint", "transport")
    assert provider.abstention_log == ()


@pytest.mark.parametrize(
    ("absent", "expected"),
    [
        ("credential", ("credential",)),
        ("model_id", ("model_id",)),
        ("endpoint", ("endpoint",)),
    ],
)
def test_each_missing_configuration_field_is_reported_individually(
    snapshot_with_fault: Snapshot, absent: str, expected: tuple[str, ...]
) -> None:
    """NEGATIVE CONTROL, RX-40: a partial configuration is not a configuration."""
    settings = {key: value for key, value in CONFIGURED.items() if key != absent}
    provider = GovernedModelRepairProvider(
        **settings, transport=StubTransport(REPAIRED_SOURCE)
    )
    manifest, reader = snapshot_with_fault
    with pytest.raises(ProviderNotConfigured) as caught:
        provider.propose(diagnose(), manifest, reader, None)
    assert caught.value.missing == expected


def test_a_missing_transport_is_reported(snapshot_with_fault: Snapshot) -> None:
    """NEGATIVE CONTROL: credentials without a transport cannot reach anything."""
    provider = GovernedModelRepairProvider(**CONFIGURED)
    manifest, reader = snapshot_with_fault
    with pytest.raises(ProviderNotConfigured) as caught:
        provider.propose(diagnose(), manifest, reader, None)
    assert caught.value.missing == ("transport",)


def test_the_route_satisfies_the_provider_protocol() -> None:
    """RX-06: both routes implement one interface, so a caller can hold either."""
    provider = GovernedModelRepairProvider()
    assert isinstance(provider, RepairProvider)
    assert isinstance(StubTransport("x"), ModelTransport)


def test_the_request_carries_no_credential() -> None:
    """A credential is configuration, never content: it cannot be in a request.

    Asserted on the dataclass's own field list, so adding a credential-shaped
    field later fails this test.
    """
    names = {field.name for field in dataclasses.fields(ModelRepairRequest)}
    assert names == {
        "diagnosis",
        "target_path",
        "target_source",
        "snapshot_paths",
        "instruction",
    }


# ---------------------------------------------------------------------------
# This module's own handling, exercised with the injected test double.
# ---------------------------------------------------------------------------


def test_the_diff_is_computed_here_from_the_snapshot_bytes(
    snapshot_with_fault: Snapshot,
) -> None:
    """RX-06: the reviewable patch is always ours, computed from preserved bytes.

    The stub returns file *content*; the diff a reviewer reads is produced by
    this package from the snapshot. A route therefore cannot hand over a
    misleading patch.
    """
    manifest, reader = snapshot_with_fault
    transport = StubTransport(REPAIRED_SOURCE)
    provider = GovernedModelRepairProvider(**CONFIGURED, transport=transport)

    proposal = provider.propose(diagnose(), manifest, reader, None)

    assert proposal is not None
    assert proposal.provider == "governed-model-route"
    assert proposal.unified_diff == build_unified_diff(TARGET, WRONG_PATH_SOURCE, REPAIRED_SOURCE)
    assert proposal.candidate_hash == candidate_digest(
        manifest, TARGET, REPAIRED_SOURCE.encode("utf-8")
    )
    assert len(transport.requests) == 1
    assert transport.requests[0].target_source == WRONG_PATH_SOURCE
    assert transport.requests[0].snapshot_paths == manifest.paths


def test_the_instruction_states_the_restraint_rules(snapshot_with_fault: Snapshot) -> None:
    """RX-14: a route is told the rule as well as held to it."""
    manifest, reader = snapshot_with_fault
    transport = StubTransport(REPAIRED_SOURCE)
    GovernedModelRepairProvider(**CONFIGURED, transport=transport).propose(
        diagnose(), manifest, reader, None
    )
    instruction = transport.requests[0].instruction
    for phrase in ("exclusion rule", "random seed", "train/test split", "row filter"):
        assert phrase in instruction


def test_returned_content_that_changes_a_seed_is_refused(
    snapshot_with_fault: Snapshot,
) -> None:
    """NEGATIVE CONTROL, RX-14: a model proposal is not privileged evidence.

    The returned content fixes the path *and* adds a seeded sample. The path
    fix alone would have been accepted; the whole proposal is refused, because
    the patch would change what the analysis measures.
    """
    manifest, reader = snapshot_with_fault
    provider = GovernedModelRepairProvider(
        **CONFIGURED, transport=StubTransport(RESEEDED_SOURCE)
    )

    assert provider.propose(diagnose(), manifest, reader, None) is None

    recorded = provider.abstention_log[-1]
    assert recorded.reason is AbstentionReason.RANDOM_SEED
    assert recorded.is_scientific_restraint


def test_a_meaning_changing_fault_class_is_refused_without_calling_the_route(
    snapshot_with_fault: Snapshot,
) -> None:
    """NEGATIVE CONTROL, RX-14, RX-35: no request is made for a refused question.

    Asserted on the transport's call log, because "we would not have used the
    answer" is not the same as not asking -- asking spends budget and sends
    the snapshot's source off the host.
    """
    manifest, reader = snapshot_with_fault
    transport = StubTransport(REPAIRED_SOURCE)
    provider = GovernedModelRepairProvider(**CONFIGURED, transport=transport)

    refused = diagnose(FaultClass.RANDOM_SEED_CHANGED)
    assert provider.propose(refused, manifest, reader, None) is None

    assert transport.requests == []
    assert provider.abstention_log[-1].reason is AbstentionReason.RANDOM_SEED


@pytest.mark.parametrize(
    "reply",
    ["", "   \n  ", "x" * (MAX_RESPONSE_BYTES + 1), 42, None, b"bytes are not text"],
)
def test_an_unusable_response_is_refused(snapshot_with_fault: Snapshot, reply: object) -> None:
    """NEGATIVE CONTROL, RX-10: a response is untrusted input of unknown shape."""
    manifest, reader = snapshot_with_fault
    provider = GovernedModelRepairProvider(**CONFIGURED, transport=StubTransport(reply))
    assert provider.propose(diagnose(), manifest, reader, None) is None
    assert provider.abstention_log[-1].reason is AbstentionReason.PROVIDER_RESPONSE_UNUSABLE


def test_an_unchanged_response_is_not_an_empty_patch(snapshot_with_fault: Snapshot) -> None:
    """NEGATIVE CONTROL, RX-06: there is no such thing as a proposal with no change."""
    manifest, reader = snapshot_with_fault
    provider = GovernedModelRepairProvider(
        **CONFIGURED, transport=StubTransport(WRONG_PATH_SOURCE)
    )
    assert provider.propose(diagnose(), manifest, reader, None) is None
    assert provider.abstention_log[-1].reason is AbstentionReason.DIFF_WOULD_BE_EMPTY


def test_a_target_outside_the_snapshot_is_refused(
    build_snapshot: Callable[[dict[str, str]], Snapshot],
) -> None:
    """NEGATIVE CONTROL, RX-01: the route cannot propose against unpreserved content."""
    manifest, reader = build_snapshot({"analysis/other.py": "import pandas as pd\n"})
    provider = GovernedModelRepairProvider(
        **CONFIGURED, transport=StubTransport(REPAIRED_SOURCE)
    )
    assert provider.propose(diagnose(), manifest, reader, None) is None
    assert provider.abstention_log[-1].reason is AbstentionReason.TARGET_NOT_IN_SNAPSHOT


# ---------------------------------------------------------------------------
# Writes go through the same guard as every other route (RX-07).
# ---------------------------------------------------------------------------


def test_the_candidate_is_written_through_the_authority_guard(
    snapshot_with_fault: Snapshot, tmp_path: Path
) -> None:
    """RX-07: one guard for every route, not one guard per route."""
    scratch = tmp_path / "scratch" / "candidate-0002"
    scratch.mkdir(parents=True)
    authority = RepairAuthority(repo_root=tmp_path, scratch_dirs=(scratch,))
    provider = GovernedModelRepairProvider(
        **CONFIGURED, transport=StubTransport(REPAIRED_SOURCE), authority=authority
    )
    manifest, reader = snapshot_with_fault

    proposal = provider.propose(diagnose(), manifest, reader, scratch)

    assert proposal is not None
    assert (scratch / TARGET).read_text(encoding="utf-8") == REPAIRED_SOURCE


def test_an_unguarded_write_is_refused(snapshot_with_fault: Snapshot, tmp_path: Path) -> None:
    """NEGATIVE CONTROL, RX-07: the governed route gets no exemption."""
    manifest, reader = snapshot_with_fault
    provider = GovernedModelRepairProvider(
        **CONFIGURED, transport=StubTransport(REPAIRED_SOURCE)
    )
    scratch = tmp_path / "ungoverned"
    scratch.mkdir()
    with pytest.raises(WriteRefused) as caught:
        provider.propose(diagnose(), manifest, reader, scratch)
    assert caught.value.rule is AuthorityRule.UNGUARDED_WRITE
    assert not (scratch / TARGET).exists()

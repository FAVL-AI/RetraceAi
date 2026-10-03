"""The governed model route for repair proposals (RX-06, RX-33, PRECHECK B6).

Status on this host
-------------------
PRECHECK B6 records that **no model-provider credential and no execution budget
exist on this machine**. This module therefore implements the route's real
interface and refuses: with no credential and no transport,
:meth:`GovernedModelRepairProvider.propose` raises
:class:`~retrace_domain.errors.ProviderNotConfigured`. It does not open a
socket, it does not read an environment variable for a key, and it does not
return a fabricated proposal. A test asserts the refusal, so the claim is
evidence rather than prose.

Why the transport is injected
-----------------------------
The provider depends on a :class:`ModelTransport` supplied by the caller rather
than constructing one. Three reasons, in order of importance:

1. **No network code exists in this package.** Egress policy, budgets, retries
   and provider pinning (RX-33, RX-35) belong to the service layer. A domain
   package that could reach the network would make that boundary advisory.
2. The configuration gate is then honestly testable: "not configured" is a
   state the type system can express, not a runtime guess.
3. Substituting a transport in a test exercises *this module's* parsing and
   restraint logic without claiming anything about a provider's behaviour.

The response contract, and why it is content rather than a diff
---------------------------------------------------------------
A transport returns the **full proposed content** of the single target file.
This package then diffs that content against the snapshot's own bytes with
:mod:`difflib`. Consequences that matter:

* The diff a reviewer reads is always computed here, from preserved bytes, so a
  malformed or misleading patch cannot be passed through.
* No patch applier is needed, so there is no second, weaker implementation of
  "what this change means".
* The candidate digest is computed from the content, exactly as for the
  deterministic provider, so the two routes produce comparable candidates.

Restraint applies identically to both routes. A returned content that would
change an exclusion rule, a seed, a split, a unit conversion, a row filter or a
row-count-changing call is **refused**, and the provider abstains with the
matching reason (RX-14). A model proposal is not privileged evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, runtime_checkable

from retrace_contracts import RepairProposal

from ..authority import RepairAuthority
from ..errors import AuthorityRule, ProviderNotConfigured, WriteRefused
from ..snapshot import SnapshotManifest, SnapshotReader
from .base import (
    MEANING_CHANGING_FAULT_CLASSES,
    Abstention,
    Diagnosis,
    build_unified_diff,
    candidate_digest,
    changed_lines,
)
from .restraint import AbstentionReason, first_protected_construct

__all__ = [
    "MAX_RESPONSE_BYTES",
    "GovernedModelRepairProvider",
    "ModelRepairRequest",
    "ModelTransport",
]

MAX_RESPONSE_BYTES: Final[int] = 1 << 20
"""Upper bound on a transport response, in UTF-8 bytes.

Bounded because the response is untrusted input of unknown length, and an
unbounded read is a denial-of-service surface dressed as a feature (RX-10).
"""


@dataclass(frozen=True, slots=True)
class ModelRepairRequest:
    """Everything a transport is given, and nothing else (RX-06).

    Deliberately explicit and closed: a request that could carry arbitrary
    extra context would make it impossible to say, afterwards, what evidence a
    proposal was based on.

    Attributes
    ----------
    diagnosis:
        The frozen diagnosis record being answered.
    target_path:
        The single snapshot-relative file the response may replace.
    target_source:
        The target's current text, read from the snapshot.
    snapshot_paths:
        Every path the snapshot declares, so a route can see what inputs exist
        without being able to read them.
    instruction:
        The task statement, including the restraint rules the response must
        respect. Stated to the route as well as enforced here, because a route
        that is told the rule produces fewer refused proposals -- but being
        told is never what makes the rule hold.
    """

    diagnosis: Diagnosis
    target_path: str
    target_source: str
    snapshot_paths: tuple[str, ...]
    instruction: str


@runtime_checkable
class ModelTransport(Protocol):
    """Carries one :class:`ModelRepairRequest` to a governed route (RX-33).

    Implementations live in the service layer, where egress policy, budgets,
    model pinning and cost accounting are enforced. An implementation must
    return the full proposed content of ``request.target_path`` as text, and
    must raise rather than return a partial or placeholder response.
    """

    def complete(self, request: ModelRepairRequest) -> str:
        """Return the full proposed content of the request's target file."""
        ...


_INSTRUCTION: Final[str] = (
    "Return the complete corrected content of the named file and nothing else. "
    "Do not change any exclusion rule, random seed, train/test split, unit "
    "conversion, row filter, or any operation that changes the number of rows: "
    "such a change alters what the analysis measures and will be refused."
)


class GovernedModelRepairProvider:
    """Repair proposals from a governed model route, or an honest refusal (RX-06).

    Parameters
    ----------
    credential:
        Opaque reference to the credential the transport will use. Absent on
        this host (PRECHECK B6). Never logged and never placed in a request.
    model_id:
        The route identifier to be pinned on the run record (RX-33).
    endpoint:
        The governed endpoint the transport will reach.
    transport:
        The injected :class:`ModelTransport`. No implementation ships in this
        package.
    authority:
        Write guard required before any scratch write (RX-07).
    provider_id:
        Recorded on every proposal produced.
    """

    def __init__(
        self,
        *,
        credential: str | None = None,
        model_id: str | None = None,
        endpoint: str | None = None,
        transport: ModelTransport | None = None,
        authority: RepairAuthority | None = None,
        provider_id: str = "governed-model-route",
    ) -> None:
        self._credential = credential
        self._model_id = model_id
        self._endpoint = endpoint
        self._transport = transport
        self._authority = authority
        self._provider_id = provider_id
        self._abstentions: list[Abstention] = []

    @property
    def provider_id(self) -> str:
        """Stable id recorded on every proposal this provider produces (RX-33)."""
        return self._provider_id

    @property
    def model_id(self) -> str | None:
        """The route identifier to pin on a run record, or ``None`` if unset (RX-33)."""
        return self._model_id

    @property
    def abstention_log(self) -> tuple[Abstention, ...]:
        """Abstentions recorded by this instance, oldest first (RX-06)."""
        return tuple(self._abstentions)

    @property
    def is_configured(self) -> bool:
        """Whether every required configuration field is present (RX-40)."""
        return not self.missing_configuration()

    def missing_configuration(self) -> tuple[str, ...]:
        """Return the absent configuration field names, in declaration order (RX-40).

        Exposed so a status surface can report ``NEEDS_CONFIGURATION`` with the
        specific gap, rather than a bare unavailable flag.
        """
        missing: list[str] = []
        if not self._credential:
            missing.append("credential")
        if not self._model_id:
            missing.append("model_id")
        if not self._endpoint:
            missing.append("endpoint")
        if self._transport is None:
            missing.append("transport")
        return tuple(missing)

    # -- the interface ---------------------------------------------------

    def propose(
        self,
        diagnosis: Diagnosis,
        snapshot_manifest: SnapshotManifest,
        snapshot_reader: SnapshotReader,
        scratch: Path | None,
    ) -> RepairProposal | None:
        """Propose a patch via the governed route, or abstain (RX-06).

        Raises
        ------
        ProviderNotConfigured:
            When any configuration field is absent -- the state on this host
            (PRECHECK B6). Raised **before** anything else happens, so an
            unconfigured route cannot be mistaken for one that found nothing.
        WriteRefused:
            If ``scratch`` is given without an authority guard, or the guard
            refuses the destination (RX-07).
        """
        missing = self.missing_configuration()
        if missing:
            raise ProviderNotConfigured(provider_id=self._provider_id, missing=missing)
        transport = self._transport
        if transport is None:  # pragma: no cover - missing_configuration covers this
            raise ProviderNotConfigured(
                provider_id=self._provider_id, missing=("transport",)
            )

        restraint = MEANING_CHANGING_FAULT_CLASSES.get(diagnosis.fault_class)
        if restraint is not None:
            return self._abstain(
                diagnosis,
                restraint,
                detail=(
                    f"fault class {diagnosis.fault_class.value} names a change to the "
                    "declared method; no route may repair it (RX-14)"
                ),
                construct_label=diagnosis.fault_class.value,
            )

        if diagnosis.target_path not in snapshot_manifest:
            return self._abstain(
                diagnosis,
                AbstentionReason.TARGET_NOT_IN_SNAPSHOT,
                detail=f"snapshot does not contain {diagnosis.target_path!r}",
            )

        try:
            original = snapshot_reader(diagnosis.target_path).decode("utf-8")
        except UnicodeDecodeError:
            return self._abstain(
                diagnosis,
                AbstentionReason.NO_RULE_MATCHED,
                detail=f"{diagnosis.target_path!r} is not UTF-8 text",
            )

        response = transport.complete(
            ModelRepairRequest(
                diagnosis=diagnosis,
                target_path=diagnosis.target_path,
                target_source=original,
                snapshot_paths=snapshot_manifest.paths,
                instruction=_INSTRUCTION,
            )
        )
        unusable = _response_defect(response)
        if unusable is not None:
            return self._abstain(
                diagnosis, AbstentionReason.PROVIDER_RESPONSE_UNUSABLE, detail=unusable
            )

        unified_diff = build_unified_diff(diagnosis.target_path, original, response)
        if not unified_diff:
            return self._abstain(
                diagnosis,
                AbstentionReason.DIFF_WOULD_BE_EMPTY,
                detail="the route returned content identical to the snapshot",
            )

        construct = first_protected_construct(changed_lines(unified_diff))
        if construct is not None:
            return self._abstain(
                diagnosis,
                construct.reason,
                detail=(
                    f"the returned content would change a line carrying {construct.label}; "
                    "refused regardless of which route produced it (RX-14)"
                ),
                construct_label=construct.label,
            )

        patched_bytes = response.encode("utf-8")
        candidate_hash = candidate_digest(
            snapshot_manifest, diagnosis.target_path, patched_bytes
        )
        proposal = RepairProposal(
            proposal_id=f"prop-{candidate_hash[:16]}",
            snapshot_id=diagnosis.snapshot_id,
            target_path=diagnosis.target_path,
            unified_diff=unified_diff,
            candidate_hash=candidate_hash,
            rationale=(
                f"proposed by the governed model route {self._model_id!r} in answer to "
                f"{diagnosis.diagnosis_id!r}; the diff shown was computed here from the "
                "snapshot's preserved bytes, and it changes no exclusion, seed, split, "
                "unit or row-count operation"
            ),
            provider=self._provider_id,
        )
        if scratch is not None:
            self._write_candidate(scratch, diagnosis.target_path, patched_bytes)
        return proposal

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

        Always ``None``: in the proposal domain ``None`` IS the abstention.
        Typed ``RepairProposal | None`` so ``return self._abstain(...)`` reads as
        returning a result rather than tripping mypy's func-returns-value.
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
        """Write candidate bytes into the granted scratch directory (RX-07)."""
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


def _response_defect(response: object) -> str | None:
    """Return why a transport response is unusable, or ``None`` if it is usable.

    Checked rather than assumed: a response is untrusted input, and a route
    that returns an apology, an empty string or a megabyte of prose must be
    refused rather than diffed.
    """
    if not isinstance(response, str):
        return f"transport returned {type(response).__name__}, not text"
    if not response.strip():
        return "transport returned empty content"
    size = len(response.encode("utf-8"))
    if size > MAX_RESPONSE_BYTES:
        return f"transport returned {size} bytes, above the {MAX_RESPONSE_BYTES}-byte bound"
    return None

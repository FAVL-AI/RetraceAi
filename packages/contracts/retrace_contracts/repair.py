"""The repair proposal shape (RX-06, RX-56).

A repair in RETRACE is a *proposal*, and a proposal is a **diff**. It never
carries file content to write in place, because a reviewer cannot review a
replacement they cannot compare, and an in-place write destroys the baseline
the verifier needs.

Two refusals are enforced here rather than deferred to an apply step:

* A payload that is not a unified diff is refused. Raw file content, a JSON
  blob or a prose description all fail, so "the proposal carries a diff" is a
  parse-time property, not a convention.
* A diff whose own ``---``/``+++`` headers name a file other than
  ``target_path`` is refused. Otherwise a proposal could declare one target and
  patch another, which is an authority bypass dressed as a typo (RX-07).

``injected`` marks a fault that this repository authored for its own fixtures
(RX-56). It defaults to ``False``, so a fixture fault must be *declared*
injected; nothing in this layer can infer it.

"""

from __future__ import annotations

import re
from typing import Annotated, ClassVar, Final

from pydantic import Field, StringConstraints, field_validator, model_validator

from .base import FrozenRecord, Identifier, NonEmptyStr, Sha256Hex
from .paths import validate_relative_path

__all__ = ["MAX_DIFF_BYTES", "DiffText", "RepairProposal", "parse_unified_diff_targets"]

MAX_DIFF_BYTES: Final[int] = 1_048_576
"""Authoritative upper bound on a proposal diff, in UTF-8 bytes.

Enforced by :meth:`RepairProposal._diff_is_bounded` so the refusal names the
byte limit. ``DiffText`` carries a larger character backstop only so that the
byte check is the gate that fires, not a generic length constraint.
"""

DiffText = Annotated[str, StringConstraints(min_length=1, max_length=4_194_304)]
"""Raw diff text. Not whitespace-stripped; bounded well above MAX_DIFF_BYTES."""

_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")
_OLD_HEADER = re.compile(r"^--- (?P<path>.+)$")
_NEW_HEADER = re.compile(r"^\+\+\+ (?P<path>.+)$")
_DEV_NULL: Final[str] = "/dev/null"


def _strip_diff_prefix(raw: str) -> str:
    """Strip diff metadata and a single ``a/``/``b/`` prefix from a header path."""
    path = raw.split("\t", 1)[0].strip()
    if path.startswith(('"', "'")) and path.endswith(('"', "'")) and len(path) >= 2:
        path = path[1:-1]
    if path == _DEV_NULL:
        return path
    head, _, tail = path.partition("/")
    if head in ("a", "b") and tail:
        return tail
    return path


def parse_unified_diff_targets(unified_diff: str) -> tuple[frozenset[str], int]:
    """Return the paths a unified diff names and its hunk count (RX-06).

    Parameters
    ----------
    unified_diff:
        The raw diff text.

    Returns
    -------
    tuple:
        ``(paths, hunk_count)`` where ``paths`` holds every non-``/dev/null``
        path appearing in a ``---`` or ``+++`` header, with a leading ``a/`` or
        ``b/`` prefix removed, and ``hunk_count`` is the number of ``@@`` hunk
        headers.

    This is a *structural* parse only. It does not apply, validate or trust the
    diff body, and it never reads the filesystem.
    """
    paths: set[str] = set()
    hunks = 0
    for line in unified_diff.splitlines():
        if _HUNK_HEADER.match(line):
            hunks += 1
            continue
        old = _OLD_HEADER.match(line)
        if old:
            candidate = _strip_diff_prefix(old.group("path"))
            if candidate != _DEV_NULL:
                paths.add(candidate)
            continue
        new = _NEW_HEADER.match(line)
        if new:
            candidate = _strip_diff_prefix(new.group("path"))
            if candidate != _DEV_NULL:
                paths.add(candidate)
    return frozenset(paths), hunks


class RepairProposal(FrozenRecord):
    """A reviewable patch against a named snapshot (RX-06, RX-56).

    Invariants enforced at construction, each with a negative control in
    ``tests/contracts/test_repair_proposal.py``:

    * ``unified_diff`` contains at least one ``@@`` hunk header and at least one
      ``---``/``+++`` header pair. Raw file content is refused.
    * every path the diff names equals ``target_path``.
    * ``target_path`` is snapshot-relative and traversal-free.
    * ``injected`` is ``False`` unless explicitly declared.

    The proposal carries ``candidate_hash``, the digest an approval binds
    (RX-05). This layer does not compute it from the diff: the candidate's
    identity is whatever the producing worker digested, and inventing it here
    would hide a producer bug.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.RepairProposal"

    proposal_id: Identifier = Field(description="Stable id of this proposal.")
    snapshot_id: Identifier = Field(
        description="Id of the immutable snapshot this patch applies against (RX-01)."
    )
    target_path: NonEmptyStr = Field(
        description="Snapshot-relative path the diff modifies. Exactly one file per proposal."
    )
    unified_diff: DiffText = Field(
        description="The patch itself, in unified diff format. Never file content."
    )
    candidate_hash: Sha256Hex = Field(
        description="Digest of the candidate this proposal represents (RX-05)."
    )
    rationale: NonEmptyStr = Field(
        description="Why this change is proposed, in the proposer's own words."
    )
    provider: NonEmptyStr = Field(
        description=(
            "Id of the provider that produced the proposal, e.g. "
            "'deterministic-local' or a configured model provider (RX-33)."
        )
    )
    injected: bool = Field(
        default=False,
        description=(
            "True only for a fault this repository authored for its own fixtures "
            "(RX-56). Never inferred; an injected fault must declare itself."
        ),
    )

    @field_validator("target_path")
    @classmethod
    def _target_is_snapshot_relative(cls, value: str) -> str:
        """Refuse an absolute or traversing target path (RX-06, RX-42)."""
        return validate_relative_path(value, field="RepairProposal.target_path")

    @field_validator("unified_diff")
    @classmethod
    def _diff_is_bounded(cls, value: str) -> str:
        """Refuse an unreviewably large diff (RX-06)."""
        if len(value.encode("utf-8")) > MAX_DIFF_BYTES:
            raise ValueError(
                f"unified_diff exceeds {MAX_DIFF_BYTES} bytes; a reviewable patch is smaller"
            )
        return value

    @model_validator(mode="after")
    def _diff_is_a_diff_for_this_target(self) -> RepairProposal:
        """Refuse a payload that is not a diff, or is a diff for another file (RX-06)."""
        paths, hunks = parse_unified_diff_targets(self.unified_diff)
        if hunks == 0:
            raise ValueError(
                "unified_diff contains no '@@' hunk header; a repair proposal carries a "
                "unified diff, never file content to write in place (RX-06)"
            )
        if not paths:
            raise ValueError(
                "unified_diff names no file in its '---'/'+++' headers; "
                "the patch target must be stated in the diff itself"
            )
        mismatched = sorted(path for path in paths if path != self.target_path)
        if mismatched:
            raise ValueError(
                f"unified_diff patches {', '.join(mismatched)} but target_path is "
                f"{self.target_path!r}; a proposal may not declare one target and patch another"
            )
        return self

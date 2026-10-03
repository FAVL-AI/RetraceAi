"""Outcome and truthfulness label keys, and the shortening guard (RX-25, RX-30).

WHY A MODULE JUST FOR KEY NAMES
    Two groups of strings in this package are not ordinary UI copy:

    * the five ``VerificationOutcome`` labels. ``docs/security/T10_REVIEW.md``
      control 1 states the exposure plainly: the real risk is that a reader
      takes ``REPRODUCED_WITHIN_CONTRACT`` to mean "the science is right", and
      the STRING is the attack surface. The qualifier *within contract* may not
      be separated from the label, and the label may not be shortened to
      "Reproduced" or rendered as "verified" or "passed". RETRACE establishes
      conformance to a declared contract, not correctness.
    * the nine truthfulness tokens (``docs/UX.md``, RX-25). These must never be
      hidden or restyled away, so in the catalogues the TOKEN ITSELF is a
      protected span (RX-29) and only the gloss around it is translatable. A
      translation pass therefore cannot alter, localise or drop the token.

HONEST LIMIT OF THE GUARD BELOW
    :func:`outcome_label_violations` is a LEXICAL check. For the source locale it
    is strong: the value must equal the string ``docs/UX.md`` mandates. For any
    other language it can only catch the obvious failures - an empty value, or a
    value equal to a known bare-affirmation word. It cannot tell whether a
    Dutch or Arabic rendering preserves the conformance qualifier. That judgement
    needs a human linguist, which is exactly why all five outcome labels are
    left ``pending`` in every non-source catalogue instead of being guessed.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "BARE_AFFIRMATIONS",
    "OUTCOME_MESSAGE_KEYS",
    "REPRODUCED_KEY",
    "TRUTHFULNESS_MESSAGE_KEYS",
    "TRUTHFULNESS_TOKENS",
    "outcome_label_violations",
]

#: The five VerificationOutcome members, in the order docs/UX.md lists them,
#: mapped to their catalogue key. The enum member name is the key suffix, so a
#: renamed outcome breaks loudly instead of leaving an orphan string.
OUTCOME_MESSAGE_KEYS: Final[dict[str, str]] = {
    "REPRODUCED_WITHIN_CONTRACT": "outcome.reproduced_within_contract",
    "EXECUTED_NOT_VERIFIED": "outcome.executed_not_verified",
    "CHANGED_RESULT": "outcome.changed_result",
    "BLOCKED_MISSING_EVIDENCE": "outcome.blocked_missing_evidence",
    "FAILED_EXECUTION": "outcome.failed_execution",
}

REPRODUCED_KEY: Final[str] = "outcome.reproduced_within_contract"

#: The nine mandated truthfulness tokens (docs/UX.md, RX-25), spelled exactly as
#: the specification spells them - mixed case included.
TRUTHFULNESS_TOKENS: Final[tuple[str, ...]] = (
    "STALE",
    "UNAVAILABLE",
    "REPLAY",
    "DEMO",
    "beta",
    "NEEDS_CONFIGURATION",
    "SYNTHETIC",
    "injected",
    "machine-translated",
)

TRUTHFULNESS_MESSAGE_KEYS: Final[dict[str, str]] = {
    "STALE": "truth.stale",
    "UNAVAILABLE": "truth.unavailable",
    "REPLAY": "truth.replay",
    "DEMO": "truth.demo",
    "beta": "truth.beta",
    "NEEDS_CONFIGURATION": "truth.needs_configuration",
    "SYNTHETIC": "truth.synthetic",
    "injected": "truth.injected",
    "machine-translated": "truth.machine_translated",
}

#: Words that assert correctness or success on their own. Any of these standing
#: alone as the reproduced-outcome label converts a conformance statement into a
#: correctness claim, which T10 control 1 forbids.
BARE_AFFIRMATIONS: Final[frozenset[str]] = frozenset(
    {
        "reproduced",
        "verified",
        "validated",
        "passed",
        "pass",
        "ok",
        "success",
        "successful",
        "correct",
        "confirmed",
        "true",
        "yes",
        "✓",
        "✔",
    }
)


def outcome_label_violations(
    value: str | None,
    *,
    key: str = REPRODUCED_KEY,
    locale: str = "",
    mandated: str | None = None,
) -> tuple[str, ...]:
    """Return reasons ``value`` is an unsafe outcome label (RX-25).

    ``mandated`` is the string ``docs/UX.md`` requires and is compared exactly;
    pass it for the source locale only. ``None`` or an empty ``value`` is NOT a
    violation - a pending translation is the honest state and is reported by the
    coverage checker, not by this guard.
    """
    if value is None or not value.strip():
        return ()
    prefix = f"{locale or 'source'}/{key}: "
    problems: list[str] = []
    stripped = value.strip()
    normalised = stripped.strip(" .!—-").casefold()
    if key == REPRODUCED_KEY and normalised in BARE_AFFIRMATIONS:
        problems.append(
            f"{prefix}{stripped!r} is a bare affirmation. The qualifier 'within contract' is "
            "the whole claim (T10 control 1); conformance is not correctness."
        )
    if mandated is not None and stripped != mandated:
        problems.append(f"{prefix}expected the docs/UX.md label {mandated!r}, found {stripped!r}")
    return tuple(problems)

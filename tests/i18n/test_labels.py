"""Outcome labels and truthfulness tokens (RX-25, RX-30).

The authority for the five outcome labels is ``docs/UX.md``, parsed by the
``ux_outcome_labels`` fixture. Nothing in this package may restate them.
"""

from __future__ import annotations

import pytest
from retrace_i18n.catalogue import Catalogue
from retrace_i18n.labels import (
    OUTCOME_MESSAGE_KEYS,
    REPRODUCED_KEY,
    TRUTHFULNESS_MESSAGE_KEYS,
    TRUTHFULNESS_TOKENS,
    outcome_label_violations,
)
from retrace_i18n.protected import protected_spans, unprotect
from retrace_i18n.registry import LocaleRegistry


def test_the_five_outcome_labels_match_the_ux_document_exactly(
    catalogues: dict[str, Catalogue], ux_outcome_labels: dict[str, str]
) -> None:
    """Byte-exact agreement with docs/UX.md, em dashes included (RX-25)."""
    source = catalogues["en"]
    assert set(OUTCOME_MESSAGE_KEYS) == set(ux_outcome_labels)
    for member, key in OUTCOME_MESSAGE_KEYS.items():
        assert source.entries[key].value == ux_outcome_labels[member], member


def test_reproduced_within_contract_keeps_its_qualifier(
    catalogues: dict[str, Catalogue], ux_outcome_labels: dict[str, str]
) -> None:
    """The label may never be shortened to 'Reproduced' (T10 control 1, RX-25).

    Shortening it converts a statement about conformance to a declared contract
    into a claim that the result is correct - the one property RETRACE does not
    establish.
    """
    value = catalogues["en"].entries[REPRODUCED_KEY].value
    assert value == "Reproduced within contract"
    assert value == ux_outcome_labels["REPRODUCED_WITHIN_CONTRACT"]
    assert value.lower() != "reproduced"
    assert "within contract" in value
    assert outcome_label_violations(value, mandated=value) == ()


def test_no_catalogue_anywhere_shortens_the_reproduced_label(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """The guard runs over all 36 catalogues, source and translations (RX-25).

    Every non-source value is ``None`` today, so this is a forward gate: the day
    a reviewer writes a translation, a bare affirmation fails here.
    """
    problems: list[str] = []
    for code in reg.codes:
        value = catalogues[code].entries[REPRODUCED_KEY].value
        mandated = "Reproduced within contract" if code == "en" else None
        problems.extend(
            outcome_label_violations(value, locale=code, mandated=mandated)
        )
    assert not problems, problems


def test_the_outcome_description_states_the_prohibition(
    catalogues: dict[str, Catalogue],
) -> None:
    """A translator must be told, in the catalogue, not to shorten it (RX-25)."""
    description = catalogues["en"].entries[REPRODUCED_KEY].description
    assert "Reproduced" in description
    assert "conformance" in description.lower()
    assert "correctness" in description.lower()


def test_all_nine_truthfulness_tokens_have_a_key(
    catalogues: dict[str, Catalogue],
) -> None:
    """The nine mandated tokens of docs/UX.md each have a message (RX-25)."""
    assert len(TRUTHFULNESS_TOKENS) == 9
    assert set(TRUTHFULNESS_MESSAGE_KEYS) == set(TRUTHFULNESS_TOKENS)
    for key in TRUTHFULNESS_MESSAGE_KEYS.values():
        assert key in catalogues["en"].keys


def test_truthfulness_tokens_render_verbatim_in_every_locale(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """The token survives display, in every locale that has a value (RX-25, RX-29)."""
    for code in reg.codes:
        for token, key in TRUTHFULNESS_MESSAGE_KEYS.items():
            message = catalogues[code].entries[key]
            if not isinstance(message.value, str):
                continue
            assert token in protected_spans(message.value), (code, key)
            assert token in unprotect(message.value), (code, key)


def test_the_machine_translation_tokens_are_the_mandated_spellings() -> None:
    """Mixed case is deliberate: ``beta`` and ``machine-translated`` are lowercase."""
    assert "beta" in TRUTHFULNESS_TOKENS
    assert "machine-translated" in TRUTHFULNESS_TOKENS
    assert "BETA" not in TRUTHFULNESS_TOKENS


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["Reproduced", "reproduced", "Reproduced.", "Verified", "Passed", "OK", "✓",
     "Confirmed", "Validated", "Success"],
)
def test_negative_control_bare_affirmations_are_rejected(bad: str) -> None:
    """MANDATORY negative control: the guard rejects every bare-affirmation form.

    A gate that has only ever seen compliant input is not evidence; these are the
    strings a well-meaning translator or a terse redesign would actually produce.
    """
    problems = outcome_label_violations(bad, locale="nl")
    assert problems, f"the guard did NOT reject {bad!r}"
    assert "conformance is not correctness" in " ".join(problems)


def test_negative_control_a_wrong_source_label_is_rejected() -> None:
    """Drift from docs/UX.md is detected exactly (RX-25)."""
    problems = outcome_label_violations(
        "Reproduced within the contract", mandated="Reproduced within contract"
    )
    assert problems
    assert "docs/UX.md label" in problems[0]


def test_guard_accepts_a_qualified_label_and_a_pending_null() -> None:
    """No false positives: a qualified label passes, and ``null`` is not a violation."""
    assert outcome_label_violations("Reproduced within contract") == ()
    assert outcome_label_violations("Gereproduceerd binnen contract", locale="nl") == ()
    assert outcome_label_violations(None, locale="ak") == ()
    assert outcome_label_violations("   ", locale="ak") == ()


def test_negative_control_the_guard_is_scoped_to_the_reproduced_key() -> None:
    """'Failed execution' must not be caught by the bare-affirmation rule (RX-25)."""
    assert outcome_label_violations(
        "Failed execution", key="outcome.failed_execution"
    ) == ()

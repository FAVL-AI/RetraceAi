"""Honest labelling of the five verification outcomes (RX-11, RX-12, RX-25).

The authority is ``docs/UX.md`` for the label strings and
``docs/security/T10_REVIEW.md`` control 1 for what may not be done to them:

    "REPRODUCED_WITHIN_CONTRACT must never render as a bare tick, 'verified', or
    'passed'. The contract identity must be adjacent and the qualifier *within
    contract* must be inseparable from the label [...] the text may not be
    shortened to 'Reproduced'."

These tests hold the workspace to that, and the negative controls in
``test_negative_controls.py`` plant each violation to show the checks see it.

WHAT THESE TESTS CANNOT DO. They read source. They cannot prove that the label
is visible at a given viewport, that the icon renders, or that a screen reader
announces it: no browser runs in this suite.
"""

from __future__ import annotations

import checks
from retrace_contracts.enums import VerificationOutcome
from retrace_i18n.labels import BARE_AFFIRMATIONS


def test_the_presentation_table_covers_the_frozen_outcome_enum(
    ui_sources: dict[str, str]
) -> None:
    """Exactly the five members, and no sixth (RX-12)."""
    source = ui_sources["packages/ui/src/outcome.js"]
    members = tuple(member.value for member in VerificationOutcome)
    assert checks.OUTCOME_NAMES == members, (
        "this suite and retrace_contracts disagree about the outcome vocabulary"
    )
    for name in members:
        assert checks.js_object_entry(source, "OUTCOME_PRESENTATION", name), (
            f"OUTCOME_PRESENTATION has no entry for {name}"
        )
    declared = set(
        key
        for key in checks.OUTCOME_NAMES
        if checks.js_object_entry(source, "OUTCOME_PRESENTATION", key)
    )
    assert declared == set(members)


def test_every_outcome_renders_icon_text_and_colour(
    ui_sources: dict[str, str], ux_outcome_labels: dict[str, str]
) -> None:
    """No outcome may be carried by colour alone - the docs/UX.md rule (RX-25)."""
    problems = checks.outcome_presentation_violations(
        ui_sources["packages/ui/src/outcome.js"], ux_outcome_labels
    )
    assert problems == [], "\n".join(problems)


def test_the_badge_emits_geometry_and_text_in_the_same_element(
    ui_sources: dict[str, str]
) -> None:
    """The renderer must place an icon node and a label node in every badge."""
    source = ui_sources["packages/ui/src/outcome.js"]
    render = source[source.index("export function renderOutcome") :]
    assert "rx-outcome__icon" in render, "the badge renders no icon element"
    assert "icon(entry.icon" in render, "the badge does not render the declared icon"
    assert "rx-outcome__label" in render, "the badge renders no label element"
    assert "text: entry.label" in render, "the badge does not render the full label text"
    assert "dataset: { outcome" in render, "the badge does not carry the outcome as data"


def test_the_contract_identity_is_adjacent_to_the_label(ui_sources: dict[str, str]) -> None:
    """T10 control 1: "within contract" names no contract on its own."""
    source = ui_sources["packages/ui/src/outcome.js"]
    assert "context.contractRef" in source
    assert "needs contractRef" in source, (
        "renderOutcome does not refuse a badge with no contract identity"
    )


def test_no_source_file_shortens_the_reproduced_label(all_js_sources: dict[str, str]) -> None:
    """'Reproduced' standing alone is refused in every module (T10 control 1)."""
    for path, source in all_js_sources.items():
        problems = checks.shortened_reproduced_violations(source)
        assert problems == [], f"{path}:\n" + "\n".join(problems)


def test_no_source_file_asserts_success_with_a_bare_affirmation(
    all_js_sources: dict[str, str]
) -> None:
    """'verified', 'validated', 'passed', a bare tick: none may stand as a label.

    The vocabulary is ``retrace_i18n.labels.BARE_AFFIRMATIONS``, so the browser
    and the translation layer refuse the same list rather than two similar ones.
    """
    for path, source in all_js_sources.items():
        problems = checks.bare_affirmation_violations(source, BARE_AFFIRMATIONS)
        assert problems == [], f"{path}:\n" + "\n".join(problems)


def test_the_label_strings_live_in_exactly_one_module(
    all_js_sources: dict[str, str], ux_outcome_labels: dict[str, str]
) -> None:
    """One chokepoint, so no view can invent a shorter label.

    This is the structural reason the rule above is enforceable: if a second
    module could spell an outcome label, every future view would have to be
    reviewed for the wording instead of the component guaranteeing it.
    """
    for label in ux_outcome_labels.values():
        holders = [
            path
            for path, source in all_js_sources.items()
            if label in source or label.replace("—", "\\u2014") in source
        ]
        assert holders == ["packages/ui/src/outcome.js"], (
            f"the label {label!r} appears in {holders}; it may appear only in the outcome "
            "component, which always renders it in full"
        )


def test_the_outcome_gate_blocks_display_until_the_verifier_asserts_rx18_and_rx14(
    ui_sources: dict[str, str]
) -> None:
    """The T10 deployment restriction, enforced as a gate rather than re-derived.

    T10_REVIEW states that while RX-18 and RX-14 are unimplemented "no
    verification outcome may be displayed, exported, or returned by an API to
    any party", and that the restrictions "must be enforced as gates when those
    arrive". A browser workspace is such an arrival.
    """
    source = ui_sources["packages/ui/src/outcome-gate.js"]
    assert "independent_recomputation: 'RX-18'" in source
    assert "methodology_delta: 'RX-14'" in source
    assert "VERIFIER_CAPABILITY_UNKNOWN" in source
    assert "NO_REFERENCE_CANNOT_REPRODUCE" in source, (
        "the gate does not refuse the NO_REFERENCE / REPRODUCED_WITHIN_CONTRACT pairing"
    )
    decision = source[source.index("export function outcomeDisplayDecision") :]
    assert "if (!verifierCapability)" in decision, (
        "the gate does not refuse a missing capability record first"
    )


def test_the_only_renderer_of_an_outcome_in_the_application_is_the_gate(
    web_sources: dict[str, str]
) -> None:
    """Views call renderGatedOutcome, never renderOutcome directly.

    Importing the badge directly would route around the T10 gate, which is the
    one bypass that matters here.
    """
    for path, source in web_sources.items():
        assert "renderOutcome" not in source, (
            f"{path} renders an outcome badge directly; it must go through renderGatedOutcome "
            "so the T10 display gate cannot be bypassed"
        )


def test_execution_status_and_verification_outcome_are_different_vocabularies(
    web_sources: dict[str, str]
) -> None:
    """RX-11, asserted on the shapes the browser carries."""
    source = web_sources["apps/web/src/api/shapes.js"]
    outcomes = set(checks.js_string_array(source, "VERIFICATION_OUTCOMES"))
    statuses = set(checks.js_string_array(source, "EXECUTION_STATUSES"))
    assert outcomes and statuses
    assert outcomes & statuses == set(), (
        f"the two vocabularies share value(s) {sorted(outcomes & statuses)}; a run that exited 0 "
        "would then be representable as a verification outcome"
    )

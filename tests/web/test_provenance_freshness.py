"""Data provenance and event freshness are two attributes (RX-25, RX-56).

The brief states the defect plainly: data provenance (synthetic vs real) must be
shown SEPARATELY from event freshness (live / stale / replay), and conflating
them is a defect. ``docs/evidence/SPEC_RECONCILIATION_CLOSURE.md`` section 4
makes the same separation in the contract layer - data provenance, proposal
provenance, execution state and verification outcome stay four separate
attributes, and `SYNTHETIC` is explicitly not a `reference_kind`.

Why it matters in practice: a synthetic fixture can stream at full rate and be
perfectly fresh while describing nothing that ever happened, and a real recorded
measurement can be hours stale and still be the best evidence available. One
merged "status" loses whichever half the reader needed.
"""

from __future__ import annotations

import checks


def test_the_two_vocabularies_are_disjoint_and_the_modules_are_independent(
    ui_sources: dict[str, str]
) -> None:
    """Separate files, separate value ids, neither importing the other."""
    problems = checks.provenance_freshness_separation_violations(
        ui_sources["packages/ui/src/provenance.js"],
        ui_sources["packages/ui/src/freshness.js"],
    )
    assert problems == [], "\n".join(problems)


def test_each_module_declares_its_own_attribute_name_and_legend(
    ui_sources: dict[str, str]
) -> None:
    """The chip group is labelled, so a reader is never left to guess which
    attribute a row of chips describes."""
    provenance = ui_sources["packages/ui/src/provenance.js"]
    freshness = ui_sources["packages/ui/src/freshness.js"]
    assert "PROVENANCE_LEGEND = 'Data provenance'" in provenance
    assert "FRESHNESS_LEGEND = 'Event freshness'" in freshness
    assert "PROVENANCE_ATTRIBUTE = 'data-provenance'" in provenance
    assert "FRESHNESS_ATTRIBUTE = 'event-freshness'" in freshness
    assert "a chip group must name its attribute" in ui_sources[
        "packages/ui/src/truthfulness.js"
    ], "renderChipGroup does not require an attribute name"


def test_no_single_label_anywhere_carries_both_attributes(
    all_js_sources: dict[str, str]
) -> None:
    """One string mixing both vocabularies is the conflation, in miniature."""
    for path, source in all_js_sources.items():
        problems = checks.conflated_label_violations(source)
        assert problems == [], f"{path}:\n" + "\n".join(problems)


def test_the_envelope_carries_provenance_and_freshness_as_separate_fields(
    web_sources: dict[str, str]
) -> None:
    """The separation starts at the transport, not at the renderer.

    If the client returned one combined status, every view would have to
    reconstruct the two attributes - and would eventually get it wrong.
    """
    client = web_sources["apps/web/src/api/client.js"]
    assert "provenance: fields.provenance" in client
    assert "freshness: fields.freshness" in client
    assert "status: fields.status" in client, "status, provenance and freshness are three fields"


def test_every_view_renders_both_groups_through_one_scaffold(
    web_sources: dict[str, str]
) -> None:
    """`renderEnvelope` always emits both chip groups, as sibling elements."""
    common = web_sources["apps/web/src/views/common.js"]
    assert "renderProvenance(" in common
    assert "renderFreshness(" in common
    header = common[common.index("const header = el(") : common.index("if (envelope.status")]
    assert "renderProvenance(" in header and "renderFreshness(" in header, (
        "the attribute header does not render both groups"
    )


def test_a_disconnected_stream_is_branded_rather_than_left_looking_current(
    ui_sources: dict[str, str], web_sources: dict[str, str]
) -> None:
    """docs/UX.md: a disconnected stream must say so, not keep showing the last
    frame as current."""
    freshness = ui_sources["packages/ui/src/freshness.js"]
    assert "export function renderStaleFrame" in freshness
    body = freshness[freshness.index("export function renderStaleFrame") :]
    assert "It is not the current state." in body, (
        "the stale frame does not state that the content is not current"
    )
    assert "renderStaleFrame needs a non-current freshness value" in freshness, (
        "renderStaleFrame would accept LIVE and brand fresh content as stale"
    )
    common = web_sources["apps/web/src/views/common.js"]
    assert "renderStaleFrame(content" in common, (
        "views do not wrap stale content; they would present an old frame as current"
    )
    client = web_sources["apps/web/src/api/client.js"]
    assert "STALE_AFTER_MS" in client, "no declared interval after which a stream is stale"
    assert "the last frame received" in client


def test_the_fixture_source_labels_itself_on_every_envelope(
    web_sources: dict[str, str]
) -> None:
    """RX-25: fixtures are labelled DEMO. Here, DEMO and SYNTHETIC, always."""
    demo = web_sources["apps/web/src/api/demo-source.js"]
    assert "const PROVENANCE = Object.freeze(['DEMO_FIXTURE', 'SYNTHETIC']);" in demo
    assert demo.count("provenance: PROVENANCE") >= 2, (
        "not every envelope builder in the fixture stamps its provenance"
    )
    assert "freshness: 'UNAVAILABLE'" in demo, (
        "the fixture does not declare its freshness as UNAVAILABLE; a static fixture is not live"
    )
    assert "freshness: 'LIVE'" not in demo, "the fixture claims to be live"
    assert "setInterval" not in demo and "setTimeout" not in demo, (
        "the fixture contains a timer, which could only serve to make it look active"
    )


def test_the_fixture_cannot_produce_a_verification_outcome(
    web_sources: dict[str, str]
) -> None:
    """A fixture must not be able to talk its way past the T10 display gate."""
    demo = web_sources["apps/web/src/api/demo-source.js"]
    capability = demo[demo.index("verifierCapability:") :]
    assert "unconfigured(" in capability[:200], (
        "the fixture returns something other than NEEDS_CONFIGURATION for the verifier capability"
    )
    for outcome in checks.OUTCOME_NAMES:
        assert outcome not in demo, (
            f"the fixture mentions the outcome {outcome}; it must carry no outcome at all"
        )


def test_the_fixture_is_never_the_default_source(web_sources: dict[str, str]) -> None:
    """A fallback from the API to fixture data would be the most dangerous line
    in the workspace, so the choice is explicit and one-way."""
    main = web_sources["apps/web/src/main.js"]
    assert "params.get('data') === 'demo'" in main
    assert "wantsDemo ? createDemoSource() : createClient()" in main, (
        "the source selection is not a single explicit branch"
    )
    client_code = checks.strip_js_comments(web_sources["apps/web/src/api/client.js"])
    assert "emo" not in client_code, (
        "the client module's CODE references the fixture; a quiet fallback could exist. "
        "(Its comments may discuss the fixture - they are stripped before this check.)"
    )

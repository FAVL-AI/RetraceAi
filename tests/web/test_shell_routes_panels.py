"""The workspace shell, the thirteen routes, and the panel surface (RX-20, RX-21,
RX-23, RX-25, RX-40).

RX-20's acceptance condition is "each route renders; no dead nav entry". The
route list is parsed from ``docs/REQUIREMENTS.md`` rather than copied here, so a
change to the requirement fails these tests instead of drifting away from them.

The shell regions docs/UX.md names - header (project selector, prompt bar,
connection state, world clock, user), left navigation, centre panel surface,
right context inspector, bottom timeline and console - are each asserted to
exist. What is NOT asserted is that they lay out correctly: there is no browser
in this suite, so no rendered geometry, focus order or screen-reader output is
observed.
"""

from __future__ import annotations

import re

import checks

#: Route-level `id:` lines sit at four-space indentation in apps/web/src/routes.js;
#: panel specs are single-line objects, so their ids never match this.
_ROUTE_ID = re.compile(r"(?m)^    id: '([a-z-]+)',$")


def _route_ids(routes_source: str) -> tuple[str, ...]:
    ids = tuple(_ROUTE_ID.findall(routes_source))
    assert len(ids) == 13, (
        f"parsed {len(ids)} route ids from routes.js: {ids}. Fix the parser if the file changed "
        "shape; do not relax the expectation."
    )
    return ids


def test_the_thirteen_routes_are_exactly_the_ones_rx20_names(
    web_sources: dict[str, str], rx20_routes: tuple[str, ...]
) -> None:
    """One list, parsed from the requirement, not restated in the code review."""
    ids = _route_ids(web_sources["apps/web/src/routes.js"])
    assert ids == rx20_routes, (
        f"routes.js declares {ids}; docs/REQUIREMENTS.md RX-20 names {rx20_routes}"
    )


def test_no_navigation_entry_is_dead(web_sources: dict[str, str]) -> None:
    """Every panel kind a route names must resolve to a registered view."""
    routes = web_sources["apps/web/src/routes.js"]
    registry = web_sources["apps/web/src/views/registry.js"]
    kinds = set(re.findall(r"kind: '([a-z-]+)'", routes))
    assert len(kinds) >= 13, f"only {len(kinds)} distinct panel kinds across 13 routes"
    registered = set(re.findall(r"(?m)^  '?([a-z-]+)'?:\s", registry))
    missing = sorted(kinds - registered)
    assert missing == [], (
        f"these panel kinds are named by a route but have no view: {missing}. Each would render "
        "as an exception, which is what a dead nav entry looks like at runtime."
    )


def test_every_journey_view_is_reachable_from_at_least_one_route(
    web_sources: dict[str, str]
) -> None:
    """The eight views of the central journey, each reachable (RX-20)."""
    routes = web_sources["apps/web/src/routes.js"]
    registry = web_sources["apps/web/src/views/registry.js"]
    journey = checks.js_string_array(registry, "JOURNEY_KINDS")
    assert len(journey) == 8, f"expected the eight journey views, found {journey}"
    unreachable = [kind for kind in journey if f"kind: '{kind}'" not in routes]
    assert unreachable == [], f"journey views with no route: {unreachable}"


def test_the_navigation_renders_every_route_and_marks_the_current_one(
    web_sources: dict[str, str]
) -> None:
    """A selection shown only by background colour is not conveyed at all."""
    nav = web_sources["apps/web/src/nav.js"]
    assert "ROUTES.map(" in nav, "the navigation is not generated from the route table"
    assert "'aria-current': 'page'" in nav, "the current route is not marked in the a11y tree"


def test_the_header_carries_the_five_elements_the_specification_names(
    web_sources: dict[str, str]
) -> None:
    """Project selector, prompt bar, connection state, world clock, user."""
    header = web_sources["apps/web/src/header.js"]
    for marker, what in (
        ("rx-header__project", "project selector"),
        ("rx-header__prompt", "prompt bar"),
        ("rx-header__connection", "connection state"),
        ("rx-header__clock", "world clock"),
        ("rx-header__user", "user"),
    ):
        assert marker in header, f"the header has no {what}"
    assert "subscribeConnection(" in header, "the connection state is static"


def test_the_connection_indicator_is_text_plus_chip_never_colour_alone(
    web_sources: dict[str, str]
) -> None:
    """The indicator that tells a reader whether anything is current."""
    header = web_sources["apps/web/src/header.js"]
    assert "CONNECTION_TEXT" in header, "the connection state has no text form"
    assert "renderTruthfulnessChip(token)" in header, "the connection state renders no chip"
    assert "showing the last frame received" in header, (
        "a disconnected stream does not say that what is shown is not current"
    )


def test_the_prompt_bar_is_unavailable_with_a_reason_not_a_dead_input(
    web_sources: dict[str, str]
) -> None:
    """A model-dependent feature renders UNAVAILABLE with the reason (RX-22, RX-32)."""
    header = web_sources["apps/web/src/header.js"]
    prompt = header[header.index("rx-header__prompt") :]
    assert "renderUnavailableFeature(" in prompt
    # The sentence is written across a `' + '` join, so search the MERGED text:
    # the check should test what the reader sees, not how the source is wrapped.
    joined = checks.join_js_concatenations(prompt)
    assert "No provider is configured" in joined, joined[:300]
    assert "<input" not in header and "type: 'text'" not in header, (
        "a text input that cannot produce a plan is worse than no input"
    )


def test_the_shell_declares_all_five_regions(web_sources: dict[str, str]) -> None:
    """Header, left nav, centre surface, right inspector, bottom console."""
    shell = web_sources["apps/web/src/shell.js"]
    for marker in (
        "rx-shell__header",
        "rx-shell__nav",
        "rx-slot--centre",
        "rx-slot--right",
        "rx-slot--bottom",
    ):
        assert marker in shell, f"the shell has no {marker} region"
    assert "renderInspector(" in shell, "the right column has no context inspector"
    assert "renderConsole(" in shell, "the bottom bar has no timeline or console"


def test_the_layout_is_persisted_per_route_and_rehydrated(
    web_sources: dict[str, str], ui_sources: dict[str, str]
) -> None:
    """Panel positions survive a reload, and a stored layout is not trusted."""
    layout = ui_sources["packages/ui/src/layout.js"]
    assert "retrace.layout.${this.routeId}" in layout, "the layout key is not per route"
    assert "storage.setItem(this.storageKey" in layout
    for method in ("reorder", "resize", "collapse", "pin"):
        body_start = layout.index(f"  {method}(")
        body = layout[body_start : body_start + 900]
        assert "this.persist();" in body, f"{method} does not persist the layout"
    assert "if (!panel) continue;" in layout, (
        "hydrate() does not discard unknown panel ids from storage"
    )
    shell = web_sources["apps/web/src/shell.js"]
    assert "model.hydrate()" in shell, "the shell never restores the saved layout"


def test_storage_access_is_guarded_everywhere_it_happens(
    ui_sources: dict[str, str], web_sources: dict[str, str]
) -> None:
    """`localStorage` throws rather than returning null in a private window.

    An unguarded read would take the whole workspace down for a reader whose
    browser blocks site data - a preference failure escalated into a blank page.
    """
    for path, source in {**ui_sources, **web_sources}.items():
        # Comments first. theme.js explains IN A DOCSTRING that it wraps storage
        # in try/catch, and scanning raw text flagged that explanation as the
        # offence - the same "prose is not a use" trap that bit the runner
        # surface scan. Both localStorage calls there are in fact guarded.
        code = checks.strip_js_comments(source)
        if "localStorage" not in code:
            continue
        for match in re.finditer(r"localStorage", code):
            window = code[max(0, match.start() - 400) : match.start() + 200]
            assert "try {" in window, (
                f"{path} touches localStorage outside a try/catch at offset {match.start()}"
            )


def test_every_surface_state_carries_a_reason(
    ui_sources: dict[str, str], web_sources: dict[str, str]
) -> None:
    """An unexplained blank panel tells the reader nothing about what is missing."""
    for path, source in {**ui_sources, **web_sources}.items():
        problems = checks.surface_state_reason_violations(source)
        assert problems == [], f"{path}:\n" + "\n".join(problems)


def test_the_nine_required_surface_states_all_exist(ui_sources: dict[str, str]) -> None:
    """docs/UX.md: empty, loading, error, offline, stale, replay, partial,
    permission-denied, needs-configuration."""
    states = ui_sources["packages/ui/src/states.js"]
    required = (
        "empty",
        "loading",
        "error",
        "offline",
        "stale",
        "replay",
        "partial",
        "permission-denied",
        "needs-configuration",
    )
    for state in required:
        assert re.search(rf"(?m)^  '?{re.escape(state)}'?:\s*Object\.freeze", states), (
            f"no {state} surface state is defined"
        )


def test_model_dependent_features_render_unavailable_with_a_requirement(
    web_sources: dict[str, str]
) -> None:
    """RX-40: absence reports NEEDS_CONFIGURATION, never a simulated success."""
    callers = [
        path for path, source in web_sources.items() if "renderUnavailableFeature(" in source
    ]
    assert len(callers) >= 5, (
        f"only {len(callers)} surfaces declare an unavailable feature; the journey depends on "
        "several things this build has not got, and each should say so"
    )
    for path, source in web_sources.items():
        for match in re.finditer(r"renderUnavailableFeature\(", source):
            # call_at, not enclosing_call: the latter searches backwards and
            # returns '' for the first occurrence in a file, which made
            # `"reason:" in call` false for a call that does pass a reason.
            call = checks.call_at(source, match.start(), "renderUnavailableFeature(")
            assert "reason:" in call, f"{path}: an unavailable feature with no reason"
            assert "feature:" in call, f"{path}: an unavailable feature with no name"


def test_the_timeline_is_populated_only_by_real_events(web_sources: dict[str, str]) -> None:
    """A fabricated history is indistinguishable from a real one at a glance."""
    console = web_sources["apps/web/src/console.js"]
    assert "const entries" in console
    assert "entries.push(entry)" in console
    assert "setUnavailable" in console, "there is no state for having no event stream"
    shell = web_sources["apps/web/src/shell.js"]
    assert "openEventStream((event)" in shell, "the console is not fed from the event stream"

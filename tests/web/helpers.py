"""Planted violations for the negative controls (RX-19 .. RX-25).

Every builder here takes REAL source text and returns a mutated copy, in memory
only. Nothing is written to the repository and nothing on disk is changed, so a
violation exists exactly as long as the assertion that proves the checker sees
it.

WHY MUTATE THE REAL SOURCE RATHER THAN HAND-WRITE A FIXTURE. A hand-written
fixture drifts: it keeps failing the checker long after the real file has
changed shape, and it can be written in a form the checker happens to catch
while the real file would not be. Mutating the real text means each negative
control is a question about the file that actually ships: "if this exact
property were removed from this exact file, would the check notice?"

Every builder asserts that its own mutation changed something. A planter that
silently matched nothing would make its negative control pass vacuously, which
is the failure mode the controls exist to rule out.
"""

from __future__ import annotations


def _require_changed(before: str, after: str, what: str) -> str:
    assert before != after, f"the planter for {what} matched nothing; its control would be vacuous"
    return after


def css_token_only_in_dark(
    tokens_css: str, custom_property: str = "--state-reproduced"
) -> str:
    """Delete a token from bare ``:root``, leaving it defined only in dark.

    The failure this models is the one that actually happens: someone adds a
    colour while working in dark mode and never notices that every light reader
    now gets an unstyled state label.
    """
    root_end = tokens_css.index("@media (prefers-color-scheme: dark)")
    head = tokens_css[:root_end]
    tail = tokens_css[root_end:]
    pruned = "\n".join(
        line for line in head.splitlines() if f"  {custom_property}:" not in line
    )
    return _require_changed(
        tokens_css, pruned + "\n" + tail, f"{custom_property} missing from :root"
    )


def css_unguarded_dark_block(tokens_css: str) -> str:
    """Target bare ``:root`` inside the dark media query, dropping the guard."""
    return _require_changed(
        tokens_css,
        tokens_css.replace(':root:not([data-theme="light"]) {', ":root {", 1),
        "unguarded dark media block",
    )


def css_without_data_theme_dark(tokens_css: str) -> str:
    """Remove the explicit ``:root[data-theme="dark"]`` block entirely."""
    start = tokens_css.index(':root[data-theme="dark"] {')
    end = tokens_css.index("\n}", start) + 2
    return _require_changed(
        tokens_css, tokens_css[:start] + tokens_css[end:], "missing [data-theme=dark] block"
    )


def css_with_literal_colour(css: str) -> str:
    """Replace a token reference with a hard-coded hex value."""
    return _require_changed(
        css,
        css.replace("background: var(--surface-panel);", "background: #ffffff;", 1),
        "literal colour in a component stylesheet",
    )


def css_state_colour_outside_namespace(components_css: str) -> str:
    """Tint an unrelated selector by outcome colour - colour-only encoding."""
    injected = (
        "\n.rx-table tr[data-outcome] {\n"
        "  background: var(--state-reproduced);\n"
        "}\n"
    )
    return _require_changed(
        components_css, components_css + injected, "state colour outside .rx-outcome"
    )


def js_outcome_label_shortened(outcome_js: str) -> str:
    """Shorten the reproduced label to "Reproduced"."""
    return _require_changed(
        outcome_js,
        outcome_js.replace("label: 'Reproduced within contract'", "label: 'Reproduced'", 1),
        "shortened reproduced label",
    )


def js_outcome_label_removed(outcome_js: str) -> str:
    """Remove a label, leaving icon and colour to carry the state."""
    return _require_changed(
        outcome_js,
        outcome_js.replace("    label: 'Changed result',\n", "", 1),
        "outcome with no text label",
    )


def js_outcome_icon_removed(outcome_js: str) -> str:
    """Remove the icon, leaving text and colour only."""
    return _require_changed(
        outcome_js,
        outcome_js.replace("    icon: 'diverged',\n", "", 1),
        "outcome with no icon",
    )


def js_bare_tick_label(outcome_js: str) -> str:
    """Replace the label with a bare tick - the exact thing T10 control 1 names."""
    return _require_changed(
        outcome_js,
        outcome_js.replace("label: 'Reproduced within contract'", "label: '✓'", 1),
        "bare tick as an outcome label",
    )


def ops_without_keys(operations_js: str) -> str:
    """Remove the key combinations from a drag operation."""
    return _require_changed(
        operations_js,
        operations_js.replace(
            "    keys: Object.freeze(['Alt+ArrowUp', 'Alt+ArrowDown']),",
            "    keys: Object.freeze([]),",
            1,
        ),
        "drag operation with no keyboard path",
    )


def ops_without_menu(operations_js: str) -> str:
    """Remove the menu availability from a drag operation."""
    return _require_changed(
        operations_js,
        operations_js.replace(
            "    keys: Object.freeze(['Alt+Shift+ArrowUp', 'Alt+Shift+ArrowDown']),\n"
            "    menu: true,",
            "    keys: Object.freeze(['Alt+Shift+ArrowUp', 'Alt+Shift+ArrowDown']),\n"
            "    menu: false,",
            1,
        ),
        "drag operation with no non-drag pointer path",
    )


def panel_handle_without_menu_mention(panel_js: str) -> str:
    """Strip the menu path out of a drag handle's accessible name."""
    return _require_changed(
        panel_js,
        panel_js.replace(", or use the panel menu.`", "`"),
        "drag handle whose name omits the menu path",
    )


def panel_menu_not_from_table(panel_js: str) -> str:
    """Build the menu from a hand-written subset instead of the table."""
    return _require_changed(
        panel_js,
        panel_js.replace("PANEL_OPERATION_IDS.map(", "['collapse'].map(", 1),
        "panel menu built from a hand-written subset",
    )


def provenance_takes_a_freshness_value(provenance_js: str) -> str:
    """Add a freshness value to the provenance vocabulary - the conflation."""
    injected = (
        "  STALE: Object.freeze({\n"
        "    label: 'Stale',\n"
        "    truthToken: 'STALE',\n"
        "    icon: 'synthetic',\n"
        "    detail: 'old',\n"
        "  }),\n"
    )
    anchor = "export const DATA_PROVENANCE = Object.freeze({\n"
    return _require_changed(
        provenance_js,
        provenance_js.replace(anchor, anchor + injected, 1),
        "freshness value inside the provenance vocabulary",
    )


def provenance_imports_freshness(provenance_js: str) -> str:
    """Make provenance depend on freshness."""
    return _require_changed(
        provenance_js,
        "import { EVENT_FRESHNESS } from './freshness.js';\n" + provenance_js,
        "provenance importing freshness",
    )


def conflated_single_label(source: str) -> str:
    """Add one label that carries both attributes at once."""
    return _require_changed(
        source,
        source + "\nconst conflated = 'SYNTHETIC / STALE';\n",
        "one label carrying provenance and freshness together",
    )


def view_calls_fetch(view_js: str) -> str:
    """Make a view reach the network directly, bypassing the client."""
    return _require_changed(
        view_js,
        view_js + "\nconst rogue = await fetch('/v1/runs/1');\n",
        "a network call outside the client module",
    )


def view_uses_inner_html(view_js: str) -> str:
    """Set markup from data instead of building nodes."""
    return _require_changed(
        view_js,
        view_js + "\nhost.innerHTML = untrusted;\n",
        "markup assignment from data",
    )


def surface_state_without_reason(view_js: str) -> str:
    """Render a blank surface state with no explanation."""
    return _require_changed(
        view_js,
        view_js + "\nconst silent = renderSurfaceState('empty', { title: 'Nothing' });\n",
        "a surface state with no reason",
    )

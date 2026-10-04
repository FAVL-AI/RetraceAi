"""Panel operations: keyboard and menu paths for every drag (RX-21, RX-23).

docs/UX.md: "Every drag operation must also have a keyboard path and a
menu/click path (RX-21) - WCAG's non-drag pointer requirement and keyboard
operability are separate obligations and both apply."

They are checked separately here for that reason. WCAG 2.1.1 (Keyboard) and
WCAG 2.5.7 (Dragging Movements) are different success criteria: a keyboard
shortcut does not help a pointer user who cannot drag, and a menu item does not
help a keyboard-only user if it cannot be reached from the keyboard. A single
"accessible alternative exists" assertion would hide the failure of either one.

WHAT IS NOT PROVEN HERE. That pressing Alt+ArrowUp moves a panel on a rendered
page. No browser, no DOM and no driver exist in this suite, so these tests
assert the structures - one model entry point, a table declaring both paths, a
menu built from the whole table, a keydown handler resolving through the table,
and drag handles whose accessible names name both alternatives.
"""

from __future__ import annotations

import checks
from retrace_contracts.ui_plan import PROTECTED_REGION_IDS


def test_every_operation_declares_a_keyboard_path_and_a_menu_path(
    ui_sources: dict[str, str]
) -> None:
    """The two obligations, asserted as two separate conditions."""
    operations = checks.parse_panel_operations(
        ui_sources["packages/ui/src/panel-operations.js"]
    )
    assert len(operations) >= 7, f"only {len(operations)} operations parsed: {sorted(operations)}"
    problems = checks.panel_operation_violations(operations)
    assert problems == [], "\n".join(problems)


def test_the_drag_operations_are_identified_as_such(ui_sources: dict[str, str]) -> None:
    """2.5.7 applies to the operations whose pointer affordance IS a drag.

    If nothing were marked `pointer: 'drag'`, the 2.5.7 half of the check would
    pass vacuously - so the set is asserted to be non-empty and to contain the
    operations a pointer actually drags.
    """
    operations = checks.parse_panel_operations(
        ui_sources["packages/ui/src/panel-operations.js"]
    )
    drags = {name for name, entry in operations.items() if entry["pointer"] == "drag"}
    assert drags, "no operation is marked as drag-driven; the 2.5.7 check would be vacuous"
    assert {"reorder", "resize"} <= drags, (
        f"reordering and resizing are drag affordances in this UI; parsed drags: {sorted(drags)}"
    )


def test_every_drag_handle_names_both_alternatives_in_its_accessible_name(
    ui_sources: dict[str, str]
) -> None:
    """A draggable control that is silent about the alternatives is not operable.

    The accessible name is the only part of the affordance a screen-reader user
    receives, so both the keyboard combination and the menu are named there.
    """
    problems = checks.drag_handle_affordance_violations(ui_sources["packages/ui/src/panel.js"])
    assert problems == [], "\n".join(problems)


def test_the_menu_is_built_from_the_whole_operation_table(ui_sources: dict[str, str]) -> None:
    """A hand-written menu subset is how an operation silently loses its 2.5.7 path."""
    problems = checks.menu_coverage_violations(ui_sources["packages/ui/src/panel.js"])
    assert problems == [], "\n".join(problems)


def test_all_three_input_routes_funnel_through_one_model_entry_point(
    ui_sources: dict[str, str]
) -> None:
    """Pointer, keyboard and menu must produce the same state transition.

    If the menu called `model.collapse` while the keyboard called something
    else, the two paths could diverge in behaviour while both existing. They all
    call `applyOperation`, which calls `model.apply`.
    """
    panel = ui_sources["packages/ui/src/panel.js"]
    assert panel.count("applyOperation(model,") >= 4, (
        "fewer than four call sites route through applyOperation; some input path is bypassing it"
    )
    assert "model.apply(operationId, panelId, direction)" in panel
    layout = ui_sources["packages/ui/src/layout.js"]
    assert "apply(operationId, panelId, direction = 1)" in layout, (
        "the layout model has no single entry point for operations"
    )


def test_a_keyboard_combination_exists_for_each_operation_and_resolves_uniquely(
    ui_sources: dict[str, str]
) -> None:
    """Two operations sharing a combination would make one of them unreachable."""
    operations = checks.parse_panel_operations(
        ui_sources["packages/ui/src/panel-operations.js"]
    )
    seen: dict[str, str] = {}
    for name, entry in operations.items():
        for combination in entry["keys"]:
            assert combination not in seen, (
                f"{combination} is claimed by both {seen.get(combination)} and {name}; "
                "operationForKeys returns the first match, so one is unreachable"
            )
            seen[combination] = name
    assert len(seen) >= 9, f"only {len(seen)} key combinations declared"


def test_the_protected_regions_match_the_frozen_contract_layer(
    ui_sources: dict[str, str]
) -> None:
    """RX-23: one list, shared with retrace_contracts, not a second copy."""
    declared = checks.js_string_array(
        ui_sources["packages/ui/src/layout.js"], "PROTECTED_REGION_IDS"
    )
    assert set(declared) == set(PROTECTED_REGION_IDS), (
        f"the UI protects {sorted(declared)}; retrace_contracts protects "
        f"{sorted(PROTECTED_REGION_IDS)}"
    )


def test_the_layout_model_refuses_to_hide_a_protected_region(
    ui_sources: dict[str, str]
) -> None:
    """The refusal lives in the model, not in the menu rendering.

    A guard that only existed in the menu would be bypassed by the keyboard path
    and by a hydrated layout from storage - which is why `collapse`, `float` and
    `hydrate` all consult it.
    """
    layout = ui_sources["packages/ui/src/layout.js"]
    assert "assertNotProtected" in layout
    assert layout.count("assertNotProtected(panel,") >= 2, (
        "fewer than two operations consult the protected-region guard"
    )
    assert "PROTECTED_REGION_HIDDEN" in layout
    hydrate = layout[layout.index("  hydrate()") :]
    assert "PROTECTED_REGION_IDS.includes(panel.region)" in hydrate, (
        "a saved layout is untrusted input; hydrate() does not re-check RX-23 on the way in"
    )


def test_a_generated_plan_hiding_a_protected_region_is_refused(
    ui_sources: dict[str, str]
) -> None:
    """RX-23 applied to a prompt-generated UIPlan, mirroring the server gate."""
    layout = ui_sources["packages/ui/src/layout.js"]
    assert "export function refuseProtectedRegionHiding" in layout
    body = layout[layout.index("export function refuseProtectedRegionHiding") :]
    assert "hidden_region_ids" in body, "the plan's hidden_region_ids list is not consulted"
    assert "PROTECTED_REGION_MISSING" in body, "a plan omitting every region is not refused"


def test_every_route_carries_all_three_protected_regions(web_sources: dict[str, str]) -> None:
    """A new route cannot be added without them, because one helper appends them."""
    routes = web_sources["apps/web/src/routes.js"]
    assert "function withProtectedRegions" in routes
    for region in PROTECTED_REGION_IDS:
        assert f"region: '{region}'" in routes, f"no route declares the {region} region"
    assert routes.count("panels: withProtectedRegions([") == 13, (
        "not every one of the thirteen routes appends the protected regions"
    )

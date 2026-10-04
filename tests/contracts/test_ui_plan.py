"""The UI plan rejection gate (RX-22, RX-23).

Every forbidden case the requirement names gets its own negative control, and
the positive controls prove the gate is not simply refusing everything.

"""

from __future__ import annotations

from typing import Any

import pytest
from contracts_support import ALLOWLISTS, build_component, build_plan, protected_components
from retrace_contracts import (
    PROTECTED_REGION_IDS,
    UIAllowlists,
    UIComponent,
    UIPlan,
    UIPlanRejected,
    UIPlanRejectionReason,
    validate_ui_plan,
)


def expect_rejection(plan: UIPlan, reason: UIPlanRejectionReason, **policy: Any) -> UIPlanRejected:
    """Assert the plan is refused with ``reason`` and return the exception."""
    allowlists = ALLOWLISTS.model_copy(update=policy) if policy else ALLOWLISTS
    with pytest.raises(UIPlanRejected) as caught:
        validate_ui_plan(plan, allowlists)
    assert caught.value.reason == reason.value, (
        f"expected {reason.value}, got {caught.value.reason}: {caught.value}"
    )
    return caught.value


# --- positive controls ------------------------------------------------------


def test_protected_region_ids_are_exactly_the_three_specified() -> None:
    """RX-23: the protected set is security context, approval, truthfulness."""
    assert PROTECTED_REGION_IDS == frozenset(
        {"security-context", "approval-controls", "truthfulness-labels"}
    )


def test_a_well_formed_plan_is_accepted() -> None:
    """RX-22 positive control: the gate accepts a legitimate plan."""
    assert validate_ui_plan(build_plan(), ALLOWLISTS) is None


def test_a_non_protected_region_may_be_hidden() -> None:
    """RX-23 positive control: only the protected regions are protected."""
    plan = build_plan(hidden_region_ids=("sidebar", "minimap"))
    assert validate_ui_plan(plan, ALLOWLISTS) is None


def test_ordinary_prose_with_the_word_select_in_a_title_is_allowed() -> None:
    """RX-22 positive control: a bare SQL keyword is not a SQL statement."""
    plan = build_plan(
        components=(build_component(title="Selected runs"), *protected_components())
    )
    assert validate_ui_plan(plan, ALLOWLISTS) is None


def test_bidi_marks_needed_for_rtl_identifiers_are_allowed() -> None:
    """RX-28 positive control: LRM/RLM are not treated as control characters.

    RX-28 requires LTR scientific identifiers inside RTL text, which needs these
    marks. Only bidi *overrides* (the Trojan-Source reordering characters) are
    refused.
    """
    plan = build_plan(
        components=(
            build_component(title="‏متوسط الكتلة‎ mean_body_mass‏"),
            *protected_components(),
        )
    )
    assert validate_ui_plan(plan, ALLOWLISTS) is None


# --- allowlist refusals -----------------------------------------------------


def test_unknown_component_type_is_refused() -> None:
    """RX-22: a component type outside the allowlist is refused."""
    plan = build_plan(
        components=(
            build_component(component_type="raw-html-embed"),
            *protected_components(),
        )
    )
    error = expect_rejection(plan, UIPlanRejectionReason.COMPONENT_NOT_ALLOWLISTED)
    assert "raw-html-embed" in str(error)


def test_unauthorised_query_id_is_refused() -> None:
    """RX-22: a query id the server has not authorised is refused."""
    plan = build_plan(
        components=(build_component(query_id="q.all-tenants"), *protected_components())
    )
    expect_rejection(plan, UIPlanRejectionReason.QUERY_NOT_AUTHORISED)


def test_unregistered_action_is_refused() -> None:
    """RX-22: an action outside the registry is refused."""
    plan = build_plan(
        components=(
            build_component(action_id="a.force-approve"),
            *protected_components(),
        )
    )
    expect_rejection(plan, UIPlanRejectionReason.ACTION_NOT_REGISTERED)


# --- injection refusals -----------------------------------------------------


SCRIPT_PAYLOADS = [
    "<script>steal()</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:void(0)",
    "eval('1+1')",
    "document.cookie",
    "window.location = '/'",
    "fetch('/api/keys')",
    "${constructor.constructor('x')()}",
    "<iframe src=//evil></iframe>",
    "data:text/html;base64,PHNjcmlwdD4=",
]


@pytest.mark.parametrize("payload", SCRIPT_PAYLOADS)
def test_raw_javascript_in_a_title_is_refused(payload: str) -> None:
    """RX-22: executable payload shapes in any field are refused."""
    plan = build_plan(
        components=(build_component(title=payload), *protected_components())
    )
    expect_rejection(plan, UIPlanRejectionReason.SCRIPT_INJECTION)


def test_raw_javascript_in_a_prop_value_is_refused() -> None:
    """RX-22: props are untrusted too."""
    plan = build_plan(
        components=(
            build_component(props={"caption": "<script>x()</script>"}),
            *protected_components(),
        )
    )
    expect_rejection(plan, UIPlanRejectionReason.SCRIPT_INJECTION)


def test_raw_javascript_in_a_prop_key_is_refused() -> None:
    """RX-22: the key can be the vector even when the value looks innocent."""
    plan = build_plan(
        components=(
            build_component(props={"onclick": "goToRun()"}),
            *protected_components(),
        )
    )
    error = expect_rejection(plan, UIPlanRejectionReason.SCRIPT_INJECTION)
    assert "onclick" in str(error)


@pytest.mark.parametrize("key", ["dangerouslySetInnerHTML", "innerHTML", "srcdoc", "formaction"])
def test_renderer_executing_prop_keys_are_refused(key: str) -> None:
    """RX-22: prop keys that bind markup or behaviour are refused on sight."""
    plan = build_plan(
        components=(build_component(props={key: "value"}), *protected_components())
    )
    expect_rejection(plan, UIPlanRejectionReason.SCRIPT_INJECTION)


def test_javascript_in_the_source_prompt_is_refused() -> None:
    """RX-22: the provenance field is untrusted input like every other string."""
    plan = build_plan(source_prompt="render the table <script>exfiltrate()</script>")
    expect_rejection(plan, UIPlanRejectionReason.SCRIPT_INJECTION)


def test_javascript_in_a_component_id_is_refused() -> None:
    """RX-22: ids are rendered too, so they are scanned too."""
    plan = build_plan(
        components=(
            build_component(component_id="cmp-<script>x</script>"),
            *protected_components(),
        )
    )
    expect_rejection(plan, UIPlanRejectionReason.SCRIPT_INJECTION)


SQL_PAYLOADS = [
    "SELECT secret FROM credentials",
    "1; DROP TABLE approvals",
    "' UNION ALL SELECT password FROM users --",
    "DELETE FROM snapshots",
    "INSERT INTO approvals VALUES (1)",
    "UPDATE contracts SET approved = true",
    "' OR 1=1 --",
    "SELECT pg_sleep(10)",
    "GRANT ALL ON approvals TO public",
]


@pytest.mark.parametrize("payload", SQL_PAYLOADS)
def test_raw_sql_in_a_field_is_refused(payload: str) -> None:
    """RX-22: SQL statement shapes in any field are refused."""
    plan = build_plan(
        components=(build_component(title=payload), *protected_components())
    )
    expect_rejection(plan, UIPlanRejectionReason.SQL_INJECTION)


def test_raw_sql_in_a_query_id_is_refused_before_the_allowlist_check() -> None:
    """RX-22: the documented check order puts string safety before authority."""
    plan = build_plan(
        components=(
            build_component(query_id="SELECT * FROM users"),
            *protected_components(),
        )
    )
    expect_rejection(plan, UIPlanRejectionReason.SQL_INJECTION)


@pytest.mark.parametrize(
    "payload",
    [
        "label\x00truncated",
        "line\nbreak",
        "tab\tseparated",
        "‮override",
        "⁦isolate",
        " separator",
    ],
)
def test_control_and_bidi_override_characters_are_refused(payload: str) -> None:
    """RX-22: control characters and Trojan-Source reordering marks are refused."""
    plan = build_plan(
        components=(build_component(title=payload), *protected_components())
    )
    expect_rejection(plan, UIPlanRejectionReason.CONTROL_CHARACTERS)


def test_over_long_field_is_refused() -> None:
    """RX-22: an unbounded string is a resource and rendering hazard."""
    plan = build_plan(
        components=(build_component(title="x" * 2001), *protected_components())
    )
    expect_rejection(plan, UIPlanRejectionReason.FIELD_TOO_LONG)


# --- protected region refusals ---------------------------------------------


@pytest.mark.parametrize("region", sorted(PROTECTED_REGION_IDS))
def test_explicitly_hiding_a_protected_region_is_refused(region: str) -> None:
    """RX-23: each protected region is refused individually."""
    plan = build_plan(hidden_region_ids=(region,))
    error = expect_rejection(plan, UIPlanRejectionReason.PROTECTED_REGION_HIDDEN)
    assert region in str(error)


def test_hiding_a_protected_region_component_is_refused() -> None:
    """RX-23: the hidden flag on a protected component is refused."""
    components = list(protected_components())
    components[1] = components[1].model_copy(update={"hidden": True})
    plan = build_plan(components=(build_component(), *components))
    expect_rejection(plan, UIPlanRejectionReason.PROTECTED_REGION_HIDDEN)


@pytest.mark.parametrize(
    "props",
    [
        {"display": "none"},
        {"visibility": "hidden"},
        {"aria-hidden": True},
        {"opacity": 0},
        {"visible": False},
        {"style": "display:none"},
        {"class": "d-none"},
        {"className": "sr-only"},
        {"collapsed": "true"},
    ],
)
def test_css_shaped_hiding_of_a_protected_region_is_refused(props: dict[str, Any]) -> None:
    """RX-23: hiding by prop is hiding, however it is spelled."""
    components = list(protected_components())
    components[1] = components[1].model_copy(update={"props": props})
    plan = build_plan(components=(build_component(), *components))
    expect_rejection(plan, UIPlanRejectionReason.PROTECTED_REGION_HIDDEN)


def test_hiding_an_ancestor_of_a_protected_region_is_refused() -> None:
    """RX-23: hiding the parent hides the child, and is refused as such."""
    wrapper = UIComponent(
        component_id="cmp-wrapper",
        component_type="panel",
        region_id="main",
        hidden=True,
        children=protected_components(),
    )
    plan = build_plan(components=(build_component(), wrapper))
    error = expect_rejection(plan, UIPlanRejectionReason.PROTECTED_REGION_HIDDEN)
    assert "hidden ancestor" in str(error)


def test_omitting_a_protected_region_is_refused_by_default() -> None:
    """RX-23: an omitted protected region is treated as a hidden one."""
    plan = build_plan(components=(build_component(),))
    error = expect_rejection(plan, UIPlanRejectionReason.PROTECTED_REGION_MISSING)
    assert "approval-controls" in str(error)


def test_omission_is_permitted_only_by_explicit_server_policy() -> None:
    """RX-23: the escape hatch exists, defaults off, and must be set by the server."""
    assert UIAllowlists.model_fields["require_protected_regions"].default is True
    plan = build_plan(components=(build_component(),))
    permissive = ALLOWLISTS.model_copy(update={"require_protected_regions": False})
    assert validate_ui_plan(plan, permissive) is None


def test_protected_region_nested_inside_a_visible_parent_is_accepted() -> None:
    """RX-23 positive control: nesting alone is not hiding."""
    wrapper = UIComponent(
        component_id="cmp-wrapper",
        component_type="panel",
        region_id="main",
        children=protected_components(),
    )
    plan = build_plan(components=(build_component(), wrapper))
    assert validate_ui_plan(plan, ALLOWLISTS) is None


# --- structural refusals ----------------------------------------------------


def test_empty_plan_is_refused() -> None:
    """RX-23: a plan that renders nothing renders no protected region either."""
    expect_rejection(build_plan(components=()), UIPlanRejectionReason.EMPTY_PLAN)


def test_duplicate_component_ids_are_refused() -> None:
    """RX-22: ambiguous component ids make a plan unreviewable."""
    plan = build_plan(
        components=(build_component(), build_component(), *protected_components())
    )
    expect_rejection(plan, UIPlanRejectionReason.DUPLICATE_COMPONENT_ID)


def test_oversize_plan_is_refused() -> None:
    """RX-22: plan size is bounded; generated layouts are not unbounded input."""
    many = tuple(
        build_component(component_id=f"cmp-{index}", title=f"Panel {index}")
        for index in range(12)
    )
    plan = build_plan(components=(*many, *protected_components()))
    expect_rejection(plan, UIPlanRejectionReason.PLAN_TOO_LARGE, max_components=10)


def test_over_deep_plan_is_refused() -> None:
    """RX-22: nesting depth is bounded."""
    node = build_component(component_id="cmp-leaf")
    for index in range(4):
        node = UIComponent(
            component_id=f"cmp-wrap-{index}",
            component_type="panel",
            region_id="main",
            children=(node,),
        )
    plan = build_plan(components=(node, *protected_components()))
    expect_rejection(plan, UIPlanRejectionReason.PLAN_TOO_DEEP, max_depth=3)


# --- gate contract ----------------------------------------------------------


def test_a_dict_that_looks_like_a_plan_is_not_accepted_as_one() -> None:
    """RX-22 negative control: unvalidated input cannot reach the gate's output."""
    with pytest.raises(TypeError):
        validate_ui_plan({"plan_id": "plan-0001"}, ALLOWLISTS)  # type: ignore[arg-type]


def test_a_dict_policy_is_not_accepted_as_allowlists() -> None:
    """RX-22 negative control: policy must be the typed server-side record."""
    with pytest.raises(TypeError):
        validate_ui_plan(build_plan(), {"components": {"evidence-table"}})  # type: ignore[arg-type]


def test_rejection_carries_a_machine_readable_reason_and_path() -> None:
    """RX-22: the reviewer is told which rule refused the plan, and where."""
    plan = build_plan(
        components=(build_component(component_type="raw-html-embed"), *protected_components())
    )
    error = expect_rejection(plan, UIPlanRejectionReason.COMPONENT_NOT_ALLOWLISTED)
    assert error.path is not None
    assert "component_type" in error.path
    assert error.detail is not None


def test_every_rejection_reason_is_a_closed_enum_member() -> None:
    """RX-22: rejection reasons come from a closed vocabulary."""
    assert len(UIPlanRejectionReason) == 13
    with pytest.raises(ValueError):
        UIPlanRejectionReason("BECAUSE_I_SAID_SO")

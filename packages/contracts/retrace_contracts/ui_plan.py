"""Declarative UI plans and their rejection gate (RX-22, RX-23).

A prompt-generated layout is untrusted input that happens to look like
configuration. This module treats it that way: the models are deliberately
*permissive* about string content so that a hostile plan can be represented and
then refused by one explicit gate, :func:`validate_ui_plan`, which raises
:class:`~retrace_contracts.exceptions.UIPlanRejected` with a specific
:class:`~retrace_contracts.enums.UIPlanRejectionReason`.

Putting the refusals in the model validators instead would mean a hostile plan
could not be constructed, which sounds safer but is worse: the rejection would
surface as a generic validation error, the reviewer would not be told which rule
refused it, and the gate itself could never be tested against the payloads it
exists to stop.

Checks run in a fixed, documented order so a given plan always produces the
same reason:

1. structural -- empty plan, size, depth, duplicate component ids
2. string safety -- control characters, over-long fields, script, SQL
3. authority -- component allowlist, query allowlist, action registry
4. protected regions -- hidden, or missing entirely

Protected regions (RX-23) are ``security-context``, ``approval-controls`` and
``truthfulness-labels``. They cannot be hidden directly, cannot be hidden by
CSS-shaped props, and cannot be hidden by hiding an ancestor.

"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Annotated, Any, ClassVar, Final

from pydantic import Field, StringConstraints

from .base import FrozenRecord
from .enums import UIPlanRejectionReason
from .exceptions import UIPlanRejected

__all__ = [
    "PROTECTED_REGION_IDS",
    "UIAllowlists",
    "UIComponent",
    "UIPlan",
    "validate_ui_plan",
]

PROTECTED_REGION_IDS: Final[frozenset[str]] = frozenset(
    {"security-context", "approval-controls", "truthfulness-labels"}
)
"""Regions a generated layout may never hide or omit (RX-23)."""

UntrustedStr = Annotated[str, StringConstraints(min_length=1, max_length=65_536)]
"""A string from an untrusted plan. Bounded only; content is judged by the gate."""

PropValue = str | int | float | bool | None

# --- string-safety patterns -------------------------------------------------
# Control characters, C1, line/paragraph separators (JS string-break vectors)
# and bidirectional *override* characters (Trojan-Source style reordering).
# U+200E/U+200F (LRM/RLM) are deliberately NOT forbidden: RX-28 requires
# mixed-direction scientific identifiers inside RTL text, which needs them.
_FORBIDDEN_CODEPOINTS: Final[frozenset[str]] = frozenset(
    [chr(code) for code in range(0x00, 0x20)]
    + [chr(0x7F)]
    + [chr(code) for code in range(0x80, 0xA0)]
    + [" ", " "]
    + [chr(code) for code in range(0x202A, 0x202F)]
    + [chr(code) for code in range(0x2066, 0x206A)]
)

_SCRIPT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"<\s*/?\s*script\b",
        r"<\s*(iframe|object|embed|svg|math|link|meta|base)\b",
        r"javascript\s*:",
        r"vbscript\s*:",
        r"data\s*:\s*text/html",
        r"\bon[a-z]{3,20}\s*=",
        r"\beval\s*\(",
        r"\bnew\s+Function\s*\(",
        r"\b(setTimeout|setInterval)\s*\(",
        r"\bdocument\s*\.\s*(cookie|write|location|domain)",
        r"\bwindow\s*\.\s*(location|open|parent|top|name)",
        r"\blocalStorage\b|\bsessionStorage\b",
        r"\bfetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\s*\(",
        r"\b(import|require)\s*\(",
        r"\$\{",
        r"&#x?0*6[aA]avascript",
    )
)

# SQL patterns require *structure* (two co-occurring tokens or a known
# injection idiom), not a bare keyword. A bare "select" in a label is ordinary
# English; "SELECT ... FROM" in a layout field is not. This gate fails closed:
# a legitimate label such as "Select rows from cohort" will be refused, and the
# author must reword it. That trade-off is deliberate and recorded in
# `KNOWN_GATE_LIMITS`.
_SQL_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bselect\b[\s\S]{0,200}?\bfrom\b",
        r"\bunion\b\s+(all\s+)?\bselect\b",
        r"\binsert\b\s+\binto\b",
        r"\bdelete\b\s+\bfrom\b",
        r"\bupdate\b[\s\S]{0,200}?\bset\b",
        r"\b(drop|truncate|alter)\b\s+\b(table|database|schema|view|index|role)\b",
        r"\bcreate\b\s+\b(table|database|schema|view|index|function|role)\b",
        r"\bgrant\b[\s\S]{0,80}?\bto\b",
        r"\binformation_schema\b|\bpg_catalog\b|\bsqlite_master\b|\bpg_sleep\s*\(",
        r"\bxp_cmdshell\b|\bcopy\b[\s\S]{0,80}?\bfrom\s+program\b",
        r";\s*--",
        r"/\*[\s\S]*?\*/",
        r"\bor\b\s+['\"]?1['\"]?\s*=\s*['\"]?1",
    )
)

# A prop *key* can be the injection vector even when its value looks innocent:
# `{"onclick": "go()"}` carries no payload shape the value scan would match, but
# a renderer that spreads props onto a DOM node has just bound an event handler.
# These keys are refused on sight. Checked against keys only, never against free
# text, so a legitimate title such as "online calibration" is unaffected.
_FORBIDDEN_PROP_KEY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^on[a-z]{3,20}$",
        r"^dangerously",
        r"^(inner|outer)html$",
        r"^srcdoc$",
        r"^(formaction|xlink:href)$",
    )
)

_HIDING_PROP_KEYS: Final[frozenset[str]] = frozenset(
    {"hidden", "ishidden", "aria-hidden", "ariahidden", "visible", "isvisible", "display",
     "visibility", "opacity", "collapsed", "iscollapsed"}
)
_HIDING_STYLE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"display\s*:\s*none",
        r"visibility\s*:\s*(hidden|collapse)",
        r"opacity\s*:\s*0(\.0+)?\b",
        r"(^|\s)(d-none|hidden|invisible|sr-only|visually-hidden)(\s|$)",
    )
)
_STYLE_PROP_KEYS: Final[frozenset[str]] = frozenset({"style", "class", "classname", "css"})


class UIComponent(FrozenRecord):
    """One node of a declarative layout plan (RX-22).

    String fields are bounded but otherwise unconstrained, because this record
    must be able to *hold* a hostile value so that :func:`validate_ui_plan` can
    refuse it with a specific reason.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.UIComponent"

    component_id: UntrustedStr = Field(description="Id unique within the plan.")
    component_type: UntrustedStr = Field(
        description="Component type; must appear in the allowlist (RX-22)."
    )
    region_id: UntrustedStr | None = Field(
        default=None, description="Layout region this component renders into."
    )
    query_id: UntrustedStr | None = Field(
        default=None, description="Authorised query id this component reads (RX-22)."
    )
    action_id: UntrustedStr | None = Field(
        default=None, description="Registered action id this component invokes (RX-22)."
    )
    title: UntrustedStr | None = Field(default=None, description="Display title.")
    props: dict[str, PropValue] = Field(
        default_factory=dict, description="Component props. Keys and values are untrusted."
    )
    hidden: bool = Field(default=False, description="Whether the component is hidden.")
    children: tuple[UIComponent, ...] = Field(default=(), description="Nested components.")


UIComponent.model_rebuild()


class UIAllowlists(FrozenRecord):
    """Server-side policy the plan is judged against (RX-22, RX-23).

    This object is policy, not plan: it is supplied by the server, never by the
    prompt. ``require_protected_regions`` defaults to ``True`` -- omitting a
    protected region is treated as hiding it, because a reviewer who cannot see
    the approval controls is in the same position either way. Setting it
    ``False`` is a deliberate policy decision and must be justified by whoever
    sets it.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.UIAllowlists"

    components: frozenset[str] = Field(description="Permitted component types.")
    query_ids: frozenset[str] = Field(
        default=frozenset(), description="Authorised query ids."
    )
    action_ids: frozenset[str] = Field(
        default=frozenset(), description="Registered action ids."
    )
    protected_region_ids: frozenset[str] = Field(
        default=PROTECTED_REGION_IDS, description="Regions that may not be hidden (RX-23)."
    )
    require_protected_regions: bool = Field(
        default=True, description="Treat an omitted protected region as hiding it."
    )
    max_components: int = Field(default=200, ge=1, description="Upper bound on plan size.")
    max_depth: int = Field(default=8, ge=1, description="Upper bound on nesting depth.")
    max_field_length: int = Field(default=2000, ge=1, description="Upper bound per string field.")


class UIPlan(FrozenRecord):
    """A declarative, reviewable layout plan (RX-22).

    ``source_prompt`` records the prompt that produced the plan. It is scanned
    as untrusted input like every other string, so an injection carried in the
    provenance field is refused rather than stored and later rendered.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.UIPlan"

    KNOWN_GATE_LIMITS: ClassVar[tuple[str, ...]] = (
        "The SQL gate is pattern-based and fails closed: a legitimate label "
        "such as 'Select rows from cohort' is refused. Authors reword; the gate "
        "is not loosened to accommodate prose.",
        "The script gate matches known executable-payload shapes. It is a "
        "defence in depth, not a proof of safety: rendering must still escape "
        "every value, and this gate must never be the only control.",
        "Hiding detection covers the plan's own declarations (hidden flag, "
        "hidden_region_ids, CSS-shaped props, hidden ancestors). A stylesheet "
        "outside the plan can still hide a region; that is the renderer's "
        "responsibility, not this gate's.",
    )

    plan_id: UntrustedStr = Field(description="Stable id of this plan.")
    plan_version: int = Field(default=1, ge=1, description="Plan version.")
    title: UntrustedStr = Field(description="Human-readable plan title.")
    created_by: UntrustedStr = Field(description="Identity that requested the plan.")
    components: tuple[UIComponent, ...] = Field(
        default=(), description="Root components of the layout."
    )
    hidden_region_ids: tuple[UntrustedStr, ...] = Field(
        default=(), description="Regions the plan explicitly hides."
    )
    source_prompt: UntrustedStr | None = Field(
        default=None, description="The prompt that generated this plan. Untrusted."
    )


def _iter_components(
    components: tuple[UIComponent, ...], depth: int = 1, hidden_ancestor: bool = False
) -> Iterator[tuple[UIComponent, int, bool]]:
    """Yield ``(component, depth, hidden_by_ancestor)`` depth-first (RX-23)."""
    for component in components:
        yield component, depth, hidden_ancestor
        yield from _iter_components(
            component.children,
            depth + 1,
            hidden_ancestor or _declares_hidden(component),
        )


def _iter_strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Yield ``(path, text)`` for every string in a dumped plan, keys included."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for key, item in value.items():
            key_path = f"{path}.{key}"
            if isinstance(key, str):
                yield f"{key_path}<key>", key
            yield from _iter_strings(item, key_path)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for index, item in enumerate(value):
            yield from _iter_strings(item, f"{path}[{index}]")


def _declares_hidden(component: UIComponent) -> bool:
    """Whether a component declares itself hidden, by flag, prop or style (RX-23)."""
    if component.hidden:
        return True
    for key, value in component.props.items():
        lowered = key.strip().lower()
        if lowered in _HIDING_PROP_KEYS:
            if lowered in ("visible", "isvisible"):
                if value is False or (isinstance(value, str) and value.strip().lower() == "false"):
                    return True
                continue
            if lowered == "opacity":
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    if float(value) == 0.0:
                        return True
                elif isinstance(value, str) and value.strip() in ("0", "0.0", "0%"):
                    return True
                continue
            if value is True:
                return True
            if isinstance(value, str) and value.strip().lower() in (
                "true",
                "none",
                "hidden",
                "collapse",
                "yes",
                "1",
            ):
                return True
        if lowered in _STYLE_PROP_KEYS and isinstance(value, str):
            if any(pattern.search(value) for pattern in _HIDING_STYLE_PATTERNS):
                return True
    return False


def _reject(reason: UIPlanRejectionReason, detail: str, path: str | None = None) -> None:
    """Raise :class:`UIPlanRejected` carrying a machine-readable reason."""
    raise UIPlanRejected(reason=reason.value, detail=detail, path=path)


def validate_ui_plan(plan: UIPlan, allowlists: UIAllowlists) -> None:
    """Validate a generated plan, or refuse it with a reason (RX-22, RX-23).

    Parameters
    ----------
    plan:
        The plan to judge. Every string in it is treated as untrusted input.
    allowlists:
        Server-side policy: permitted component types, authorised query ids,
        registered actions, protected regions and resource bounds.

    Returns
    -------
    None:
        The plan is acceptable under this policy. "Acceptable" means it passed
        these rules -- it is not a statement that rendering it is safe without
        escaping.

    Raises
    ------
    TypeError:
        If ``plan`` or ``allowlists`` is not the expected record type. A dict
        that merely looks like a plan has not been validated and must not be
        accepted as one.
    UIPlanRejected:
        With ``reason`` set to the first rule broken, in the order documented at
        module level, plus ``detail`` and ``path`` naming the offending value.
    """
    if not isinstance(plan, UIPlan):
        raise TypeError(f"validate_ui_plan expects a UIPlan, got {type(plan).__name__}")
    if not isinstance(allowlists, UIAllowlists):
        raise TypeError(
            f"validate_ui_plan expects UIAllowlists policy, got {type(allowlists).__name__}"
        )

    # 1. structural
    if not plan.components:
        _reject(
            UIPlanRejectionReason.EMPTY_PLAN,
            "a plan with no components renders nothing and cannot show the protected regions",
            "$.components",
        )

    walked = list(_iter_components(plan.components))
    if len(walked) > allowlists.max_components:
        _reject(
            UIPlanRejectionReason.PLAN_TOO_LARGE,
            f"{len(walked)} components exceeds the limit of {allowlists.max_components}",
            "$.components",
        )
    for component, depth, _ in walked:
        if depth > allowlists.max_depth:
            _reject(
                UIPlanRejectionReason.PLAN_TOO_DEEP,
                f"component {component.component_id!r} is nested {depth} deep; "
                f"the limit is {allowlists.max_depth}",
                "$.components",
            )

    seen: set[str] = set()
    for component, _, _ in walked:
        if component.component_id in seen:
            _reject(
                UIPlanRejectionReason.DUPLICATE_COMPONENT_ID,
                f"component_id {component.component_id!r} appears more than once",
                "$.components",
            )
        seen.add(component.component_id)

    # 2. string safety -- every string field, keys included
    for path, text in _iter_strings(plan.model_dump(mode="python")):
        offending = sorted(_FORBIDDEN_CODEPOINTS.intersection(text))
        if offending:
            codes = ", ".join(f"U+{ord(char):04X}" for char in offending)
            _reject(
                UIPlanRejectionReason.CONTROL_CHARACTERS,
                f"forbidden codepoint(s) {codes}",
                path,
            )
        if len(text) > allowlists.max_field_length:
            _reject(
                UIPlanRejectionReason.FIELD_TOO_LONG,
                f"{len(text)} characters exceeds the field limit of "
                f"{allowlists.max_field_length}",
                path,
            )
        for pattern in _SCRIPT_PATTERNS:
            match = pattern.search(text)
            if match:
                _reject(
                    UIPlanRejectionReason.SCRIPT_INJECTION,
                    f"executable payload shape {match.group(0)!r}",
                    path,
                )
        for pattern in _SQL_PATTERNS:
            match = pattern.search(text)
            if match:
                _reject(
                    UIPlanRejectionReason.SQL_INJECTION,
                    f"SQL statement shape {match.group(0)!r}",
                    path,
                )

    for component, _, _ in walked:
        for key in component.props:
            stripped = key.strip()
            for pattern in _FORBIDDEN_PROP_KEY_PATTERNS:
                if pattern.search(stripped):
                    _reject(
                        UIPlanRejectionReason.SCRIPT_INJECTION,
                        f"prop key {key!r} binds executable behaviour in the renderer",
                        f"$.components[{component.component_id}].props.{key}<key>",
                    )

    # 3. authority
    for component, _, _ in walked:
        if component.component_type not in allowlists.components:
            _reject(
                UIPlanRejectionReason.COMPONENT_NOT_ALLOWLISTED,
                f"component type {component.component_type!r} is not allowlisted",
                f"$.components[{component.component_id}].component_type",
            )
        if component.query_id is not None and component.query_id not in allowlists.query_ids:
            _reject(
                UIPlanRejectionReason.QUERY_NOT_AUTHORISED,
                f"query id {component.query_id!r} is not authorised",
                f"$.components[{component.component_id}].query_id",
            )
        if component.action_id is not None and component.action_id not in allowlists.action_ids:
            _reject(
                UIPlanRejectionReason.ACTION_NOT_REGISTERED,
                f"action id {component.action_id!r} is not in the action registry",
                f"$.components[{component.component_id}].action_id",
            )

    # 4. protected regions
    protected = allowlists.protected_region_ids
    explicitly_hidden = sorted(protected.intersection(plan.hidden_region_ids))
    if explicitly_hidden:
        _reject(
            UIPlanRejectionReason.PROTECTED_REGION_HIDDEN,
            f"plan hides protected region(s): {', '.join(explicitly_hidden)}",
            "$.hidden_region_ids",
        )

    visible_regions: set[str] = set()
    for component, _, hidden_ancestor in walked:
        if component.region_id is None or component.region_id not in protected:
            continue
        if hidden_ancestor:
            _reject(
                UIPlanRejectionReason.PROTECTED_REGION_HIDDEN,
                f"protected region {component.region_id!r} is inside a hidden ancestor",
                f"$.components[{component.component_id}]",
            )
        if _declares_hidden(component):
            _reject(
                UIPlanRejectionReason.PROTECTED_REGION_HIDDEN,
                f"component {component.component_id!r} hides protected region "
                f"{component.region_id!r}",
                f"$.components[{component.component_id}]",
            )
        visible_regions.add(component.region_id)

    if allowlists.require_protected_regions:
        missing = sorted(protected - visible_regions)
        if missing:
            _reject(
                UIPlanRejectionReason.PROTECTED_REGION_MISSING,
                f"plan does not render protected region(s): {', '.join(missing)}",
                "$.components",
            )

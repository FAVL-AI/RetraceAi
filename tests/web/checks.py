"""Structural checkers for the browser workspace (RX-19, RX-21, RX-23, RX-25).

WHY THE CHECKS LIVE IN A MODULE RATHER THAN INSIDE THE TESTS. Every property
asserted about ``apps/web`` and ``packages/ui`` is checked by a function here,
and each function is called twice from the suite: once against the real sources,
where it must find nothing, and once against a source with a violation planted
in it (``tests/web/helpers.py``), where it must find exactly that violation. A
checker that has never been shown to fail is not evidence, and a checker that
only ever runs against passing input cannot distinguish "the property holds"
from "the regex never matched anything".

HONEST LIMIT OF EVERY CHECK BELOW. These are source-level checks. No browser
runs in this suite -- no driver, no DOM, no layout, no axe -- so nothing here
can prove that a key press moves a panel on screen or that a rendered label is
actually visible. What they can prove is that the structures which make those
behaviours possible are present, that the one module allowed to touch the
network is the only one that does, and that the labels the product shows cannot
be written anywhere except through the component that labels them fully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Verification outcomes, in the order docs/UX.md lists them.
OUTCOME_NAMES: tuple[str, ...] = (
    "REPRODUCED_WITHIN_CONTRACT",
    "EXECUTED_NOT_VERIFIED",
    "CHANGED_RESULT",
    "BLOCKED_MISSING_EVIDENCE",
    "FAILED_EXECUTION",
)

#: Outcome -> the CSS custom property docs/UX.md assigns it.
OUTCOME_TOKENS: dict[str, str] = {
    "REPRODUCED_WITHIN_CONTRACT": "--state-reproduced",
    "EXECUTED_NOT_VERIFIED": "--state-unverified",
    "CHANGED_RESULT": "--state-changed",
    "BLOCKED_MISSING_EVIDENCE": "--state-blocked",
    "FAILED_EXECUTION": "--state-failed",
}

#: Browser APIs that reach the network. Permitted in the client module only.
NETWORK_APIS: tuple[str, ...] = (
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "sendBeacon",
)

#: Markup- and code-execution sinks. Permitted nowhere.
UNSAFE_SINKS: tuple[str, ...] = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "new Function(",
    "eval(",
)

#: The data-provenance vocabulary (packages/ui/src/provenance.js).
PROVENANCE_VALUES: tuple[str, ...] = (
    "REAL_RECORDED",
    "SYNTHETIC",
    "DEMO_FIXTURE",
    "INJECTED_FAULT",
)

#: The event-freshness vocabulary (packages/ui/src/freshness.js).
FRESHNESS_VALUES: tuple[str, ...] = ("LIVE", "STALE", "REPLAY", "UNAVAILABLE")

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_QUOTES = "\"'`"


def strip_css_comments(text: str) -> str:
    """Remove ``/* ... */`` comments so a commented-out rule is never counted."""
    return _COMMENT.sub(" ", text)


#: Object keys whose value is text a person reads. The label rules apply to
#: these and not to attribute plumbing: `aria-hidden: 'true'` is not a claim
#: that anything succeeded, and treating it as one would make the checker noise.
LABEL_KEYS: tuple[str, ...] = (
    "label",
    "text",
    "title",
    "detail",
    "qualifier",
    "summary",
    "reason",
    "'aria-label'",
    "legend",
    "gloss",
)


def strip_js_comments(text: str) -> str:
    """Remove JavaScript comments, string- and escape-aware.

    WHY THIS IS NECESSARY RATHER THAN FUSSY. The modules that forbid a string
    have to NAME it: `outcome.js` quotes T10 control 1, which contains the word
    the control prohibits. A checker that scanned comments would fire on the
    file documenting the rule and would then be silenced - which is how a real
    control gets turned into a disabled one. Emitted text always comes from a
    literal in code, so stripping comments loses no coverage.
    """
    out: list[str] = []
    index = 0
    quote = ""
    length = len(text)
    while index < length:
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\":
                if index + 1 < length:
                    out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in _QUOTES:
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            index = length if end == -1 else end + 2
            out.append(" ")
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            end = text.find("\n", index)
            index = length if end == -1 else end
            out.append(" ")
            continue
        out.append(char)
        index += 1
    return "".join(out)


def blank_js_comments(text: str) -> str:
    """Blank comments while PRESERVING offsets and line numbers.

    :func:`strip_js_comments` collapses each comment to a single space, which is
    right for substring checks but shifts every line number after it. A checker
    that reports "line 24" must mean line 24 of the file a reader will open, so
    this variant replaces comment characters with spaces and keeps the newlines.
    """
    stripped = strip_js_comments(text)
    if len(stripped) == len(text):
        return stripped
    out: list[str] = []
    index = 0
    length = len(text)
    quote = ""
    while index < length:
        char = text[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in _QUOTES:
            quote = char
            out.append(char)
            index += 1
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "*":
            end = text.find("*/", index + 2)
            stop = length if end == -1 else end + 2
            out.append("".join("\n" if c == "\n" else " " for c in text[index:stop]))
            index = stop
            continue
        if char == "/" and index + 1 < length and text[index + 1] == "/":
            end = text.find("\n", index)
            stop = length if end == -1 else end
            out.append(" " * (stop - index))
            index = stop
            continue
        out.append(char)
        index += 1
    return "".join(out)


def join_js_concatenations(text: str) -> str:
    """Merge adjacent string literals joined by ``+`` into one literal.

    A long human-facing sentence is written as ``'...No ' + 'provider is...'``,
    so a substring search for the sentence finds nothing even though the rendered
    text contains it. Merging the joins first means the check tests what the
    reader sees rather than how the source happens to be wrapped.
    """
    return re.sub(r"(['\"])\s*\+\s*\1", "", text)


def label_literals(text: str) -> list[tuple[int, str]]:
    """Every human-facing string literal, as (line number, value).

    A literal counts as human-facing when it is the value of one of
    ``LABEL_KEYS``. Template literals are included: they are how the longer
    accessible names are composed.
    """
    code = strip_js_comments(text)
    found: list[tuple[int, str]] = []
    keys = "|".join(re.escape(key) for key in LABEL_KEYS)
    pattern = re.compile(rf"(?:{keys})\s*:\s*(['\"`])((?:\\.|(?!\1)[^\\])*)\1", re.DOTALL)
    for match in pattern.finditer(code):
        line = code.count("\n", 0, match.start()) + 1
        found.append((line, match.group(2)))
    return found


@dataclass(frozen=True)
class CssBlock:
    """One declaration block, with the at-rule context it sits inside."""

    at_rules: tuple[str, ...]
    selector: str
    declarations: dict[str, str]


def css_blocks(text: str) -> list[CssBlock]:
    """Parse declaration blocks, tracking nesting.

    A deliberately small parser for the subset this repository writes: at-rules
    with blocks, selector blocks, and declarations. It does not implement CSS.
    If it is ever fed something it cannot model it will produce blocks with an
    empty declaration map, which shows up as a missing-token violation rather
    than as a silent pass.
    """
    source = strip_css_comments(text)
    blocks: list[CssBlock] = []
    stack: list[str] = []
    index = 0
    prelude_start = 0
    while index < len(source):
        char = source[index]
        if char == "{":
            prelude = source[prelude_start:index].strip()
            if prelude.startswith("@"):
                stack.append(prelude)
                index += 1
                prelude_start = index
                continue
            end = source.find("}", index)
            if end == -1:
                break
            body = source[index + 1 : end]
            blocks.append(
                CssBlock(
                    at_rules=tuple(stack),
                    selector=" ".join(prelude.split()),
                    declarations=_declarations(body),
                )
            )
            index = end + 1
            prelude_start = index
            continue
        if char == "}":
            if stack:
                stack.pop()
            index += 1
            prelude_start = index
            continue
        index += 1
    return blocks


def _declarations(body: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in body.split(";"):
        if ":" not in part:
            continue
        name, _, value = part.partition(":")
        out[name.strip()] = value.strip()
    return out


DARK_MEDIA = "prefers-color-scheme: dark"
DARK_GUARD = ':root:not([data-theme="light"])'
DARK_ATTR = ':root[data-theme="dark"]'


def theme_form_violations(css_text: str, tokens: tuple[str, ...]) -> list[str]:
    """Check the three-form token rule from docs/UX.md.

    A token must be declared on bare ``:root``, inside the guarded
    ``prefers-color-scheme: dark`` block, and inside ``:root[data-theme="dark"]``.
    A token whose ONLY definition is inside a media or ``[data-theme]`` block is
    reported separately, because that is the failure that produces an unstyled
    label for every reader on the other theme.
    """
    blocks = css_blocks(css_text)
    root: set[str] = set()
    dark_media: set[str] = set()
    dark_attr: set[str] = set()
    guarded_dark_blocks = 0
    problems: list[str] = []

    for block in blocks:
        in_dark_media = any(DARK_MEDIA in rule for rule in block.at_rules)
        names = {name for name in block.declarations if name.startswith("--")}
        if not block.at_rules and block.selector == ":root":
            root |= names
        elif in_dark_media:
            if block.selector == DARK_GUARD:
                guarded_dark_blocks += 1
                dark_media |= names
            elif block.selector == ":root":
                problems.append(
                    "the prefers-color-scheme: dark block targets bare :root; it must be "
                    f'guarded as {DARK_GUARD} so an explicit light choice wins (declares: '
                    f"{sorted(names)})"
                )
        elif block.selector == DARK_ATTR:
            dark_attr |= names

    if guarded_dark_blocks == 0:
        problems.append(
            f"no {DARK_GUARD} block inside @media ({DARK_MEDIA}): the system dark palette is "
            "missing entirely"
        )
    if not dark_attr:
        problems.append(
            f"no {DARK_ATTR} block: an explicit dark choice would not win on a light system"
        )

    for token in tokens:
        if token not in root:
            problems.append(f"{token} is not declared on bare :root (the complete light palette)")
        if token not in dark_media:
            problems.append(f"{token} is not redefined in the guarded dark media block")
        if token not in dark_attr:
            problems.append(f"{token} is not redefined under {DARK_ATTR}")
        if token not in root and (token in dark_media or token in dark_attr):
            problems.append(
                f"{token} has its only definition inside a media or [data-theme] block"
            )
    return problems


_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_FUNC_COLOUR = re.compile(r"\b(rgb|rgba|hsl|hsla|oklch|lab)\s*\(")


def literal_colour_violations(css_text: str) -> list[str]:
    """Refuse a literal colour outside the token stylesheet.

    A hex code in a component stylesheet does not change with the theme, so it
    is how one panel stays white in dark mode. ``rgb(... / x%)`` is permitted
    only inside a custom-property definition, which is how the elevation
    shadows are expressed.
    """
    problems: list[str] = []
    for block in css_blocks(css_text):
        for name, value in block.declarations.items():
            if name.startswith("--"):
                continue
            if _HEX.search(value) or _FUNC_COLOUR.search(value):
                problems.append(
                    f"{block.selector} declares a literal colour in {name}: {value!r}; "
                    "use a token so the theme switch reaches it"
                )
    return problems


def state_token_scope_violations(css_text: str, namespace: str = ".rx-outcome") -> list[str]:
    """Confine ``var(--state-*)`` to the outcome component's namespace.

    docs/UX.md forbids colour as the sole carrier of a verification state. The
    outcome component always emits geometry and the full text label, so keeping
    the state colours inside its namespace is what makes "never colour-only"
    enforceable: no other surface can tint itself by outcome without going
    through the component that labels it.
    """
    problems: list[str] = []
    for block in css_blocks(css_text):
        uses_state = any("var(--state-" in value for value in block.declarations.values())
        if uses_state and not block.selector.startswith(namespace):
            problems.append(
                f"{block.selector!r} uses a --state-* colour outside {namespace}; a surface "
                "coloured by outcome without the icon and the full label is colour-only encoding"
            )
    return problems


def match_bracket(text: str, open_index: int) -> int:
    """Index just past the bracket matching the one at ``open_index``.

    String- and escape-aware, so a bracket inside a quoted label does not throw
    the count off. Returns ``len(text)`` when unbalanced, which surfaces as a
    checker finding rather than an exception.
    """
    pairs = {"(": ")", "{": "}", "[": "]"}
    opener = text[open_index]
    closer = pairs[opener]
    depth = 0
    index = open_index
    quote = ""
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = ""
            index += 1
            continue
        if char in _QUOTES:
            quote = char
            index += 1
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(text)


def enclosing_call(text: str, position: int, callee: str = "el(") -> str:
    """The nearest ``callee(...)`` call whose body contains ``position``."""
    search_from = position
    while True:
        start = text.rfind(callee, 0, search_from)
        if start == -1:
            return ""
        open_paren = start + len(callee) - 1
        end = match_bracket(text, open_paren)
        if end > position:
            return text[start:end]
        search_from = start


def call_at(text: str, position: int, callee: str) -> str:
    """The ``callee(...)`` call that STARTS at ``position``.

    Distinct from :func:`enclosing_call`, which searches BACKWARDS for a call
    whose body contains a position. Asking that function for the call at a match
    position returns the PREVIOUS call, or - for the first occurrence in a file -
    the empty string, and `"reason:" in ""` is False. Two checkers reported
    violations that were not there for exactly that reason.
    """
    open_paren = position + len(callee) - 1
    if not text.startswith(callee, position):
        return ""
    return text[position : match_bracket(text, open_paren)]


def js_string_array(text: str, name: str) -> tuple[str, ...]:
    """Extract a frozen array of string literals declared as ``const NAME``."""
    pattern = re.compile(rf"\b{re.escape(name)}\b\s*=\s*Object\.freeze\(\s*\[")
    match = pattern.search(text)
    if not match:
        return ()
    start = text.index("[", match.end() - 1)
    body = text[start : match_bracket(text, start)]
    return tuple(re.findall(r"""['"]([^'"]+)['"]""", body))


def js_object_entry(text: str, container: str, key: str) -> str:
    """The source of one entry inside a frozen object literal."""
    anchor = re.compile(rf"\b{re.escape(container)}\b\s*=\s*Object\.freeze\(\s*\{{")
    match = anchor.search(text)
    if not match:
        return ""
    start = text.index("{", match.end() - 1)
    body = text[start : match_bracket(text, start)]
    quoted = re.escape(key)
    entry = re.compile(
        rf"(?m)^\s*(?:{quoted}|'{quoted}')\s*:\s*Object\.freeze\(\s*\{{"
    )
    found = entry.search(body)
    if not found:
        return ""
    inner = body.index("{", found.end() - 1)
    return body[inner : match_bracket(body, inner)]


def js_field(entry_source: str, field: str) -> str | None:
    """A string field's value from an object-literal source, or ``None``."""
    match = re.search(rf"""(?m)\b{re.escape(field)}\s*:\s*(['"])(.*?)\1""", entry_source)
    return match.group(2) if match else None


def _decode_js_escapes(value: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), value)


def outcome_presentation_violations(text: str, ux_labels: dict[str, str]) -> list[str]:
    """Every outcome must carry the exact docs/UX.md label, an icon and a token.

    This is the check behind "no outcome label is rendered colour-only": the
    component cannot be constructed without geometry (``icon``) and text
    (``label``), and the colour it applies is the token docs/UX.md assigns.
    """
    problems: list[str] = []
    for name in OUTCOME_NAMES:
        entry = js_object_entry(text, "OUTCOME_PRESENTATION", name)
        if not entry:
            problems.append(f"OUTCOME_PRESENTATION has no entry for {name}")
            continue
        label = js_field(entry, "label")
        if label is None:
            problems.append(f"{name} declares no label; colour and icon alone would carry it")
        else:
            expected = ux_labels.get(name)
            if expected is not None and _decode_js_escapes(label) != expected:
                problems.append(
                    f"{name} label is {_decode_js_escapes(label)!r}; docs/UX.md mandates "
                    f"{expected!r}"
                )
        if not js_field(entry, "icon"):
            problems.append(f"{name} declares no icon; the state would be text and colour only")
        token = js_field(entry, "token")
        if token != OUTCOME_TOKENS[name]:
            problems.append(
                f"{name} token is {token!r}; docs/UX.md assigns {OUTCOME_TOKENS[name]!r}"
            )
        if not js_field(entry, "qualifier"):
            problems.append(f"{name} declares no qualifier sentence")
    return problems


_BARE_REPRODUCED = re.compile(r"\bReproduced\b(?! within contract)")
_STRING_LITERAL = re.compile(r"""(['"])((?:\\.|(?!\1)[^\\])*)\1""")


def shortened_reproduced_violations(text: str) -> list[str]:
    """Refuse "Reproduced" standing alone in any string a person would read.

    T10 control 1: the qualifier *within contract* may not be separated from the
    label, and the label may not be shortened to "Reproduced". Comments are
    stripped first (see ``strip_js_comments``) and the scan is case-sensitive on
    the capitalised human spelling, so the enum member
    ``REPRODUCED_WITHIN_CONTRACT`` and the token ``--state-reproduced`` are not
    false positives while the rendered spelling is caught.
    """
    problems: list[str] = []
    code = strip_js_comments(text)
    for match in _STRING_LITERAL.finditer(code):
        value = match.group(2)
        hit = _BARE_REPRODUCED.search(value)
        if hit:
            line = code.count("\n", 0, match.start()) + 1
            problems.append(
                f"line {line}: {value[:80]!r} says 'Reproduced' without 'within contract' -- "
                "a conformance statement shortened into a correctness claim"
            )
    for match in re.finditer(r"`((?:\\.|[^`\\])*)`", code, re.DOTALL):
        value = match.group(1)
        if _BARE_REPRODUCED.search(value):
            line = code.count("\n", 0, match.start()) + 1
            problems.append(
                f"line {line}: a template literal says 'Reproduced' without 'within contract'"
            )
    return problems


def bare_affirmation_violations(text: str, affirmations: frozenset[str]) -> list[str]:
    """Refuse a human-facing label that is only an affirmation of success.

    Scoped to ``LABEL_KEYS`` values, because the rule is about what a reader
    sees. ``aria-hidden: 'true'`` is plumbing, not a claim about a result.
    """
    problems: list[str] = []
    for line, raw in label_literals(text):
        value = raw.strip().strip(" .!\u2014-")
        if value.casefold() in affirmations:
            problems.append(
                f"line {line}: the label {value!r} asserts success on its own; RETRACE "
                "establishes conformance with a declared contract, never correctness"
            )
    return problems


def panel_operation_violations(operations: dict[str, dict[str, object]]) -> list[str]:
    """Keyboard and menu are SEPARATE obligations, so they are checked separately.

    WCAG 2.1.1 (keyboard operable) and WCAG 2.5.7 (a single-pointer alternative
    to every dragging movement) are different success criteria. A keyboard path
    does not discharge 2.5.7: a pointer user who cannot drag is not a keyboard
    user. docs/UX.md says both apply; so does this function.
    """
    problems: list[str] = []
    if not operations:
        problems.append("no panel operations were parsed; the check would pass vacuously")
    for name, operation in operations.items():
        keys = operation.get("keys") or ()
        if not keys:
            problems.append(
                f"operation {name!r} declares no key combination: WCAG 2.1.1 requires every "
                "operation to be completable from the keyboard"
            )
        if operation.get("menu") is not True:
            problems.append(
                f"operation {name!r} has no menu item: WCAG 2.5.7 requires a single-pointer, "
                "non-drag path, which a keyboard shortcut does not provide"
            )
        if operation.get("pointer") == "drag" and operation.get("menu") is not True:
            problems.append(
                f"drag operation {name!r} has no non-drag pointer alternative at all"
            )
    return problems


def parse_panel_operations(text: str) -> dict[str, dict[str, object]]:
    """Parse the PANEL_OPERATIONS table into plain data."""
    anchor = re.compile(r"\bPANEL_OPERATIONS\b[^=]*=\s*Object\.freeze\(\s*\{")
    match = anchor.search(text)
    if not match:
        return {}
    start = text.index("{", match.end() - 1)
    body = text[start : match_bracket(text, start)]
    out: dict[str, dict[str, object]] = {}
    for entry in re.finditer(r"(?m)^\s{2}([A-Za-z_][\w-]*)\s*:\s*Object\.freeze\(\s*\{", body):
        inner = body.index("{", entry.end() - 1)
        source = body[inner : match_bracket(body, inner)]
        keys_match = re.search(r"keys\s*:\s*Object\.freeze\(\s*\[", source)
        keys: tuple[str, ...] = ()
        if keys_match:
            bracket = source.index("[", keys_match.end() - 1)
            keys = tuple(
                re.findall(
                    r"""['"]([^'"]+)['"]""", source[bracket : match_bracket(source, bracket)]
                )
            )
        out[entry.group(1)] = {
            "pointer": js_field(source, "pointer"),
            "keys": keys,
            "menu": re.search(r"\bmenu\s*:\s*true\b", source) is not None,
            "label": js_field(source, "label"),
        }
    return out


def accessible_name_region(call_source: str) -> str:
    """The ``attrs`` object of an element call, when it carries an aria-label.

    The accessible name in this codebase is often a template literal spread over
    two lines and joined with ``+``, so the whole attribute object is returned
    rather than one quoted chunk: a checker that read only the first chunk would
    report a missing keyboard hint that is present on the following line, and
    the natural response to that false positive is to delete the checker.
    """
    marker = "attrs: {"
    position = call_source.find(marker)
    if position == -1:
        return ""
    brace = call_source.index("{", position)
    region = call_source[brace : match_bracket(call_source, brace)]
    return region if "aria-label" in region else ""


def drag_handle_affordance_violations(text: str) -> list[str]:
    """Every drag handle must advertise both alternatives in its accessible name.

    A handle that is draggable and silent tells an assistive-technology user
    nothing about the two other ways to perform the operation. This checks the
    accessible name, which is the only part of the affordance a screen-reader
    user receives.
    """
    problems: list[str] = []
    handles = list(re.finditer(r"dragHandle:\s*'true'", text))
    if not handles:
        problems.append("no drag handles were found; the check would pass vacuously")
    for match in handles:
        call = enclosing_call(text, match.start())
        region = accessible_name_region(call)
        line = text.count("\n", 0, match.start()) + 1
        if not region:
            problems.append(f"line {line}: a drag handle has no aria-label at all")
            continue
        if "Keyboard" not in region:
            problems.append(
                f"line {line}: a drag handle's accessible name does not name its keyboard path"
            )
        if "menu" not in region:
            problems.append(
                f"line {line}: a drag handle's accessible name does not name the menu path "
                "(WCAG 2.5.7)"
            )
    return problems


def menu_coverage_violations(panel_text: str) -> list[str]:
    """The panel menu must be built from the whole operation table."""
    problems: list[str] = []
    if "PANEL_OPERATION_IDS.map(" not in panel_text:
        problems.append(
            "the panel menu is not built from PANEL_OPERATION_IDS, so an operation could exist "
            "with no menu item"
        )
    if "operationForKeys(keyCombination(" not in panel_text:
        problems.append(
            "the panel keydown handler does not resolve through operationForKeys(keyCombination("
            ")), so a key combination in the table could have no handler"
        )
    return problems


def provenance_freshness_separation_violations(
    provenance_text: str, freshness_text: str
) -> list[str]:
    """Data provenance and event freshness must stay two distinct components."""
    problems: list[str] = []
    prov_values = set(js_string_array(provenance_text, "PROVENANCE_VALUES")) or set(
        re.findall(r"(?m)^  ([A-Z_]+): Object\.freeze", provenance_text)
    )
    fresh_values = set(js_string_array(freshness_text, "FRESHNESS_VALUES")) or set(
        re.findall(r"(?m)^  ([A-Z_]+): Object\.freeze", freshness_text)
    )
    if not prov_values or not fresh_values:
        problems.append("one of the two vocabularies could not be parsed; the check is vacuous")
    overlap = prov_values & fresh_values
    if overlap:
        problems.append(
            f"the two vocabularies share value id(s) {sorted(overlap)}: a shared id is how "
            "'synthetic' and 'stale' end up read as one status"
        )
    # Comments are stripped for the dependency check: each module's docstring
    # NAMES the other one to explain the separation, and a checker that read
    # prose would fire on the very comment that documents the rule.
    prov_code = strip_js_comments(provenance_text)
    fresh_code = strip_js_comments(freshness_text)
    if "freshness.js" in prov_code:
        problems.append("provenance.js imports or references freshness.js in code")
    if "provenance.js" in fresh_code:
        problems.append("freshness.js imports or references provenance.js in code")
    for value in FRESHNESS_VALUES:
        if re.search(rf"(?m)^\s*{value}:\s*Object\.freeze", prov_code):
            problems.append(f"provenance.js defines the freshness value {value}")
    for value in PROVENANCE_VALUES:
        if re.search(rf"(?m)^\s*{value}:\s*Object\.freeze", fresh_code):
            problems.append(f"freshness.js defines the provenance value {value}")
    prov_legend = js_string_array(provenance_text, "PROVENANCE_LEGEND")
    if "Data provenance" not in provenance_text:
        problems.append("provenance.js does not declare the legend 'Data provenance'")
    if "Event freshness" not in freshness_text:
        problems.append("freshness.js does not declare the legend 'Event freshness'")
    del prov_legend
    return problems


def conflated_label_violations(text: str) -> list[str]:
    """Refuse one string that mixes a provenance token with a freshness token."""
    problems: list[str] = []
    code = strip_js_comments(text)
    for match in _STRING_LITERAL.finditer(code):
        value = match.group(2)
        provenance = [token for token in PROVENANCE_VALUES if token in value]
        freshness = [token for token in FRESHNESS_VALUES if token in value]
        if provenance and freshness:
            line = code.count("\n", 0, match.start()) + 1
            problems.append(
                f"line {line}: one label carries both {provenance} (provenance) and {freshness} "
                "(freshness); they are different attributes and must be rendered separately"
            )
    return problems


def network_call_violations(text: str) -> list[str]:
    """Refuse a network API outside the single client module."""
    return [
        f"{api} appears outside apps/web/src/api/client.js; every network call must go through "
        "the one typed client the integrator repoints"
        for api in NETWORK_APIS
        if api in text
    ]


def unsafe_sink_violations(text: str) -> list[str]:
    """Refuse markup and code-execution sinks everywhere."""
    return [
        f"{sink} is used; tenant data and prompt-generated plans reach these views, so nodes are "
        "built and textContent is set instead"
        for sink in UNSAFE_SINKS
        if sink in text
    ]


def surface_state_reason_violations(text: str) -> list[str]:
    """Every surface state must carry a reason the reader can see."""
    problems: list[str] = []
    code = blank_js_comments(text)
    for match in re.finditer(r"renderSurfaceState\(", code):
        # Skip the DEFINITION. `export function renderSurfaceState(state, detail)`
        # has no `reason` in its parameter list, so the regex reported the
        # declaration of the rule as a breach of it. The definition is in fact
        # the strongest enforcement there is: it THROWS when detail.reason is
        # absent, which no static scan can match.
        prefix = code[max(0, match.start() - 40) : match.start()]
        if "function" in prefix:
            continue
        # Read the call STARTING AT the match. `enclosing_call` searches
        # BACKWARDS from the position it is given, so asking it for the call at
        # a match position finds the PREVIOUS call - or, for the first one in a
        # file, nothing at all. It returned '' for outcome-gate.js:121, whose
        # call does pass a reason, so the checker reported a violation that was
        # not there. Comments are stripped first for the reason strip_js_comments
        # already documents: a checker that scanned prose would fire on the text
        # describing the rule.
        open_paren = match.end() - 1
        call = code[match.start() : match_bracket(code, open_paren)]
        if "reason" not in call:
            line = text.count("\n", 0, match.start()) + 1
            problems.append(
                f"line {line}: renderSurfaceState(...) with no reason; an unexplained blank "
                "panel tells the reader nothing about what is missing"
            )
    return problems

"""Design tokens: the three theme forms, density, motion, contrast (RX-19).

docs/UX.md states the token rule as a rule, not a preference: a complete light
palette on bare ``:root``, dark redefined under a guarded
``prefers-color-scheme`` media query, and dark redefined again under
``:root[data-theme="dark"]`` so an explicit toggle wins in both directions. The
first of these tests checks all three forms for every colour token; the negative
controls in ``test_negative_controls.py`` show each form's absence is detected.

The contrast tests compute the WCAG 2.x relative-luminance ratio from the token
values. That is the real formula over the real values, so it is stronger than an
eye check - but it is NOT an accessibility audit: it says nothing about
focus order, reading order, target size in a rendered layout, or any contrast
pairing the stylesheets actually produce but these tests do not enumerate. No
axe run is possible in this suite.
"""

from __future__ import annotations

import re

import checks
import pytest
from retrace_i18n.labels import TRUTHFULNESS_TOKENS as PY_TRUTHFULNESS_TOKENS

#: Every colour token docs/UX.md defines, including the five state colours.
THEMED_TOKENS: tuple[str, ...] = (
    "--surface-canvas",
    "--surface-panel",
    "--surface-raised",
    "--surface-sunken",
    "--border-subtle",
    "--border-strong",
    "--text-primary",
    "--text-secondary",
    "--text-tertiary",
    "--accent",
    "--focus-ring",
    "--state-reproduced",
    "--state-unverified",
    "--state-changed",
    "--state-blocked",
    "--state-failed",
)


def _channel(value: int) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4


def _luminance(hex_colour: str) -> float:
    raw = hex_colour.lstrip("#")
    red, green, blue = (int(raw[index : index + 2], 16) for index in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast_ratio(first: str, second: str) -> float:
    """WCAG 2.x contrast ratio between two opaque sRGB colours."""
    high, low = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _palette(tokens_css: str, selector: str, at_rule: str | None = None) -> dict[str, str]:
    palette: dict[str, str] = {}
    for block in checks.css_blocks(tokens_css):
        inside = any(at_rule in rule for rule in block.at_rules) if at_rule else not block.at_rules
        if inside and block.selector == selector:
            palette.update(
                {
                    name: value
                    for name, value in block.declarations.items()
                    if name.startswith("--") and value.startswith("#")
                }
            )
    return palette


def test_every_colour_token_exists_in_all_three_theme_forms(tokens_css: str) -> None:
    """Bare :root, the guarded dark media block, and [data-theme=dark] (RX-19)."""
    problems = checks.theme_form_violations(tokens_css, THEMED_TOKENS)
    assert problems == [], "\n".join(problems)


def test_no_colour_is_defined_only_inside_a_media_or_attribute_block(tokens_css: str) -> None:
    """The rule that makes the other two forms safe to rely on."""
    root = _palette(tokens_css, ":root")
    dark_media = _palette(tokens_css, checks.DARK_GUARD, "prefers-color-scheme: dark")
    dark_attr = _palette(tokens_css, checks.DARK_ATTR)
    only_in_dark = (set(dark_media) | set(dark_attr)) - set(root)
    assert only_in_dark == set(), (
        f"these colours have no light definition: {sorted(only_in_dark)}. Every light reader "
        "would get an unstyled value."
    )


def test_the_two_dark_forms_agree_value_for_value(tokens_css: str) -> None:
    """A toggle and a system preference must not produce two different palettes."""
    dark_media = _palette(tokens_css, checks.DARK_GUARD, "prefers-color-scheme: dark")
    dark_attr = _palette(tokens_css, checks.DARK_ATTR)
    assert dark_media, "the guarded dark media block declares no colours"
    differences = {
        name: (value, dark_attr.get(name))
        for name, value in dark_media.items()
        if dark_attr.get(name) != value
    }
    assert differences == {}, (
        f"the explicit dark palette differs from the system dark palette: {differences}"
    )


@pytest.mark.parametrize("surface", ["--surface-canvas", "--surface-panel"])
def test_primary_text_contrast_meets_the_stated_intent(tokens_css: str, surface: str) -> None:
    """docs/UX.md targets >= 7:1 for --text-primary on canvas and panel."""
    for label, palette in (
        ("light", _palette(tokens_css, ":root")),
        ("dark", _palette(tokens_css, checks.DARK_ATTR)),
    ):
        ratio = contrast_ratio(palette["--text-primary"], palette[surface])
        assert ratio >= 7.0, f"{label}: --text-primary on {surface} is {ratio:.2f}:1, below 7:1"


def test_secondary_and_tertiary_text_contrast(tokens_css: str) -> None:
    """Secondary >= 4.5:1; tertiary >= 3:1 and permitted at large sizes only."""
    for label, palette in (
        ("light", _palette(tokens_css, ":root")),
        ("dark", _palette(tokens_css, checks.DARK_ATTR)),
    ):
        for surface in ("--surface-canvas", "--surface-panel"):
            secondary = contrast_ratio(palette["--text-secondary"], palette[surface])
            tertiary = contrast_ratio(palette["--text-tertiary"], palette[surface])
            assert secondary >= 4.5, f"{label}: secondary on {surface} is {secondary:.2f}:1"
            assert tertiary >= 3.0, f"{label}: tertiary on {surface} is {tertiary:.2f}:1"


def test_every_state_colour_is_legible_on_the_surfaces_it_is_drawn_on(tokens_css: str) -> None:
    """A state colour carries an icon stroke and a border, so it must be legible.

    4.5:1 is required rather than 3:1 because the icon is a thin 1.75px stroke,
    not a large graphical object.
    """
    state_tokens = [name for name in THEMED_TOKENS if name.startswith("--state-")]
    for label, palette in (
        ("light", _palette(tokens_css, ":root")),
        ("dark", _palette(tokens_css, checks.DARK_ATTR)),
    ):
        for token in state_tokens:
            for surface in ("--surface-canvas", "--surface-panel"):
                ratio = contrast_ratio(palette[token], palette[surface])
                assert ratio >= 4.5, f"{label}: {token} on {surface} is {ratio:.2f}:1"


def test_density_is_defined_for_both_values_and_keeps_a_pointer_target(tokens_css: str) -> None:
    """comfortable 40px, compact 30px, with a >= 24px pointer target (docs/UX.md)."""
    root = next(
        block for block in checks.css_blocks(tokens_css)
        if not block.at_rules and block.selector == ":root"
    )
    assert root.declarations["--row-height"] == "40px"
    assert root.declarations["--pointer-target-min"] == "24px"
    compact = next(
        block for block in checks.css_blocks(tokens_css)
        if block.selector == ':root[data-density="compact"]'
    )
    assert compact.declarations["--row-height"] == "30px"


def test_motion_collapses_under_reduced_motion_and_nothing_loops(
    css_sources: dict[str, str]
) -> None:
    """Every duration becomes 0ms under prefers-reduced-motion; no idle animation.

    docs/UX.md: an animation implies live activity and must be driven by a real
    event. A looping animation is therefore refused outright rather than only
    disabled for users who ask.
    """
    tokens = css_sources["packages/ui/tokens/tokens.css"]
    reduced = [
        block
        for block in checks.css_blocks(tokens)
        if any("prefers-reduced-motion" in rule for rule in block.at_rules)
    ]
    assert reduced, "no prefers-reduced-motion block"
    declared = {name: value for block in reduced for name, value in block.declarations.items()}
    for name in ("--motion-state", "--motion-panel", "--motion-overlay"):
        assert declared.get(name) == "0ms", f"{name} does not collapse to 0ms"
    for path, css in css_sources.items():
        body = checks.strip_css_comments(css)
        assert "@keyframes" not in body, f"{path} declares a keyframe animation"
        assert not re.search(r"\binfinite\b", body), f"{path} declares a looping animation"


def test_literal_colours_appear_only_in_the_token_stylesheet(
    css_sources: dict[str, str]
) -> None:
    """A hard-coded colour outside tokens.css would survive the theme switch."""
    for path, css in css_sources.items():
        if path.endswith("tokens/tokens.css"):
            continue
        problems = checks.literal_colour_violations(css)
        assert problems == [], f"{path}:\n" + "\n".join(problems)


def test_state_colours_are_confined_to_the_outcome_component(
    css_sources: dict[str, str]
) -> None:
    """No surface may be tinted by outcome outside the component that labels it."""
    for path, css in css_sources.items():
        problems = checks.state_token_scope_violations(css)
        assert problems == [], f"{path}:\n" + "\n".join(problems)


def test_the_javascript_token_registry_matches_the_stylesheet(
    tokens_css: str, ui_sources: dict[str, str]
) -> None:
    """A token named in JS but absent from CSS resolves to nothing at runtime."""
    declared = checks.js_string_array(
        ui_sources["packages/ui/src/tokens.js"], "THEMED_COLOUR_TOKENS"
    )
    assert set(declared) == set(THEMED_TOKENS), (
        "packages/ui/src/tokens.js and this test disagree about the token list"
    )
    root = _palette(tokens_css, ":root")
    missing = [token for token in declared if token not in root]
    assert missing == [], f"referenced from JavaScript but not declared in CSS: {missing}"


def test_the_nine_truthfulness_tokens_match_the_frozen_python_vocabulary(
    ui_sources: dict[str, str]
) -> None:
    """One spelling of each token across the UI and the i18n layer (RX-25, RX-29).

    The token itself is a protected span: a translation pass may localise the
    gloss around it but never the token, so the two layers must agree exactly.
    """
    in_js = checks.js_string_array(
        ui_sources["packages/ui/src/truthfulness.js"], "TRUTHFULNESS_TOKENS"
    )
    assert in_js == tuple(PY_TRUTHFULNESS_TOKENS), (
        f"UI tokens {in_js} differ from retrace_i18n {tuple(PY_TRUTHFULNESS_TOKENS)}"
    )

"""Direction and bidirectional isolation (RX-28).

The scientific identifiers used here are the real failure cases: a run
identifier with an underscore, an inequality whose operator can visually flip,
and a sha256 digest. All three are left-to-right runs that must keep their
logical order inside right-to-left prose.
"""

from __future__ import annotations

import pytest
from retrace_i18n.bidi import (
    LRI,
    PDI,
    isolate,
    isolation_violations,
    render_for_direction,
    render_message,
    strip_isolates,
)
from retrace_i18n.protected import protect, protected_spans, unprotect
from retrace_i18n.registry import LocaleRegistry

RTL_LOCALES = ("ar", "he", "fa", "ur")
LTR_SAMPLE = ("en", "nl", "de", "ja", "zh-Hans", "hi", "sw", "el")

#: Mixed-direction scientific identifiers. Each is wrapped as a protected span,
#: because what must not be translated is exactly what must not be reordered.
IDENTIFIERS = (
    "run_00001",
    "p < 0.05",
    "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "12.5 ms",
    "CO2 >= 400 ppm",
)


def message_with(identifier: str) -> str:
    """A message whose only protected span is ``identifier``."""
    return f"Result for {protect(identifier)} is ready."


@pytest.mark.parametrize("code", RTL_LOCALES)
@pytest.mark.parametrize("identifier", IDENTIFIERS)
def test_rtl_locales_isolate_every_identifier(
    code: str, identifier: str, reg: LocaleRegistry
) -> None:
    """All four RTL locales wrap the identifier in LRI..PDI (RX-28).

    ``ur`` is included deliberately: Urdu is rtl in the registry even though the
    upstream prose named only Arabic, Hebrew and Persian.
    """
    value = message_with(identifier)
    rendered = render_message(code, value, source=reg)
    assert isolation_violations(code, value, rendered) == ()
    assert f"{LRI}{identifier}{PDI}" in rendered
    assert rendered.count(LRI) == 1
    assert rendered.count(PDI) == 1


@pytest.mark.parametrize("code", RTL_LOCALES)
@pytest.mark.parametrize("identifier", IDENTIFIERS)
def test_payload_bytes_and_logical_order_are_unchanged(
    code: str, identifier: str, reg: LocaleRegistry
) -> None:
    """Isolation changes presentation only: strip the controls and nothing moved (RX-28)."""
    value = message_with(identifier)
    rendered = render_message(code, value, source=reg)
    assert strip_isolates(rendered) == unprotect(value)
    assert identifier in rendered
    assert protected_spans(value) == (identifier,)


@pytest.mark.parametrize("code", LTR_SAMPLE)
def test_ltr_locales_insert_no_control_characters(code: str, reg: LocaleRegistry) -> None:
    """No isolates in LTR text: inserting controls that do no work is not free (RX-28).

    Stray controls pollute copy-paste, string comparison and digest inputs, so
    the renderer adds them only where the algorithm would otherwise reorder.
    """
    value = message_with("run_00001")
    rendered = render_message(code, value, source=reg)
    assert rendered == unprotect(value)
    assert LRI not in rendered and PDI not in rendered


def test_multiple_identifiers_are_each_isolated(reg: LocaleRegistry) -> None:
    value = f"{protect('run_00001')} and {protect('p < 0.05')} in one sentence"
    rendered = render_message("ar", value, source=reg)
    assert isolation_violations("ar", value, rendered) == ()
    assert rendered.count(LRI) == 2


def test_real_catalogue_messages_render_for_every_rtl_locale(
    catalogues: dict[str, object], reg: LocaleRegistry
) -> None:
    """Every spanned source message renders cleanly in all four RTL locales (RX-28)."""
    from retrace_i18n.catalogue import Catalogue

    source: Catalogue = catalogues["en"]  # type: ignore[assignment]
    checked = 0
    for key, message in source.entries.items():
        for text in message.strings():
            if not protected_spans(text):
                continue
            for code in RTL_LOCALES:
                rendered = render_message(code, text, source=reg)
                assert isolation_violations(f"{code}/{key}", text, rendered) == ()
                checked += 1
    assert checked >= 4 * 20, f"only {checked} renders checked"


def test_isolate_rejects_an_unknown_direction() -> None:
    with pytest.raises(ValueError, match="direction"):
        isolate("x", direction="upwards")
    with pytest.raises(ValueError, match="direction"):
        render_for_direction("x", "upwards")


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def naive_render(value: str) -> str:
    """A renderer that strips markers and inserts no isolates - the defect (RX-28)."""
    return unprotect(value)


@pytest.mark.parametrize("code", RTL_LOCALES)
@pytest.mark.parametrize("identifier", IDENTIFIERS)
def test_negative_control_unisolated_identifier_is_detected(
    code: str, identifier: str
) -> None:
    """MANDATORY negative control: the checker fails a render with no isolates.

    This is what the defective implementation looks like - the bytes are right
    and the reading is wrong - so the gate must reject it.
    """
    value = message_with(identifier)
    problems = isolation_violations(code, value, naive_render(value))
    assert problems, f"{code}: an unisolated {identifier!r} was NOT detected"
    assert "not isolated" in " ".join(problems)


def test_negative_control_altered_payload_is_detected() -> None:
    """A renderer that reorders or edits the payload is detected (RX-28, RX-29)."""
    value = message_with("p < 0.05")
    broken = unprotect(value).replace("p < 0.05", f"{LRI}0.05 > p{PDI}")
    problems = isolation_violations("ar", value, broken)
    assert problems
    assert "missing or altered" in " ".join(problems)


def test_negative_control_dropped_isolate_close_is_detected() -> None:
    value = message_with("run_00001")
    broken = unprotect(value).replace("run_00001", f"{LRI}run_00001")
    assert isolation_violations("he", value, broken)

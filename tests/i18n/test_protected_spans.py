"""Protected spans survive a translation pass byte-identically (RX-29).

The headline test runs a HOSTILE full translation pass over every string in
every one of the 36 catalogues and asserts that each protected payload comes out
byte-identical. The pass is deliberately destructive - it uppercases, reverses
and pads the translatable text - because a gentle pass would not distinguish
"the protection works" from "the translator happened not to change anything".
"""

from __future__ import annotations

import pytest
from helpers import catalogue_from, entry
from retrace_i18n.catalogue import Catalogue
from retrace_i18n.labels import TRUTHFULNESS_MESSAGE_KEYS, TRUTHFULNESS_TOKENS
from retrace_i18n.protected import (
    CLOSE,
    OPEN,
    ProtectedSpanError,
    placeholders,
    protect,
    protected_spans,
    segments,
    span_violations,
    translate_preserving,
    unprotect,
    validate,
)
from retrace_i18n.registry import LocaleRegistry


def hostile_translate(text: str) -> str:
    """A translator that mangles everything it is allowed to touch.

    Upper-casing, reversing and padding are all things a real translation would
    never do; any of them leaking into a protected payload is a detectable
    failure. If this function were gentle the test would prove nothing.
    """
    return f">>{text.upper()[::-1]}<<"


def destroy_everything(value: str) -> str:
    """A WRONG pass: translates the whole value, markers and payload included.

    This is the defect RX-29 exists to catch - a translation pipeline that does
    not know about protected spans. Used by the negative control.
    """
    return hostile_translate(value)


def test_every_catalogue_string_has_well_formed_spans(
    catalogues: dict[str, Catalogue],
) -> None:
    """No unmatched, nested or inverted markers anywhere (RX-29)."""
    for code, catalogue in catalogues.items():
        for key, message in catalogue.entries.items():
            for text in message.strings():
                validate(text, field=f"{code}/{key}")


def test_full_translation_pass_over_every_catalogue_preserves_every_span(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """THE RX-29 gate: a destructive pass over all 36 catalogues alters no span."""
    checked = 0
    spans_seen = 0
    problems: list[str] = []
    for code in reg.codes:
        for key, message in catalogues[code].entries.items():
            for text in message.strings():
                translated = translate_preserving(text, hostile_translate)
                problems.extend(span_violations(text, translated, label=f"{code}/{key}"))
                spans_seen += len(protected_spans(text))
                checked += 1
    assert not problems, problems
    # Anti-vacuity guard, derived from the corpus rather than a round number.
    # The original `checked > 1000` was a guess that happened to exceed the real
    # corpus (917 strings, because many locales are legitimately `pending`), so
    # it failed while the property it guarded was holding. Asserting the sweep
    # touched EVERY string is both stronger and immune to corpus size drift: it
    # fails if any catalogue or key is silently skipped.
    expected = sum(
        len(message.strings())
        for code in reg.codes
        for message in catalogues[code].entries.values()
    )
    assert expected > 0, "no strings in any catalogue; the gate would be vacuous"
    assert checked == expected, f"swept {checked} of {expected} strings; some were skipped"
    # Second anti-vacuity guard, also corpus-derived. `spans_seen > 100` was
    # another guessed round number (the real corpus holds 92 spans across 36
    # catalogues) and failed while the property held. What actually matters is
    # that spans EXIST, that the sweep counted every one of them, and that
    # protection is exercised in the source rather than only in translations -
    # none of which needs a magic constant.
    expected_spans = sum(
        len(protected_spans(text))
        for code in reg.codes
        for message in catalogues[code].entries.values()
        for text in message.strings()
    )
    source_span_keys = [
        key
        for key, message in catalogues[reg.source_locale].entries.items()
        for text in message.strings()
        if protected_spans(text)
    ]
    assert expected_spans > 0, "no protected spans anywhere; the gate would be vacuous"
    assert spans_seen == expected_spans, (
        f"counted {spans_seen} of {expected_spans} spans; some were skipped"
    )
    assert source_span_keys, (
        "the English source declares no protected spans, so preserving them in "
        "translations proves nothing about real content"
    )


def test_translatable_text_actually_changed_in_that_pass(
    catalogues: dict[str, Catalogue],
) -> None:
    """Discrimination check: the pass must have changed the unprotected text.

    Without this, a ``translate_preserving`` that returned its input unchanged
    would pass the test above while protecting nothing.
    """
    source = catalogues["en"]
    changed = 0
    for message in source.entries.values():
        for text in message.strings():
            if translate_preserving(text, hostile_translate) != text:
                changed += 1
    assert changed == sum(len(m.strings()) for m in source.entries.values())


def test_english_source_carries_spans_in_every_protected_category(
    catalogues: dict[str, Catalogue],
) -> None:
    """Identifiers, digests, units, standards and tokens are all marked (RX-29)."""
    spans = {
        span
        for message in catalogues["en"].entries.values()
        for text in message.strings()
        for span in protected_spans(text)
    }
    for required in ("sha256", "IANA", "DOI", "days", "..", "{run_id}", "{timestamp}"):
        assert required in spans, f"{required!r} is not protected in the source catalogue"


def test_every_truthfulness_token_is_a_protected_span(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """The nine mandated tokens are protected in every catalogue that has them (RX-25, RX-29).

    A translated or case-folded ``STALE`` is no longer the token the interface
    contract names, so the token is marked and only the gloss is translatable.
    """
    for code in reg.codes:
        for token, key in TRUTHFULNESS_MESSAGE_KEYS.items():
            message = catalogues[code].entries[key]
            for text in message.strings():
                assert token in protected_spans(text), (code, key, token)
    assert len(TRUTHFULNESS_TOKENS) == 9


def test_placeholders_are_preserved_in_every_translation(
    catalogues: dict[str, Catalogue], reg: LocaleRegistry
) -> None:
    """A translation must carry the same ``{name}`` placeholders as its source (RX-26).

    A dropped placeholder breaks the message as surely as an altered digest, and
    the failure is invisible until the message is formatted at runtime.
    """
    source = catalogues["en"]
    problems: list[str] = []
    for code in reg.codes:
        if code == reg.source_locale:
            continue
        for key, message in catalogues[code].entries.items():
            source_message = source.entries[key]
            if message.is_plural:
                for category, form in (message.forms or {}).items():
                    if not isinstance(form, str):
                        continue
                    want = placeholders(
                        next(iter(source_message.strings()), "")
                    )
                    if placeholders(form) != want:
                        problems.append(f"{code}/{key}#{category}: {placeholders(form)} != {want}")
            else:
                if not isinstance(message.value, str):
                    continue
                want = placeholders(source_message.value or "")
                if placeholders(message.value) != want:
                    problems.append(f"{code}/{key}: {placeholders(message.value)} != {want}")
    assert not problems, problems


def test_segments_round_trip() -> None:
    value = f"Run {protect('run_00001')} finished at {protect('12:00Z')}."
    assert [s.protected for s in segments(value)] == [False, True, False, True, False]
    assert unprotect(value) == "Run run_00001 finished at 12:00Z."
    assert protected_spans(value) == ("run_00001", "12:00Z")


def test_protect_refuses_to_nest() -> None:
    with pytest.raises(ProtectedSpanError, match="already contains"):
        protect(protect("sha256"))


# ---------------------------------------------------------------------------
# Negative controls
# ---------------------------------------------------------------------------


def test_negative_control_a_pass_that_alters_a_span_fails(
    catalogues: dict[str, Catalogue],
) -> None:
    """MANDATORY negative control: a protected span altered by a translation pass FAILS.

    Runs the WRONG pass - one that translates the whole value, ignoring the
    markers - over the same source strings, and asserts the comparator reports a
    violation for every string that has a span. A gate that has never been shown
    to fail is not evidence the property holds.
    """
    detected = 0
    with_spans = 0
    for key, message in catalogues["en"].entries.items():
        for text in message.strings():
            if not protected_spans(text):
                continue
            with_spans += 1
            problems = span_violations(text, destroy_everything(text), label=f"en/{key}")
            assert problems, f"en/{key}: the comparator did NOT detect a destroyed span"
            detected += 1
    assert with_spans > 20, "too few spanned strings for the control to be meaningful"
    assert detected == with_spans


@pytest.mark.parametrize(
    ("before", "after", "why"),
    [
        (protect("sha256"), protect("SHA256"), "case folded"),
        (protect("run_00001"), protect("run_0001"), "a character dropped"),
        (protect("p < 0.05"), protect("p > 0.05"), "an operator flipped"),
        (protect("10.1000/xyz"), protect("10.1000/XYZ"), "a DOI case folded"),
        (f"a{protect('ms')}b", "ab", "the span removed entirely"),
        (protect("a") + protect("b"), protect("a"), "a span count change"),
        ("plain", protect("plain"), "a span added"),
    ],
)
def test_negative_control_comparator_detects_each_alteration(
    before: str, after: str, why: str
) -> None:
    """Each individual way of corrupting a span is detected (RX-29)."""
    assert span_violations(before, after), f"undetected: {why}"


@pytest.mark.parametrize(
    "bad",
    [
        f"{OPEN}unterminated",
        f"unopened{CLOSE}",
        f"{OPEN}outer{OPEN}inner{CLOSE}{CLOSE}",
        f"{CLOSE}{OPEN}inverted",
    ],
)
def test_negative_control_malformed_markers_are_refused(bad: str) -> None:
    with pytest.raises(ProtectedSpanError):
        validate(bad)


def test_negative_control_catalogue_with_a_malformed_span_is_refused() -> None:
    """A catalogue file containing a broken span cannot be loaded (RX-26, RX-29)."""
    with pytest.raises(ProtectedSpanError):
        catalogue_from("nl", {"a.key": entry(f"{OPEN}unterminated")})


def test_comparator_passes_an_identical_pair() -> None:
    """The comparator must not fire on a correct pass - no false positives (RX-29)."""
    text = f"Digest {protect('sha256')} over {protect('run_00001')}"
    assert span_violations(text, translate_preserving(text, hostile_translate)) == ()

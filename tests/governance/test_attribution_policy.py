"""Repository-local attribution control.

WHY THIS EXISTS. The machine-wide pre-commit guard exempts the approved-evidence
path class from its prose-credit scan: one shared flag disables both the
structural scan (intentionally) and the prose scan (not intentionally). A real
negative control demonstrated the gap -- see docs/evidence/ATTRIBUTION_CONTROL.md.

Until that is resolved upstream, this repository enforces the property itself
rather than depending on a hook whose exemption it benefits from. These tests
are deliberately independent of the hook: they read tracked files directly, so
they fail in CI and locally even if the hook is absent, stale, or bypassed.

The patterns here mirror the upstream control's intent. They are data, not a
claim: a file that must refuse a string necessarily contains it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Single source of truth for the vendor vocabulary. Kept as plain NAMES -- a
#: name is an identifier, not a claim. Every hostile fixture below is COMPOSED
#: from these at runtime, so this file proves the detector works without ever
#: containing a hand-spelled credit. Fixtures that were spelled around the guard
#: would prove nothing about the guard; fixtures generated from the pattern's own
#: vocabulary cannot drift away from it.
VENDOR_NAMES: tuple[str, ...] = (
    "Claude", "Anthropic", "ChatGPT", "OpenAI", "Copilot", "Codex", "Cursor",
)
VENDOR_PHRASES: tuple[str, ...] = ("the AI", "an AI", "this AI")

_VENDOR = "(" + "|".join(
    [*VENDOR_NAMES, *(f"[{w[0].upper()}{w[0]}]{w[1:]}" for w in VENDOR_PHRASES)]
) + ")"
_CREDIT_NOUN = r"(co-?authors?|contributors?|creators?|maintainers?|authors?|developers?|writers?)"

#: A credit asserted as an ordinary sentence. Matched on the subject-verb-noun
#: relation, not on the nouns alone, so that *discussing* attribution policy
#: (as this very file does) is not itself an offence.
PROSE_CREDIT = re.compile(
    rf"{_VENDOR}[^.;:!?]{{0,30}}\s(is|was|are|were|remains|remained)\s+"
    rf"(a\s+|an\s+|the\s+|one\s+of\s+the\s+)?{_CREDIT_NOUN}(\s|[.,;:!?)]|$)"
    rf"|(contributions?|credit)\s+(from|by)\s+{_VENDOR}\b",
    re.IGNORECASE,
)

#: Trailer- and metadata-shaped attribution. Refused by SHAPE, so it is refused
#: even when the name in it is Frank's: authorship is carried by git identity,
#: never by a text header.
SHAPED_ATTRIBUTION = re.compile(
    r"(^|\s)[Cc]o-[Aa]uthored-[Bb]y:"
    r"|(^|\s)(Generated|Authored|Created|Powered|Signed-off)-[Bb]y:"
    r"|^\s*(Author|Authors|Contributor|Contributors|Maintainer|Maintainers"
    r"|Credits|Credit|Acknowledgements|Acknowledgments)\s*:",
    re.MULTILINE,
)

#: Vendor names are permitted only as functional identifiers in evidence records
#: and the requirement matrix. Source trees must stay free of them.
SOURCE_ROOTS = ("packages/", "services/", "apps/", "tests/")

SELF = Path(__file__).relative_to(REPO).as_posix()


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    paths = []
    for rel in filter(None, out.split("\0")):
        p = REPO / rel
        if not p.is_file():
            continue
        if p.suffix in {".png", ".jpg", ".pdf", ".zip", ".whl", ".db"}:
            continue
        paths.append(p)
    return paths


@pytest.fixture(scope="module")
def tracked() -> list[tuple[str, str]]:
    files = _tracked_text_files()
    assert files, "git ls-files returned nothing -- the control would pass vacuously"
    return [
        (p.relative_to(REPO).as_posix(), p.read_text(encoding="utf-8", errors="replace"))
        for p in files
    ]


def test_no_prose_credit_anywhere(tracked: list[tuple[str, str]]) -> None:
    """No tracked file may ASSERT that a vendor authored this work (incl. docs/evidence/)."""
    hits = [
        (rel, m.group(0))
        for rel, text in tracked
        if rel != SELF
        for m in PROSE_CREDIT.finditer(text)
    ]
    assert not hits, f"prose attribution claim in tracked files: {hits}"


def test_no_shaped_attribution_anywhere(tracked: list[tuple[str, str]]) -> None:
    """No trailer- or metadata-shaped attribution, regardless of the name in it."""
    hits = [
        (rel, m.group(0).strip())
        for rel, text in tracked
        if rel != SELF
        for m in SHAPED_ATTRIBUTION.finditer(text)
    ]
    assert not hits, f"shaped attribution in tracked files: {hits}"


def test_source_trees_contain_no_vendor_names(tracked: list[tuple[str, str]]) -> None:
    """Vendor names belong in evidence records, not in the source tree."""
    pat = re.compile(_VENDOR)
    hits = [
        (rel, m.group(0))
        for rel, text in tracked
        if rel != SELF and rel.startswith(SOURCE_ROOTS)
        for m in pat.finditer(text)
    ]
    assert not hits, f"vendor name in source tree: {hits}"


# ---------------------------------------------------------------------------
# Negative controls. A check that has never been shown to fail is not evidence
# that the property holds -- it may simply be unable to detect the violation.
# ---------------------------------------------------------------------------

#: Claim templates. Each is incomplete on its own -- no vendor name is adjacent,
#: so none of these literals is a credit. They become hostile only once composed
#: with a vendor token at runtime, which is exactly what the detector must catch.
CLAIM_TEMPLATES: tuple[str, ...] = (
    "{v} is a co-author of this work.",
    "{v} was the author of this module.",
    "{v} are contributors to the result.",
    "{v} remains one of the maintainers.",
    "This includes contributions from {v}.",
    "Parts of it are credit by {v}.",
)


@pytest.mark.parametrize("vendor", [*VENDOR_NAMES, *VENDOR_PHRASES])
@pytest.mark.parametrize("template", CLAIM_TEMPLATES)
def test_prose_pattern_detects_every_composed_claim(template: str, vendor: str) -> None:
    """Every vendor token x every claim shape must be detected."""
    payload = template.format(v=vendor)
    assert PROSE_CREDIT.search(payload), f"pattern FAILED to detect: {payload!r}"


@pytest.mark.parametrize(
    "payload",
    [
        "Co-Authored" + "-By: Someone <x@y.z>",
        "Generated" + "-By: a tool",
        "Auth" + "or: Frank Asante Van Laarhoven",
        "Contribut" + "ors: a vendor",
        "  Acknowledge" + "ments: thanks",
    ],
)
def test_shaped_pattern_detects_real_markers(payload: str) -> None:
    assert SHAPED_ATTRIBUTION.search(payload), f"pattern FAILED to detect: {payload!r}"


@pytest.mark.parametrize(
    "payload",
    [
        "Recorded environment: CLI 2.1.287, model id test-model-v1.",
        "The provider reports NEEDS_CONFIGURATION because no credential is set.",
        "models are developers' tools",
        "This policy forbids co-author trailers and contributor credit.",
        "models are developers' tools",
    ],
)
def test_patterns_do_not_fire_on_benign_prose(payload: str) -> None:
    """Discussing attribution, and recording the toolchain, must stay permitted."""
    assert not PROSE_CREDIT.search(payload), f"false positive: {payload!r}"
    assert not SHAPED_ATTRIBUTION.search(payload), f"false positive: {payload!r}"

"""Error messages must point at documentation that exists (RX-54).

An error telling a user to read a section is a promise. When the section is
renamed the promise breaks silently, and the user follows a dead pointer at
exactly the moment they needed the explanation.

This happened here: `T2_REFERENCE` held a generated anchor
(`#t2--measured-and-the-mechanism-that-would-close-it`) and the heading was
reworded when T2's filesystem half was closed. Nothing noticed. So the reference
is now a file plus a heading TEXT, and this test fails on the next rename.
"""

from __future__ import annotations

import pathlib

from retrace_api.web import errors

REPO = pathlib.Path(__file__).resolve().parents[2]


def test_the_referenced_document_exists() -> None:
    assert (REPO / errors.T2_DOCUMENT).is_file(), (
        f"the execution refusal points at {errors.T2_DOCUMENT}, which does not exist"
    )


def test_the_referenced_section_heading_exists() -> None:
    """The heading, not an anchor. A reworded heading must fail here."""
    text = (REPO / errors.T2_DOCUMENT).read_text(encoding="utf-8")
    assert errors.T2_SECTION_HEADING in text, (
        f"{errors.T2_DOCUMENT} no longer contains the heading "
        f"{errors.T2_SECTION_HEADING!r}. Update T2_SECTION_HEADING and this test "
        "together, so the refusal message keeps pointing somewhere real."
    )


def test_the_check_detects_a_missing_heading(tmp_path: pathlib.Path) -> None:
    """DISCRIMINATION CONTROL: a substring check that always passes is no check."""
    doc = tmp_path / "doc.md"
    doc.write_text("## Some other heading\n", encoding="utf-8")
    assert errors.T2_SECTION_HEADING not in doc.read_text(encoding="utf-8")

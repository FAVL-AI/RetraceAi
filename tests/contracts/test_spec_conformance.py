"""Executable conformance against the RECOVERED ORIGINAL schema (RX-03).

``docs/evidence/SPEC_RECONCILIATION_CLOSURE.md`` is the decision record for the
reconciliation. This module is its executable half: the prose says which fields
were adopted, renamed, extended or tightened, and these tests load the original
schema from the staging copy and check that the adoption actually happened.

What conformance means here, precisely
--------------------------------------
Not byte equality of two schema documents. The original sets
``additionalProperties: false``, so it would reject every extension field the
closure document records as scientifically necessary (``output_definitions``,
``population``, ``comparison``, ``units``, ``exclusions``, ``seed``, ``split``,
``created_by``, and ``role`` on an input). The **decided relaxation** is
therefore: a document our model produces must validate against the original
schema once those recorded extension fields are stripped. That is a decision
taken in closure section 2, not a surprise discovered here.

One deviation remains, and it is named rather than hidden:
``required_checks``. The original models each check as an object carrying
``kind``, ``description`` and ``source_of_expectation``; this implementation
still carries check ids as strings with tolerances in ``ComparisonSpec``.
Closure section 3 adopted the original's object form but sequenced it *after*
the identity/tenancy/reference fields because it changes the verifier's
comparison path. :data:`RECORDED_DEVIATIONS` is the allowlist that keeps the
deviation visible: every other validation error fails these tests, and when the
object form lands the allowlist simply stops being exercised -- it does not have
to be edited, and it cannot absorb a new deviation.

``format`` is deliberately not relied on anywhere: see
``test_schema_format_is_annotation.py``.

"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from contracts_support import build_contract, digest
from jsonschema import Draft202012Validator
from retrace_contracts.export_schemas import default_output_directory

#: The verified staging copy of the recovered blueprint. Read-only here.
ORIGINAL_SPEC_PATH = Path(
    "/home/favl/retrace-blueprint-staging/retrace-ai-blueprint/specs/result-contract.schema.json"
)

#: Top-level properties our model adds that the original cannot express. Each is
#: classified EXTENSION in closure section 2, with the reason it is necessary.
EXTENSION_PROPERTIES = frozenset(
    {
        "output_definitions",
        "population",
        "units",
        "exclusions",
        "seed",
        "split",
        "comparison",
        "created_by",
    }
)

#: Extension keys inside an `inputs` item. `role` lets the verifier tell a raw
#: measurement input from the reference output a result is compared against.
EXTENSION_INPUT_KEYS = frozenset({"role"})

#: The single remaining shape deviation, sequenced by closure section 3. Any
#: validation error whose path does NOT start inside this set fails the gate.
RECORDED_DEVIATIONS = frozenset({"required_checks"})

#: Probe strings used to compare two digest patterns by BEHAVIOUR rather than by
#: spelling. `^[a-f0-9]{64}$` and `^[0-9a-f]{64}$` are different strings and the
#: same language; asserting the text would be testing the expression, and would
#: fail on a rewrite that changed nothing. The uppercase probe is the one that
#: matters: it is what a case-insensitive pattern would wrongly accept.
DIGEST_PROBES = (
    "a" * 64,
    "0123456789abcdef" * 4,
    ("a" * 64).upper(),
    "a" * 63,
    "a" * 65,
    "z" * 64,
    "",
    " " + "a" * 63,
)

ORIGINAL_REQUIRED = (
    "contract_id",
    "tenant_id",
    "project_id",
    "version",
    "status",
    "reference_kind",
    "inputs",
    "required_checks",
    "limitations",
)


def _load_original() -> dict[str, Any]:
    """Return the original schema, or skip with a reason if the staging copy is gone.

    Skipping is the honest outcome when the evidence is unavailable: a test that
    silently passed without ever reading the original would be a gate that
    cannot fail, which is worth less than no gate at all.
    """
    if not ORIGINAL_SPEC_PATH.is_file():
        pytest.skip(
            "recovered original schema not present at "
            f"{ORIGINAL_SPEC_PATH}; conformance NOT VERIFIED in this environment"
        )
    return json.loads(ORIGINAL_SPEC_PATH.read_text(encoding="utf-8"))


def _load_generated() -> dict[str, Any]:
    """Return our generated result-contract schema from ``specs/schemas``."""
    path = default_output_directory() / "result_contract.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    """Resolve a one-level local ``$ref`` into ``#/$defs``.

    Enough for the generated schema's shape (pydantic emits enum members as
    ``$defs`` entries referenced from each property) and deliberately not a
    general resolver: a general one would hide a ref shape we did not expect.
    """
    ref = node.get("$ref")
    if ref is None:
        return node
    if not ref.startswith("#/$defs/"):  # pragma: no cover - defensive
        raise AssertionError(f"unexpected $ref form: {ref}")
    return dict(schema["$defs"][ref.removeprefix("#/$defs/")])


def _strip_extensions(document: dict[str, Any]) -> dict[str, Any]:
    """Return ``document`` in the shape the original schema describes.

    Two normalisations, both decided rather than discovered:

    1. The recorded extension fields are removed. This is the decided relaxation
       of the original's ``additionalProperties: false`` (closure section 2).
    2. An OPTIONAL field whose value is ``None`` is dropped. The original models
       ``approval_ref`` as an optional ``string`` -- absent when there is no
       approval -- whereas pydantic serialises an unset optional as explicit
       ``null``. Only keys absent from :data:`ORIGINAL_REQUIRED` are dropped, so
       this cannot hide a missing or null *required* field: such a field stays in
       the document and still fails validation. The canonical digest form keeps
       nulls deliberately (see :mod:`retrace_contracts.canonical`); that is a
       different document for a different purpose.
    """
    stripped = {
        key: value
        for key, value in document.items()
        if key not in EXTENSION_PROPERTIES
        and not (value is None and key not in ORIGINAL_REQUIRED)
    }
    stripped["inputs"] = [
        {key: value for key, value in item.items() if key not in EXTENSION_INPUT_KEYS}
        for item in document["inputs"]
    ]
    return stripped


def _errors_against_original(document: dict[str, Any]) -> list[Any]:
    """Return every validation error of ``document`` against the original schema."""
    validator = Draft202012Validator(_load_original())
    return sorted(validator.iter_errors(document), key=lambda error: list(error.path))


def _outside_the_allowlist(errors: list[Any]) -> list[str]:
    """Return a readable line per error that is NOT a recorded deviation."""
    offending = []
    for error in errors:
        path = list(error.path)
        if path and str(path[0]) in RECORDED_DEVIATIONS:
            continue
        offending.append(f"{'/'.join(str(part) for part in path) or '<root>'}: {error.message}")
    return offending


# --------------------------------------------------------------------------- #
# The original's requirements are our requirements
# --------------------------------------------------------------------------- #
def test_the_original_schema_is_itself_valid_draft_2020_12() -> None:
    """The reference we check against is a well-formed schema in the stated dialect."""
    original = _load_original()
    assert original["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    Draft202012Validator.check_schema(original)


def test_the_recorded_required_list_matches_the_original_exactly() -> None:
    """Meta-test: :data:`ORIGINAL_REQUIRED` is read from the original, not asserted.

    Without this, the per-field test below could drift into checking a list
    somebody typed rather than the list the original actually requires.
    """
    assert tuple(_load_original()["required"]) == ORIGINAL_REQUIRED


@pytest.mark.parametrize("field", ORIGINAL_REQUIRED)
def test_every_field_the_original_requires_is_required_in_ours(field: str) -> None:
    """Closure section 2: the original's required set is adopted in full."""
    assert field in _load_generated()["required"]


def test_we_use_the_originals_dialect() -> None:
    """Closure section 5: both schemas are draft 2020-12, so the semantics match."""
    assert _load_generated()["$schema"] == _load_original()["$schema"]


# --------------------------------------------------------------------------- #
# The closed enums match member for member
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("field", ["status", "reference_kind"])
def test_the_closed_enums_match_the_original_exactly(field: str) -> None:
    """Closure sections 2 and 4: same members, no extras, nothing missing.

    Equality rather than a subset check in either direction. A superset would
    mean we accept a value the original never defined (the ``SYNTHETIC``
    mistake); a subset would mean we refuse one it did.
    """
    original = _load_original()
    generated = _load_generated()
    expected = set(original["properties"][field]["enum"])
    ours = set(_resolve(generated, generated["properties"][field])["enum"])
    assert ours == expected


def test_the_inputs_item_keeps_the_originals_identity_and_digest_rules() -> None:
    """Closure section 2: an input item still requires ``id`` and a 64-hex ``sha256``."""
    original = _load_original()
    generated = _load_generated()
    original_item = original["properties"]["inputs"]["items"]
    ours_item = _resolve(generated, generated["properties"]["inputs"]["items"])

    assert set(original_item["required"]) <= set(ours_item["required"])
    assert {"id", "sha256"} <= set(ours_item["required"])

    original_pattern = re.compile(original_item["properties"]["sha256"]["pattern"])
    our_pattern = re.compile(ours_item["properties"]["sha256"]["pattern"])
    for probe in DIGEST_PROBES:
        assert bool(our_pattern.fullmatch(probe)) == bool(
            original_pattern.fullmatch(probe)
        ), f"digest patterns disagree on {probe!r}"
    # Guard against two patterns that agree only by both accepting nothing.
    assert original_pattern.fullmatch("a" * 64)
    assert our_pattern.fullmatch("a" * 64)
    assert not our_pattern.fullmatch(("a" * 64).upper())


# --------------------------------------------------------------------------- #
# A document our model produces validates against the original
# --------------------------------------------------------------------------- #
def test_a_real_contract_validates_against_the_original_schema() -> None:
    """Closure section 2: conformance holds for a document the model produced.

    Extension fields are stripped first -- the decided relaxation of the
    original's ``additionalProperties: false`` (see the module docstring). The
    only tolerated residue is :data:`RECORDED_DEVIATIONS`.
    """
    document = _strip_extensions(json.loads(build_contract().model_dump_json()))
    offending = _outside_the_allowlist(_errors_against_original(document))
    assert offending == [], "deviation(s) from the original outside the allowlist:\n" + "\n".join(
        offending
    )


def test_an_approved_contract_satisfies_the_originals_conditional() -> None:
    """Closure section 2: ``status == APPROVED`` implies ``approval_ref`` is present.

    The original expresses this as an ``if/then``, so a document that claims
    APPROVED without a reference must fail *the original schema*, not only our
    model validator.
    """
    approved = build_contract(status="APPROVED", approval_ref="ap-0001")
    document = _strip_extensions(json.loads(approved.model_dump_json()))
    assert _outside_the_allowlist(_errors_against_original(document)) == []

    forged = dict(document)
    forged.pop("approval_ref")
    assert _outside_the_allowlist(_errors_against_original(forged)) != []


def test_the_recorded_deviation_is_exactly_required_checks() -> None:
    """Closure section 3: the one remaining shape conflict, stated as a fact.

    Read as documentation of *where* the implementation still differs from the
    original. The allowlist is not consulted to decide whether this passes --
    the errors are inspected directly -- so if the object form lands and the
    deviation disappears, this test reports it rather than quietly continuing.
    """
    document = _strip_extensions(json.loads(build_contract().model_dump_json()))
    deviating = {
        str(list(error.path)[0]) for error in _errors_against_original(document) if error.path
    }
    assert deviating <= RECORDED_DEVIATIONS
    assert deviating == {"required_checks"}, (
        "the set of deviations from the original changed; update "
        "SPEC_RECONCILIATION_CLOSURE.md section 3 rather than this allowlist. "
        f"observed: {sorted(deviating)}"
    )


# --------------------------------------------------------------------------- #
# Negative controls: the gate must reject the bad cases
# --------------------------------------------------------------------------- #
def test_a_document_missing_tenant_id_fails_the_original_schema() -> None:
    """RX-47 negative control: the gate detects a contract with no tenancy."""
    document = _strip_extensions(json.loads(build_contract().model_dump_json()))
    document.pop("tenant_id")
    offending = _outside_the_allowlist(_errors_against_original(document))
    assert any("tenant_id" in line for line in offending), offending


def test_a_reference_kind_of_synthetic_fails_the_original_schema() -> None:
    """Closure section 4 negative control: ``SYNTHETIC`` is not a reference kind.

    Our model refuses it too (see ``test_result_contract.py``); this asserts the
    *original* refuses it, which is what makes the enum-equality test above
    meaningful rather than circular.
    """
    document = _strip_extensions(json.loads(build_contract().model_dump_json()))
    document["reference_kind"] = "SYNTHETIC"
    offending = _outside_the_allowlist(_errors_against_original(document))
    assert any("reference_kind" in line for line in offending), offending


@pytest.mark.parametrize(
    "bad_sha256",
    ["", "abc", digest("x").upper(), digest("x")[:63], digest("x") + "0", "z" * 64],
)
def test_a_malformed_input_digest_fails_the_original_schema(bad_sha256: str) -> None:
    """RX-01 negative control: the original's ``sha256`` pattern is enforcing.

    Includes the uppercase case specifically: ``^[a-f0-9]{64}$`` is
    case-sensitive, and an uppercase digest of the right length is the error a
    pattern that had been written case-insensitively would let through.
    """
    document = _strip_extensions(json.loads(build_contract().model_dump_json()))
    document["inputs"][0]["sha256"] = bad_sha256
    offending = _outside_the_allowlist(_errors_against_original(document))
    assert any("sha256" in line for line in offending), offending


def test_dropping_null_optionals_cannot_hide_a_missing_required_field() -> None:
    """Negative control for the normalisation in :func:`_strip_extensions`.

    A normalisation step that could delete a required field would silently widen
    every conformance test above, so it is shown here that it does not: a
    required field explicitly set to ``None`` survives the strip and fails.
    """
    document = json.loads(build_contract().model_dump_json())
    document["tenant_id"] = None
    stripped = _strip_extensions(document)
    assert "tenant_id" in stripped
    assert _outside_the_allowlist(_errors_against_original(stripped)) != []


def test_an_unstripped_extension_field_fails_the_original_schema() -> None:
    """Positive control for the relaxation: stripping is genuinely necessary.

    This proves the module docstring's claim rather than asserting it. The
    original really does reject our extension fields, so "validates after
    stripping" is a decided relaxation and not a no-op dressed up as one.
    """
    document = json.loads(build_contract().model_dump_json())
    offending = _outside_the_allowlist(_errors_against_original(document))
    assert offending != []
    assert any("additional" in line.lower() for line in offending), offending


def test_a_missing_original_abstains_instead_of_passing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control for the loader: no original means SKIP, never a silent pass.

    This is the failure mode that would quietly void every test in this module:
    if the staging copy disappeared and :func:`_load_original` returned an empty
    schema, ``iter_errors`` would report nothing and each conformance test would
    pass while checking nothing at all. Asserting the skip is what keeps "0
    deviations" meaning "we read the original and found none".
    """
    monkeypatch.setattr(
        "test_spec_conformance.ORIGINAL_SPEC_PATH",
        Path("/nonexistent/retrace-blueprint-staging/result-contract.schema.json"),
    )
    with pytest.raises(pytest.skip.Exception, match="NOT VERIFIED"):
        _load_original()

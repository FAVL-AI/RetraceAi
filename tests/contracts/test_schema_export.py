"""The committed JSON Schemas are generated, current and enforceable (RX-03, RX-22).

"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import (
    build_approval,
    build_bundle,
    build_contract,
    build_draft,
    build_plan,
    build_proposal,
)
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from retrace_contracts.export_schemas import (
    SCHEMA_EXPORTS,
    build_schema,
    default_output_directory,
    export_all,
    main,
    render_schema,
    stale_schemas,
)
from retrace_contracts.result_contract import SCHEMA_VERSION

SCHEMA_DIR = default_output_directory()


def test_default_output_directory_resolves_to_specs_schemas() -> None:
    """The exporter writes to the repository's specs/schemas, not the cwd."""
    assert SCHEMA_DIR.name == "schemas"
    assert SCHEMA_DIR.parent.name == "specs"


def test_committed_schemas_are_in_sync_with_the_models() -> None:
    """RX-03: a model change without a schema regeneration fails here.

    This is the gate that keeps `specs/schemas/` honest. If it fails, run
    `python -m retrace_contracts.export_schemas`.
    """
    assert stale_schemas() == []


@pytest.mark.parametrize("filename", [name for name, _, _ in SCHEMA_EXPORTS])
def test_each_schema_is_committed(filename: str) -> None:
    """RX-03: every exported schema exists on disk."""
    assert (SCHEMA_DIR / filename).is_file()


def test_export_is_byte_identical_on_repeat(tmp_path: Path) -> None:
    """RX-03: regeneration is deterministic, so the diff is empty when nothing changed."""
    first = {path.name: path.read_bytes() for path in export_all(tmp_path / "a")}
    second = {path.name: path.read_bytes() for path in export_all(tmp_path / "b")}
    assert first == second


def test_export_matches_the_committed_files(tmp_path: Path) -> None:
    """RX-03: a fresh export equals what is committed, byte for byte."""
    for path in export_all(tmp_path):
        assert path.read_text(encoding="utf-8") == (SCHEMA_DIR / path.name).read_text(
            encoding="utf-8"
        )


def test_check_mode_detects_drift(tmp_path: Path) -> None:
    """RX-03 negative control: the staleness gate can actually fail.

    A gate that only ever passes proves nothing, so a schema is deliberately
    corrupted and the gate must notice.
    """
    export_all(tmp_path)
    assert stale_schemas(tmp_path) == []
    target = tmp_path / "result_contract.schema.json"
    target.write_text('{"title": "edited by hand"}\n', encoding="utf-8")
    assert stale_schemas(tmp_path) == ["result_contract.schema.json"]
    assert main(["--check", "--out-dir", str(tmp_path)]) == 1


def test_check_mode_detects_a_missing_schema(tmp_path: Path) -> None:
    """RX-03 negative control: a deleted schema counts as stale."""
    export_all(tmp_path)
    (tmp_path / "ui_plan.schema.json").unlink()
    assert stale_schemas(tmp_path) == ["ui_plan.schema.json"]


def test_check_mode_passes_on_a_fresh_export(tmp_path: Path) -> None:
    """RX-03 positive control: the gate passes when nothing has drifted."""
    export_all(tmp_path)
    assert main(["--check", "--out-dir", str(tmp_path)]) == 0


def test_write_mode_creates_every_schema(tmp_path: Path) -> None:
    """The exporter writes every declared schema and reports success."""
    assert main(["--out-dir", str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.glob("*.json")) == sorted(
        name for name, _, _ in SCHEMA_EXPORTS
    )


@pytest.mark.parametrize(("filename", "model", "requirement"), SCHEMA_EXPORTS)
def test_schema_metadata_is_present_and_self_describing(
    filename: str, model: type, requirement: str
) -> None:
    """RX-03: each schema names its dialect, id, source model and requirement."""
    document = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert document["$id"].startswith("urn:retrace:schema:")
    assert document["title"] == model.__name__
    assert document["x-retrace-requirement"] == requirement
    assert document["x-retrace-source-model"].endswith(model.__name__)
    assert document["additionalProperties"] is False
    Draft202012Validator.check_schema(document)


@pytest.mark.parametrize("filename", [name for name, _, _ in SCHEMA_EXPORTS])
def test_schema_is_sorted_and_newline_terminated(filename: str) -> None:
    """Deterministic rendering: sorted keys, two-space indent, trailing newline."""
    text = (SCHEMA_DIR / filename).read_text(encoding="utf-8")
    assert text.endswith("\n")
    document = json.loads(text)
    assert text == json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _validator(filename: str) -> Draft202012Validator:
    document = json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))
    return Draft202012Validator(document)


REAL_INSTANCES = {
    "result_contract.schema.json": build_contract,
    "result_contract_draft.schema.json": build_draft,
    "repair_proposal.schema.json": build_proposal,
    "approval.schema.json": build_approval,
    "evidence_bundle_manifest.schema.json": build_bundle,
    "ui_plan.schema.json": build_plan,
}


@pytest.mark.parametrize("filename", sorted(REAL_INSTANCES))
def test_a_real_record_validates_against_its_committed_schema(filename: str) -> None:
    """RX-03: the generated schema actually accepts what the model produces."""
    record = REAL_INSTANCES[filename]()
    _validator(filename).validate(json.loads(record.model_dump_json()))


@pytest.mark.parametrize("filename", sorted(REAL_INSTANCES))
def test_an_unknown_field_fails_schema_validation(filename: str) -> None:
    """RX-10 negative control: the schema rejects what the model rejects."""
    record = REAL_INSTANCES[filename]()
    payload = json.loads(record.model_dump_json())
    payload["unexpected_field"] = "value"
    with pytest.raises(JsonSchemaValidationError):
        _validator(filename).validate(payload)


def test_result_contract_schema_requires_limitations() -> None:
    """RX-03 negative control: the schema carries the non-empty limitations rule.

    `limitations` is the original schema's name for what this model used to call
    `known_limits`; the non-empty rule is deliberately stricter than the
    original, which permits an empty array (closure section 2).
    """
    payload = json.loads(build_contract().model_dump_json())
    payload["limitations"] = []
    with pytest.raises(JsonSchemaValidationError):
        _validator("result_contract.schema.json").validate(payload)


@pytest.mark.parametrize("field", ["contract_id", "tenant_id", "status", "approval_ref"])
def test_the_draft_schema_rejects_a_server_established_field(field: str) -> None:
    """RX-10/RX-47 negative control: the published boundary schema refuses them too.

    The model refuses these (see `test_result_contract.py`); this asserts the
    *generated schema* does, so a client validating its payload before sending
    learns the same thing the server would tell it.
    """
    payload = json.loads(build_draft().model_dump_json())
    payload[field] = "tenant-victim" if field == "tenant_id" else "x"
    with pytest.raises(JsonSchemaValidationError):
        _validator("result_contract_draft.schema.json").validate(payload)


def test_the_result_contract_schema_id_carries_the_document_shape_version() -> None:
    """Closure section 5: the `$id` version is the shape version, not a contract's.

    `SCHEMA_VERSION` would be inert if nothing consumed it, and an inert version
    constant drifts from the shape it claims to describe.
    """
    document = json.loads((SCHEMA_DIR / "result_contract.schema.json").read_text())
    assert document["$id"] == f"urn:retrace:schema:result_contract:{SCHEMA_VERSION}"
    assert build_contract().version != SCHEMA_VERSION


def test_evidence_bundle_schema_requires_limitations() -> None:
    """RX-15 negative control: the schema carries the non-empty limitations rule."""
    payload = json.loads(build_bundle().model_dump_json())
    payload["limitations"] = []
    with pytest.raises(JsonSchemaValidationError):
        _validator("evidence_bundle_manifest.schema.json").validate(payload)


def test_schema_is_not_hand_written() -> None:
    """RX-03: the committed files declare their generator."""
    for filename, model, requirement in SCHEMA_EXPORTS:
        on_disk = (SCHEMA_DIR / filename).read_text(encoding="utf-8")
        assert on_disk == render_schema(build_schema(filename, model, requirement))
        assert json.loads(on_disk)["x-retrace-generated-by"] == (
            "retrace_contracts.export_schemas"
        )

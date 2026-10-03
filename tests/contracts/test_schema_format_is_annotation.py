"""`format` asserts nothing; the model constraints do the work (closure section 5).

JSON Schema's ``format`` keyword is an **annotation** by default. A validator
that has not been given a format checker reads ``"format": "date-time"`` and
asserts nothing whatsoever about the value. Anything in RETRACE that relies on a
timestamp or an identifier being well-formed therefore has to be enforced by a
pydantic constraint and tested directly -- which is what this module does.

The gate this closes is a specific one: a reviewer who reads
``specs/schemas/approval.schema.json``, sees ``format: date-time``, and concludes
the timestamp is validated. It is not, by that keyword. It is validated because
:class:`~retrace_contracts.Approval` declares ``AwareDatetime``.

"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from conftest import build_approval, build_contract, digest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from retrace_contracts import Approval, ReferenceInput
from retrace_contracts.export_schemas import default_output_directory

MALFORMED_TIMESTAMP = "approved last Tuesday"


def _schema(filename: str) -> dict:
    return json.loads((default_output_directory() / filename).read_text(encoding="utf-8"))


def test_the_timestamp_property_carries_only_the_format_annotation() -> None:
    """Premise of this module, asserted rather than assumed.

    ``approved_at`` has ``format`` and ``type`` and no assertion keyword, so a
    plain validator has nothing to check it with.
    """
    approved_at = _schema("approval.schema.json")["properties"]["approved_at"]
    assert approved_at["format"] == "date-time"
    assert approved_at["type"] == "string"
    assert not {"pattern", "enum", "const"} & set(approved_at)


def test_a_bare_validator_accepts_a_malformed_timestamp() -> None:
    """The annotation really does assert nothing -- demonstrated, not claimed.

    This is the negative control for the test below: it proves the schema-level
    check cannot detect a bad timestamp, so the model-level check is load-bearing
    rather than belt-and-braces.
    """
    document = json.loads(build_approval(contract_hash=digest("c")).model_dump_json())
    document["approved_at"] = MALFORMED_TIMESTAMP
    Draft202012Validator(_schema("approval.schema.json")).validate(document)


def test_the_model_refuses_a_malformed_timestamp() -> None:
    """RX-05: the timestamp rule is enforced by pydantic, where it is real."""
    with pytest.raises(ValidationError):
        build_approval(contract_hash=digest("c"), approved_at=MALFORMED_TIMESTAMP)


def test_the_model_refuses_a_naive_timestamp() -> None:
    """RX-05: a timezone-less instant is ambiguous, and no ``format`` catches it.

    ``2026-10-02T09:00:00`` is a *valid* ``date-time``-shaped string to a format
    checker's eye in many implementations, yet it names no instant. Only the
    ``AwareDatetime`` annotation refuses it.
    """
    naive = dt.datetime(2026, 10, 2, 9, 0, 0)  # noqa: DTZ001 - the point of the test
    assert naive.tzinfo is None
    with pytest.raises(ValidationError):
        Approval(
            approval_id="ap-0001",
            contract_hash=digest("contract"),
            candidate_hash=digest("candidate"),
            input_snapshot_id="snap-0001",
            environment_policy_digest=digest("env"),
            action_digest=digest("action"),
            approved_by="operator",
            approved_at=naive,
        )


@pytest.mark.parametrize(
    "field", ["contract_id", "tenant_id", "project_id", "approval_ref"]
)
def test_identifier_properties_carry_an_assertion_keyword_not_a_format(field: str) -> None:
    """RX-03: identity fields are constrained by ``pattern``, which does assert.

    The distinction matters for the generated schema's usefulness to a client:
    an identifier rule expressed as ``pattern`` is checked by every conforming
    validator, whereas one expressed as ``format`` would be checked by none of
    them unless configured.
    """
    properties = _schema("result_contract.schema.json")["properties"][field]
    # `approval_ref` is nullable, so its constraints sit inside `anyOf`.
    branches = properties.get("anyOf", [properties])
    string_branches = [branch for branch in branches if branch.get("type") == "string"]
    assert string_branches, properties
    for branch in string_branches:
        assert "pattern" in branch
        assert branch["maxLength"] == 128


@pytest.mark.parametrize(
    "bad_id", ["../escape", "has space", "<script>", "-leading-dash", "", "x" * 129]
)
def test_the_model_refuses_a_malformed_identifier(bad_id: str) -> None:
    """RX-03 negative control: an id cannot smuggle markup, a path or whitespace."""
    with pytest.raises(ValidationError):
        build_contract(contract_id=bad_id)


def test_a_bare_validator_also_refuses_a_malformed_identifier() -> None:
    """RX-03 positive control: because it is a ``pattern``, the schema catches it too.

    The contrast with the timestamp case is the whole point of this module: a
    rule written as an assertion keyword survives the trip into JSON Schema, and
    a rule written as ``format`` does not.
    """
    document = json.loads(build_contract().model_dump_json())
    document["contract_id"] = "../escape"
    validator = Draft202012Validator(_schema("result_contract.schema.json"))
    errors = [error for error in validator.iter_errors(document)]
    assert any("contract_id" in str(list(error.path)) for error in errors), errors


def test_the_input_id_traversal_rule_is_a_model_constraint_only() -> None:
    """RX-06/RX-42: the traversal rule lives in a validator, not in the schema.

    ``ReferenceInput.id`` is a ``minLength: 1`` string in the generated schema,
    so the schema accepts ``../outside.csv``. The refusal comes from
    ``validate_relative_path``. Recorded here so that nobody reads the schema
    and concludes a document-level check is enough: a consumer that validates
    only against JSON Schema must apply the path rule itself.
    """
    with pytest.raises(ValidationError):
        ReferenceInput(id="../outside.csv", sha256=digest("x"), role="raw")

    document = json.loads(build_contract().model_dump_json())
    document["inputs"][0]["id"] = "../outside.csv"
    validator = Draft202012Validator(_schema("result_contract.schema.json"))
    assert list(validator.iter_errors(document)) == [], (
        "the generated schema now rejects a traversing input id; if that is "
        "intended, this test should assert the new, stronger behaviour"
    )

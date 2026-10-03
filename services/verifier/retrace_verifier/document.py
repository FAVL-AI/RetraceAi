"""The shape of a run-output document, and the candidate's own declaration.

Separated from :mod:`retrace_verifier.safe_read` because the two jobs are
different: ``safe_read`` decides whether untrusted *bytes* may be parsed at all
(RX-10), while this module decides whether the resulting *mapping* is a
well-formed outputs document. Both refuse rather than coerce.

A run writes one document describing what it produced and -- critically for
RX-14 -- what methodology it actually applied. The methodology block is not
decoration: a run whose numbers match the reference while its declared
exclusions, seed, split, population or units differ from the contract's is a
reanalysis, and :mod:`retrace_verifier.methodology` detects that from this
declaration.

``reported_claims`` is whatever the run said about itself ("VERIFICATION
PASSED"). It is parsed, carried, and **never consulted** (RX-18). The only
module that reads it writes it into
:attr:`~retrace_contracts.VerificationReport.notebook_reported_claims`, which
the frozen contracts layer documents as untrusted context.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field, field_validator
from retrace_contracts import FrozenRecord, Identifier, NonEmptyStr

from .errors import OutputParseRefused

__all__ = [
    "MAX_DECLARED_OUTPUTS",
    "CandidateMethodology",
    "CandidatePopulation",
    "CandidateSplit",
    "OutputDocument",
    "OutputValue",
    "parse_output_document",
]

MAX_DECLARED_OUTPUTS: int = 1024
"""Ceiling on outputs in one document; a summary artefact, not a dataset."""

_MAX_VECTOR_LENGTH: int = 100_000
_MAX_CLAIMS: int = 500


class OutputValue(FrozenRecord):
    """One produced value and the unit the run says it is in (RX-13).

    ``unit`` is the *run's own declaration*. The verifier compares it against
    the contract's declared unit and reports a disagreement as a failure with a
    unit diagnostic. It never converts between units: a conversion would make
    the verifier assert a physical equivalence the contract did not declare.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.OutputValue"

    value: float | str | tuple[float, ...] = Field(
        description="Scalar, text, or a flat numeric vector."
    )
    unit: NonEmptyStr | None = Field(
        default=None, description="Unit as declared by the run, or None."
    )

    @property
    def is_numeric(self) -> bool:
        """Whether this value can take part in a tolerance comparison."""
        return isinstance(self.value, (float, int, tuple)) and not isinstance(self.value, bool)


class CandidateSplit(FrozenRecord):
    """The split the run says it performed (RX-14)."""

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.CandidateSplit"

    strategy: NonEmptyStr = Field(description="Split strategy the run applied.")
    train_fraction: float = Field(gt=0.0, lt=1.0, description="Train fraction the run applied.")
    seed: int | None = Field(default=None, description="Split seed the run applied.")


class CandidatePopulation(FrozenRecord):
    """The population the run says it analysed (RX-14)."""

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.CandidatePopulation"

    count: int = Field(ge=0, description="Record count the run actually analysed.")
    selection_rule: NonEmptyStr | None = Field(
        default=None, description="Selection rule the run applied, when declared."
    )


class CandidateMethodology(FrozenRecord):
    """What the run declares it actually did (RX-14).

    This is the candidate side of the methodology comparison. It is a
    *declaration by the run*, not an observation by the verifier, and the
    verifier treats it as such: a declaration that differs from the contract is
    a methodology delta; a declaration that is absent is missing evidence, not
    an implied match.
    """

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.CandidateMethodology"

    exclusions: tuple[Identifier, ...] = Field(
        default=(), description="Ids of the exclusion rules the run applied."
    )
    seed: int | None = Field(default=None, description="Seed the run used.")
    split: CandidateSplit | None = Field(default=None, description="Split the run performed.")
    population: CandidatePopulation | None = Field(
        default=None, description="Population the run analysed."
    )
    units: dict[str, str] = Field(
        default_factory=dict, description="Output name -> unit the run produced."
    )


class OutputDocument(FrozenRecord):
    """A parsed, well-formed run-output document (RX-10, RX-14, RX-18)."""

    CANONICAL_TYPE_TAG: ClassVar[str] = "retrace.OutputDocument"

    values: dict[str, OutputValue] = Field(
        default_factory=dict, description="Output name -> produced value."
    )
    methodology: CandidateMethodology | None = Field(
        default=None,
        description="What the run declares it did. None means it declared nothing, which "
        "is missing evidence rather than agreement (RX-14).",
    )
    reported_claims: tuple[str, ...] = Field(
        default=(),
        description="What the run said about its own success. Carried, never consulted (RX-18).",
    )

    @field_validator("values")
    @classmethod
    def _bounded_output_count(cls, value: dict[str, OutputValue]) -> dict[str, OutputValue]:
        """Refuse a document declaring more outputs than :data:`MAX_DECLARED_OUTPUTS`."""
        if len(value) > MAX_DECLARED_OUTPUTS:
            raise ValueError(
                f"{len(value)} outputs exceeds MAX_DECLARED_OUTPUTS={MAX_DECLARED_OUTPUTS}"
            )
        return value


def _parse_value(name: str, raw: Any, *, path: str | None) -> OutputValue:
    """Build an :class:`OutputValue` from one entry, refusing anything ambiguous."""
    if isinstance(raw, bool):
        raise OutputParseRefused(
            reason="ambiguous-output-value",
            path=path,
            detail=f"output {name!r} is a boolean; declare a number, a string or a vector",
        )
    if isinstance(raw, (int, float, str)):
        return OutputValue(value=float(raw) if not isinstance(raw, str) else raw)
    if isinstance(raw, list):
        return _parse_vector(name, raw, None, path=path)
    if not isinstance(raw, dict):
        raise OutputParseRefused(
            reason="ambiguous-output-value",
            path=path,
            detail=f"output {name!r} is a {type(raw).__name__}, which has no declared comparison",
        )
    if "value" not in raw:
        raise OutputParseRefused(
            reason="output-missing-value",
            path=path,
            detail=f"output {name!r} declares no 'value' key",
        )
    unit = raw.get("unit")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise OutputParseRefused(
            reason="output-bad-unit",
            path=path,
            detail=f"output {name!r} declares a non-string or empty unit",
        )
    inner = raw["value"]
    if isinstance(inner, list):
        return _parse_vector(name, inner, unit, path=path)
    if isinstance(inner, bool) or not isinstance(inner, (int, float, str)):
        raise OutputParseRefused(
            reason="ambiguous-output-value",
            path=path,
            detail=f"output {name!r} has a value of type {type(inner).__name__}",
        )
    return OutputValue(
        value=float(inner) if not isinstance(inner, str) else inner, unit=unit
    )


def _parse_vector(
    name: str, raw: list[Any], unit: str | None, *, path: str | None
) -> OutputValue:
    """Build a flat numeric vector value, refusing anything non-numeric."""
    if len(raw) > _MAX_VECTOR_LENGTH:
        raise OutputParseRefused(
            reason="vector-too-long",
            path=path,
            detail=f"output {name!r} has {len(raw)} elements; the ceiling is "
            f"{_MAX_VECTOR_LENGTH}",
        )
    numbers: list[float] = []
    for index, element in enumerate(raw):
        if isinstance(element, bool) or not isinstance(element, (int, float)):
            raise OutputParseRefused(
                reason="non-numeric-vector-element",
                path=path,
                detail=f"output {name!r} element {index} is {type(element).__name__}; a "
                "vector output must be flat and numeric",
            )
        numbers.append(float(element))
    return OutputValue(value=tuple(numbers), unit=unit)


def _parse_methodology(raw: Any, *, path: str | None) -> CandidateMethodology:
    """Build a :class:`CandidateMethodology`, refusing a malformed declaration."""
    if not isinstance(raw, dict):
        raise OutputParseRefused(
            reason="methodology-not-an-object",
            path=path,
            detail=f"'methodology' is a {type(raw).__name__}",
        )
    split_raw = raw.get("split")
    population_raw = raw.get("population")
    try:
        split = (
            CandidateSplit(
                strategy=str(split_raw["strategy"]),
                train_fraction=float(split_raw["train_fraction"]),
                seed=split_raw.get("seed"),
            )
            if isinstance(split_raw, dict)
            else None
        )
        population = (
            CandidatePopulation(
                count=int(population_raw["count"]),
                selection_rule=population_raw.get("selection_rule"),
            )
            if isinstance(population_raw, dict)
            else None
        )
        exclusions = tuple(str(item) for item in raw.get("exclusions", ()) or ())
        units = {str(k): str(v) for k, v in dict(raw.get("units", {}) or {}).items()}
        seed = raw.get("seed")
        return CandidateMethodology(
            exclusions=exclusions,
            seed=int(seed) if seed is not None else None,
            split=split,
            population=population,
            units=units,
        )
    except OutputParseRefused:
        raise
    except Exception as error:
        raise OutputParseRefused(
            reason="methodology-malformed", path=path, detail=repr(error)
        ) from error


def parse_output_document(
    payload: dict[str, Any], *, path: str | None = None
) -> OutputDocument:
    """Validate a parsed mapping as an outputs document, or refuse it (RX-10, RX-14).

    Accepted shapes for one output: a bare number, a bare string, a bare numeric
    list, or an object with ``value`` and optional ``unit``. Anything else is
    refused rather than guessed at.
    """
    outputs_raw = payload.get("outputs", payload.get("values"))
    if outputs_raw is None:
        raise OutputParseRefused(
            reason="no-outputs-block",
            path=path,
            detail="the document declares neither 'outputs' nor 'values'",
        )
    if not isinstance(outputs_raw, dict):
        raise OutputParseRefused(
            reason="outputs-not-an-object",
            path=path,
            detail=f"'outputs' is a {type(outputs_raw).__name__}, not a name -> value mapping",
        )
    values = {
        str(name): _parse_value(str(name), raw, path=path)
        for name, raw in outputs_raw.items()
    }
    methodology_raw = payload.get("methodology")
    methodology = (
        _parse_methodology(methodology_raw, path=path) if methodology_raw is not None else None
    )
    claims_raw = payload.get("reported_claims", ())
    if isinstance(claims_raw, str):
        claims_raw = [claims_raw]
    if not isinstance(claims_raw, (list, tuple)):
        claims_raw = ()
    claims = tuple(str(item) for item in list(claims_raw)[:_MAX_CLAIMS])
    try:
        return OutputDocument(values=values, methodology=methodology, reported_claims=claims)
    except ValueError as error:
        raise OutputParseRefused(
            reason="document-refused", path=path, detail=str(error)
        ) from error

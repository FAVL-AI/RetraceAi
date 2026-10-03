"""Fixtures for the runner and verifier suites (RX-08..RX-18).

Everything here builds *real* artefacts: real notebooks, real reference files on
disk with real digests, real contracts. Nothing is mocked, because the
properties under test are properties of bytes and processes.

Provider-shaped identifiers in fixtures are deliberately neutral
(``test-provider``, ``model-v1``): a fixture that named a real vendor would put
a vendor name in the source tree, which this repository's governance suite
refuses.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from retrace_contracts import (
    Attestation,
    ComparisonSpec,
    ContractStatus,
    EnvironmentManifest,
    ExclusionRule,
    ExecutionStatus,
    OutputDefinition,
    OutputKind,
    Population,
    ReferenceInput,
    ReferenceKind,
    ResultContract,
    RunRecord,
    SplitSpec,
    Tolerance,
    sha256_hex,
)
from retrace_verifier import REFERENCE_OUTPUT_ROLE, FilesystemReferenceReader

FIXED_MOMENT = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
"""A fixed, timezone-aware instant. Fixtures never read the clock."""


# --------------------------------------------------------------------------- #
# Notebook fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def nbformat_module() -> Any:
    """Return ``nbformat``, skipping the test when the notebook machinery is absent."""
    return pytest.importorskip("nbformat")


@dataclass
class NotebookFactory:
    """Writes real ``.ipynb`` files for the runner to execute."""

    root: Path
    nbformat: Any
    counter: int = 0

    def write(self, *sources: str, name: str | None = None) -> Path:
        """Write a notebook whose cells are ``sources`` and return its path."""
        self.counter += 1
        notebook = self.nbformat.v4.new_notebook(
            cells=[self.nbformat.v4.new_code_cell(source) for source in sources]
        )
        path = self.root / (name or f"notebook-{self.counter}.ipynb")
        self.nbformat.write(notebook, str(path))
        return path


@pytest.fixture
def notebooks(tmp_path: Path, nbformat_module: Any) -> NotebookFactory:
    """Return a factory that writes notebooks into a per-test directory."""
    root = tmp_path / "notebooks"
    root.mkdir()
    return NotebookFactory(root=root, nbformat=nbformat_module)


# --------------------------------------------------------------------------- #
# Contract and reference fixtures
# --------------------------------------------------------------------------- #
@dataclass
class ReferenceStore:
    """A real on-disk reference store plus the read-only reader over it (RX-09)."""

    root: Path

    @property
    def reader(self) -> FilesystemReferenceReader:
        """Return a read-only reader confined to this store."""
        return FilesystemReferenceReader(self.root)

    def write_json(
        self, relative: str, payload: Mapping[str, Any], *, role: str = REFERENCE_OUTPUT_ROLE
    ) -> ReferenceInput:
        """Write a reference document and return the contract input that pins it."""
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        target.write_bytes(data)
        return ReferenceInput(id=relative, sha256=sha256_hex(data), role=role)

    def write_bytes(
        self, relative: str, data: bytes, *, role: str = REFERENCE_OUTPUT_ROLE
    ) -> ReferenceInput:
        """Write raw reference bytes and return the contract input that pins them."""
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return ReferenceInput(id=relative, sha256=sha256_hex(data), role=role)

    def declare_without_writing(
        self, relative: str, data: bytes, *, role: str = REFERENCE_OUTPUT_ROLE
    ) -> ReferenceInput:
        """Return a contract input pinning bytes that are **not** on disk (RX-17)."""
        return ReferenceInput(id=relative, sha256=sha256_hex(data), role=role)


@pytest.fixture
def references(tmp_path: Path) -> ReferenceStore:
    """Return an empty reference store rooted inside the test's directory."""
    root = tmp_path / "references"
    root.mkdir()
    return ReferenceStore(root=root)


def make_contract(
    *,
    inputs: Sequence[ReferenceInput] = (),
    outputs: Sequence[OutputDefinition] | None = None,
    units: Mapping[str, str] | None = None,
    tolerances: Mapping[str, Tolerance] | None = None,
    exclusions: Sequence[ExclusionRule] = (),
    seed: int | None = 20260301,
    split: SplitSpec | None = None,
    required_checks: Sequence[str] = (),
    population_count: int = 333,
    selection_rule: str = "complete cases only",
    limitations: Sequence[str] = ("SYNTHETIC fixture; establishes nothing about real data.",),
    version: int = 1,
    # The fixture data is synthetic and references no published result, so it is a
    # newly established teaching baseline - not HISTORICAL_REFERENCE, and not
    # NO_REFERENCE (it does establish a baseline). SYNTHETIC is a data-provenance
    # attribute and is deliberately NOT a reference_kind.
    reference_kind: ReferenceKind = ReferenceKind.NEW_TEACHING_REFERENCE,
    status: ContractStatus = ContractStatus.DRAFT,
    approval_ref: str | None = None,
    contract_id: str = "contract-fixture-1",
    tenant_id: str = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    project_id: str = "project-fixture-1",
) -> ResultContract:
    """Build a valid :class:`~retrace_contracts.ResultContract` for a test.

    Defaults describe one scalar output ``mean_mass`` in grams with a declared
    absolute tolerance, which is the smallest contract that can reach
    ``REPRODUCED_WITHIN_CONTRACT``.
    """
    definitions = tuple(
        outputs
        if outputs is not None
        else (OutputDefinition(name="mean_mass", kind=OutputKind.SCALAR, unit="g"),)
    )
    resolved_tolerances = dict(tolerances) if tolerances is not None else {}
    for definition in definitions:
        if definition.kind.is_numeric and definition.name not in resolved_tolerances:
            resolved_tolerances[definition.name] = Tolerance(abs_tol=0.01)
    return ResultContract(
        inputs=tuple(inputs),
        output_definitions=definitions,
        population=Population(expected_count=population_count, selection_rule=selection_rule),
        units=dict(units) if units is not None else {},
        exclusions=tuple(exclusions),
        seed=seed,
        split=split,
        comparison=ComparisonSpec(
            algorithm="elementwise-abs-rel", tolerances=resolved_tolerances
        ),
        required_checks=tuple(required_checks),
        limitations=tuple(limitations),
        version=version,
        reference_kind=reference_kind,
        status=status,
        approval_ref=approval_ref,
        contract_id=contract_id,
        tenant_id=tenant_id,
        project_id=project_id,
        created_by="test-operator",
    )


def make_run_record(
    *, status: ExecutionStatus = ExecutionStatus.SUCCEEDED, exit_code: int | None = 0
) -> RunRecord:
    """Build a :class:`~retrace_contracts.RunRecord` with no model pinned."""
    return RunRecord(
        run_id="run-fixture",
        snapshot_id="snapshot-fixture",
        runner_identity="test-runner-identity",
        environment_policy_digest=sha256_hex(b"test-policy"),
        execution_status=status,
        started_at=FIXED_MOMENT,
        finished_at=FIXED_MOMENT,
        exit_code=exit_code,
        wall_clock_seconds=0.5,
    )


def make_environment_manifest() -> EnvironmentManifest:
    """Build an :class:`~retrace_contracts.EnvironmentManifest` with fixed values."""
    return EnvironmentManifest(
        python_version="3.13.0",
        platform="test-platform",
        packages={"retrace": "0.0.0"},
        policy_digest=sha256_hex(b"test-policy"),
        captured_at=FIXED_MOMENT,
    )


def make_attestation(*, signed: bool = False) -> Attestation:
    """Build an :class:`~retrace_contracts.Attestation` with the required disclaimer."""
    return Attestation(
        attested_by="test-operator",
        attested_at=FIXED_MOMENT,
        statement="This bundle records one synthetic run executed by the test suite.",
        non_certification_statement=(
            "Readiness evidence only. This is not a certification and asserts no "
            "conformance to any external standard."
        ),
        signature="0" * 64 if signed else None,
        signature_algorithm="test-algorithm" if signed else None,
    )


@pytest.fixture
def contract_factory() -> Any:
    """Expose :func:`make_contract` as a fixture for readability in tests."""
    return make_contract


# --------------------------------------------------------------------------- #
# Source-surface scanning (used by the two import-graph suites)
# --------------------------------------------------------------------------- #
@dataclass
class SourceSurface:
    """Static analysis over a package's source, for trust-domain assertions.

    Static analysis is the right tool here precisely *because* it does not run
    the code: an import-graph test that imported the package would be testing
    this interpreter's state rather than the package's dependencies.
    """

    @staticmethod
    def modules(package_root: Path) -> list[Path]:
        """Return every Python module under ``package_root``, sorted."""
        return sorted(package_root.rglob("*.py"))

    @staticmethod
    def imported_names(module: Path) -> set[str]:
        """Return every module name imported by ``module``, including submodules."""
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    names.add(node.module)
                    names.update(f"{node.module}.{alias.name}" for alias in node.names)
        return names

    @staticmethod
    def called_names(module: Path) -> set[str]:
        """Return every simple and dotted callee name called in ``module``."""
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        names: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            target = node.func
            if isinstance(target, ast.Name):
                names.add(target.id)
            elif isinstance(target, ast.Attribute):
                names.add(target.attr)
                if isinstance(target.value, ast.Name):
                    names.add(f"{target.value.id}.{target.attr}")
        return names


@pytest.fixture(scope="session")
def surface() -> SourceSurface:
    """Return the static source-surface scanner."""
    return SourceSurface()


@pytest.fixture
def hostile_module(tmp_path: Path) -> Iterator[Any]:
    """Write a module containing a given forbidden construct, for negative controls.

    A scanner that has only ever been shown to pass is not evidence that it can
    detect anything. Every surface assertion in this suite is paired with a
    synthetic module the scanner must flag.
    """

    def write(source: str, name: str = "hostile_fixture.py") -> Path:
        path = tmp_path / name
        path.write_text(source, encoding="utf-8")
        return path

    yield write

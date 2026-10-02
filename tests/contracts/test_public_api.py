"""The public API other workers import, and the purity of this layer.

The exception names are a cross-worker interface: a rename here breaks the
domain, verifier and UI workers silently (an `except` clause that never matches
is not a syntax error). They are asserted by exact string.

"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest
import retrace_contracts
from retrace_contracts import (
    ApprovalInvalidated,
    ContractImmutable,
    ContractNotApproved,
    RetraceContractError,
    SnapshotIntegrityError,
    UIPlanRejected,
    VerifierAuthorityError,
)

REQUIRED_EXCEPTION_NAMES = [
    "ContractNotApproved",
    "ApprovalInvalidated",
    "SnapshotIntegrityError",
    "UIPlanRejected",
    "VerifierAuthorityError",
    "ContractImmutable",
]

PACKAGE_DIR = Path(retrace_contracts.__file__).resolve().parent

# Modules that may touch the filesystem. The exporter writes specs/schemas;
# nothing else in this layer performs I/O.
FILESYSTEM_ALLOWED = {"export_schemas.py"}

FORBIDDEN_IMPORTS = {
    "pickle",
    "dill",
    "shelve",
    "marshal",
    "socket",
    "subprocess",
    "requests",
    "httpx",
    "urllib",
    "urllib.request",
    "http.client",
    "aiohttp",
    "yaml",
}


@pytest.mark.parametrize("name", REQUIRED_EXCEPTION_NAMES)
def test_required_exception_names_are_importable_with_exact_spelling(name: str) -> None:
    """Other workers import these by name; the spelling is the interface."""
    assert hasattr(retrace_contracts, name)
    exception = getattr(retrace_contracts, name)
    assert isinstance(exception, type)
    assert issubclass(exception, Exception)
    assert exception.__name__ == name


@pytest.mark.parametrize("name", REQUIRED_EXCEPTION_NAMES)
def test_every_exception_derives_from_the_package_base(name: str) -> None:
    """A caller can catch the whole layer with one `except`."""
    assert issubclass(getattr(retrace_contracts, name), RetraceContractError)


@pytest.mark.parametrize("name", REQUIRED_EXCEPTION_NAMES)
def test_every_exception_is_constructible_from_a_bare_message(name: str) -> None:
    """Other workers raise these with a plain message; keyword extras are optional."""
    exception = getattr(retrace_contracts, name)("something went wrong")
    assert "something went wrong" in str(exception)


def test_exceptions_are_not_value_errors() -> None:
    """An authority refusal must not be swallowed by `except ValueError`."""
    assert not issubclass(RetraceContractError, ValueError)


def test_exception_default_messages_are_informative() -> None:
    """A refusal raised with no message still says what was refused."""
    assert "not approved" in str(ContractNotApproved())
    assert "candidate_hash" in str(ApprovalInvalidated(field="candidate_hash"))
    assert "integrity" in str(SnapshotIntegrityError(path="data/x.csv"))
    assert "immutable" in str(ContractImmutable(record="ResultContract", field="seed"))
    assert "authority" in str(VerifierAuthorityError(actor="repair-worker"))
    assert "SCRIPT_INJECTION" in str(UIPlanRejected(reason="SCRIPT_INJECTION"))


def test_snapshot_integrity_error_carries_both_digests() -> None:
    """RX-02: the detector reports what it expected and what it found."""
    error = SnapshotIntegrityError(
        path="data/x.csv", expected_sha256="a" * 64, observed_sha256="b" * 64
    )
    assert error.expected_sha256 == "a" * 64
    assert error.observed_sha256 == "b" * 64
    assert error.path == "data/x.csv"


def test_all_public_names_resolve() -> None:
    """`__all__` is the published surface; every entry must exist."""
    missing = [name for name in retrace_contracts.__all__ if not hasattr(retrace_contracts, name)]
    assert missing == []


def test_all_is_sorted_and_unique() -> None:
    """A stable, sorted surface keeps diffs reviewable."""
    assert retrace_contracts.__all__ == sorted(set(retrace_contracts.__all__))


@pytest.mark.parametrize(
    "name",
    [
        "approval",
        "base",
        "canonical",
        "enums",
        "evidence_bundle",
        "exceptions",
        "paths",
        "repair",
        "result_contract",
        "ui_plan",
        "verification",
        "export_schemas",
    ],
)
def test_every_module_imports_cleanly(name: str) -> None:
    """No module has an import-time side effect that fails."""
    assert importlib.import_module(f"retrace_contracts.{name}") is not None


def _imported_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


@pytest.mark.parametrize(
    "module_path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda path: path.name
)
def test_contracts_layer_imports_nothing_dangerous(module_path: Path) -> None:
    """RX-10/RX-32: no pickle, no subprocess, no network client in this layer.

    The contracts layer is parsed by anything that reads a bundle or a run
    output, so it must not be able to deserialise code or open a socket. This
    is an AST check, so a dynamic `__import__` would evade it -- which is why
    the next test also forbids that.
    """
    offending = _imported_names(module_path.read_text(encoding="utf-8")) & FORBIDDEN_IMPORTS
    assert offending == set(), f"{module_path.name} imports {sorted(offending)}"


@pytest.mark.parametrize(
    "module_path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda path: path.name
)
def test_contracts_layer_uses_no_dynamic_execution(module_path: Path) -> None:
    """RX-10: no eval/exec/compile/__import__ anywhere in this layer."""
    source = module_path.read_text(encoding="utf-8")
    forbidden = {"eval", "exec", "compile", "__import__"}
    called: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in forbidden:
                called.add(node.func.id)
    assert called == set(), f"{module_path.name} calls {sorted(called)}"


@pytest.mark.parametrize(
    "module_path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda path: path.name
)
def test_only_the_exporter_touches_the_filesystem(module_path: Path) -> None:
    """The record layer is pure: construction never reads or writes files."""
    if module_path.name in FILESYSTEM_ALLOWED:
        pytest.skip("the exporter writes specs/schemas by design")
    names = _imported_names(module_path.read_text(encoding="utf-8"))
    assert "pathlib" not in names
    assert "os" not in names
    assert "io" not in names


@pytest.mark.parametrize(
    "module_path", sorted(PACKAGE_DIR.glob("*.py")), ids=lambda path: path.name
)
def test_no_module_reads_the_clock(module_path: Path) -> None:
    """Records never stamp themselves, so they stay reproducible and testable."""
    source = module_path.read_text(encoding="utf-8")
    for forbidden in ("datetime.now(", "datetime.utcnow(", "time.time(", "date.today("):
        assert forbidden not in source, f"{module_path.name} contains {forbidden}"


def test_package_declares_type_information() -> None:
    """Downstream workers get types from this package."""
    assert (PACKAGE_DIR / "py.typed").is_file()

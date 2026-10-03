"""Structural properties of the domain package itself.

Named ``test_domain_structure`` rather than ``test_public_api`` because
``tests/contracts`` already owns that basename and the suite has no
``__init__.py`` files: two test modules sharing a basename cannot both be
imported under pytest's prepend import mode.

The claims in this package's docstrings -- no network, no clock, no arbitrary
deserialisation, no dependency on the verifier -- are either checkable or they
are decoration. These tests check them by parsing the package's own source, so
a future edit that quietly adds ``import socket`` fails here rather than in
production.

The repository-wide attribution control in ``tests/governance`` reads
**git-tracked** files. New files are untracked until they are staged, so the
same properties are re-checked here against the files on disk. Two independent
detectors for one property is the right number when the property is a release
gate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import retrace_domain
from retrace_contracts import RetraceContractError
from retrace_domain import (
    ApprovalLedger,
    ContentAddressedStore,
    DeterministicRepairProvider,
    GovernedModelRepairProvider,
    LedgerAppendRefused,
    LedgerIntegrityError,
    ProviderNotConfigured,
    RepairAuthority,
    UnsafeSourcePath,
    WriteRefused,
)

PACKAGE_ROOT = Path(retrace_domain.__file__).resolve().parent
TESTS_ROOT = Path(__file__).resolve().parent

#: Modules that would make a documented property false if imported here.
#: ``pickle``/``marshal``/``shelve`` are listed for RX-10: nothing in RETRACE
#: deserialises arbitrary objects. ``subprocess`` is listed because this layer
#: has no business starting a process -- isolated execution is the runner's job.
FORBIDDEN_IMPORTS = frozenset(
    {
        "aiohttp",
        "ftplib",
        "http",
        "httpx",
        "marshal",
        "pickle",
        "random",
        "requests",
        "shelve",
        "smtplib",
        "socket",
        "ssl",
        "subprocess",
        "telnetlib",
        "time",
        "urllib",
        "xmlrpc",
    }
)

#: Call spellings that read a clock. A record that stamps itself cannot be
#: reconstructed from evidence or tested deterministically, so every timestamp
#: in this package is supplied by the caller.
CLOCK_CALLS = ("datetime.now(", ".utcnow(", "time.time(", "time.monotonic(")

# The attribution controls that used to live here (a vendor-name scan, a
# shaped-attribution scan and their negative controls) were REMOVED, not
# weakened. They duplicated tests/governance/test_attribution_policy.py, which
# is the single authority for that property repo-wide.
#
# The duplicate existed for a good reason - it swept the FILESYSTEM while the
# canonical control swept git-tracked files only, so an unstaged file could pass
# the canonical one vacuously. Rather than keep two copies of one rule, that gap
# was fixed in the canonical control, which now runs both sweeps. Keeping the
# vendor vocabulary in exactly one file also keeps it out of this one.


def source_files() -> list[Path]:
    """Every Python file this worker owns, read from disk rather than from git."""
    files = sorted(PACKAGE_ROOT.rglob("*.py")) + sorted(TESTS_ROOT.rglob("*.py"))
    assert len(files) >= 10, "the file sweep found almost nothing; it would pass vacuously"
    return files


def imported_modules(path: Path) -> set[str]:
    """Return the top-level module names ``path`` imports, parsed with :mod:`ast`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


# ---------------------------------------------------------------------------
# The public surface.
# ---------------------------------------------------------------------------


def test_every_exported_name_resolves() -> None:
    """A name in ``__all__`` that does not exist is a broken public surface."""
    for name in retrace_domain.__all__:
        assert hasattr(retrace_domain, name), f"__all__ exports missing name {name!r}"


def test_the_public_surface_is_sorted_and_unique() -> None:
    """``__all__`` is read by humans; order and duplicates are not editorial."""
    assert retrace_domain.__all__ == sorted(set(retrace_domain.__all__))


def test_the_four_load_bearing_units_are_exported() -> None:
    """The package exists for these four things; they are reachable by name."""
    assert retrace_domain.ContentAddressedStore is ContentAddressedStore
    assert retrace_domain.ApprovalLedger is ApprovalLedger
    assert retrace_domain.RepairAuthority is RepairAuthority
    assert retrace_domain.DeterministicRepairProvider is DeterministicRepairProvider
    assert retrace_domain.GovernedModelRepairProvider is GovernedModelRepairProvider


@pytest.mark.parametrize(
    "error",
    [
        UnsafeSourcePath,
        LedgerIntegrityError,
        LedgerAppendRefused,
        WriteRefused,
        ProviderNotConfigured,
    ],
)
def test_every_refusal_is_a_contract_layer_error(error: type[Exception]) -> None:
    """One ``except`` clause catches the whole authority layer's refusals."""
    assert issubclass(error, RetraceContractError)


def test_the_contracts_models_are_not_redefined() -> None:
    """The contracts layer is frozen: this package imports its models, never copies them.

    Asserted by identity against the installed package, so a shadow definition
    with the same name would fail here.
    """
    import retrace_contracts
    from retrace_domain.ledger import LedgerEntry

    assert LedgerEntry.__mro__[1] is retrace_contracts.FrozenRecord
    for name in ("Approval", "RepairProposal", "FrozenRecord", "ResultContract"):
        assert getattr(retrace_contracts, name).__module__.startswith("retrace_contracts")


# ---------------------------------------------------------------------------
# Structural properties, parsed from the source.
# ---------------------------------------------------------------------------


def test_no_module_imports_a_network_or_deserialisation_module() -> None:
    """RX-08, RX-10: this layer has no egress and deserialises nothing arbitrary.

    The architecture puts egress policy in the service layer. If the domain
    package could open a socket, that boundary would be advisory rather than
    structural.
    """
    offenders = {
        path.relative_to(PACKAGE_ROOT.parent).as_posix(): sorted(
            imported_modules(path) & FORBIDDEN_IMPORTS
        )
        for path in source_files()
        if imported_modules(path) & FORBIDDEN_IMPORTS
    }
    assert not offenders, f"forbidden imports found: {offenders}"


def test_the_detector_for_forbidden_imports_actually_detects(tmp_path: Path) -> None:
    """NEGATIVE CONTROL: a check never shown to fail is not evidence.

    Without this, the test above would also pass if ``imported_modules`` simply
    returned nothing.
    """
    hostile = tmp_path / "hostile.py"
    hostile.write_text("import socket\nfrom pickle import loads\n", encoding="utf-8")
    assert imported_modules(hostile) & FORBIDDEN_IMPORTS == {"socket", "pickle"}


def test_no_module_reads_a_clock() -> None:
    """RX-03's determinism rule, applied to this layer: timestamps are supplied."""
    offenders = [
        (path.name, call)
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        for call in CLOCK_CALLS
        if call in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"clock read in the domain package: {offenders}"


def test_nothing_imports_the_verifier_or_the_runner() -> None:
    """RX-07, RX-09: the authority rule is an import-graph property, not a convention."""
    offenders = {
        path.name: sorted(imported_modules(path) & {"retrace_verifier", "retrace_runner"})
        for path in source_files()
        if imported_modules(path) & {"retrace_verifier", "retrace_runner"}
    }
    assert not offenders, f"domain code reached into another trust domain: {offenders}"


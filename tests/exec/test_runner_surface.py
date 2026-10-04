"""The runner's trust-domain surface, enforced rather than asserted in prose.

WHY THIS FILE EXISTS. Two modules cited it by name:

* ``execution.py``: "The package contains no ``eval``, ``exec`` or ``compile``
  call, which ``tests/exec/test_runner_surface.py`` asserts over the module AST."
* ``__init__.py``: "**Trust-domain rule, enforced by test.** ...
  ``tests/exec/test_runner_surface.py`` walks this package's import graph and
  fails if that changes."

The file did not exist. The properties were real - all four were verified by hand
before this file was written - but nothing enforced them, so the docstrings
described a guarantee the repository did not have. A docstring that names a test
is a claim about the repository, and an unbacked one is worse than silence
because it stops a reader looking. Caught by the confinement worker, which
reported it rather than quietly deleting the sentence.

Each scan here is paired with a DISCRIMINATION CONTROL that runs the same
function over a planted violation in a temporary directory, so a passing result
means the scan works rather than that it cannot see. The real source is never
mutated.

The fourth scan is the interesting one: the package's docstrings MENTION
``VerificationOutcome`` in order to state the rule forbidding it. A text search
would flag the prohibition as the offence. These scans read the AST, so prose is
not a use.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

PACKAGE = pathlib.Path(__file__).resolve().parents[2] / "services" / "runner" / "retrace_runner"

#: Builtins that turn data into code. The runner executes notebooks in a child
#: process via nbclient; it must never itself be a way to run supplied source.
CODE_FROM_DATA = frozenset({"eval", "exec", "compile"})

#: The trust domain the runner must not reach into. It records HOW a process
#: terminated; it must never decide WHETHER a result is correct (RX-09, RX-11).
FORBIDDEN_IMPORTS = frozenset({"retrace_verifier"})

#: Judgement vocabulary. Importing any of these would give the runner a way to
#: represent a verdict, which is the verifier's job alone.
FORBIDDEN_CONTRACT_NAMES = frozenset(
    {"VerificationOutcome", "VerificationReport", "CheckResult", "CheckStatus", "Tolerance",
     "ComparisonSpec", "MethodologyDelta"}
)


def modules(root: pathlib.Path) -> list[pathlib.Path]:
    found = [p for p in sorted(root.rglob("*.py")) if "__pycache__" not in p.parts]
    assert found, f"no modules found under {root}; the scan would pass vacuously"
    return found


def code_from_data_calls(root: pathlib.Path) -> list[str]:
    """Calls to eval/exec/compile, by AST so a docstring mention is not a hit."""
    hits: list[str] = []
    for path in modules(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in CODE_FROM_DATA
            ):
                hits.append(f"{path.name}:{node.lineno} {node.func.id}()")
    return hits


def imported_modules(root: pathlib.Path) -> set[str]:
    """Top-level module names this package imports, from the AST."""
    names: set[str] = set()
    for path in modules(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
    return names


def judgement_name_uses(root: pathlib.Path) -> list[str]:
    """REAL uses of judgement vocabulary - a Name or Attribute node, never prose.

    This is what separates stating the rule from breaking it.
    """
    hits: list[str] = []
    for path in modules(root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_CONTRACT_NAMES:
                hits.append(f"{path.name}:{node.lineno} {node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_CONTRACT_NAMES:
                hits.append(f"{path.name}:{node.lineno} .{node.attr}")
            elif isinstance(node, ast.ImportFrom) and node.names:
                for alias in node.names:
                    if alias.name in FORBIDDEN_CONTRACT_NAMES:
                        hits.append(f"{path.name}:{node.lineno} import {alias.name}")
    return hits


# --------------------------------------------------------------------------- #
# The claims the docstrings make
# --------------------------------------------------------------------------- #
def test_the_package_contains_no_eval_exec_or_compile_call() -> None:
    """execution.py's claim, now actually enforced."""
    hits = code_from_data_calls(PACKAGE)
    assert not hits, f"the runner turns data into code: {hits}"


def test_the_package_does_not_import_the_verifier() -> None:
    """__init__.py's trust-domain claim (RX-09). The runner never judges science."""
    leaked = sorted(imported_modules(PACKAGE) & FORBIDDEN_IMPORTS)
    assert not leaked, f"the runner reached into another trust domain: {leaked}"


def test_the_package_cannot_represent_a_verification_verdict() -> None:
    """No judgement type is imported or used, so no verdict can be constructed."""
    hits = judgement_name_uses(PACKAGE)
    assert not hits, f"the runner can represent a verdict: {hits}"


def test_the_package_exposes_no_comparison_or_tolerance_api() -> None:
    """A public name about comparing or tolerating belongs to the verifier."""
    import retrace_runner

    suspicious = [
        name
        for name in retrace_runner.__all__
        if any(word in name.lower() for word in ("toleran", "compar", "verdict", "outcome"))
    ]
    assert not suspicious, f"runner exports judgement-shaped API: {suspicious}"


# --------------------------------------------------------------------------- #
# DISCRIMINATION CONTROLS - each scan run over a planted violation.
# Without these, four passes could mean four scans that cannot see.
# --------------------------------------------------------------------------- #
@pytest.fixture
def planted(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "fake_pkg"
    root.mkdir()
    (root / "__init__.py").write_text("", encoding="utf-8")
    return root


def test_the_code_from_data_scan_detects_a_planted_call(planted: pathlib.Path) -> None:
    (planted / "bad.py").write_text(
        "def run(src):\n    return eval(src)\n", encoding="utf-8"
    )
    hits = code_from_data_calls(planted)
    assert any("eval()" in hit for hit in hits), hits


def test_the_import_scan_detects_a_planted_verifier_import(planted: pathlib.Path) -> None:
    (planted / "bad.py").write_text(
        "from retrace_verifier import verify\n", encoding="utf-8"
    )
    assert "retrace_verifier" in imported_modules(planted)


def test_the_judgement_scan_detects_a_planted_verdict_use(planted: pathlib.Path) -> None:
    (planted / "bad.py").write_text(
        "from retrace_contracts import VerificationOutcome\n"
        "def judge():\n    return VerificationOutcome.REPRODUCED_WITHIN_CONTRACT\n",
        encoding="utf-8",
    )
    hits = judgement_name_uses(planted)
    assert hits, "a real verdict use was not detected"


def test_the_judgement_scan_does_not_flag_a_docstring_mention(
    planted: pathlib.Path,
) -> None:
    """THE CONTROL THAT MATTERS for this scan.

    The real package states its own prohibition in prose, naming
    ``VerificationOutcome`` to do so. A text search would report the rule as a
    violation and make the scan useless. Reading the AST must not.
    """
    (planted / "fine.py").write_text(
        '"""This module has no type that can represent a VerificationOutcome."""\n'
        "VALUE = 1\n",
        encoding="utf-8",
    )
    assert judgement_name_uses(planted) == [], (
        "the scan flagged a docstring stating the rule as a breach of it"
    )


def test_the_module_sweep_refuses_to_pass_vacuously(tmp_path: pathlib.Path) -> None:
    """An empty tree must raise, not report a clean bill of health."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AssertionError, match="vacuously"):
        modules(empty)

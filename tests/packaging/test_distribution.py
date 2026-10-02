"""Regression guard for the packaging defect recorded in docs/evidence/PACKAGING.md.

WHY THIS EXISTS. A `pytest` run can pass entirely from the source tree while the
built distribution ships nothing. That happened here: `py-modules = []` produced a
wheel containing four dist-info entries and ZERO Python modules, and the build
reported success. Setting `pythonpath` in pyproject.toml made imports work and hid
it completely.

So these tests refuse to ask "can I import it?" from inside the checkout. They
build the real artefact, look inside it, install it into a throwaway environment
with PYTHONPATH removed, and import it from a directory that contains no project
configuration. A source-tree pass is not an installed-package pass.

Marked `integration` and `slow`: they shell out to `build`, create a venv and run
pip. Deselect them for a fast loop, but never treat deselection as a pass.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import venv
import zipfile

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO = pathlib.Path(__file__).resolve().parents[2]
VENV_PY = REPO / ".venv" / "bin" / "python"

#: Every top-level package that must reach the built artefact. Add a package here
#: when it lands; a package that exists in the tree but is missing from the wheel
#: is exactly the defect this file guards.
EXPECTED_TOP_LEVEL = ("retrace_contracts",)


def _clean_env() -> dict[str, str]:
    """A child environment with PYTHONPATH removed.

    This workstation sources ROS, which exports a PYTHONPATH that a venv still
    honours. Leaving it set lets the child import things the artefact never
    declared, which is the opposite of what is being tested.
    """
    import os

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    if not VENV_PY.exists():
        pytest.skip("project venv not present")
    out = tmp_path_factory.mktemp("wheel")
    # S603: the argv is built here from a path this test constructed; there is no
    # untrusted input. The rule stays ENABLED globally because services/runner
    # executes untrusted notebooks and must not be exempt.
    proc = subprocess.run(  # noqa: S603
        [str(VENV_PY), "-m", "build", "--wheel", "--outdir", str(out), str(REPO)],
        capture_output=True, text=True, env=_clean_env(), timeout=600,
    )
    if proc.returncode != 0:
        if "No module named build" in proc.stderr:
            pytest.skip("`build` not installed in the project venv")
        pytest.fail(f"wheel build failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    wheels = sorted(out.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def test_wheel_is_not_empty(wheel: pathlib.Path) -> None:
    """The exact defect: a wheel that builds successfully and ships no modules."""
    modules = [n for n in zipfile.ZipFile(wheel).namelist() if n.endswith(".py")]
    assert modules, (
        "built wheel contains ZERO Python modules. The build succeeded, so this is "
        "silent: check [tool.setuptools] packages discovery in pyproject.toml."
    )


@pytest.mark.parametrize("top_level", EXPECTED_TOP_LEVEL)
def test_wheel_ships_each_expected_package(wheel: pathlib.Path, top_level: str) -> None:
    names = zipfile.ZipFile(wheel).namelist()
    assert any(n.startswith(f"{top_level}/") and n.endswith(".py") for n in names), (
        f"{top_level} exists in the source tree but is absent from the wheel"
    )


def test_wheel_ships_an_importable_init(wheel: pathlib.Path) -> None:
    names = zipfile.ZipFile(wheel).namelist()
    for top in EXPECTED_TOP_LEVEL:
        assert f"{top}/__init__.py" in names, f"{top} has no __init__.py in the wheel"


@pytest.fixture(scope="module")
def installed(wheel: pathlib.Path, tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    env_dir = tmp_path_factory.mktemp("cleanenv") / "venv"
    venv.create(env_dir, with_pip=True, clear=True)
    py = env_dir / "bin" / "python"
    proc = subprocess.run(  # noqa: S603 - locally constructed argv, see above
        [str(py), "-m", "pip", "install", "--quiet", str(wheel)],
        capture_output=True, text=True, env=_clean_env(), timeout=900,
    )
    assert proc.returncode == 0, f"install failed:\n{proc.stderr[-2000:]}"
    return py


def test_imports_from_site_packages_outside_the_repository(
    installed: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Run from a directory with no project config, with PYTHONPATH cleared.

    Asserts the import resolves to site-packages and that no repository path is on
    sys.path - either would mean the test proved nothing about the artefact.
    """
    probe = """
import json, sys, os
assert "PYTHONPATH" not in os.environ, "PYTHONPATH leaked into the child"
repo_paths = [p for p in sys.path if "retrace-ai" in p]
import retrace_contracts as rc
json.dump({
    "file": rc.__file__,
    "repo_paths": repo_paths,
    "outcomes": len(list(rc.VerificationOutcome)),
}, sys.stdout)
"""
    proc = subprocess.run(  # noqa: S603 - locally constructed argv, see above
        [str(installed), "-c", probe],
        capture_output=True, text=True, cwd=tmp_path, env=_clean_env(), timeout=300,
    )
    assert proc.returncode == 0, f"probe failed:\n{proc.stderr[-2000:]}"
    got = json.loads(proc.stdout)
    assert got["repo_paths"] == [], f"repository path on sys.path: {got['repo_paths']}"
    assert "site-packages" in got["file"], f"not imported from the install: {got['file']}"
    assert "retrace-ai" not in got["file"], f"imported from the source tree: {got['file']}"
    assert got["outcomes"] == 5, got["outcomes"]


def test_installed_artefact_still_enforces_approval_binding(
    installed: pathlib.Path, tmp_path: pathlib.Path
) -> None:
    """Behaviour, not just importability: the authority invariant must hold in the
    thing that actually ships."""
    probe = """
import datetime as dt, sys
import retrace_contracts as rc
c = rc.ResultContract(
    output_definitions=(rc.OutputDefinition(name="m", kind=rc.OutputKind.SCALAR, unit="g"),),
    population=rc.Population(expected_count=3, selection_rule="all"),
    comparison=rc.ComparisonSpec(algorithm="scalar_abs_rel",
                                 tolerances={"m": rc.Tolerance(abs_tol=1e-9)}),
    known_limits=("synthetic",), contract_version=1, created_by="favl")
bound = dict(contract_hash=c.contract_hash, candidate_hash="b"*64, input_snapshot_id="s",
             environment_policy_digest="c"*64, action_digest="d"*64)
ap = rc.Approval(approval_id="a", approved_by="favl",
                 approved_at=dt.datetime(2026, 10, 2, tzinfo=dt.timezone.utc), **bound)
ap.validate_binding(**bound)
for field in bound:
    altered = dict(bound); altered[field] = "0" * len(bound[field])
    try:
        ap.validate_binding(**altered)
    except rc.ApprovalInvalidated:
        continue
    sys.exit("installed artefact ACCEPTED an altered " + field)
print("OK")
"""
    proc = subprocess.run(  # noqa: S603 - locally constructed argv, see above
        [str(installed), "-c", probe],
        capture_output=True, text=True, cwd=tmp_path, env=_clean_env(), timeout=300,
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr[-2000:]}"
    assert "OK" in proc.stdout

"""Exercise the REAL attribution checker, not a reimplementation.

`test_attribution_policy.py` re-states the policy's patterns so this repository
enforces them locally. That is a compensating control, and on its own it proves
only that my copy of the rules works. These tests invoke the ACTUAL canonical
hook from FAVL-Engineering-OS against fixtures in a throwaway git repository,
and record what it accepts and refuses.

Nothing here modifies FAVL-Engineering-OS, installs anything machine-wide, or
changes the caller's git configuration. Each case builds its own repository in a
temporary directory and runs the hook against that.

The POSITIVE cases matter as much as the hostile ones. An attribution safeguard
that deletes accurate provenance - a third party's authorship, a citation, a
copyright line, a licence notice, a required AI-use disclosure - has broken
something rather than protected it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# ONE source of truth for the vendor vocabulary. Importing it keeps this file
# free of a literal vendor name - which the repository's own filesystem sweep
# correctly refused when it was spelled here - and means these probes cover
# every name the policy knows rather than one I happened to pick.
from test_attribution_policy import VENDOR_NAMES

CONTROLS = Path(
    os.environ.get(
        "FAVL_ENGINEERING_CONTROLS",
        str(Path.home() / "FAVL-Engineering-OS" / "engineering-controls"),
    )
)
HOOK = CONTROLS / "hooks" / "pre-commit"

pytestmark = pytest.mark.integration


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(
        {
            "GIT_AUTHOR_NAME": "Frank Asante Van Laarhoven",
            "GIT_AUTHOR_EMAIL": "frankleroyvan@gmail.com",
            "GIT_COMMITTER_NAME": "Frank Asante Van Laarhoven",
            "GIT_COMMITTER_EMAIL": "frankleroyvan@gmail.com",
        }
    )
    return env


@pytest.fixture(scope="module", autouse=True)
def _require_hook():
    if not HOOK.is_file():
        pytest.skip(f"canonical control not present at {HOOK}")
    if not os.access(HOOK, os.X_OK):
        pytest.skip(f"canonical control is not executable: {HOOK}")


def run_hook(tmp: Path, files: dict[str, str], *, allow: str | None = None) -> tuple[int, str]:
    """Stage ``files`` in a fresh repo and run the REAL hook. Returns (rc, output)."""
    repo = tmp / "repo"
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    subprocess.run(  # noqa: S603, S607
        ["git", "init", "-q"], cwd=repo, check=True, env=_env()  # noqa: S607
    )
    if allow is not None:
        (repo / ".attribution-allow").write_text(allow, encoding="utf-8")
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    subprocess.run(  # noqa: S603, S607
        ["git", "add", "-A"], cwd=repo, check=True, env=_env()  # noqa: S607
    )
    proc = subprocess.run(  # noqa: S603
        [str(HOOK)], cwd=repo, capture_output=True, text=True, env=_env(), timeout=300
    )
    return proc.returncode, proc.stdout + proc.stderr


# --------------------------------------------------------------------------- #
# The checker genuinely refuses attribution. If these pass trivially the rest of
# this file means nothing.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("label", "body"),
    [
        ("co-author trailer", "# x\n" + "Co-Authored" + "-By: Someone <a@b.c>\n"),
        ("generated-by trailer", "# x\n" + "Generated" + "-By: a tool\n"),
        ("author metadata key", "# x\n" + "Auth" + "or: Somebody Else\n"),
    ],
)
def test_real_checker_refuses_shaped_attribution(tmp_path: Path, label: str, body: str) -> None:
    rc, out = run_hook(tmp_path, {"docs/notes.md": body})
    assert rc != 0, f"the real checker ACCEPTED {label}: {out}"
    assert "BLOCKED" in out, out


# --------------------------------------------------------------------------- #
# The reported gap, measured against the real checker.
# --------------------------------------------------------------------------- #
PROSE_CLAIM = "# probe\n{v} is a co-author of this document.\n"


@pytest.mark.parametrize("vendor", VENDOR_NAMES)
def test_real_checker_refuses_prose_credit_in_an_ordinary_path(
    tmp_path: Path, vendor: str
) -> None:
    """Baseline: outside the evidence class the prose scan fires, for every name."""
    rc, out = run_hook(tmp_path, {"docs/science/p.md": PROSE_CLAIM.format(v=vendor)})
    assert rc != 0, f"prose credit accepted in an ordinary path for {vendor}: {out}"


def test_real_checker_accepts_prose_credit_inside_the_evidence_class(tmp_path: Path) -> None:
    """THE REPORTED DEFECT, reproduced against the real control.

    An allow-listed `docs/**evidence**/` path takes the approved-evidence scan,
    which sets struct_scan=0 and so disables BOTH the structural scan
    (intentionally) and the prose-credit scan (not intentionally). A sentence
    asserting a vendor authored the work is therefore accepted.

    This test asserts the CURRENT behaviour. It is expected to FAIL - and should
    be inverted - once the upstream control separates those two flags. Until
    then it is the evidence that the gap is real and not a misreading.
    """
    rc, out = run_hook(
        tmp_path,
        {"docs/evidence/p.md": PROSE_CLAIM.format(v=VENDOR_NAMES[0])},
        allow="docs/evidence/*\n",
    )
    assert rc == 0, (
        "the upstream control now refuses prose credit inside the evidence class. "
        "That is the fix landing: invert this test and close the finding in "
        f"docs/evidence/ATTRIBUTION_CONTROL.md. Output:\n{out}"
    )


def test_the_evidence_class_still_refuses_trailers(tmp_path: Path) -> None:
    """The exemption is narrow: shaped attribution is still refused there."""
    rc, out = run_hook(
        tmp_path,
        {"docs/evidence/p.md": "# x\n" + "Co-Authored" + "-By: Someone <a@b.c>\n"},
        allow="docs/evidence/*\n",
    )
    assert rc != 0, f"the evidence class accepted a co-author trailer: {out}"


# --------------------------------------------------------------------------- #
# POSITIVE cases. A safeguard that erases accurate provenance is a defect.
# --------------------------------------------------------------------------- #
LEGITIMATE = {
    "third-party authorship in a citation": (
        "Samuel and Mietchen (2024) studied reproducibility of biomedical "
        "Jupyter notebooks. GigaScience, DOI 10.1093/gigascience/giad113.\n"
    ),
    "a bibliography entry naming people": (
        "- Lewis et al. (2020). Retrieval-augmented generation. NeurIPS.\n"
        "- Horst, A. M., Hill, A. P., Gorman, K. B. (2020). palmerpenguins.\n"
    ),
    "a copyright line": "Copyright (c) 2026 Some Other Organisation. All rights reserved.\n",
    "an SPDX licence identifier": "SPDX-License-Identifier: Apache-2.0\n",
    "a licence grant paragraph": (
        "Licensed under the Apache License, Version 2.0 (the \"License\"); you may\n"
        "not use this file except in compliance with the License.\n"
    ),
    "a required AI-use disclosure": (
        "Disclosure: parts of this analysis were produced with machine assistance, "
        "reviewed by the named researcher, who is responsible for the content.\n"
    ),
    "a dataset attribution requirement": (
        "The Wine Quality dataset is provided by the UCI Machine Learning "
        "Repository and must be cited when used.\n"
    ),
    "prose discussing the policy itself": (
        "This repository forbids co-author trailers, contributor credit lines and "
        "generated-by notes in any tracked file.\n"
    ),
}


@pytest.mark.parametrize(("label", "body"), sorted(LEGITIMATE.items()))
def test_real_checker_preserves_legitimate_provenance(
    tmp_path: Path, label: str, body: str
) -> None:
    """Each of these must be ACCEPTED. A refusal here is a false positive that
    would force a contributor to delete true information."""
    rc, out = run_hook(tmp_path, {"docs/notes.md": body})
    assert rc == 0, f"the real checker REFUSED legitimate provenance ({label}):\n{out}"

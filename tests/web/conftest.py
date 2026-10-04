"""Fixtures for the browser-workspace suite (RX-19 .. RX-25).

Every fixture reads real repository state. The authority for the five outcome
labels is ``docs/UX.md``, parsed here rather than copied: a copy in the test
would prove only that two copies agree. The authority for the nine truthfulness
tokens, the five outcome ids, the reference categories and the protected region
ids is the frozen Python layer (``retrace_i18n``, ``retrace_contracts``), which
is importable in this suite and is the same authority the API will use.

Synthetic and hostile inputs for the negative controls live in
``tests/web/helpers.py``, so a planted violation is always visible as
``helpers.<builder>`` at the call site and can never be mistaken for real
repository content.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
UI_SRC = REPO / "packages" / "ui" / "src"
UI_TOKENS = REPO / "packages" / "ui" / "tokens"
WEB = REPO / "apps" / "web"
WEB_SRC = WEB / "src"
SPECS = REPO / "specs" / "schemas"
UX_DOC = REPO / "docs" / "UX.md"

#: docs/UX.md verification-state row: | `MEMBER` | `--token` | `#hex` | "Label" |
_UX_OUTCOME_ROW = re.compile(r"^\|\s*`([A-Z_]+)`\s*\|[^|]*\|[^|]*\|\s*\"([^\"]+)\"\s*\|\s*$")

#: docs/REQUIREMENTS.md RX-20 names the routes in one sentence.
_RX20_ROUTES = re.compile(r"Working routes:\s*([^|]+)\|")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _js_files(root: Path) -> list[Path]:
    return [path for path in sorted(root.rglob("*.js")) if "node_modules" not in path.parts]


@pytest.fixture(scope="session")
def repo() -> Path:
    """The repository root."""
    return REPO


@pytest.fixture(scope="session")
def ui_sources() -> dict[str, str]:
    """Every module in packages/ui/src, keyed by repository-relative path."""
    files = _js_files(UI_SRC)
    assert len(files) >= 12, f"only {len(files)} UI modules found; the sweep would be vacuous"
    return {path.relative_to(REPO).as_posix(): _read(path) for path in files}


@pytest.fixture(scope="session")
def web_sources() -> dict[str, str]:
    """Every module in apps/web/src, keyed by repository-relative path."""
    files = _js_files(WEB_SRC)
    assert len(files) >= 15, f"only {len(files)} web modules found; the sweep would be vacuous"
    return {path.relative_to(REPO).as_posix(): _read(path) for path in files}


@pytest.fixture(scope="session")
def all_js_sources(ui_sources: dict[str, str], web_sources: dict[str, str]) -> dict[str, str]:
    """Both trees together."""
    return {**ui_sources, **web_sources}


@pytest.fixture(scope="session")
def css_sources() -> dict[str, str]:
    """Every stylesheet this worker owns."""
    paths = [
        UI_TOKENS / "tokens.css",
        UI_TOKENS / "components.css",
        WEB / "styles" / "app.css",
    ]
    for path in paths:
        assert path.is_file(), f"missing stylesheet: {path}"
    return {path.relative_to(REPO).as_posix(): _read(path) for path in paths}


@pytest.fixture(scope="session")
def tokens_css(css_sources: dict[str, str]) -> str:
    """The token stylesheet - the authority for every colour value."""
    return css_sources["packages/ui/tokens/tokens.css"]


@pytest.fixture(scope="session")
def ux_outcome_labels() -> dict[str, str]:
    """The five outcome labels parsed from docs/UX.md - the authority (RX-25)."""
    labels: dict[str, str] = {}
    for line in _read(UX_DOC).splitlines():
        match = _UX_OUTCOME_ROW.match(line)
        if match:
            labels[match.group(1)] = match.group(2)
    assert len(labels) == 5, (
        f"expected 5 outcome rows in {UX_DOC}, parsed {sorted(labels)}. Fix the parser, not the "
        "expectation, if the table changed shape."
    )
    return labels


@pytest.fixture(scope="session")
def rx20_routes() -> tuple[str, ...]:
    """The thirteen route names parsed from docs/REQUIREMENTS.md RX-20."""
    match = _RX20_ROUTES.search(_read(REPO / "docs" / "REQUIREMENTS.md"))
    assert match, "could not find the RX-20 route list in docs/REQUIREMENTS.md"
    names = tuple(part.strip() for part in match.group(1).split(",") if part.strip())
    assert len(names) == 13, f"RX-20 should name 13 routes, parsed {names}"
    return names


@pytest.fixture(scope="session")
def node_binary() -> str | None:
    """The system ``node``, or ``None``. Nothing is installed to obtain it."""
    return shutil.which("node")


@pytest.fixture(scope="session")
def check_module_syntax(node_binary: str | None):
    """Return a callable that syntax-checks ES module source with ``node``.

    Uses ``--input-type=module --check`` over stdin, so the file is parsed as an
    ES module regardless of where it sits. This is a PARSE check only: it proves
    the module is syntactically valid JavaScript, not that it behaves.
    """

    def check(source: str) -> tuple[int, str]:
        if node_binary is None:
            pytest.skip("node is not installed; no JavaScript parse check is possible")
        completed = subprocess.run(  # noqa: S603
            [node_binary, "--input-type=module", "--check"],
            input=source,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        return completed.returncode, completed.stderr

    return check

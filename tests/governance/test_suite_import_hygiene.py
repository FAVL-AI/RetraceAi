"""No test module may import a support module whose name is ambiguous.

WHY THIS EXISTS. Several test directories each had a `conftest.py`, and 23 test
modules across three of them imported from it as a bare `conftest`. Under
pytest's prepend import mode that name resolves to whichever `conftest.py`
reached `sys.modules` first, so the imports were correct only by luck of
collection order. The luck ran out twice in one sitting:

* running `tests/api` alongside `tests/migrations` made
  `from conftest import Harness` resolve to `tests/migrations/conftest.py`, and
  five modules failed to collect;
* in the full suite, two INLINE `from conftest import TENANT_B` statements inside
  test bodies resolved to `tests/web/conftest.py`.

The first looked like a collection error, the second like two unrelated tenancy
failures. Both were one defect. Shared helpers now live in uniquely-named
modules (`api_support`, `contracts_support`, `domain_support`, `i18n_support`,
`web_support`) and each `conftest.py` star-imports its own, which keeps fixtures
discoverable while making the imported name unambiguous.

This test fails if an ambiguous bare import comes back - at any indentation,
because the inline ones are exactly the kind `sed` and the eye both miss.
"""

from __future__ import annotations

import pathlib
import re
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[2]
TESTS = REPO / "tests"

#: A bare `from X import ...` or `import X` at any indentation.
BARE_IMPORT = re.compile(r"^[ \t]*(?:from|import)[ \t]+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)


def test_modules() -> list[pathlib.Path]:
    found = [p for p in sorted(TESTS.rglob("*.py")) if "__pycache__" not in p.parts]
    assert len(found) > 20, f"only {len(found)} test modules found; the scan would be vacuous"
    return found


def basenames_by_directory() -> dict[str, set[pathlib.Path]]:
    """Module basename -> the directories that define one with that name."""
    index: dict[str, set[pathlib.Path]] = defaultdict(set)
    for path in test_modules():
        index[path.stem].add(path.parent)
    return index


def test_no_support_module_basename_is_shared_except_conftest() -> None:
    """Two directories may both hold `conftest.py` - pytest requires the name -
    but nothing else, because any other shared basename is importable and
    therefore ambiguous."""
    shared = {
        name: sorted(str(d.relative_to(REPO)) for d in dirs)
        for name, dirs in basenames_by_directory().items()
        if len(dirs) > 1 and name != "conftest"
    }
    assert not shared, f"ambiguous support-module basenames: {shared}"


def test_no_test_module_bare_imports_an_ambiguous_module() -> None:
    """The actual defect: importing a name that more than one directory defines.

    `conftest` is the one that bit, and it is ambiguous by construction, so a
    bare import of it is refused outright - including inside a function body.
    """
    ambiguous = {name for name, dirs in basenames_by_directory().items() if len(dirs) > 1}
    assert "conftest" in ambiguous, (
        "expected `conftest` to be defined in more than one test directory; if that "
        "is no longer true this test needs rethinking rather than deleting"
    )
    offenders: list[str] = []
    for path in test_modules():
        source = path.read_text(encoding="utf-8")
        for match in BARE_IMPORT.finditer(source):
            if match.group(1) in ambiguous:
                line = source.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(REPO)}:{line} imports {match.group(1)!r}")
    assert not offenders, "ambiguous bare imports:\n  " + "\n  ".join(offenders)


def test_the_scan_detects_an_inline_import(tmp_path: pathlib.Path) -> None:
    """DISCRIMINATION CONTROL: the inline form is the one that was missed.

    A line-anchored pattern without the leading-whitespace allowance finds the
    module-level imports and silently skips the ones inside function bodies,
    which is precisely how two of these survived a search-and-replace.
    """
    sample = "def t():\n    from conftest import X\n    return X\n"
    assert BARE_IMPORT.search(sample), "the inline import was not detected"
    assert BARE_IMPORT.search(sample).group(1) == "conftest"
    strict = re.compile(r"^(?:from|import)[ \t]+([A-Za-z_][A-Za-z0-9_]*)\b", re.MULTILINE)
    assert strict.search(sample) is None, (
        "a line-anchored pattern was expected to MISS the inline import; if it now "
        "matches, this control no longer demonstrates the gap it exists to show"
    )

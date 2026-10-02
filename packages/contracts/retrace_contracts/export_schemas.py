"""Deterministic JSON Schema export for the RETRACE contracts (RX-03, RX-22).

The schemas in ``specs/schemas/`` are **generated** from the pydantic models in
this package, never hand-written. A hand-written schema drifts from the code it
claims to describe, and the drift is silent; a generated schema plus a
``--check`` mode makes the drift a test failure.

Usage::

    python -m retrace_contracts.export_schemas            # write specs/schemas
    python -m retrace_contracts.export_schemas --check     # fail if stale
    python -m retrace_contracts.export_schemas --out-dir D # write elsewhere

Determinism: output is ``json.dumps`` with ``indent=2``, ``sort_keys=True``,
``ensure_ascii=True`` and a trailing newline, so two runs of the same code on
the same pydantic version produce byte-identical files. A pydantic upgrade can
legitimately change generated output; ``--check`` is what surfaces that, and the
schemas are then regenerated as a reviewed change rather than discovered later.

"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel

from .approval import Approval
from .evidence_bundle import EvidenceBundleManifest
from .repair import RepairProposal
from .result_contract import ResultContract
from .ui_plan import UIPlan

__all__ = [
    "SCHEMA_EXPORTS",
    "build_schema",
    "default_output_directory",
    "export_all",
    "main",
    "render_schema",
    "stale_schemas",
]

SCHEMA_EXPORTS: Final[tuple[tuple[str, type[BaseModel], str], ...]] = (
    ("result_contract.schema.json", ResultContract, "RX-03"),
    ("repair_proposal.schema.json", RepairProposal, "RX-06"),
    ("approval.schema.json", Approval, "RX-05"),
    ("evidence_bundle_manifest.schema.json", EvidenceBundleManifest, "RX-15"),
    ("ui_plan.schema.json", UIPlan, "RX-22"),
)
"""The exported schemas: filename, source model, and the requirement it serves."""

_JSON_SCHEMA_DIALECT: Final[str] = "https://json-schema.org/draft/2020-12/schema"


def default_output_directory() -> Path:
    """Return ``<repository root>/specs/schemas``.

    Resolved from this file's location (``packages/contracts/retrace_contracts``)
    rather than from the current working directory, so the exporter writes to the
    same place however it is invoked.
    """
    return Path(__file__).resolve().parents[3] / "specs" / "schemas"


def build_schema(filename: str, model: type[BaseModel], requirement: str) -> dict[str, Any]:
    """Return the JSON Schema document for ``model`` (RX-03).

    The ``$id`` is a URN, not an HTTP URL: these schemas are not published at a
    resolvable address in this build, and inventing one would be a claim about
    infrastructure that does not exist.
    """
    schema: dict[str, Any] = model.model_json_schema(
        mode="validation", ref_template="#/$defs/{model}"
    )
    stem = filename.split(".", 1)[0]
    schema["$schema"] = _JSON_SCHEMA_DIALECT
    schema["$id"] = f"urn:retrace:schema:{stem}:1"
    schema.setdefault("title", model.__name__)
    schema["x-retrace-requirement"] = requirement
    schema["x-retrace-source-model"] = f"{model.__module__}.{model.__qualname__}"
    schema["x-retrace-generated-by"] = "retrace_contracts.export_schemas"
    return schema


def render_schema(schema: dict[str, Any]) -> str:
    """Serialise a schema deterministically, with a trailing newline."""
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def export_all(out_dir: Path | None = None) -> list[Path]:
    """Write every schema in :data:`SCHEMA_EXPORTS` and return the paths written."""
    target = out_dir or default_output_directory()
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for filename, model, requirement in SCHEMA_EXPORTS:
        path = target / filename
        path.write_text(render_schema(build_schema(filename, model, requirement)), encoding="utf-8")
        written.append(path)
    return written


def stale_schemas(out_dir: Path | None = None) -> list[str]:
    """Return the filenames whose on-disk content differs from a fresh export.

    A missing file counts as stale. Used by ``--check`` and by
    ``tests/contracts/test_schema_export.py`` so that a model change without a
    schema regeneration fails the suite instead of shipping.
    """
    target = out_dir or default_output_directory()
    stale: list[str] = []
    for filename, model, requirement in SCHEMA_EXPORTS:
        expected = render_schema(build_schema(filename, model, requirement))
        path = target / filename
        if not path.is_file() or path.read_text(encoding="utf-8") != expected:
            stale.append(filename)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point. Returns a process exit code."""
    parser = argparse.ArgumentParser(
        prog="retrace_contracts.export_schemas",
        description="Regenerate the RETRACE JSON Schemas from the pydantic models.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory to write into (default: <repo>/specs/schemas).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; exit non-zero if any on-disk schema is stale.",
    )
    args = parser.parse_args(argv)

    if args.check:
        stale = stale_schemas(args.out_dir)
        if stale:
            print(
                "stale or missing schema(s): " + ", ".join(stale) + "\n"
                "regenerate with: python -m retrace_contracts.export_schemas",
                file=sys.stderr,
            )
            return 1
        print(f"{len(SCHEMA_EXPORTS)} schema(s) up to date")
        return 0

    for path in export_all(args.out_dir):
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

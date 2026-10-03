"""The parent/child exit-status protocol for the isolated runner (RX-08).

Kept in its own module so that :mod:`retrace_runner.execution` (the parent side)
and :mod:`retrace_runner.child_main` (the child side) share one definition
without importing each other. The statuses are deliberately coarse and
disjoint: each one maps to a different *kind* of refusal, so the parent never
has to guess whether a non-zero exit meant "the science failed", "there is no
kernel here" or "isolation could not be established".
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "EXIT_CELL_ERROR",
    "EXIT_ENVIRONMENT_UNAVAILABLE",
    "EXIT_INTERNAL_ERROR",
    "EXIT_ISOLATION_UNAVAILABLE",
    "EXIT_OK",
]

EXIT_OK: Final[int] = 0
"""The notebook ran to completion."""

EXIT_CELL_ERROR: Final[int] = 2
"""A cell raised and cell errors are not allowed. The process ran; the science did not."""

EXIT_ENVIRONMENT_UNAVAILABLE: Final[int] = 3
"""No usable execution environment. The parent turns this into a named exception."""

EXIT_ISOLATION_UNAVAILABLE: Final[int] = 4
"""A requested isolation capability could not be established. Fail closed."""

EXIT_INTERNAL_ERROR: Final[int] = 5
"""An internal child failure, reported to the parent rather than hidden."""

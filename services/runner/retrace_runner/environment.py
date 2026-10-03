"""Read-only capture of the execution environment (RX-08, RX-15, RX-16).

The manifest is what makes a second-person rerun checkable (RX-16): interpreter
version, platform, the exact installed distribution versions, and the digest of
the policy actually applied.

**This module only READS.** It never installs, upgrades, pins or resolves
anything, and it has no code path that could. A manifest that recorded an
environment the runner had just modified would describe a different environment
from the one the science ran in.
"""

from __future__ import annotations

import platform
import sys
from datetime import UTC, datetime
from importlib.metadata import distributions

__all__ = ["capture_environment", "installed_distributions"]


def installed_distributions() -> dict[str, str]:
    """Return a ``name -> version`` map of installed distributions (RX-15).

    Read-only. Names are normalised to lowercase and the first version seen for
    a name wins, so a duplicated distribution on the path cannot make the
    mapping order-dependent. A distribution with unreadable metadata is recorded
    with the version string ``"unknown"`` rather than dropped: a package that is
    importable but unidentifiable is itself a reproducibility fact.
    """
    found: dict[str, str] = {}
    for distribution in distributions():
        try:
            raw_name = distribution.metadata["Name"]
        except Exception:  # noqa: S112 - unreadable metadata is recorded, not fatal
            continue
        if not raw_name:
            continue
        name = str(raw_name).strip().lower()
        if name in found:
            continue
        found[name] = str(distribution.version or "unknown")
    return dict(sorted(found.items()))


def capture_environment(
    *, policy_digest: str, image_digest: str | None = None
) -> dict[str, object]:
    """Return the environment facts for an :class:`~retrace_contracts.EnvironmentManifest`.

    Returns a plain mapping rather than the pydantic model because this function
    runs inside the isolated child, which is deliberately given the narrowest
    possible dependency surface; the parent constructs the model (RX-15).

    ``captured_at`` reads the clock because it records *when this environment was
    observed* -- a measurement, not a derived value. Every value that must be
    reproducible (digests, bundle contents) is supplied by the caller instead.
    """
    return {
        "python_version": sys.version.split()[0],
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "packages": installed_distributions(),
        "policy_digest": policy_digest,
        "image_digest": image_digest,
        "captured_at": datetime.now(UTC).isoformat(),
    }

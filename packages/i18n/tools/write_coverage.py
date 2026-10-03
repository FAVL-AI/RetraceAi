"""Write ``packages/i18n/COVERAGE.json`` (RX-26, RX-30).

A thin runner so the report can be produced without putting anything on
``PYTHONPATH`` - which this workstation needs cleared, because a ROS entry on it
makes pytest autoload a plugin that cannot import.

Run: ``env -u PYTHONPATH ./.venv/bin/python packages/i18n/tools/write_coverage.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from retrace_i18n.coverage import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
# Authoritative test runner for RETRACE.
#
# WHY `env -u PYTHONPATH`: this workstation sources ROS Humble, which exports
#   PYTHONPATH=/opt/ros/humble/lib/python3.10/site-packages:...
# A venv still honours PYTHONPATH, so pytest autoloads ROS's `launch_testing`
# plugin, which imports `launch`, which imports `yaml` - absent from our venv.
# Result: ModuleNotFoundError at COLLECTION time, exit 1, zero tests run.
# That is an environment failure that looks nothing like a test failure, so the
# runner removes the variable rather than relying on the caller's shell.
#
# Never "fix" a failure here by relaxing a test. Fix the environment or the code.
set -euo pipefail
cd "$(dirname "$0")/.."
exec env -u PYTHONPATH ./.venv/bin/python -m pytest "$@"

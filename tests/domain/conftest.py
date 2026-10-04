"""Fixture entry point for tests/domain.

The shared helpers live in `domain_support.py` rather than here, under a UNIQUE
module name. Several test directories each had a `conftest.py`, and the test
modules imported from it as a bare `conftest` - which resolves to whichever
conftest landed in `sys.modules` first. That worked by luck of import order
until it did not: running tests/api alongside tests/migrations made
`from conftest import Harness` resolve to tests/migrations/conftest.py and
five modules failed to collect.

pytest discovers fixtures imported INTO a conftest, so the star-import below
keeps every fixture visible while the name the tests import is unambiguous.
"""

from domain_support import *  # noqa: F401,F403

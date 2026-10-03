"""Alembic script directory for the tenancy schema (RX-47, RX-48, RX-49).

This is a package (it carries `__init__.py`) so setuptools' package discovery
ships the migration scripts in the built wheel. A distribution that installs the
application but not the migrations cannot bring a database to head, which would
make the schema reproducible only from a source checkout.

Alembic ignores `__init__.py` when it enumerates revisions - the filter is in
`alembic/script/base.py` (`_only_source_rev_file`, which excludes `__init__`) -
so the file is invisible to revision resolution. Verified by reading that module
rather than assumed.
"""

from __future__ import annotations

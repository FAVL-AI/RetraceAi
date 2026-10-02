# Packaging gate — evidence

Gate: *"Built distributions installed into a clean environment; intended modules
import and services start from outside the repository without source-path shortcuts."*

## Finding: the earlier `pythonpath` fix concealed a packaging defect

Two config defects were found and reported during T0. Only one was actually fixed by
the first change, and **changing `pytest`'s `pythonpath` made source-tree imports work
while the built distribution shipped nothing.** Measured, not inferred:

```
$ ./.venv/bin/python -m build --wheel --outdir /tmp/wheelproof .
Successfully built retrace-0.0.0-py3-none-any.whl      <-- build "succeeded"
$ # inspect contents
total entries: 4
python modules shipped: 0                               <-- FAILURE
   retrace-0.0.0.dist-info/METADATA
   retrace-0.0.0.dist-info/WHEEL
   retrace-0.0.0.dist-info/top_level.txt
   retrace-0.0.0.dist-info/RECORD
```

Cause: `[tool.setuptools] py-modules = []`, which I had set to make the editable
install succeed when the source roots were still empty. A green source-tree test run
would never have surfaced this. **A source-tree pass is not an installed-package pass.**

## Fix

`[tool.setuptools.packages.find] where = [...]` listing all six monorepo source roots.

```
$ ./.venv/bin/python -m build --wheel --outdir /tmp/wheelproof2 .
modules shipped: 13
top-level packages: {'retrace_contracts': 13}
```

## Clean-environment smoke test

Conditions: fresh `python3 -m venv /tmp/cleanenv`; only the built wheel installed;
`PYTHONPATH` unset via `env -u PYTHONPATH` **and asserted absent in-process**;
cwd `/tmp`, which contains no `pyproject.toml`/`pytest.ini` that could re-add
repository source roots; `sys.path` asserted to contain no path matching `retrace-ai`.

```
imported from : /tmp/cleanenv/lib/python3.13/site-packages/retrace_contracts/__init__.py
outcomes       : 5
contract_hash  : 18cc75afa5a0ec3b ...
modules loaded : 12
CLEAN-INSTALL SMOKE TEST: PASS           exit 0
```

The test does more than import: it constructs a `ResultContract`, computes its hash,
builds an `Approval`, validates a correct binding, and asserts an **altered
candidate_hash is rejected** with `ApprovalInvalidated` — i.e. the authority invariant
holds in the *installed* artefact, not only in the checkout.

Declared-dependency consistency: pip resolved and installed the wheel's declared
`pydantic` from METADATA; the import succeeded with no manual path help.

## Scope and what is NOT proven

- Only `retrace_contracts` exists so far, so only it is covered. `retrace_domain`,
  `retrace_i18n`, `retrace_api`, `retrace_runner`, `retrace_verifier` are in the
  `where` list but **not yet built or smoke-tested** — the roots were empty at build
  time. This gate must be re-run per package as each lands.
- **No service start-up has been tested.** "Services start from outside the
  repository" is `NOT_RUN` — the API does not exist yet.
- A single distribution currently ships all roots. Per-package distributions are
  probably correct for independent versioning and are an open decision.
- No npm/frontend packaging exists yet.

## Regression guard (to add once `tests/` ownership is released by the workers)

A test that builds the wheel, asserts `modules shipped > 0` per expected top-level
package, installs it in a temp venv with `PYTHONPATH` cleared, and asserts
`site-packages` appears in each module's `__file__`. Without that test this defect
can silently return.

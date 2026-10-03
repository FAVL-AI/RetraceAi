# TEST_REPORT (interim — build in flight)

> **Run provenance.** Earlier sections of this file record runs against earlier
> trees. A test count is a measurement of a specific tree, not a property the
> project keeps. The table immediately below is the only CURRENT result; the
> `1097` figure that appeared in review belongs to tree `27875ff`
> (commit `8a5eafb`) and was re-measured on that tree before being quoted again.

## Current run

| Field | Value |
|---|---|
| Commit | `4acb93b` |
| Branch | `build/retrace-t0-t2` |
| Worktree | clean (0 dirty entries at time of run) |
| Command | `./scripts/test.sh` |
| Result | **1117 passed, 5 skipped, 0 failed** |
| Exit code | **0** |
| Duration | 27.5 s |
| Interpreter | `.venv/bin/python` 3.13.13, `PYTHONPATH` cleared by the runner |
| Lint | `ruff check packages services tests` — clean |
| Types | `mypy packages services` — clean, 55 source files |

Prior measurement for comparison, same commands, tree `27875ff` / `8a5eafb`:
1097 passed, 2 skipped, exit 0, 29 s. The delta is +20 passed and +3 skipped,
all from `tests/authority` (T2), and nothing else changed.

The 5 skips are each a deliberate, reasoned `NOT_RUN`, not an incidental skip:
one no-I/O purity exemption for the schema exporter, one authenticated-tenant
gate needing `services/api`, and three T2 attempts needing an authoritative
store or the action-proposal envelope.

Every number here is from a recorded run. Nothing is projected. Where a gate has not
executed it says `NOT_RUN`, never a zero that reads as a pass.

Runner: `scripts/test.sh` (clears `PYTHONPATH`; see Finding F2).
Interpreter: `.venv/bin/python` 3.13.13. Tested tree: `build/retrace-t0-t2`, uncommitted.

## Executed runs

| # | Command | Collected | Passed | Failed | Exit | When |
|---|---|---|---|---|---|---|
| 1 | `python probe_contracts.py` (integrator adversarial probe, v1) | 36 | 33 | 3 | 1 | 2026-10-02 |
| 2 | `python probe_contracts.py` (v2, probe defects fixed) | 37 | **37** | 0 | **0** | 2026-10-02 |
| 3 | `pytest tests/contracts` (ROS `PYTHONPATH` present) | **0** | 0 | — | 1 | collection error — see F2 |
| 4 | `pytest tests/contracts` (`PYTHONPATH` cleared) | 93 | 93 | 0 | 0 | 2026-10-02 |
| 5 | `pytest tests/contracts` (worker added 2 more files) | 146 | 145 | **1** | 1 | 2026-10-02 |
| 6 | clean-env wheel install smoke test, outside repo | 1 | 1 | 0 | 0 | 2026-10-02 |
| 7 | `pytest tests/contracts` after schema regeneration | 417 | 416 | 0 (1 skip) | 0 | 2026-10-02 |
| 8 | `pytest tests/postgres -m integration` (first attempt) | 11 | 4 | **7** | 1 | 2026-10-02 |
| 9 | `pytest tests/postgres -m integration` (after two DDL/test fixes) | 11 | **11** | 0 | **0** | 2026-10-02 |
| 10 | `scripts/test.sh` — whole suite, integration included | 501 | **500** | 0 (1 skip) | **0** | 2026-10-02 |

Run 10 breakdown: 416 contracts + 73 governance + 11 PostgreSQL integration.
`ruff check` clean across all committed paths; `mypy` clean across 13 contract modules.

Run 1's three "failures" were **defects in my probe, not the implementation**: in all
three cases the code was *stricter* than the probe assumed — it rejects `units` naming
an undeclared output, raises the named `ContractImmutable` (not a bare `TypeError`), and
requires protected regions to be *rendered*, not merely not-hidden. Probe corrected;
run 2 is the result. Recorded rather than quietly overwritten.

## Current failure (run 5) — open

`tests/contracts/test_repair_proposal.py::test_oversize_diff_is_refused`

```
with pytest.raises(ValidationError, match="exceeds"):
E   AssertionError: Regex pattern did not match.
E     Expected regex: 'exceeds'
E     Actual message: "String should have at most 1048576 characters
E                      [type=string_too_long]"
```

**The oversize diff IS refused — the safety property holds.** What failed is the
assertion on the error *text*. Root cause is a genuine defect underneath it (F1).

## Findings

### F1 — unit conflation makes a validator unreachable (real defect, **FIXED**)

**Resolved.** `unified_diff` is now typed `DiffText`
(`max_length=4_194_304`, deliberately well above `MAX_DIFF_BYTES`) so the
byte-length validator is the single size authority and its message is reachable.
`test_oversize_diff_is_refused` passes. Original analysis retained below.



`packages/contracts/retrace_contracts/base.py:53`
```python
LongText = Annotated[str, StringConstraints(min_length=1, max_length=1_048_576)]  # CHARACTERS
```
`packages/contracts/retrace_contracts/repair.py:36,157`
```python
MAX_DIFF_BYTES: Final[int] = 1_048_576                      # BYTES
if len(value.encode("utf-8")) > MAX_DIFF_BYTES: raise ValueError(f"...exceeds...")
```

Same magic number, two different units, and the field-type constraint runs **before**
the custom validator. Consequences:

- **ASCII input** (chars == bytes): the character limit fires first, so the custom
  message is unreachable and the byte guard is dead for the common case.
- **Multi-byte input** (bytes > chars): e.g. 600 000 four-byte characters = 2.4 MB in
  748 KB of... characters — passes the char limit, then the byte guard correctly
  refuses. So the byte guard is reachable, just not by the test's fixture.

Severity: low for safety (both paths refuse), **medium for maintainability** — a reader
will assume one limit, and the two can drift apart silently. For UTF-8, a byte limit of
N is always at least as strict as a char limit of N, so the byte guard is the real
authority and the char constraint is redundant-but-first-firing.

Fix (to apply once the worker releases ownership of these files): type `unified_diff`
with `min_length=1` only and let `_diff_is_bounded` be the single size authority with
its explicit message; keep `MAX_DIFF_BYTES` byte-based. Then split the test into an
ASCII case and a multi-byte case so **both** limits are exercised.

Per the standing rule *test the property, not the expression*: the test should assert
`ValidationError` on the `unified_diff` field, not a substring of pydantic's prose.
Pinning the message is what made a passing safety property look like a failure.

### F2 — ROS `PYTHONPATH` contamination silently zeroes the suite (environment, mitigated)

```
PYTHONPATH=/opt/ros/humble/lib/python3.10/site-packages:/opt/ros/humble/local/lib/python3.10/dist-packages
```
A venv still honours `PYTHONPATH`, so pytest autoloads ROS's `launch_testing`
entry-point plugin → imports `launch` → imports `yaml`, absent from our venv →
`ModuleNotFoundError` at **collection** time. Exit 1, **0 tests run**.

This is the dangerous shape: an environment fault that is not a test failure, and a
zero-collection run that a careless reader scores as "no failures". Mitigated by
`scripts/test.sh`, which removes the variable rather than trusting the caller's shell.
Matches the standing ROS-contamination rule from prior work on this workstation.

### F3 — built distribution shipped zero modules (real defect, fixed + verified)

See `docs/evidence/PACKAGING.md`. The `pytest pythonpath` change made source-tree
imports work while the wheel contained **0 Python modules**; the build still reported
success. Fixed via multi-root `packages.find.where`; wheel now ships 13 modules and a
clean-env install outside the repo passes, including rejecting an altered candidate hash.
A regression test is owed (listed in PACKAGING.md) and does not yet exist.

### F4 — `Author:` metadata key is refused by shape, even with Frank's name (process, fixed)

The machine-wide commit guard refuses `Author:`/`Contributors:`-shaped metadata
*by shape*, correctly — authorship is carried by git identity, never a text
header. My worker brief said "author is Frank Asante Van Laarhoven only", which
caused 38 `Author:` lines across generated modules and blocked the commit. All
removed; the phase-2 brief now forbids the construct explicitly, and
`tests/governance` fails on it so it cannot return.

### F5 — service role was SUPERUSER, silently bypassing RLS (real defect, fixed + verified)

The postgres image makes `POSTGRES_USER` a **superuser with BYPASSRLS**. A
superuser is not subject to row-level security, so had the application used that
role every policy would have been decorative — and an isolation test run as that
role would have proven nothing. Added `retrace_svc`
(`NOSUPERUSER NOBYPASSRLS`, owns no tables, cannot `CREATE`), plus
`FORCE ROW LEVEL SECURITY` because `ENABLE` alone exempts a table's owner.

### F6 — `nullif()` is load-bearing in the RLS policy (real defect, fixed + verified)

A setting established with `set_config(..., is_local => true)` does **not** revert
to `NULL` at transaction end — it reverts to the **empty string**. The policy then
evaluated `''::uuid` and raised `invalid_text_representation` on the next
statement of a pooled connection, instead of cleanly matching no rows. Data was
still denied, so this was not a leak, but an ordinary pooled-connection code path
errored. **SQLite cannot exhibit this**; it was visible only because the test runs
against real PostgreSQL. Fixed with
`nullif(current_setting('retrace.tenant_id', true), '')::uuid`.

### F7 — my own test used `SET LOCAL` with a bind parameter (test defect, fixed)

PostgreSQL's `SET LOCAL` does not accept bind parameters. Replaced with
`select set_config('retrace.tenant_id', %s, true)`, which is parameterizable and
transaction-scoped. Caused 7 of the 7 errors in run 8.

## Gates

| Gate | Status |
|---|---|
| Specification reconciliation | **BLOCKED** — archive not on this host; `/mnt/data` does not exist here (`SPEC_RECONCILIATION.md`). 32 originals unmapped, 57 RX entries unclassified |
| Installed-package correctness | **PASS for `retrace_contracts`** — wheel ships 13 modules, installed into a clean venv, imported from `site-packages` from `/tmp` with `PYTHONPATH` cleared and no repo path on `sys.path`, and the installed artefact still invalidates all five bound approval fields. `NOT_RUN` for the five packages that do not exist yet. **Service start-up `NOT_RUN`** — no service exists. No regression test yet guards the empty-wheel defect |
| Contract conformance tests | **PASS (Python)** — 416 passed, 1 skipped, 0 failed; schemas generated from the models with a sync test that caught real drift. **GAP:** no TypeScript representation exists, so the cross-representation conformance check the directive requires does not exist yet |
| Scientific workflow (valid / result-changing / missing-evidence) | **NOT_RUN** — domain, runner and verifier are being written now. Nothing executed, nothing claimed |
| Browser integration | **NOT_RUN** — no web app exists |

## PostgreSQL

**EXECUTED.** PostgreSQL 17.11, disposable container, loopback-only on a port chosen
to avoid an unrelated project's container. 11 proofs pass, and **every isolation
claim is paired with a discrimination control**: a `BYPASSRLS` role reads the same
rows and confirms they exist, so an empty result cannot be mistaken for an empty
table. Covered: role is neither superuser nor BYPASSRLS; owns no tables; RLS
enabled *and forced*; tenant sees only its own rows; cross-tenant read by explicit
id returns nothing; unset identity returns nothing (fails closed); identity does not
leak into the next transaction on the same connection; `WITH CHECK` refuses writing
another tenant's row; composite `(tenant_id, id)` FK refuses a cross-tenant
reference; the service role cannot create tables.

Not covered: migration/restore, concurrency under load, pgvector, and RLS on tables
that do not exist yet. Alembic migrations are **not written** — the DDL is currently
a plain SQL file applied by hand, which is adequate for a proof and not adequate for
a release.

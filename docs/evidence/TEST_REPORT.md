# TEST_REPORT (interim — build in flight)

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

### F1 — unit conflation makes a validator unreachable (real defect, open)

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

## Gates

| Gate | Status |
|---|---|
| Specification reconciliation | **BLOCKED** — archive not on this host (`SPEC_RECONCILIATION.md`) |
| Installed-package correctness | **PASS for `retrace_contracts`**; `NOT_RUN` for the five packages that do not exist yet; service start-up `NOT_RUN` |
| Contract conformance tests | **PARTIAL** — 145/146 pass, 1 open failure (F1). Python side only; no TypeScript representation exists, so no cross-representation conformance check exists |
| Scientific workflow (valid / result-changing / missing-evidence) | **NOT_RUN** — runner, verifier and domain layers not yet written |
| Browser integration | **NOT_RUN** — no web app exists |

## PostgreSQL

`NOT_RUN`. No PostgreSQL instance has been started; no RLS, migration or concurrency
test has executed. SQLite evidence will not be substituted for PostgreSQL behaviour.

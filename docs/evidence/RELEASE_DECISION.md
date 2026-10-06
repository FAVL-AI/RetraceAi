# RELEASE_DECISION

## Decision: **REVISE**

Named profile: **local development checkpoint, published for review.**

Not authorised by this decision: deployment, a production release, a hosted
multi-tenant deployment, public arbitrary-code execution, a change of repository
visibility, or marking any gate below as passed.

---

## Tested revision

| Field | Value |
|---|---|
| Repository | `/home/favl/retrace-ai` |
| Branch | `build/retrace-t0-t2` |
| Commit measured | `028230dd0bd1bc97b40919df1c282f1fac3861c2` |
| Tree measured | `97d40d6` |
| Working tree at measurement | clean (0 modified, 0 untracked) |
| Measured at | 2026-10-06T22:35:20Z |

A test count measures one tree, not a project. Every number below comes from the
run recorded here. Earlier totals in `TEST_REPORT.md` belong to earlier trees and
are not carried forward.

## Commands and results

| Command | Result | Exit |
|---|---|---|
| `./scripts/test.sh` | **1601 passed, 5 skipped, 0 failed** (45.2 s) | **0** |
| `ruff check packages services tests apps` | All checks passed | 0 |
| `mypy packages services` | no issues in 101 source files | 0 |

PostgreSQL 17.11 (disposable container) was **healthy** during the run, so the
integration tests genuinely executed rather than skipping.

Per area, summing exactly to 1601:

| Area | Passed | Skipped |
|---|---|---|
| `tests/contracts` | 529 | 1 |
| `tests/i18n` | 273 | |
| `tests/domain` | 233 | |
| `tests/api` | 186 | |
| `tests/exec` | 108 | |
| `tests/governance` | 99 | |
| `tests/migrations` | 73 | |
| `tests/web` | 56 | |
| `tests/postgres` | 17 | 1 |
| `tests/authority` | 17 | 3 |
| `tests/packaging` | 10 | |

### The 5 skips are each a reasoned `NOT_RUN`, not an incidental skip

1. forging a verifier payload into the authoritative record — needs a
   verification store that does not exist;
2. an unauthorised verdict write — needs that store plus a broker admitting only
   run/digest-bound results;
3. replay protection — needs the `action-proposal` envelope and its
   `idempotency_key`, recorded `UNRESOLVED-WITH-DECISION` and unimplemented;
4. authenticated tenant derivation **is** covered, at `tests/api`, and cannot be
   asserted from a database-layer file;
5. a no-I/O purity exemption for the schema exporter, which writes by design.

## The five gates

| # | Gate | Verdict | Basis |
|---|---|---|---|
| 1 | All 32 originals accounted for; contract conformance and negative cases executed; no unrecorded schema drift | **PASS** | 32/32 mapped; 68 RX entries classified; `tests/contracts` 529 passed, including conformance against the recovered original schema. The one deviation (`required_checks` item shape) is held in a named one-member allowlist whose own test fails if that set changes |
| 2 | Fresh and upgrade migrations on PostgreSQL; the real application identity passes own-tenant and denied cross-tenant tests | **PASS** | `tests/migrations` 73 passed: empty database to head, the prior hand-applied schema upgraded with its fixture data intact, equivalence to a fresh install, realised-catalogue inspection of `relrowsecurity`/`relforcerowsecurity` and `pg_policies`, and role attributes asserted non-superuser / non-`BYPASSRLS` / owning no tables. `tests/postgres` 17 passed covering missing, empty and malformed tenant context, commit, rollback, connection reuse and cross-tenant writes |
| 3 | Independent-authority enforcement, or execution remains blocked with T2 open | **FAIL — T2 OPEN** | Filesystem half closed over **declared** paths: a child writing natively is denied `EROFS` and a credential read `ENOENT`, verified back from `/proc/self/mountinfo` and proven fail-closed under three reverted source mutations. **Identity half open**: no distinct OS execution identity is available, `DEFAULT_LIMITS` is `NONE`, and no caller requests confinement. The execution endpoint refuses by design |
| 4 | Browser/API demonstration of valid, changed-result and missing-evidence outcomes | **NOT_RUN** | The three outcomes are demonstrated at the verifier layer (`tests/exec/test_scientific_triad.py`, including real notebook execution inside the runner's isolation boundary). They have **never been demonstrated through a browser**: `tests/web` is 56 source-level checks with no driver, no DOM and no axe |
| 5 | Evidence export/import and a clean supported rerun | **NOT_RUN** | Bundle build and import are implemented and unit-tested; a clean second-person rerun has not been executed |

## Why REVISE and not GO-PRODUCTION

Gate 3 fails on measured evidence, and gates 4 and 5 have no evidence at all.
Beyond those:

- **T10 is an accepted limitation, not a solved problem.** Passing a result
  contract establishes agreement with declared checks; it does not independently
  establish the correctness of the reference data, the adequacy of the
  methodology, or the truth of the conclusion. Two of the three mitigations the
  threat model once cited for it are **given no credit** because they were
  unimplemented when assessed.
- **No human scientific review and no independent red team have taken place**
  (`RX-62`). One agent's review is not independent validation. This is the
  requirement most likely to flatter the build by its absence, and it was itself
  missing from the reconstruction until the archive was recovered.
- **No dataset is admitted** (B5) and **no model provider is configured** (B6).
- **Eleven requirements are mapped but `NOT_STARTED`** (`RX-58`…`RX-68`).
- **Readiness artefacts are not certification.** The threat model, ASVS
  applicability matrix, data map, retention procedure and licence review are
  drafts; none has had external review, and the SBOM is an inventory of the
  development environment rather than of release artefacts.

## Why not STOP

The central scientific journey is implemented and executes: snapshot → approved
contract → reviewed repair → isolated run → independent verification → evidence
bundle. The three scientific outcomes are each reached for the right reason, with
discrimination controls proving the checks can fail. Nothing found so far
suggests the approach is unsound — only that it is unfinished and that its
authority separation is incomplete.

## What would change this decision

1. Close T2's identity half: distinct execution identity, and distinct restricted
   database credentials for runner and verifier. Then invert the GAP tests.
2. Make the service profile request confinement with a reviewed path
   declaration, so the shipped default is not the exposed one.
3. Run gate 4 through a real browser driver, and gate 5 as a clean rerun.
4. Admit datasets under reviewed rights (B5) and configure a provider with a
   budget (B6), then run the three real-data case studies.
5. Obtain human scientific review and an independent red team (`RX-62`).
6. Decide the licence, and review dependency licence compatibility.

Until then this remains a development checkpoint, and publishing it is
publication of work in progress — not a release.

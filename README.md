# RETRACE AI

A scientific evidence workbench: recover an existing computational analysis,
inspect every meaningful change, verify declared results against an approved
contract, and hand the work over reproducibly.

---

## Read this first: what this repository is

**This is an incomplete development checkpoint, published for review. It is not a
release, and it is not production-ready.** Two of five release gates pass, one
fails with measured evidence, and two have never been run. The sections below say
which, and why. Nothing here should be read as a claim that RETRACE verifies
science.

**Release decision: REVISE.** See `docs/evidence/RELEASE_DECISION.md`.

### The five gates, as measured

| Gate | Status | Where the evidence is |
|---|---|---|
| Requirement mapping + contract conformance | **PASS** | `docs/evidence/SPEC_RECONCILIATION_CLOSURE.md`, `tests/contracts` |
| Migrations + actual-role database isolation | **PASS** | `tests/migrations`, `tests/postgres` |
| Independent authority (T2) | **FAIL — OPEN** | `docs/security/THREAT_MODEL.md` §T2, `tests/authority` |
| Browser journey: valid / changed-result / missing-evidence | **NOT_RUN** | no browser driver exists in this repository |
| Evidence export/import + clean rerun | **NOT_RUN** | not executed |

### The four things most likely to be misread

1. **`REPRODUCED_WITHIN_CONTRACT` does not mean the science is right.** It means
   the run agreed with the checks its contract declared. It says nothing about
   whether the reference data are correct, the methodology adequate, or the
   conclusion true. `docs/security/T10_REVIEW.md` sets out that boundary, and the
   interface is forbidden from shortening the label to "Reproduced".
2. **The repair worker is not yet separated from the evidence it is judged by.**
   T2's filesystem half is closed by kernel mount-namespace confinement — a child
   writing natively to a protected artefact is denied `EROFS`, and a credential
   read is denied `ENOENT`. Its **identity half is open**: no distinct OS
   execution identity is available on the development host, and
   `DEFAULT_LIMITS.filesystem_confinement` is `NONE`, so the shipped default is as
   exposed as before. The execution endpoint refuses, by design.
3. **`tests/web` is 56 source-level checks, not browser tests.** No driver, no
   DOM, no layout, no axe. They prove the structures exist and that outcome
   labels cannot be written except through the component that labels them fully.
   They cannot prove a key press moves a panel.
4. **The three real-data case studies are `NOT_RUN`.** No dataset has been
   admitted (blocker B5), so the scientific fixtures are `SYNTHETIC` and labelled
   as such. `SYNTHETIC` is a data-provenance attribute and deliberately *not* a
   `reference_kind`.

### Open blockers

| ID | Blocker |
|---|---|
| B4 | Reuse rights for the private `RESEARCH_AI` repository are unresolved |
| B5 | No dataset admitted; the three real-data case studies stay `NOT_RUN` |
| B6 | No model-provider credential or cost budget; model-dependent features report `NEEDS_CONFIGURATION` rather than simulating success |
| T2 | Identity half open (above) |
| — | `RX-58`…`RX-68` are mapped but `NOT_STARTED`: Slack, Calendar, Colab, backup/restore, human review + independent red team, supply chain, share links, export injection, encryption at rest, dataset rights admission, evidence-bound release decision |

---

## What does work, with evidence

The central authority layer is implemented and tested:

- **Content-addressed snapshots** with read-only blobs, re-hash on every read,
  and refusal of `..`/escaping-symlink source trees.
- **Result contracts** reconciled to the recovered specification, canonically
  hashed. Approvals bind a `declaration_digest` that excludes the lifecycle
  label, so marking a contract APPROVED does not invalidate the approval it
  records — while `contract_hash` still covers every field for audit.
- **An append-only approval ledger** with a per-line hash chain, so an edited or
  deleted middle line is detectable, and `supersede()` appends rather than
  rewrites.
- **Scientific restraint**: the deterministic repair provider abstains, with a
  recorded machine-readable reason, rather than touch an exclusion rule, a seed,
  a split, a unit conversion or a row filter. Abstention is a first-class result.
- **An independent verifier** that reads outputs as untrusted data (JSON/CSV
  only; pickle refused by magic bytes and extension), honours declared
  tolerances, treats a changed methodology as `CHANGED_RESULT` *even when every
  number agrees*, and can never report `REPRODUCED_WITHIN_CONTRACT` for a
  contract declaring `NO_REFERENCE`.
- **Row-level security** proven against real PostgreSQL 17 with a non-superuser,
  non-`BYPASSRLS` application role, `FORCE ROW LEVEL SECURITY`, composite
  tenant-consistent foreign keys, and pooled-connection identity handling.

Every gate above is paired with a **discrimination control** — a planted
violation showing the check can actually fail. A check never shown to fail is not
evidence.

## Running the suite

```bash
python3 -m venv .venv && ./.venv/bin/python -m pip install -e '.[dev]'
docker compose --env-file .env -f infra/docker-compose.yml up -d   # disposable PostgreSQL
./scripts/test.sh
```

Use `scripts/test.sh`, not a bare `pytest`. It clears `PYTHONPATH`: on a
workstation with ROS sourced, pytest otherwise autoloads a ROS plugin, fails
importing `yaml`, and exits having collected **zero** tests — a failure that
reads like success.

Requires Python **3.12+** (the runner uses `os.unshare`, added in 3.12) on Linux.
`.env` is not committed; `infra/docker-compose.yml` names the variables it needs.

## Licence

**Not yet determined.** No licence file is present, so default copyright applies
and no permission to use, copy or modify is granted. This is a deliberate open
decision, not an oversight — see `docs/security/LICENCE_REVIEW.md`, which also
records that dependency licence compatibility has **not** been reviewed.

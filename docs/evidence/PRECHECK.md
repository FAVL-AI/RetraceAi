# RETRACE AI — Pre-Execution Audit (PRECHECK)

Date: 2026-10-02
Status: **BLOCKED — specification package absent from this machine**
Evidence states used: VERIFIED / OBSERVED / INFERRED / ASSUMPTION / BLOCKED / UNKNOWN

---

## 1. Objective

Build RETRACE AI as an evidence-led scientific workflow repair and verification
application, per the pasted master implementation prompt: the journey
`authenticate → import authorised source → quarantine/inspect → snapshot →
approved result contract → reproduce baseline failure → reviewed repair →
isolated run → independent verification → explain → portable evidence bundle →
second-researcher rerun`, followed by interface, wiki, model governance,
connectors, collaboration, 36-locale localisation, formats and hardening.

Terminal deliverable: `BUILD_REPORT`, `TEST_REPORT`, `SECURITY_REPORT`,
`BENCHMARK_REPORT`, `CONNECTOR_STATUS`, `I18N_STATUS`, `RELEASE_DECISION`
(GO-PRODUCTION / REVISE / STOP) for a named release profile.

**Objective status: NOT STARTED.** The named source of implementation truth is
not present (field 3).

---

## 2. Repository / HEAD / working-tree state

| Item | Finding | State |
|---|---|---|
| Primary working directory | `/home/favl` | VERIFIED |
| Git repository at `/home/favl` | No — `fatal: not a git repository` | VERIFIED |
| HEAD | None. No repository, therefore no HEAD, no branch, no working tree | VERIFIED |
| RETRACE repository anywhere on host | Absent | VERIFIED |
| This directory (`/home/favl/retrace-ai`) | Created by this audit solely to hold this file. Not a git repository. No application code written | VERIFIED |

`/home/favl` is an unversioned home directory containing many sibling project
repositories. No authorised RETRACE feature branch exists, so the prompt's
"local atomic commits on an authorised feature branch" has no target.

---

## 3. Source of truth and rights — **PRIMARY BLOCKER**

The prompt instructs: "Read MASTER_PROMPT.md and CLAUDE.md", "Use the current
repository as the source of implementation truth", and "Use the custom RETRACE
skills shipped here". None of these inputs exist on this host.

### 3.1 Searches performed (commands and results)

| Search | Result | State |
|---|---|---|
| `find / -xdev -iname "*RETRACE*"` | 0 real matches (only `BuildFeatureTracer.h` / `libgstcoretracers.so` substring hits) | VERIFIED |
| `find /home/favl -iname "*retrace*"` | Same false positives only | VERIFIED |
| `RETRACE_AI_Claude_Code_Blueprint.zip` | Not found anywhere on the filesystem | VERIFIED |
| `MASTER_PROMPT.md` (any depth) | Not found | VERIFIED |
| `/home/favl/CLAUDE.md` (project-level) | Does not exist | VERIFIED |
| Mounted external volumes | None (`/media` holds only `nomachine`; `/mnt` empty) | VERIFIED |
| `~/.claude/skills/` | `enterprise-execution`, `find-skills`, `remotion-*`, `rio-research`, `supabase*`, `task-observer`. **No `retrace-*` skill** | VERIFIED |
| `~/.claude/commands/` | `checkpoint`, `low-context`, `restart-brief`. **No `/retrace-build`** | VERIFIED |

### 3.2 Package artefacts named by the prompt but not present

All of the following are unavailable, so neither their content nor the
"70/70 blueprint-structure checks passed" claim can be verified here:

- `MASTER_PROMPT.md` (stated controlling specification)
- 11 custom skills (`/retrace-build`, `-design`, `-research`, `-science`,
  `-backend`, `-security`, `-connectors`, `-wiki`, `-i18n`, `-redteam`, `-release`)
- 8 specialist agent definitions
- 32 requirements mapped to acceptance tests (the requirement-coverage matrix)
- 4 JSON Schemas (incl. the `UIPlan` schema)
- `specs/locales.json` (36-locale manifest)
- `docs/02-UX.md` (design tokens), `docs/07-EVALUATION.md` (case-study protocols)
- Scientific evidence templates

**Consequence:** a requirement-coverage report cannot be produced against the
32 packaged requirements, because those requirement IDs and their acceptance
tests are not available to read. Reconstructing them from the pasted prose and
then reporting "coverage" against that reconstruction would be coverage against
an invention, which the governing instructions forbid.

### 3.3 Reuse rights

| Source | Finding | State |
|---|---|---|
| RESEARCH_AI repository | Not present locally. Prompt states it is private with **no licence file** | BLOCKED |
| Publication/IP rights for RESEARCH_AI reuse | Not established; requires Frank's review before any code moves into an open-source RETRACE release | BLOCKED |
| Palmer Penguins (CC0), TUM RGB-D, UCI Wine Quality | Not downloaded. No network fetch attempted — no egress authorisation on record | BLOCKED |
| UCI Air Quality | Prompt records conflicting usage statements; correctly excluded pending clarification | OBSERVED |

---

## 4. Installed tools / models / versions

| Component | Version | State |
|---|---|---|
| Claude Code CLI | 2.1.287 | VERIFIED |
| Model (this session) | Opus 5 (1M context), `claude-opus-5[1m]` | VERIFIED |
| Node.js | v22.23.2 | VERIFIED |
| Python | 3.13.13 | VERIFIED |
| git | 2.34.1 | VERIFIED |
| Docker | Server 29.1.3, Ubuntu 22.04.5 LTS | VERIFIED |
| PostgreSQL client (`psql`) | Not on PATH — would require container or install | VERIFIED |
| Redis (`redis-server`) | Not on PATH — would require container | VERIFIED |
| Free disk | 318 GB of 916 GB (64% used) | VERIFIED |

Standing Disk Rule (≥50 GB before test/build): **PASS.**

### 4.1 Command availability

`/effort` is confirmed available (invoked this session; ultracode active).
`/skills`, `/goal`, `/mcp`, `/agents` were **not** independently probed and are
recorded UNKNOWN rather than assumed present.

### 4.2 MCP connections (session-reported)

- **Connected:** Claude Docs, Gmail, Google Calendar, Notion, Vercel, Zapier,
  Context7, Supabase, Scholar Gateway, sequential-thinking, claude-mem,
  claude-in-chrome.
- **Auth required:** Google Drive, Stripe, S&P Deterministic Retrieval.
- **FAILED:** `skill-retrieval` — `CONNECT_TIMEOUT` after 30000ms.

The global skill-retrieval policy requires searching `skill-retrieval` before
finalising a plan. That server is down this session, so the policy could not be
satisfied by tool call. Recorded per policy item 7 (record and continue).
Prior project memory notes this server requires an `mcp==1.29.0` pin to start.

---

## 5. Data classification and egress

| Class | Determination | State |
|---|---|---|
| Scientific source data | None admitted. No datasets fetched or hashed | VERIFIED |
| Credentials in scope | None provisioned for RETRACE (no Anthropic app key, OpenRouter key, GitHub App, Slack app, Google OAuth client) | VERIFIED |
| Host contains unrelated private research | Yes — many sibling project repositories under `/home/favl`. Must not be read into RETRACE or any public release | OBSERVED |
| Egress performed this session | **None.** No network calls, no remote reads, no sends | VERIFIED |
| Egress authorised | Not granted. Prompt forbids push, publication, deployment, paid execution and external sends without explicit approval | VERIFIED |

---

## 6. Authorized actions and budget

**Permitted (and exercised):** local read-only inspection of this host;
creation of this evidence file.

**Permitted but not yet exercised:** local implementation under a declared
directory; local tests; local atomic commits on an authorised branch.

**Explicitly withheld by the prompt:** remote push, publication, deployment,
paid execution, external messages, production migration, infrastructure apply,
public data release, plugin installation, bypass permissions.

**Budget: UNKNOWN.** The prompt requires an "approved execution budget" and
run-level token/request/time/cost ceilings. No figure has been supplied, and no
billing or model-provider credential is configured, so no paid execution path
exists and none was attempted. Anthropic subscription ≠ API budget; not conflated.

**Attribution rule (resolved, no conflict):** the global ownership rule and
`AGENTS.md` require Frank-only authorship with no co-author trailers, AI branding
or generated-by notes. The harness reminder proposing `Co-Authored-By` and
"Generated with Claude Code" lines is overridden by the user's own instructions,
by that reminder's own precedence clause. Any commit will carry Frank's identity
only.

---

## 7. Acceptance tests and baseline health

| Item | Finding | State |
|---|---|---|
| Application code | None exists | VERIFIED |
| Test suite | None exists | VERIFIED |
| Tests executed | **Zero.** Nothing to run | VERIFIED |
| Packaged acceptance tests (32 requirements) | Unavailable (field 3) | BLOCKED |
| Baseline health | No baseline. Nothing to measure | NOT_RUN |
| Scientific results | `NOT_RUN` — no hypothesis tested, no case study executed, no benchmark | NOT_RUN |

No gate has been evaluated. No badge, score or readiness claim is asserted.

---

## 8. Blockers and assumptions

### Blockers (each recorded individually, per instruction)

| ID | Blocker | Owner | Unblocks |
|---|---|---|---|
| B1 | `RETRACE_AI_Claude_Code_Blueprint.zip` / `MASTER_PROMPT.md` absent from host | Frank | Spec authority; the 32-requirement matrix; 4 JSON Schemas; `specs/locales.json`; `docs/02-UX.md`; `docs/07-EVALUATION.md` |
| B2 | 11 `/retrace-*` skills and 8 agent definitions not installed | Frank | The prompt's mandated skill/agent execution path |
| B3 | No authorised repository or feature branch for RETRACE | Frank | Any commit |
| B4 | RESEARCH_AI reuse rights unresolved (private, no licence file) | Frank | Any code/concept reuse in an open-source release |
| B5 | No dataset admission or egress authorisation | Frank | Case studies; `BENCHMARK_REPORT` |
| B6 | No model-provider credential or cost budget | Frank | The in-product repair worker; any paid execution |
| B7 | No connector credentials (GitHub App, Slack, Google, Colab) | Frank | `CONNECTOR_STATUS` beyond `NEEDS_CONFIGURATION` |
| B8 | `skill-retrieval` MCP server `CONNECT_TIMEOUT` | Frank / env | Global skill-retrieval policy compliance |
| B9 | No sandbox boundary evaluated; `psql`/`redis` absent locally | Frank | Isolated untrusted execution; transactional authority |
| B10 | External/independent review and deployment permission not granted | Frank | Release gates; `RELEASE_DECISION` above REVISE |

### Assumptions (declared, unverified)

- A1 — ASSUMPTION: the pasted master prompt and blueprint are faithful copies of
  the package's intent. Their *existence claims* about the package are
  nonetheless unverifiable here, and the package's structure checks are not
  evidence that the application exists.
- A2 — ASSUMPTION: Docker 29.1.3 is usable for development containers. Not
  tested, and container availability is not evidence of a safe sandbox for
  untrusted scientific code.
- A3 — ASSUMPTION: `/home/favl` is the intended parent for a RETRACE repository.
  Not confirmed by Frank.

### Decision

**STOP-AND-CONFIRM at the precheck gate.** Field 3 is unsatisfied: the document
the prompt names as controlling specification is not on this machine, and the
skills it instructs me to execute are not installed. Proceeding would mean
authoring a substitute contract and then reporting coverage against it.

Nothing is claimed as built, tested, verified or ready. Awaiting Frank's
direction on B1–B3.

---

## Addendum A — Gate decisions (2026-10-02)

Frank's direction at the precheck gate:

- **Specification authority: the pasted master prompt + blueprint.** The package
  remains absent (B1/B2 stay OPEN). Every requirement ID, JSON Schema and locale
  entry produced here is a **RECONSTRUCTION authored in this build**, not the
  package's artefact. Reconciliation will be required if the real package appears.
  Reconstructed IDs are namespaced `RX-*` to keep them distinguishable.
- **Build rights: full local build.** `git init` at `/home/favl/retrace-ai`,
  npm/PyPI installs, Postgres/Redis container images, local test execution.
  Still withheld: push, deploy, publication, paid execution, external sends.
- **Dataset fetch: NOT authorised.** B5 remains OPEN. The three real-data case
  studies (Palmer Penguins, TUM RGB-D, UCI Wine Quality) stay `NOT_RUN`.
  The vertical slice uses synthetic fixtures authored in this repository and
  labelled `SYNTHETIC`; they are not presented as, or derived from, those datasets.
- **Model provider: NOT configured.** B6 remains OPEN. The in-product repair
  worker is implemented against a provider interface with a deterministic local
  provider; the Claude provider reports `NEEDS_CONFIGURATION`.

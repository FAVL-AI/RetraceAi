# RETRACE AI — Reconstructed Requirement Matrix

**Provenance warning.** The packaged "32 requirements mapped to acceptance tests"
were NOT available on this host (see `docs/evidence/PRECHECK.md` B1). Every
requirement below was **reconstructed in this build from the pasted master
prompt and blueprint**. IDs are namespaced `RX-` to mark them as reconstructions,
not the package's identifiers. If the original package is recovered, this matrix
must be reconciled against it before any coverage claim is repeated.

Status vocabulary: `IMPLEMENTED` (code + passing test) · `PARTIAL` (code, gaps
named) · `SCAFFOLD` (structure only, no behaviour) · `NOT_STARTED` ·
`BLOCKED` (external dependency, blocker ID given) · `NOT_RUN` (needs execution).

Status is maintained in `docs/evidence/COVERAGE.md`, which is generated from
test results — not asserted here.

---

## A. Scientific core (the central journey)

| ID | Requirement | Acceptance test |
|---|---|---|
| RX-01 | Content-addressed immutable snapshot of an imported source; SHA-256 per file plus a manifest digest | Snapshot twice → identical digest; mutate one byte → digest changes; stored bytes unchanged after re-read |
| RX-02 | Snapshot is tamper-evident: any post-hoc edit to stored bytes is detected | Corrupt a stored blob → verification raises `SnapshotIntegrityError` |
| RX-03 | Versioned, hashed `ResultContract` declaring reference inputs, schema, population, units, exclusions, seed/split, output definitions, comparison algorithm, tolerances, required checks, known limits | Contract round-trips; semantically equal contracts hash equal; any field change changes `contract_hash` |
| RX-04 | A contract must be explicitly approved before any candidate repair can be accepted | Accepting a candidate against an unapproved contract raises `ContractNotApproved` |
| RX-05 | Approval binds candidate hash + contract hash + input snapshot id + environment policy + action digest | Alter any one bound field → `ApprovalInvalidated` |
| RX-06 | Repair proposal is a reviewable patch against a named snapshot, never an in-place mutation | Proposal carries unified diff + candidate hash; source snapshot bytes unchanged after proposal |
| RX-07 | The repair worker cannot modify contracts, reference outputs, approval records or verifier code | Write-allowlist denies each of the four paths; import-graph test proves repair module does not import verifier |
| RX-08 | Execution happens in an isolated runner: no network, bounded wall-clock, bounded memory, scratch-only writes | Notebook attempting a socket connection fails closed; runaway loop is killed at the limit; write outside scratch denied |
| RX-09 | Verifier runs with a separate identity and read-only access to references | Verifier attempting to write a reference raises; verifier credential differs from runner credential |
| RX-10 | Verifier parses run outputs defensively — no `pickle`, no `eval`, no arbitrary deserialisation | Malicious pickle payload in outputs is rejected, not loaded; oversized/deep JSON rejected |
| RX-11 | Execution status is separate from verification status | A run that exits 0 but fails checks reports `EXECUTED_NOT_VERIFIED` / `CHANGED_RESULT`, never `REPRODUCED` |
| RX-12 | Verification outcome is exactly one of `REPRODUCED_WITHIN_CONTRACT`, `EXECUTED_NOT_VERIFIED`, `CHANGED_RESULT`, `BLOCKED_MISSING_EVIDENCE`, `FAILED_EXECUTION` | Each outcome reachable by a dedicated test; no sixth value representable |
| RX-13 | Numerical comparison honours declared tolerances and units; unit mismatch is a failure, not a conversion | g vs kg reference → `CHANGED_RESULT` with unit diagnostic |
| RX-14 | A changed methodology is classified as reanalysis even when results look plausible | Altered exclusion/split → `CHANGED_RESULT` with methodology-delta reason |
| RX-15 | Portable evidence bundle: snapshot, patch, environment manifest, logs, numerical checks, limitations, attestation; RO-Crate-shaped | Bundle validates against profile; bundle digest stable; limitations section non-empty |
| RX-16 | Second-person rerun: an independent import of a bundle re-executes and re-verifies it | Fresh working dir + fresh store imports bundle → same outcome, independently recomputed |
| RX-17 | Missing evidence yields abstention, never an inferred pass | Absent reference output → `BLOCKED_MISSING_EVIDENCE` |
| RX-18 | Notebook-reported outputs are untrusted until independently recomputed | Notebook printing a false "PASS" does not influence the outcome |

## B. Interface

| ID | Requirement | Acceptance test |
|---|---|---|
| RX-19 | Dark / light / system themes with persisted preference; comfortable + compact density | Theme and density round-trip; no colour-only state encoding |
| RX-20 | Working routes: workspaces, projects, sources, studio, lineage, repairs, contracts, runs, evidence, wiki, connectors, calendar, settings | Each route renders; no dead nav entry |
| RX-21 | Panels drag / resize / dock / float / collapse / pin / reorder / restore, with keyboard and menu alternatives for every drag operation | Keyboard-only path achieves each layout operation; axe pass on the workspace |
| RX-22 | Prompt-generated UI returns a schema-valid `UIPlan` over allowlisted components, authorised query IDs and registered actions | Non-allowlisted component rejected; arbitrary JS/SQL in a plan rejected; preview precedes apply; apply reversible |
| RX-23 | Security context, approval controls and truthfulness labels cannot be hidden by a generated layout | A plan hiding any protected region is rejected |
| RX-24 | Graph distinguishes observed/approved relationships from proposed/inferred ones, and exposes a table alternative plus provenance drilldown | Proposed edge renders distinctly; table view lists identical edges |
| RX-25 | Disconnected streams show `STALE`/`UNAVAILABLE`; replay labelled `REPLAY`; fixtures labelled `DEMO` — never synthetic motion | Socket drop → `STALE` within the declared interval; no animation continues |

## C. Localisation and time

| ID | Requirement | Acceptance test |
|---|---|---|
| RX-26 | All 36 locales present across navigation, forms, validation, errors, notifications, help, consent, invites, email, a11y labels, export chrome | Key-coverage check: zero missing keys in any of the 36 catalogues |
| RX-27 | ICU pluralisation, locale-aware numbers/dates, script-appropriate font fallback | Plural categories resolve per locale; no hardcoded date format |
| RX-28 | RTL layout for Arabic, Hebrew, Persian including mixed-direction scientific identifiers | RTL snapshot correct; LTR identifier inside RTL text preserves order |
| RX-29 | Source quotations, code, DOIs, units and datasets are never silently translated | Translation pass leaves protected spans byte-identical |
| RX-30 | Unreviewed translations are labelled `beta` until human linguistic review passes | Locale without review record renders the beta label |
| RX-31 | UTC storage, local display, pinned IANA zones, DST-safe scheduling, ambiguous local-time confirmation | DST spring-forward and fall-back cases resolve explicitly; ambiguous time prompts |

## D. Models, retrieval, wiki

| ID | Requirement | Acceptance test |
|---|---|---|
| RX-32 | Claude is the default provider via server-side credentials; no client-side key | No provider key reachable from the browser bundle |
| RX-33 | OpenRouter selector backed by a timestamped capability catalogue + administrator allowlist; actual model/provider IDs pinned per run | Unlisted model refused; run record pins resolved IDs and catalogue timestamp |
| RX-34 | No silent fallback across a data boundary; blocked choices show the reason | Cross-boundary fallback attempt is refused and surfaced |
| RX-35 | Run-level token, request, time and cost budgets enforced | Exceeding each budget halts the run with the specific reason |
| RX-36 | Live prices require their own verified timestamp; otherwise `cost unavailable` or a labelled estimate | Stale price source → labelled estimate, never a bare number |
| RX-37 | Wiki pipeline preserves page/line/cell anchors and the exact source version; missing evidence abstains | Claim without a resolvable anchor is not published |
| RX-38 | Generated text never promoted to primary evidence | Published page cites a source anchor, not another generated page |
| RX-39 | Cache keys include tenant, principal/entitlement fingerprint, project, source revisions, policy version, model/provider, embedding version, prompt-template version; revocation invalidates derived artefacts | Revoking access invalidates cached context, embeddings, summaries and translations |

## E. Connectors and formats

| ID | Requirement | Acceptance test |
|---|---|---|
| RX-40 | Connector absence reports `NEEDS_CONFIGURATION` — never simulated success | Every unconfigured connector returns that status; no mock success path exists in production code |
| RX-41 | GitHub App consent/install, repo selection, read-only snapshot at a pinned commit, webhook signature verification, revocation; writes are a separate higher permission | Invalid signature rejected; write attempted under read scope refused |
| RX-42 | Uploads quarantined: type/size validation, decompression limits, isolated parsers, no macro execution, no arbitrary pickle deserialisation | Zip-bomb, path-traversal archive, macro-bearing document and pickle payload each rejected |
| RX-43 | Format support declared by an explicit compatibility matrix; originals preserved; no lossless-conversion claim | Matrix published; unsupported format refused rather than best-effort |
| RX-44 | RETRACE's own versioned REST API and MCP tools expose search/inspect/diagnose/propose/request-run/export only — no shell, SQL or approval bypass | Tool list contains no destructive or bypass capability |

## F. Identity, tenancy, security, operations

| ID | Requirement | Acceptance test |
|---|---|---|
| RX-45 | OIDC-based identity; server-managed sessions; CSRF defence; precise CORS; no custom cryptography | Session fixation and CSRF probes fail; wildcard CORS absent |
| RX-46 | Invitations are expiring, single-use, recipient-bound and role-scoped; membership is never inferred from an email domain | Replayed invite refused; domain-match alone grants nothing |
| RX-47 | PostgreSQL tenant isolation enforced by RLS plus server authorization; services are not owner/superuser/BYPASSRLS | Cross-tenant read returns zero rows under the service role; role attributes asserted in test |
| RX-48 | Transaction-local identity context under pooling; background jobs and projections carry it too | Connection reuse cannot leak identity between transactions |
| RX-49 | Composite tenant keys prevent cross-tenant foreign references | Cross-tenant FK insert rejected by constraint |
| RX-50 | Logs redact by schema before emission; content logging off by default | Secret/PII-shaped fields never appear in emitted records |
| RX-51 | Rate limits on account, IP, tenant, route, upload bytes, concurrent runs, tokens and spend; upstream `Retry-After` honoured | Each limit trips in test; duplicate webhook delivery deduplicated |
| RX-52 | Frozen evidence is amended or versioned under a retention procedure — never silently edited or deleted | Edit attempt on a frozen record creates an amendment and preserves the original |
| RX-53 | Resume must not repeat a send, spend, approval or notebook mutation | Checkpoint replay produces no duplicate external effect (idempotency key + outbox dedup) |
| RX-54 | Readiness artefacts exist and are labelled as readiness, not certification: ASVS applicability matrix, threat model, data map, retention/deletion workflow, SBOM, licence review | Each document present; each carries an explicit non-certification statement |

## G. Scientific process record

| ID | Requirement | Acceptance test |
|---|---|---|
| RX-55 | `HYPOTHESES`, `EXPERIMENT_DESIGN`, `INITIAL_RESULTS`, `FAILURES`, `REFINEMENTS`, `FURTHER_EXPERIMENTS`, `INSIGHTS`, `CONCLUSIONS` maintained; `NOT_RUN` until executed | Each file present; unexecuted sections state `NOT_RUN` with no placeholder numbers |
| RX-56 | Injected faults are labelled injected and never attributed as defects in third-party software | Every fixture fault carries an `injected: true` provenance field |
| RX-57 | Adversarial result-changing variants are not accepted by the verifier | Each variant in the trap set yields `CHANGED_RESULT`; zero accepted |

---

## H. Requirements added to close uncovered originals (see `docs/evidence/SPEC_RECONCILIATION_CLOSURE.md`)

Added after recovering the blueprint archive, which showed the reconstruction had
silently omitted six whole areas. **All are `NOT_STARTED`**; appearing here means
they are visible in the ledger, not that anything is implemented.

| ID | Original | Requirement | Acceptance test |
|---|---|---|---|
| RX-58 | R18 | Slack: scoped install, channel selection, redacted notifications, verified event signatures, replay dedup; sending research content needs explicit approval | Invalid signature refused; duplicate delivery applied once; unapproved send refused |
| RX-59 | R19 | Calendar: internal scheduling, Google OAuth, ICS import/export, free-busy within authorised scope only, DST-safe invitations naming both time zones | Spring-forward and fall-back resolve explicitly; ambiguous local time prompts; replayed invite creates no duplicate |
| RX-60 | R20 | Colab import/export and a reviewed local MCP bridge with its real client requirements; never presented as unattended hosted execution | Round-trip import/export; bridge absent reports NEEDS_CONFIGURATION; no path claims hosted execution |
| RX-61 | R28 | Backup/restore with a measured RPO/RTO, observability over the documented journey, incident runbook with a named owner | A restore reproduces a known evidence-bundle digest; RPO/RTO measured, never asserted |
| RX-62 | R30 | Release gate requiring human scientific review by someone who did not build it, plus an independent red team with reproducible findings | Release refuses to advance past REVISE without both records; one agent's review satisfies neither |
| RX-63 | R31 | Exact version pins, SBOM from the RELEASE ARTEFACTS, per-dependency licence review, cold build from a clean checkout | Cold build yields the expected wheel contents; an unpinned dependency fails the gate |
| RX-64 | R17 | Share links, and what a shared lineage graph may expose | A shared graph discloses no entity the recipient could not already read |
| RX-65 | R23 | Export injection: formula/CSV injection neutralised in every exported tabular format | A cell beginning `=`, `+`, `-` or `@` cannot execute in a spreadsheet client |
| RX-66 | R25 | Encryption at rest, managed key control, and a subject-erasure workflow distinct from destroying scientific evidence | Erasure removes personal data, records what was retained and why, and leaves the evidence chain verifiable |
| RX-67 | R29 | Rights admission before any dataset is used, and fair benchmark arms held at equal budget and information | An unadmitted dataset cannot be snapshotted; a missing comparison arm blocks the benchmark claim |
| RX-68 | R32 | A release decision bound to actual executed evidence, naming the profile | The decision cites artefact paths and exit codes; absent evidence forces REVISE or STOP |

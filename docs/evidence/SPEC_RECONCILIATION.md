# Specification reconciliation — R01–R32 vs reconstructed RX-*

Status: **COMPLETE for requirement identity. Schema reconciliation OPEN (section 5).**

## 1. Archive provenance — verified by me, not reported

| Check | Result |
|---|---|
| Path | `/home/favl/Downloads/RETRACE_AI_Claude_Code_Blueprint.zip` |
| Size | 74 380 bytes |
| SHA-256 expected | `1864898f9d815862072f640642fdc42c2bd34e5f62dd74f7da728e4b27a81070` |
| SHA-256 actual | **MATCH** (computed before extraction) |
| ZIP CRC (`testzip`) | **PASS** |
| Entries | 55 |
| Internal `SHA256SUMS` | **54 OK / 0 FAILED** (`sha256sum -c`) |
| Extraction safety | No absolute paths, no `..` traversal, no symlink entries, ratio 2.2x, 142 934 B uncompressed — all checked *before* writing |
| Staged at | `/home/favl/retrace-blueprint-staging/` — **beside** the repo, never over `build/retrace-t0-t2` |

The checksum establishes that these are the intended bytes. It establishes nothing about whether the design is sound or the packaged instructions are safe to run. **No packaged skill, agent definition or tool has been enabled or executed** (section 6).

`specs/requirements.json` carries `"status": "SPECIFIED_NOT_IMPLEMENTED"` and every requirement has `"evidence": []`. The package agrees it is a specification, not evidence.

## 2. Counts

| Measure | Value |
|---|---|
| Original requirements | **32** (R01–R32), all `SPECIFIED_NOT_IMPLEMENTED` |
| Original acceptance test ids | **85** |
| Reconstructed RX entries | **57** |
| Originals accounted for | **32 / 32** |
| — aligned 1:1 | 6 (R08, R09, R15, R16, R24, R27) |
| — refined into several RX | 15 (R01, R02, R03, R04, R05, R06, R07, R10, R11, R12, R13, R14, R21, R22, R26) |
| — partially covered | 5 (R17, R23, R25, R29, R32) |
| — **not covered at all** | **6** (R18, R19, R20, R28, R30, R31) |
| RX entries mapped to an original | 55 / 57 |
| RX entries with no original counterpart | 2 (RX-28, RX-40) |

**32 and 57 are not summed.** 89 is not a count of anything. The RX set is finer-grained, not larger in scope — and section 4 shows it is in fact narrower in scope.

## 3. Mapping

| Original | Title | Tranche | Original tests | RX | Class | Note |
|---|---|---|---|---|---|---|
| **R01** | Identity/signup/session/MFA integration | T1 | `AUTH-01`, `AUTH-02`, `TENANT-01` | RX-45, RX-46 | **REFINEMENT** | RX-45 OIDC/session/CSRF/CORS + RX-46 invitations decompose it. MFA itself is delegated to the IdP and has no RX of its own. |
| **R02** | Tenant-aware CRUD and migrations | T1 | `CRUD-01`, `TENANT-02`, `MIGRATION-01` | RX-20, RX-47, RX-48, RX-49 | **REFINEMENT** | Tenancy split into RLS, transaction-local identity and composite keys. MIGRATION-01 has NO RX counterpart - Alembic migrations are unwritten. |
| **R03** | Quarantine upload and safe downloads | T1 | `UPLOAD-01`, `ARCHIVE-01`, `DOWNLOAD-01` | RX-42, RX-43 | **REFINEMENT** | Quarantine + compatibility matrix. 'Safe downloads' (expiring authorised URLs) is NOT covered by any RX. |
| **R04** | Immutable snapshot and reference provenance | T2 | `SNAPSHOT-01`, `HASH-01` | RX-01, RX-02 | **REFINEMENT** | Content addressing + tamper evidence. |
| **R05** | Protected result contracts and approvals | T2 | `CONTRACT-01`, `APPROVAL-01`, `REPLAY-01` | RX-03, RX-04, RX-05, RX-06, RX-07, RX-52, RX-53 | **REFINEMENT** | The largest decomposition: contract shape, approval gate, five-field binding, diff-not-content, repair authority, append-only amendment, replay safety. |
| **R06** | Sandboxed build/run and independent verifier | T2 | `SANDBOX-01`, `VERIFY-01`, `VERIFY-02` | RX-08, RX-09, RX-10, RX-11, RX-12, RX-13, RX-14, RX-17, RX-18 | **REFINEMENT** | Nine RX for one original. The verifier's independence, defensive parsing, outcome algebra, tolerance handling and methodology delta were each made separately testable. |
| **R07** | Portable evidence and clean rerun | T2 | `BUNDLE-01`, `HANDOVER-01` | RX-15, RX-16 | **REFINEMENT** | Bundle + second-person rerun. |
| **R08** | Light/dark/system premium UI | T3 | `THEME-01`, `RESPONSIVE-01`, `A11Y-01` | RX-19 | **ALIGNED** | 1:1. RESPONSIVE-01 and A11Y-01 are inside RX-19's acceptance test. |
| **R09** | Drag/dock/resize/freeform panels and undo | T3 | `LAYOUT-01`, `LAYOUT-02`, `A11Y-DRAG-01` | RX-21 | **ALIGNED** | 1:1, including the keyboard/menu alternative to every drag. |
| **R10** | Schema-constrained prompt-generated UI | T3 | `UIPLAN-01`, `UIPLAN-INJECTION-01` | RX-22, RX-23 | **REFINEMENT** | Schema validity + the protected-region rule separated, because they fail differently. |
| **R11** | Live typed ontology and explanatory inspector | T3 | `GRAPH-01`, `EVENT-01`, `EVENT-REVOKE-01` | RX-24, RX-25 | **REFINEMENT** | Observed-vs-proposed edges + stale/replay labelling. EVENT-REVOKE-01 maps to RX-39 rather than here. |
| **R12** | Claude-first API/Agent SDK with budgets | T4 | `MODEL-01`, `BUDGET-01` | RX-32, RX-35 | **REFINEMENT** | Server-side credential + run budgets. |
| **R13** | Policy-filtered OpenRouter selector | T4 | `ROUTING-01`, `EGRESS-01` | RX-33, RX-34, RX-36 | **REFINEMENT** | Catalogue/allowlist, no cross-boundary fallback, price timestamping. |
| **R14** | Source-grounded wiki and claim graph | T4 | `CITATION-01`, `CLAIM-01` | RX-37, RX-38 | **REFINEMENT** | Anchors/abstention + no generated-text-as-evidence. |
| **R15** | RAG/CAG and permission-aware cache | T4 | `RAG-01`, `CACHE-TENANT-01`, `CACHE-REVOKE-01` | RX-39 | **ALIGNED** | 1:1; RX-39 carries the full cache-key and revocation rule. |
| **R16** | GitHub App connector | T5 | `GITHUB-OAUTH-01`, `GITHUB-PIN-01`, `GITHUB-REVOKE-01` | RX-41 | **ALIGNED** | 1:1. |
| **R17** | Share links and invite friend | T5 | `INVITE-01`, `SHARE-01`, `SHARE-GRAPH-01` | RX-46 | **PARTIAL** | RX-46 covers recipient-bound expiring invitations only. SHARE-01 and SHARE-GRAPH-01 (share links, and what a shared graph may expose) have NO RX counterpart. |
| **R18** | Slack connector and notification approvals | T5 | `SLACK-01`, `SLACK-REPLAY-01` | — | **GAP** | No RX covers Slack beyond RX-40's generic NEEDS_CONFIGURATION. Scoped install, channel selection, redaction, verified events and replay/idempotency are unrepresented. |
| **R19** | Calendar scheduling, Google OAuth and ICS | T5 | `CALENDAR-01`, `CALENDAR-DST-01`, `CALENDAR-REPLAY-01` | — | **GAP** | No RX covers calendar at all: internal scheduling, Google OAuth, ICS, free-busy scope, DST-safe invitations, replay. RX-31 covers clock/DST for the UI only, not invitations. |
| **R20** | Colab import/export and supported local MCP bridge | T5 | `COLAB-01`, `COLAB-CONSENT-01` | — | **GAP** | No RX covers Colab import/export or the local MCP bridge and its consent requirements. |
| **R21** | 36 complete locale catalogues and reviewer gates | T6 | `I18N-KEY-01`, `I18N-RTL-01`, `I18N-REVIEW-01` | RX-26, RX-29, RX-30 | **REFINEMENT** | Key coverage, protected spans, reviewer gate. RX-28 (RTL) also serves I18N-RTL-01. |
| **R22** | World clock and locale-safe units/dates | T6 | `CLOCK-01`, `CLOCK-DST-01`, `UNITS-LOCALE-01` | RX-27, RX-31 | **REFINEMENT** | Plurals/number/date + world clock and DST. |
| **R23** | Multi-format compatibility and exports | T6 | `FORMAT-01`, `EXPORT-01`, `EXPORT-INJECTION-01` | RX-43 | **PARTIAL** | Compatibility matrix covered. EXPORT-01 partly; EXPORT-INJECTION-01 (formula/CSV injection in exports) has NO RX counterpart. |
| **R24** | Scoped REST and RETRACE MCP interfaces | T5 | `MCP-AUTH-01`, `MCP-INJECTION-01` | RX-44 | **ALIGNED** | 1:1. |
| **R25** | Hashing/encryption/cache/privacy lifecycle | T7 | `SECRET-01`, `CACHE-01`, `ERASURE-01` | RX-39, RX-50, RX-52 | **PARTIAL** | Cache scoping, log redaction and amendment covered. Encryption at rest, key management and a subject-erasure workflow have no RX; ERASURE-01 is unrepresented as a requirement. |
| **R26** | Rate limits, concurrency and model spending | T7 | `RATE-01`, `BUDGET-02`, `QUOTA-01` | RX-35, RX-51 | **REFINEMENT** | Budgets + rate limits/concurrency. |
| **R27** | Compliance applicability and evidence register | T7 | `ASVS-01`, `DPIA-01`, `COOKIE-01` | RX-54 | **ALIGNED** | 1:1; RX-54 names the readiness artefacts and forbids calling them certification. |
| **R28** | Backup/restore/observability/incident readiness | T7 | `RESTORE-01`, `LOAD-01`, `INCIDENT-01` | — | **GAP** | No RX covers backup/restore, observability or incident readiness. I wrote the RETENTION procedure and recorded RPO/RTO as unmeasured, but never created a requirement, so RESTORE-01, LOAD-01 and INCIDENT-01 have nothing to test against. |
| **R29** | Real-data cases and fair benchmark | T7 | `ADMISSION-01`, `BENCHMARK-01`, `ABSTAIN-01` | RX-56, RX-57 | **PARTIAL** | Injected-fault labelling and the adversarial trap set covered. ADMISSION-01 (rights admission before use) and BENCHMARK-01 (fair comparison arms) have no RX; both are blocked anyway. |
| **R30** | Human scientific review and independent red team | T7 | `REDTEAM-01`, `RELEASE-01` | — | **GAP** | No RX covers human scientific review or an independent red team as a release gate. This is the gap most likely to flatter the build, because it is the requirement that would have caught the others. |
| **R31** | Version-pinned dependencies and supply chain | T7 | `SBOM-01`, `LICENSE-01`, `COLD-BUILD-01` | — | **GAP** | No RX covers version pinning, supply chain or a cold build. RX-54 mentions an SBOM as a document only. COLD-BUILD-01 is unrepresented - notable since the packaging defect was exactly a build-integrity failure. |
| **R32** | Actual evidence and release decision | T7 | `EVIDENCE-01`, `RELEASE-02` | RX-55 | **PARTIAL** | RX-55 covers the eight process documents. EVIDENCE-01/RELEASE-02 (a release decision bound to actual evidence) is a process obligation with no RX. |

## 4. The eight uncovered originals — what my reconstruction missed

This is the most important output of the reconciliation. Working from the pasted prose, I produced 57 requirements that look thorough and **silently omitted six whole areas**, plus parts of two more:

- **R18 — Slack connector and notification approvals** (`SLACK-01`, `SLACK-REPLAY-01`): No RX covers Slack beyond RX-40's generic NEEDS_CONFIGURATION. Scoped install, channel selection, redaction, verified events and replay/idempotency are unrepresented.
- **R19 — Calendar scheduling, Google OAuth and ICS** (`CALENDAR-01`, `CALENDAR-DST-01`, `CALENDAR-REPLAY-01`): No RX covers calendar at all: internal scheduling, Google OAuth, ICS, free-busy scope, DST-safe invitations, replay. RX-31 covers clock/DST for the UI only, not invitations.
- **R20 — Colab import/export and supported local MCP bridge** (`COLAB-01`, `COLAB-CONSENT-01`): No RX covers Colab import/export or the local MCP bridge and its consent requirements.
- **R28 — Backup/restore/observability/incident readiness** (`RESTORE-01`, `LOAD-01`, `INCIDENT-01`): No RX covers backup/restore, observability or incident readiness. I wrote the RETENTION procedure and recorded RPO/RTO as unmeasured, but never created a requirement, so RESTORE-01, LOAD-01 and INCIDENT-01 have nothing to test against.
- **R30 — Human scientific review and independent red team** (`REDTEAM-01`, `RELEASE-01`): No RX covers human scientific review or an independent red team as a release gate. This is the gap most likely to flatter the build, because it is the requirement that would have caught the others.
- **R31 — Version-pinned dependencies and supply chain** (`SBOM-01`, `LICENSE-01`, `COLD-BUILD-01`): No RX covers version pinning, supply chain or a cold build. RX-54 mentions an SBOM as a document only. COLD-BUILD-01 is unrepresented - notable since the packaging defect was exactly a build-integrity failure.

- *R17 — Share links and invite friend* (partial): RX-46 covers recipient-bound expiring invitations only. SHARE-01 and SHARE-GRAPH-01 (share links, and what a shared graph may expose) have NO RX counterpart.
- *R23 — Multi-format compatibility and exports* (partial): Compatibility matrix covered. EXPORT-01 partly; EXPORT-INJECTION-01 (formula/CSV injection in exports) has NO RX counterpart.
- *R25 — Hashing/encryption/cache/privacy lifecycle* (partial): Cache scoping, log redaction and amendment covered. Encryption at rest, key management and a subject-erasure workflow have no RX; ERASURE-01 is unrepresented as a requirement.
- *R29 — Real-data cases and fair benchmark* (partial): Injected-fault labelling and the adversarial trap set covered. ADMISSION-01 (rights admission before use) and BENCHMARK-01 (fair comparison arms) have no RX; both are blocked anyway.
- *R32 — Actual evidence and release decision* (partial): RX-55 covers the eight process documents. EVIDENCE-01/RELEASE-02 (a release decision bound to actual evidence) is a process obligation with no RX.

R30 deserves separate note: a requirement for **independent human review and an independent red team** is exactly the control that would have caught the other seven gaps. Its absence from my reconstruction is self-serving in effect, even though it was not deliberate — a reconstruction grades its own homework unless something external forces the comparison. That is the argument for recovering the archive, and it is now evidenced rather than asserted.

### Action
`docs/REQUIREMENTS.md` must gain RX entries for R18, R19, R20, R28, R30, R31 and the uncovered halves of R17, R23, R25, R29, R32 **before** any coverage figure is quoted. Until then, coverage is reported against the originals (section 2), not against the RX set.


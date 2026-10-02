# RETRACE AI — Threat model

**This is a readiness artefact, not a certification.** No penetration test, external
review or audit has been performed. Nothing here has been validated by a third party.

Trust domains (separated by design, co-located in local development):
public web → API → orchestrator → **runner** (untrusted code) → **verifier**
(protected references, separate identity) → connectors (scoped credentials).

| ID | Threat | Asset | Mitigation in this build | Residual risk |
|---|---|---|---|---|
| T1 | Malicious notebook escapes execution and reaches host, network or other tenants' data | Host, tenant data | Subprocess, process-group kill on timeout, `setrlimit` memory cap, scratch-only cwd, cooperative socket block | **HIGH and unmitigated for hosted use.** The runner is a cooperative in-process restriction, NOT a kernel/VM boundary. Determined native code escapes it. No public arbitrary-code execution until a tested gVisor/microVM boundary exists (RX-08) |
| T2 | The repair worker edits the contract, reference outputs, approval ledger or verifier code to manufacture a pass | Scientific integrity | `RepairAuthority` write-allowlist by prefix AND resolved realpath; verifier import-graph test; append-only hash-chained ledger (RX-07, RX-09, RX-52) | Guard is in-process; a compromised orchestrator could bypass it. Needs OS-level separation in production |
| T3 | Crafted result file exploits the verifier's parser | Verifier | JSON/CSV only; pickle magic-byte + extension refusal; size, depth and key caps; no `eval`/`exec`/`yaml.load`/`pickle.loads` (RX-10) | Parser bugs in stdlib remain possible |
| T4 | Cross-tenant read via RLS bypass or identity bleed under connection pooling | Tenant data | Transaction-local tenant contextvar asserted before query; composite `(tenant_id, id)` keys; fail-closed authorization; RLS DDL in migration with non-owner service role (RX-47–49) | **Live RLS enforcement is NOT_RUN** — no PostgreSQL in the local suite. SQLite tests cannot prove RLS |
| T5 | Prompt injection via an ingested source steering the repair worker or wiki | Scientific integrity | Repair worker is bounded (defined task, allowed files, approved tools, output schema); it cannot write protected paths; verifier has no model authority | Untested — no model provider configured (B6). Injection resistance is **unverified** |
| T6 | Stale permission: revoked access still served from cached context, embeddings, summaries or translations | Confidentiality | Cache key includes tenant, entitlement fingerprint, source revisions, policy version, model/provider, embedding and prompt-template version (RX-39) | Retrieval/caching layer **NOT IMPLEMENTED** in this build. Requirement recorded only |
| T7 | Evidence bundle tampering, zip-slip, decompression bomb | Handover integrity | Per-file digest verification on import; path-traversal refusal; ratio and total-size caps (RX-15, RX-42) | Attestation is unsigned — no signing key provisioned. Bundle authenticity is **not** established |
| T8 | Connector credential misuse; webhook replay | External systems | All connectors report `NEEDS_CONFIGURATION`; no credential exists to misuse; signature verification and replay dedup specified | **Untested** — no connector credentials (B7) |
| T9 | Prompt-generated UI used as a permission bypass | Authorization | `UIPlan` restricted to allowlisted components/queries/registered actions; raw JS/SQL refused; protected regions cannot be hidden; mutations require a separate governed action (RX-22, RX-23) | Allowlist completeness is a design assumption |
| T10 | **Malicious scientific code fabricates internally consistent artefacts** (full review: `T10_REVIEW.md`; note two of the three mitigations below are NOT YET IMPLEMENTED) | Scientific truth | Independent recomputation from stored inputs; notebook self-reported status ignored (RX-18); methodology delta forces `CHANGED_RESULT` even when numbers agree (RX-14) | **NOT SOLVED, and not solvable by this architecture.** Code that computes a plausible wrong answer from real inputs will verify. RETRACE detects changed *method* and changed *result*, not a dishonest-but-consistent method. This limit must be stated in every evidence bundle |

## Out of scope / not addressed

Infrastructure administrators remain a documented trust boundary. No key management,
no signing, no secret store, no IdP, no audit sink are provisioned. Supply-chain
integrity of Python/npm dependencies is not verified beyond version pinning.

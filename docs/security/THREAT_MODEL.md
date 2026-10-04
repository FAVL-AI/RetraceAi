# RETRACE AI — Threat model

**This is a readiness artefact, not a certification.** No penetration test, external
review or audit has been performed. Nothing here has been validated by a third party.

Trust domains (separated by design, co-located in local development):
public web → API → orchestrator → **runner** (untrusted code) → **verifier**
(protected references, separate identity) → connectors (scoped credentials).

| ID | Threat | Asset | Mitigation in this build | Residual risk |
|---|---|---|---|---|
| T1 | Malicious notebook escapes execution and reaches host, network or other tenants' data | Host, tenant data | Subprocess, process-group kill on timeout, `setrlimit` memory cap, scratch-only cwd, cooperative socket block | **HIGH and unmitigated for hosted use.** The runner is a cooperative in-process restriction, NOT a kernel/VM boundary. Determined native code escapes it. No public arbitrary-code execution until a tested gVisor/microVM boundary exists (RX-08) |
| T2 | The repair worker edits the contract, reference outputs, approval ledger or verifier code to manufacture a pass | Scientific integrity | Kernel mount-namespace confinement (read-only binds + tmpfs-hidden credentials), verified back from `/proc/self/mountinfo` inside the child. `RepairAuthority` is defence in depth only | **FILESYSTEM HALF CLOSED for the local profile over DECLARED paths, when a caller requests it. IDENTITY HALF OPEN. DEFAULT PROFILE STILL EXPOSED.** See below |
| T3 | Crafted result file exploits the verifier's parser | Verifier | JSON/CSV only; pickle magic-byte + extension refusal; size, depth and key caps; no `eval`/`exec`/`yaml.load`/`pickle.loads` (RX-10) | Parser bugs in stdlib remain possible |
| T4 | Cross-tenant read via RLS bypass or identity bleed under connection pooling | Tenant data | Transaction-local tenant contextvar asserted before query; composite `(tenant_id, id)` keys; fail-closed authorization; RLS DDL in migration with non-owner service role (RX-47–49) | **Live RLS enforcement is NOT_RUN** — no PostgreSQL in the local suite. SQLite tests cannot prove RLS |
| T5 | Prompt injection via an ingested source steering the repair worker or wiki | Scientific integrity | Repair worker is bounded (defined task, allowed files, approved tools, output schema); it cannot write protected paths; verifier has no model authority | Untested — no model provider configured (B6). Injection resistance is **unverified** |
| T6 | Stale permission: revoked access still served from cached context, embeddings, summaries or translations | Confidentiality | Cache key includes tenant, entitlement fingerprint, source revisions, policy version, model/provider, embedding and prompt-template version (RX-39) | Retrieval/caching layer **NOT IMPLEMENTED** in this build. Requirement recorded only |
| T7 | Evidence bundle tampering, zip-slip, decompression bomb | Handover integrity | Per-file digest verification on import; path-traversal refusal; ratio and total-size caps (RX-15, RX-42) | Attestation is unsigned — no signing key provisioned. Bundle authenticity is **not** established |
| T8 | Connector credential misuse; webhook replay | External systems | All connectors report `NEEDS_CONFIGURATION`; no credential exists to misuse; signature verification and replay dedup specified | **Untested** — no connector credentials (B7) |
| T9 | Prompt-generated UI used as a permission bypass | Authorization | `UIPlan` restricted to allowlisted components/queries/registered actions; raw JS/SQL refused; protected regions cannot be hidden; mutations require a separate governed action (RX-22, RX-23) | Allowlist completeness is a design assumption |
| T10 | **Malicious scientific code fabricates internally consistent artefacts** (full review: `T10_REVIEW.md`; note two of the three mitigations below are NOT YET IMPLEMENTED) | Scientific truth | Independent recomputation from stored inputs; notebook self-reported status ignored (RX-18); methodology delta forces `CHANGED_RESULT` even when numbers agree (RX-14) | **NOT SOLVED. Scope boundary, not an impossibility claim:** passing a result contract establishes agreement with its declared checks; it does not independently establish the correctness of the reference data, the adequacy of the methodology, or the truth of the conclusion. Code that computes a plausible wrong answer from real inputs will still conform. **Two of the three mitigations listed left of this cell (RX-18, RX-14) are NOT IMPLEMENTED and are given no credit** — see `T10_REVIEW.md` for the exposure that remains and the deployment restrictions that follow |

## T2 — measured, then half closed. Read all three parts.

### 1. What was measured as unenforced (the original finding, retained)

A child process writing directly, never calling the guard, **overwrote** a
stand-in approval ledger, a reference output, verifier code and a verification
verdict — four for four **ALLOWED** — and **read** a canary credential.
`RepairAuthority` cannot refuse a write that does not ask it, so it is defence in
depth and must never be cited as the verifier boundary.

### 2. What is now enforced, and exactly how far it reaches

`FilesystemConfinement.KERNEL_MOUNT_NAMESPACE` enters `CLONE_NEWUSER|CLONE_NEWNS`
and, inside the namespace, bind-mounts every **declared** protected path
read-only and replaces every **declared** secret directory with an empty tmpfs.
The four-for-four ALLOWED finding is inverted to four-for-four **DENIED**:

| Attempt (native `ctypes` libc, no Python guard in the path) | Unconfined | Confined |
|---|---|---|
| overwrite approval ledger / reference / verifier code / verdict | ALLOWED | **DENIED** `EROFS` |
| `unlink` a protected artefact | ALLOWED | **DENIED** `EROFS` |
| read a canary credential | ALLOWED | **DENIED** `ENOENT` |
| write to the granted scratch area | ALLOWED | ALLOWED — *control: proves the namespace applied rather than failing shut* |

Three properties make this evidence rather than a claim:

- **Verified, not requested.** The child reads `/proc/self/mountinfo` back after
  mounting and refuses unless every declared protected path is a `ro` mount,
  every declared secret directory is a tmpfs, and no writable submount survives
  underneath. Only then is a `RealisedConfinement` returned, so
  `IsolationReport.readonly_paths` quotes an observation.
- **Fails closed, proven by mutation.** Three transient source mutations were
  run and reverted: reporting confinement without mounting, fabricating the
  realised path lists, and honestly reporting `NONE` after skipping the mounts.
  The first two fail the authority test; the third is refused by the parent with
  *"requested KERNEL_MOUNT_NAMESPACE but the child applied NONE; a downgrade is
  never accepted"*. There is no path that silently executes unconfined.
- **In the policy, not a hidden default.** `policy_digest` covers the
  confinement mode and both path lists, so a run recorded under one confinement
  cannot be confused with another.

### 3. What remains OPEN — three distinct things, none of them small

1. **The identity half.** No distinct OS execution identity is achievable on this
   host: `sudo` needs a password and `chown` is refused. The confined child runs
   under the **same uid** as the runner. This therefore confines a
   *cooperatively launched* child; it is **not** protection against a compromised
   host, and credential separation by file ownership is impossible here. A
   restricted database role for the runner, separate from the verifier's, is
   `NEEDS_CONFIGURATION`.
2. **Declared-deny, not deny-by-default.** Only paths the caller *declares* are
   protected. This is a declared-deny confinement, not a read-only root with
   scratch carved out, so an **undeclared** authoritative artefact stays
   writable — which makes the declaration itself part of the control. Nothing
   yet verifies that a deployment's declared list enumerates every authoritative
   artefact. (A separate filesystem mounted under a declared path is detected and
   refused rather than silently half-protected.)
3. **The shipped default is still exposed.** `DEFAULT_LIMITS.filesystem_confinement`
   is `NONE`, and **no caller in the repository requests confinement** — only
   tests do. The validator refuses `KERNEL_MOUNT_NAMESPACE` with no declared
   paths, so the default cannot simply be flipped: the service profile that
   constructs `ExecutionLimits` must declare the real protected and secret paths.
   That is owed by `services/api` and is a **release blocker** for any execution
   endpoint. Asserted honestly by
   `test_an_unconfined_run_still_reaches_every_protected_artefact`.

**Consequence for release.** T2 stays **OPEN**. Execution endpoints must remain
disabled or restricted until (a) the service profile requests confinement with a
reviewed path declaration and (b) the runner and verifier hold distinct,
restricted database credentials. No claim of an independently protected
verification system may be made on the strength of part 2 alone.

## Out of scope / not addressed

Infrastructure administrators remain a documented trust boundary. No key management,
no signing, no secret store, no IdP, no audit sink are provisioned. Supply-chain
integrity of Python/npm dependencies is not verified beyond version pinning.

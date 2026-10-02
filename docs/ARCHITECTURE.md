# RETRACE AI — architecture

Modular monorepo. Trust domains stay separate in code even while co-located locally.

```
apps/web            Next.js / React / TypeScript workspace
packages/contracts  retrace_contracts - scientific authority models + JSON Schemas
packages/domain     retrace_domain    - snapshot store, approval ledger, repair authority
packages/i18n       retrace_i18n      - 36-locale catalogues, plurals, bidi, coverage
packages/ui         shared accessible components
services/api        retrace_api       - FastAPI, tenancy, quarantine, routes
services/orchestrator   workflow, checkpoints, approvals, outbox  [NOT IMPLEMENTED]
services/runner     retrace_runner    - isolated execution (untrusted code)
services/verifier   retrace_verifier  - independent verification + evidence bundles
services/connectors GitHub/Slack/Calendar/Colab  [all NEEDS_CONFIGURATION]
```

## The authority rule (the core invariant)

```
  repair worker ──proposes diff──▶ candidate (hashed)
        │                               │
        │ CANNOT WRITE:                 ▼
        │   contracts/                approval (binds 5 fields)
        │   verifier/                   │
        │   references/                 ▼
        │   approval ledger       isolated runner ──outputs──▶ independent verifier
        │   docs/evidence/                                      (separate identity,
        ▼                                                        read-only references,
   VerifierAuthorityError                                        no model authority)
```

Enforced three ways: a path allowlist resolving symlinks and `..` before deciding; an
import-graph test proving the verifier imports neither runner nor repair provider; and an
append-only hash-chained approval ledger whose middle cannot be edited undetectably.

## Persistence

PostgreSQL is the transactional authority (SQLite only for the local unit suite).
Relational edge tables for the initial ontology and pgvector for authorised semantic
search — **a graph database is deliberately deferred** until a measured requirement
exists. Object storage for large versioned artefacts. Redis for short-lived caching,
queue dispatch and rate limits — **never the sole store of evidence or approval state**.

## Deliberately NOT built in this tranche

`services/orchestrator` (LangGraph workflow, checkpoints, outbox, idempotent external
effects), the retrieval/wiki pipeline, RAG/CAG, the OpenRouter catalogue, and every
connector beyond a status registry. They are specified in `docs/REQUIREMENTS.md` and
remain `NOT_STARTED` — not quietly dropped.

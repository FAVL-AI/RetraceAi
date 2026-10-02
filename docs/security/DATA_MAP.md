# Data map

| Category | Example | Store | Classification | Retention | Egress |
|---|---|---|---|---|---|
| Scientific source artefacts | notebooks, CSV inputs | content-addressed blob store (immutable) | Research-confidential | Indefinite while project live; deletion via documented procedure only | None |
| Snapshot manifests, contracts, approvals | digests, tolerances, approver identity | relational (Postgres in production; SQLite locally) | Research-confidential + personal (approver identity) | Append-only; superseded, never deleted in place | None |
| Run logs / stdout | execution output | object/file store | May contain data fragments — treat as source-equivalent | Configurable; default retain with project | None |
| Evidence bundles | ZIP handover | object store | Inherits source classification | Explicit export only | **Only on explicit user export.** No automatic send |
| Identity / session | OIDC subject, session cookie | IdP + server session | Personal data | Session lifetime | To IdP only |
| Connector credentials | GitHub/Slack/Google tokens | secret store (**not provisioned**) | Secret | Until revoked | To the named provider only |
| Model prompts / completions | repair diagnoses | run record | May embed research-confidential content | With run | **To the model provider — a real egress boundary.** None occurs today: no provider configured (B6) |

Personal data present: approver identity, invitation recipient, session subject.
No special-category data handled. DPIA screening: **NOT DONE.** Lawful basis:
**NOT DETERMINED.** Processor register: empty (no processor engaged).
Egress performed by this build to date: **none.**

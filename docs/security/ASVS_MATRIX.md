# OWASP ASVS applicability matrix

**Readiness artefact, not certification.** Verification level and ASVS version must be
pinned and the applicability reviewed by a human before any release claim. No control
below has been externally verified.

Target: ASVS v4.0.3, Level 2 (institutional pilot). **Applicability review: NOT DONE.**

| ASVS chapter | Applicability | State in this build |
|---|---|---|
| V1 Architecture | Applicable | Trust domains documented (THREAT_MODEL). Threat model exists; not reviewed |
| V2 Authentication | Applicable | **NOT IMPLEMENTED.** OIDC seam only; no IdP configured (B-auth). No password store by design |
| V3 Session management | Applicable | Server-managed cookie specified (HttpOnly/Secure/SameSite). Rotation/revocation NOT implemented |
| V4 Access control | Applicable | Fail-closed tenant context + composite keys; RLS DDL present. **Live enforcement NOT_RUN** |
| V5 Validation / encoding / injection | Applicable | Upload quarantine, defensive output parsing, UIPlan allowlist. No raw SQL string building |
| V6 Stored cryptography | Applicable | **NOT IMPLEMENTED.** No key management, no encryption at rest, no signing key. SHA-256 used for identity only, never secrecy |
| V7 Error handling / logging | Applicable | Schema-based redaction before emission; content logging off by default. Signed audit sink NOT implemented |
| V8 Data protection | Applicable | Cache-control rules specified; data map drafted. Retention workflow documented, not implemented |
| V9 Communications | Applicable | TLS is a deployment concern; local dev is loopback-only. NOT verified |
| V10 Malicious code | Applicable | No `eval`/`exec`/pickle in parsers; macro execution refused; dependency inventory in SBOM |
| V11 Business logic | Applicable | Approval binding, idempotency and outbox specified. Resume-safety test coverage incomplete |
| V12 Files / resources | Applicable | Size/type/ratio caps, path-traversal and zip-slip refusal |
| V13 API / web service | Applicable | Versioned REST; MCP tool surface restricted to non-destructive operations |
| V14 Configuration | Applicable | No secrets in repo; `.env` gitignored; explicit CORS allowlist. Hardening review NOT done |

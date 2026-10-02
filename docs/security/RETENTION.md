# Retention, export and deletion

**Documented procedure, NOT IMPLEMENTED.** No automated retention or deletion job exists.

## Principle (RX-52)

Approved scientific evidence is **amended or versioned, never silently edited**. An
append-only hash-chained ledger makes a deleted or altered middle entry detectable.
"Correcting" a frozen record in place is a defect, not a feature.

## Procedures

1. **Amendment** — append a new version referencing the superseded id; the original
   stays readable and is marked superseded. Verified by `ApprovalLedger.verify_chain()`.
2. **Export** — the user exports an evidence bundle explicitly. No background send.
3. **Deletion** — lawful deletion of personal data is distinct from destroying
   scientific evidence. A deletion request must: identify the subject, enumerate
   affected records, be authorised by a named owner, be executed under an audit entry,
   and record what was retained and on what basis. Destroying evidence that another
   party's published claim depends on requires explicit sign-off.
   **No deletion has been executed. The implementing code does not exist.**
4. **Backup / restore** — restore exercise: **NOT_RUN.** The prompt's RPO ≤15 min /
   RTO ≤60 min targets are unmeasured and must not be reported as met.

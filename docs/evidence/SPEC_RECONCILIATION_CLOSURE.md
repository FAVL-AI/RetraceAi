# Reconciliation closure — field-by-field classification and the six gaps

Supersedes the status line in `SPEC_RECONCILIATION.md`, which **overstated
completion**: identity mapping was done, but the schema differences were only
described, not classified, and the six uncovered originals had no RX entries.
Corrected here. Reconciliation is **COMPLETE for classification and mapping**;
implementation of the classified changes is tracked separately below.

Originals read from the verified staging copy at
`/home/favl/retrace-blueprint-staging/retrace-ai-blueprint/specs/`. The archive
was not re-requested.

## 1. Classification vocabulary

| Class | Meaning |
|---|---|
`MISSING_ORIGINAL` | the original requires it, the implementation lacks it. Must be added |
`RENAME` | same concept, different name. The original's name wins |
`EXTENSION` | the implementation adds something the original does not express, and it is scientifically necessary. Kept, and recorded |
`TIGHTER` | the implementation validates more strictly than the original draft. Kept |
`BOUNDARY` | a deliberate difference between an external payload and a persisted record |
`UNRESOLVED` | a structural conflict needing a decision before dependent code changes |

## 2. `result-contract.schema.json` — field by field

Original: `$schema` draft 2020-12, `additionalProperties: false`, required
`contract_id, tenant_id, project_id, version, status, reference_kind, inputs,
required_checks, limitations`; optional `approval_ref`; conditional
`if status == APPROVED then require approval_ref`.

| Original | Implementation now | Class | Decision |
|---|---|---|---|
| `contract_id` | *absent* | **MISSING_ORIGINAL** | add; stable identity independent of content hash |
| `tenant_id` | *absent* | **MISSING_ORIGINAL** | add. Without it a contract cannot be isolated by the RLS already proven in `tests/postgres`, so the two halves do not join |
| `project_id` | *absent* | **MISSING_ORIGINAL** | add |
| `version` | `contract_version` | **RENAME** | adopt `version`. This is the SCIENTIFIC contract version, distinct from the schema version (§5) |
| `status` | *absent* (approval inferred from the ledger) | **MISSING_ORIGINAL** | add `DRAFT/APPROVED/SUPERSEDED`. **A client-supplied status establishes nothing**: the ledger stays the authority and the field is server-set |
| `reference_kind` | *absent* | **MISSING_ORIGINAL** | add the three original values unchanged (§4) |
| `inputs` (items `{id, sha256}`) | `reference_inputs` (items `{path, sha256, role}`) | **RENAME** + **EXTENSION** | adopt `inputs`; map `path`→`id`; **keep `role`**, which the verifier needs to tell a reference output from an input |
| `required_checks` (objects: `id, kind, description, source_of_expectation`, optional `absolute_tolerance`, `relative_tolerance`) | tuple of check-id **strings**; tolerances live in `ComparisonSpec` | **UNRESOLVED** | see §3 |
| `limitations` | `known_limits` | **RENAME** | adopt `limitations`; keep the non-empty rule, which the original does not require (**TIGHTER**) |
| `approval_ref` (string) | `approval` (embedded object) | **RENAME** + **BOUNDARY** | adopt `approval_ref` as a string reference into the ledger. Embedding the approval inside the material it authorises is also a digest-recursion hazard (§6) |
| *not in original* | `output_definitions` | **EXTENSION** | required: outputs cannot be compared without their names, kinds and units |
| *not in original* | `population` | **EXTENSION** | the declared record count and selection rule |
| *not in original* | `comparison.algorithm` | **EXTENSION** | which comparison was used |
| *not in original* | `units`, `exclusions`, `seed`, `split` | **EXTENSION** | the methodology fields RX-14 compares; a changed one is a reanalysis |
| *not in original* | `created_by` | **EXTENSION** | |
| `additionalProperties: false` | — | **UNRESOLVED→decided** | the original draft would **reject** every extension above. Decision: the generated schema relaxes it, and the conformance test asserts the original's required fields, enums and item shapes are all satisfied — not byte equality. Recorded so it is a decision, not drift |

## 3. `required_checks` — the one genuinely unresolved conflict

The original models each check as an object carrying `kind` (one of
`INPUT_IDENTITY, SCHEMA, POPULATION, UNITS, NUMERIC, SPLIT, METHOD, EVIDENCE`),
a `description`, a **`source_of_expectation`**, and its own tolerances. The
implementation carries check ids as strings and keeps tolerances in
`ComparisonSpec`.

The original is **better** on one scientifically important point:
`source_of_expectation` records *where the expected value came from*, which is
exactly the provenance question a reviewer asks. And per-check tolerances remove
the possibility of a tolerance applying to the wrong thing.

**Decision: adopt the original's object form, and move tolerances into it**, so
there is one place a tolerance can live. This changes the verifier's comparison
path, so it is sequenced AFTER the identity/tenancy/reference fields rather than
bundled with them — those block the API, this does not.

**Status: UNRESOLVED-WITH-DECISION, not yet implemented.** Until it lands,
tolerances remain in `ComparisonSpec` and that is recorded drift, not silent.

## 4. `reference_kind` — semantics preserved exactly

Values retained verbatim; no replacement vocabulary invented.

| Value | Meaning | Gate |
|---|---|---|
`HISTORICAL_REFERENCE` | identified prior evidence | requires **resolvable, integrity-checked, approved** provenance for the referenced artefact. A label plus a non-empty string proves nothing |
`NEW_TEACHING_REFERENCE` | an explicitly established teaching baseline | must not be described as reproducing a published result |
`NO_REFERENCE` | no numerical reference exists | **must never yield `REPRODUCED_WITHIN_CONTRACT`.** Checks not needing a reference may still run; the outcome is `EXECUTED_NOT_VERIFIED` or `BLOCKED_MISSING_EVIDENCE` per the required-check semantics |

**`SYNTHETIC` is not a `reference_kind`.** Data provenance, proposal provenance,
execution state and verification outcome stay four separate attributes. The
current triad's fixtures are synthetic data that will carry
`NEW_TEACHING_REFERENCE` once a teaching baseline is explicitly established —
and its repair proposals are scripted/deterministic, which stays distinguishable
from a model-generated proposal (B6 unresolved).

## 5. One authoring source, and two different versions

`packages/contracts` (pydantic v2) is the single authoring source. JSON Schema is
**generated** from it, never hand-written, with a sync test that already caught
real drift once.

- **Schema dialect**: `https://json-schema.org/draft/2020-12/schema`, matching the originals.
- **Validator**: `jsonschema` `Draft202012Validator`.
- **`format` is an ANNOTATION by default** and asserts nothing unless a format
  checker is configured. Identifier and timestamp checks must therefore be
  enforced by pydantic constraints and tested directly — not assumed from a
  `format` keyword. Owed as a test.
- **`schema_version`** (the shape of the document) is distinct from
  **`version`** (the scientific contract's revision). They must never be
  conflated or derived from one another.

## 6. Approval binding and digest recursion

Approval binds candidate + contract content/version + input snapshot +
environment/action policy; changing any bound material invalidates it (already
implemented and tested). Two additions required by this directive:

- `approval_ref` is a **reference**, so the contract's digest covers the
  reference, never the approval's own digest — removing the recursion hazard
  that embedding created.
- `status` is server-set from the ledger. A client-supplied `"APPROVED"` is
  rejected, not believed.

## 7. The six uncovered originals, now mapped

New RX ids continue from RX-57. **No equivalence is inferred from numeric
resemblance** — `R14` is *"Source-grounded wiki and claim graph"* and `RX-14` is
*"a changed methodology is a reanalysis"*; they are unrelated and the digits are
a coincidence.

| Original | Title | New RX | Requirement | Acceptance test |
|---|---|---|---|---|
| **R18** | Slack connector and notification approvals | **RX-58** | Scoped workspace install, channel selection, redacted notification content, verified event signatures, replay/idempotency dedup. Sending research content requires explicit approval | Invalid signature refused; duplicate delivery applied once; unapproved send refused; unconfigured connector reports `NEEDS_CONFIGURATION` |
| **R19** | Calendar scheduling, Google OAuth and ICS | **RX-59** | Internal scheduling, Google OAuth consent, ICS import/export, free-busy only within authorised scope, DST-safe invitations naming both time zones, replay-duplicate prevention | Spring-forward and fall-back invitations resolve explicitly; ambiguous local time prompts; replayed invite creates no duplicate |
| **R20** | Colab import/export and local MCP bridge | **RX-60** | Notebook import/export and deep-link; a reviewed local bridge with its documented client and browser-session requirements; never presented as unattended hosted execution | Import/export round-trips; bridge absent reports `NEEDS_CONFIGURATION`; no code path claims hosted Colab execution |
| **R28** | Backup/restore/observability/incident readiness | **RX-61** | Executed restore exercise with measured RPO/RTO, structured observability for the documented journey, and an incident runbook with a named owner | A restore from backup reproduces a known evidence bundle digest; RPO/RTO are **measured**, never asserted |
| **R30** | Human scientific review and independent red team | **RX-62** | A release gate requiring (a) human scientific review by someone who did not build it and (b) an independent red team, with findings carrying reproduction steps and severity | Release decision refuses to advance past REVISE without both records; one agent's review does not satisfy either |
| **R31** | Version-pinned dependencies and supply chain | **RX-63** | Exact version pins, SBOM generated from the **release artefacts** (not the dev environment), licence review per dependency, and a cold build from a clean checkout | Cold build in a clean environment produces the expected wheel contents; an unpinned dependency fails the gate |

Also closing the five partials: **RX-64** share links and what a shared graph may
expose (R17), **RX-65** formula/CSV injection in exports (R23), **RX-66**
encryption at rest, key management and subject erasure (R25), **RX-67** rights
admission before dataset use and fair benchmark arms (R29), **RX-68** a release
decision bound to actual evidence (R32).

**Counts after closure: 32/32 originals mapped; 68 RX entries, of which 57 are
the original reconstruction and 11 were added to close real gaps.** Mapping
coverage is not implementation coverage: RX-58..RX-68 are **NOT_STARTED**, and
saying they are "mapped" says only that they are now visible in the ledger.

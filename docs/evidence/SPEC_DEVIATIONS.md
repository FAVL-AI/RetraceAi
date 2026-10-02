# Deviations from the pasted specification

Each entry is a place where this build does not do what the pasted prompt says,
with the reason. Recorded so the deviation is reviewable rather than silent.

| # | Pasted spec | What this build does | Reason |
|---|---|---|---|
| D1 | "Read MASTER_PROMPT.md and CLAUDE.md" | Used the pasted prompt + blueprint as spec authority | Those files are absent from the host (PRECHECK B1). Authorised by Frank at the precheck gate |
| D2 | "Use the packaged custom specialist skills" (`/retrace-build` et al.) | Used scoped workflow agents with explicit file ownership, ≤4 mutating | The 11 skills are not installed (PRECHECK B2) |
| D3 | "32 requirements mapped to acceptance tests" | 57 `RX-*` requirements reconstructed in `docs/REQUIREMENTS.md` | The packaged matrix is unavailable; count and IDs are therefore mine, not the package's |
| D4 | RTL for "Arabic, Hebrew and Persian" | Urdu additionally marked RTL | **CORRECTED — see Amendment 1 below.** Urdu is Arabic-script and right-to-left; treating it as LTR would be a real localisation defect |
| D5 | Three real-data case studies (Palmer Penguins, TUM RGB-D, UCI Wine Quality) | `NOT_RUN`. Synthetic fixtures authored here, labelled `SYNTHETIC` | Dataset fetch not authorised (PRECHECK B5). Fixtures are not presented as those datasets |
| D6 | "bounded Claude repair worker" inside the product | Provider interface + deterministic local provider; Claude provider reports `NEEDS_CONFIGURATION` | No model credential or cost budget (PRECHECK B6) |

---

## Amendment 1 to D4 (2026-10-02) — provenance corrected

The original D4 wording implied the packaged specification got Urdu wrong. Frank
reports that is not so: the original machine-readable `specs/locales.json`
**already** carries

```json
{ "tag": "ur-PK", "language": "Urdu", "direction": "rtl",
  "catalogue_status": "NOT_IMPLEMENTED", "linguistic_review": "NOT_REVIEWED" }
```

So the accurate finding is narrower and is an **internal inconsistency in the
package**, not a defect in its locale JSON:

- the master-prompt **prose** names only Arabic, Hebrew and Persian as RTL — it
  **omits Urdu**;
- the **locale manifest** correctly marks `ur-PK` as `rtl`.

The prose is the document that is incomplete. My reconstruction reached the right
direction value for the wrong stated reason, and by a different route (script
knowledge rather than reading the manifest).

Retained: Urdu RTL support. Corrected: the provenance claim. Original D4 wording
is preserved above rather than rewritten away, per RX-52.

Two consequences carried into reconciliation:

1. **Tag format.** Mine uses bare `ur`; the original uses region-qualified
   `ur-PK`. All 36 tags must be reconciled to the original scheme before any
   catalogue is keyed, or every lookup key breaks later.
2. **Status vocabulary.** The original uses `catalogue_status` /
   `linguistic_review` (`NOT_IMPLEMENTED` / `NOT_REVIEWED`); mine uses
   `review_status: beta` + `reviewer: null`. The original's is more precise —
   it separates "no catalogue" from "catalogue present but unreviewed". Adopt the
   original's two-field scheme on receipt.

**CLDR provenance.** The plural categories I added were derived from my own
knowledge of CLDR cardinal rules, **not** read from a pinned CLDR release. No
CLDR version is recorded because none was consulted as a source. This is an
`ASSUMPTION`, not a `VERIFIED FACT`, and must be regenerated from a pinned CLDR
version (or from the original manifest if it carries them) before any
pluralisation claim is made.

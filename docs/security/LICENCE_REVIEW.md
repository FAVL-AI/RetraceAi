# Licence review

**NOT COMPLETE.** This records what is known and what is unresolved. It is not a legal
opinion and does not clear anything for publication.

## This repository

Declared `UNLICENSED` / private pending Frank's decision. **No open-source release may
occur until the items below are resolved.**

## Reuse rights — unresolved

| Source | Issue | Status |
|---|---|---|
| RESEARCH_AI | Private repository with **no licence file**. Concepts may be reusable; code and corpus are not cleared. Its `data/`, auth files, logs, secrets and provider defaults must never enter a public RETRACE repo | **BLOCKED (B4)** — needs Frank's rights determination |
| Palmer Penguins | CC0 per source, with citation guidance | Not admitted (B5); not downloaded |
| TUM RGB-D | Licence has stated exceptions requiring per-file check | Not admitted (B5) |
| UCI Wine Quality | Attribution required | Not admitted (B5) |
| UCI Air Quality | **Conflicting usage statements** — research-only in the description, permissive elsewhere | **EXCLUDED pending clarification.** The more convenient reading was not adopted |

## Dependencies

Python inventory: `docs/security/sbom-python.json` (generated from the installed
environment — real versions, not declared ranges). Licence compatibility of each
dependency: **NOT REVIEWED.** No npm SBOM yet.

# Specification reconciliation — original R01–R32 vs reconstructed RX-*

Status: **BLOCKED on hand-off. 0 of 32 original requirements can be mapped.**

## 1. The hand-off blocker (B1 restated precisely)

Frank reports the archive exists and supplied its integrity record:

| Property | Reported value |
|---|---|
| Name | `RETRACE_AI_Claude_Code_Blueprint.zip` |
| SHA-256 | `1864898f9d815862072f640642fdc42c2bd34e5f62dd74f7da728e4b27a81070` |
| Size | 74 380 bytes |
| Entries | 55 (54 content hashes, 54/54 matched) |
| Package validator | exit 0, "70/70 passed" |
| Requirement IDs | `R01`–`R32` |
| Locale targets | 36 |

**The archive is not reachable from this machine.** Searches performed
2026-10-02, all negative:

| Search | Result |
|---|---|
| `ls /mnt/data` | `No such file or directory` — that is a ChatGPT sandbox path, not a path on this host |
| `find / -xdev -iname "RETRACE_AI_Claude_Code_Blueprint.zip"` | no match |
| `find / -xdev -type f -size +70k -size -80k -name "*.zip"` | 6 matches, all Omniverse/TeX licence bundles; none is the archive |
| `find Downloads Desktop /tmp -newermt "-6 hours"` filtered to zip/retrace/blueprint | no match |

So the SHA-256 could not be compared against any local bytes. **No checksum
verification has been performed by me.** The integrity table above is Frank's
reported result, recorded as a report, not as a finding of mine.

**To unblock:** place the file on this host (e.g. `~/Downloads/`) and tell me the
path. I will then verify the SHA-256 *before* extracting, extract to a staging
directory beside the repo (never over `build/retrace-t0-t2`), read the skills and
agent definitions before enabling anything, and complete the mapping below.
Per the directive, I have not claimed to read these files and have not invented a
second "original" specification.

## 2. What is known about the originals

**Known:** the 32 IDs `R01`–`R32`, that 36 locales are targeted, and that the
archive contains `docs/01-ARCHITECTURE.md`, `docs/02-UX.md`,
`specs/design-tokens.json`, `specs/requirements.json`, `specs/locales.json`,
four draft JSON Schemas, 11 skills and 8 agent definitions.

**Unknown:** the *text* of every one of R01–R32. An ID list is not a requirement.
Any mapping I produced now would be invention, so the table below is left
deliberately unpopulated.

| Original | Text | Mapped RX | Implementation | Test | Evidence | Status |
|---|---|---|---|---|---|---|
| R01–R32 | **UNKNOWN — archive not local** | — | — | — | — | `BLOCKED_MISSING_EVIDENCE` |

Counts to carry forward: **32 original requirements, 0 accounted for.**
**57 reconstructed RX entries, 0 classified** against an original.
The two sets must not be summed; 89 is not a number that means anything here.

## 3. Classification scheme (ready to apply on receipt)

Every RX entry will be classified as exactly one of:

- `REFINEMENT` — splits one original into several finer, testable requirements
- `EXTENSION` — genuine addition with no original counterpart
- `DUPLICATE` — restates another RX entry; to be merged
- `CONFLICT` — contradicts an original; must be resolved before dependent code
- `UNRESOLVED` — cannot be classified from the original text

Expected shape, based on how the RX set was derived: the 18 scientific-core RX
entries (RX-01…RX-18) are likely refinements of a smaller number of originals,
since they decompose one journey into individually testable steps. That is an
expectation, not a finding.

## 4. Divergence risk already accrued

Work completed against the reconstruction that may need reconciliation:

| Artefact | Risk if originals differ |
|---|---|
| `packages/contracts` (3017 LOC, 5 JSON Schemas) | **Highest.** The four *draft* schemas in the archive are the intended authority. Field names, enum spellings and the canonical-hash form may differ. Schema drift here invalidates digests already computed |
| `specs/locales.json` | Tag format differs: mine uses `ur`, the original uses `ur-PK`. Likely **all 36 tags** are region-qualified in the original. Mechanical but must be done before catalogues are keyed |
| `docs/UX.md` tokens | Original `specs/design-tokens.json` is machine-readable and authoritative; my tokens are prose values and must yield to it |
| `docs/ARCHITECTURE.md` | Supersede with `docs/01-ARCHITECTURE.md` where they disagree |
| `docs/REQUIREMENTS.md` | Keep both namespaces; never collapse |

One authoritative runtime contract source must be chosen on receipt — the
archive's draft schemas unless they are demonstrably weaker — with the Python and
TypeScript representations **generated or conformance-tested against it**, never
hand-maintained in parallel. Schema validity does not substitute for runtime
authorisation; both are required.

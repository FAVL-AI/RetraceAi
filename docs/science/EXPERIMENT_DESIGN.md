# Experiment design

Status: **PRE-REGISTERED, NOT_RUN.**

## Pre-registration rule

Contract definitions and tolerances are frozen BEFORE any candidate is generated, and
the verifier's check code is frozen and owned outside the repair worker's write scope
(RX-07). Tolerances must not be widened after seeing a result. Any change to a frozen
contract requires a new contract version and invalidates prior approvals (RX-05).

## Experimental unit

One (snapshot, contract, injected-fault) triple. A case is NOT a dataset; nine cases
over three source families are nine cases, not nine independent studies.

## Arms

| Arm | Description | Status |
|---|---|---|
| A0 | Baseline: no repair. Establishes the reproducible failure | Implementable locally |
| A1 | RETRACE: contract + bounded repair + independent verifier | Implementable locally |
| A2 | Execution-only coding agent (exit-code-0 = success) | Requires model credential — **BLOCKED (B6)** |
| A3 | Existing notebook-testing baseline | Requires tool selection + rights review — **BLOCKED** |
| A4 | Manual human repair | Requires human participants — **BLOCKED** |

Only A0 and A1 are reachable in this build. A comparative claim needs A2–A4, so **no
comparative claim may be made.**

## Fault taxonomy

Mechanically repairable (H2 target): wrong relative data path; wrong CSV delimiter;
missing-but-resolvable import.

Result-changing traps (H1 target — must be refused, never repaired): altered exclusion
rule; unit substitution (g↔kg); changed train/test split or seed; preprocessing applied
before the split (leakage); silent record removal.

Every injected fault carries `injected: true` provenance (RX-56) and is attributed to
this repository, never to any third-party author.

## Materials

**Datasets: NOT ADMITTED.** Fetch is unauthorised (PRECHECK B5), so Palmer Penguins,
TUM RGB-D and UCI Wine Quality are not present and the three planned case studies are
`NOT_RUN`. The slice is exercised with `SYNTHETIC` fixtures authored here, which are not
derived from and must not be reported as those datasets. UCI Air Quality stays excluded
over its conflicting usage statements.

## Measurement

Per case: verification outcome, which checks fired, abstention (yes/no), wall-clock,
and the exact digests of snapshot/contract/candidate. Outcomes are recorded as emitted —
a failure is kept as evidence, never re-run until it passes (RX-55 / FAILURES.md).

## Validity threats

Trap-set coverage bounds H1. Synthetic fixtures bound external validity severely —
nothing here generalises to real published notebooks. Development and evaluation cases
are not yet separated by repository, so **no held-out claim is available.** Single
implementer; no independent adjudicator; one agent's review is not independent
scientific validation.

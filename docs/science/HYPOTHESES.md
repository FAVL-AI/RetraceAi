# Hypotheses

Status: **PRE-REGISTERED, NOT_RUN.** No experiment in this file has been executed.
No result, effect size or benchmark number appears anywhere in this document.

## H1 — Scientific restraint (primary)

A protected result contract plus an independent verifier causes **zero acceptance**
of result-changing repair candidates, where "accept" means emitting
`REPRODUCED_WITHIN_CONTRACT`.

- Independent variable: verification regime (RETRACE contract+verifier vs.
  execution-only agent that treats exit code 0 as success).
- Dependent variable: count of result-changing variants accepted.
- Falsified if: any adversarial variant in the frozen trap set is accepted.
- Note: zero observed acceptances would NOT establish zero risk. The claim is
  bounded by the trap set's coverage, which is itself a limitation, not a result.

## H2 — Repair capability

Within a declared budget, the system recovers a defined share of *mechanically*
repairable cases (path, delimiter, dependency-resolution faults) without altering
scientific meaning.

- Falsified if: recovery requires altering an exclusion, seed, split or unit.
- Abstention is a SUCCESS for H1 and a FAILURE for H2. The two hypotheses are in
  deliberate tension; reporting one without the other would be misleading.

## H3 — Handover

An independent second party can import an evidence bundle into a clean environment
and reproduce the recorded verification outcome.

- Falsified if: the bundle is insufficient to recompute the outcome, or the outcome
  differs on rerun.

## H4 — Researcher effort (NOT TESTABLE HERE)

RETRACE reduces median active researcher time vs. manual recovery.

- **Status: cannot be tested in this build.** Requires human participants, a manual
  baseline arm, ethics/consent review and an independent timekeeper. No human-subject
  measurement has been designed or approved. Any effort claim would be fabrication.

## Explicitly NOT claimed

Novelty, SOTA, production readiness, generalisation beyond CPU Python notebooks with
CSV inputs, or that metric agreement establishes a scientific hypothesis.

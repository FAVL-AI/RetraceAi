# T10 — review of the residual scientific-integrity limitation

Requested because the threat-model table row alone is not enough to judge whether
this is an acceptable residual limitation or a deployment blocker. The answer is:
**acceptable for the stated purpose, and a blocker for a purpose RETRACE must not
be sold or used for.**

## Exact text under review

From `docs/security/THREAT_MODEL.md`, row T10, quoted verbatim:

> | T10 | **Malicious scientific code fabricates internally consistent artefacts** |
> Scientific truth | Independent recomputation from stored inputs; notebook
> self-reported status ignored (RX-18); methodology delta forces `CHANGED_RESULT`
> even when numbers agree (RX-14) | **NOT SOLVED, and not solvable by this
> architecture.** Code that computes a plausible wrong answer from real inputs
> will verify. RETRACE detects changed *method* and changed *result*, not a
> dishonest-but-consistent method. This limit must be stated in every evidence
> bundle |

(The "not solvable by this architecture" phrasing in the row above is the text as
originally written and is retained here for provenance. It is **withdrawn** in the
Verdict below and corrected in the threat-model table itself.)

## Affected assets

1. **Scientific truth** — whether a reported finding is correct. This is the asset
   RETRACE cannot protect.
2. **The verification outcome vocabulary** — specifically
   `REPRODUCED_WITHIN_CONTRACT`. The real exposure is that a reader interprets it
   as "the science is right". The *string* is the attack surface.
3. **The evidence bundle** as a persuasion artefact. A bundle is more convincing
   than a bare claim; a bundle wrapped around a fabricated method is therefore
   *more* dangerous than no bundle, not less.
4. Downstream: anyone relying on a handover — a reviewer, a successor researcher,
   an institution.

## Actor and capabilities assumed

The actor is the **author of the analysis**, an insider, not an external attacker.
No system compromise is required. Assumed capabilities:

- writes arbitrary analysis code that will be snapshotted and run;
- authors the `ResultContract`, or materially influences the human who approves it;
- knows how the verifier compares outputs, including the declared tolerances;
- can produce outputs that are internally consistent with the method as declared.

Not required: breaking isolation (T1), defeating the write guard (T2), exploiting
the parser (T3), or any credential. **T10 needs no vulnerability.** It is a
property of verifying conformance rather than correctness.

## Mitigations actually present (verified in code, not aspirational)

| Mitigation | Requirement | Verified |
|---|---|---|
| Outputs are recomputed independently from stored inputs; the notebook's own claims about success are ignored | RX-18 | Specified; verifier not yet built — **NOT_RUN** |
| A changed exclusion, seed, split, population or unit forces `CHANGED_RESULT` even when every number agrees | RX-14 | Specified; verifier not yet built — **NOT_RUN** |
| A contract declaring no `known_limits` is refused at construction | RX-03 | **VERIFIED** — executed, `tests/contracts` |
| An evidence bundle must carry a non-empty `limitations` block | RX-15 | **VERIFIED** — `limitations` is a required field on `EvidenceBundleManifest` |
| Approval binds the exact candidate, so a post-approval swap invalidates it | RX-05 | **VERIFIED** — all five bound fields invalidate, including in the installed wheel |
| The repair worker cannot edit contracts, references, approvals or verifier code | RX-07 | Specified; `RepairAuthority` not yet built — **NOT_RUN** |

So two of the three mitigations the threat-model row cites for T10 are **not yet
implemented**. The row overstates present protection and is corrected by this review.

### No credit for specified-but-unimplemented mitigations

RX-18 and RX-14 are **excluded from the residual-risk assessment entirely**. They
are design intent, not controls. The exposure is therefore assessed as if they do
not exist, because today they do not.

| Unimplemented mitigation | Exposure that remains RIGHT NOW | Deployment restriction while unimplemented |
|---|---|---|
| RX-18 — notebook self-reported status ignored | Nothing in the running system ignores a notebook's own verdict, because nothing reads notebook output at all yet. A notebook printing a passing verdict would be the ONLY verdict present. Any outcome shown today would be the author's own claim, relabelled | No verification outcome may be displayed, exported, or returned by an API to any party, including the author. No evidence bundle may be issued |
| RX-14 — methodology delta forces CHANGED_RESULT | No comparison of declared exclusions, seed, split, population or units against the contract exists. A silently altered method would not be flagged by any code path | No contract may be marked satisfied. `REPRODUCED_WITHIN_CONTRACT` must be unreachable in the product until the verifier implements the delta check and its tests pass |

Both restrictions are currently satisfied trivially — there is no UI, no verifier
and no API — but they must be enforced as gates when those arrive, not re-derived
then. Each is recorded against its RX id in `docs/REQUIREMENTS.md`.

## Residual exposure

**What RETRACE detects:** divergence — a method that changed relative to an
approved contract, a result that changed relative to a reference, missing
evidence, and a notebook asserting its own success.

**What RETRACE cannot detect:** a method that was wrong, biased or fraudulent
*from the outset*, because then the flaw is encoded in the contract itself, and
the contract is the reference. Conformance to a wrong declaration is still
conformance. Concretely, all of the following would verify:

- a leakage-contaminated pipeline, pre-registered honestly as the method;
- an exclusion rule that removes inconvenient records, declared openly;
- a metric chosen after seeing results, then frozen before verification;
- hard-coded output values, if the contract's tolerances are wide enough to admit them.

The only defence against a flawed contract is the **human approver**, who sits
outside the software. RETRACE makes that approval explicit, versioned, bound and
attributable — which is a real improvement over an unreviewed notebook — but it
does not make the approver correct.

A second-order exposure: `tolerances` are author-proposed. A tolerance wide enough
to admit a desired answer converts verification into theatre. The tolerance *is*
part of the hashed contract (**VERIFIED**: changing a tolerance changes
`contract_hash`), so widening it is detectable and attributable — but only if
someone looks.

## Permitted deployment profile

**Permitted** — recovery, inspection, reproducible rerun and handover of
computational analyses, where the outcome is read as *"this ran, and conformed to
this declared contract"*.

**Not permitted** — presenting or operating RETRACE as any of:
fraud detection; scientific validation or peer review; a correctness certificate;
evidence that a hypothesis holds; a basis for a "verified"/"trusted" badge on a
result. Marketing or configuring it that way turns T10 from an accepted
limitation into a **release blocker**, because the product would then claim
exactly the property it does not have.

## Required controls before any release that shows a verification outcome

1. `REPRODUCED_WITHIN_CONTRACT` must never render as a bare tick, "verified", or
   "passed". The contract identity must be adjacent and the qualifier
   *within contract* must be inseparable from the label. `docs/UX.md` already
   mandates icon + text + colour and forbids colour-only state; this adds that the
   text may not be shortened to "Reproduced".
2. Every evidence bundle must carry this limitation in its `limitations` block —
   enforced structurally today only insofar as the block must be **non-empty**;
   a check that this *specific* limitation is present is **owed and not written**.
3. Documentation, UI copy, API responses and exports must keep **"reproduced
   within contract"** and **"scientifically validated"** strictly separate. The
   first is a statement about agreement with declared checks; the second is a
   claim RETRACE never makes anywhere, in any surface. No synonym of the second
   ("validated", "confirmed", "verified correct", "trusted result") may appear
   attached to an outcome.
4. The release decision must record T10 as a known, accepted, unmitigated residual
   risk with a named owner.

## Verdict

T10 is an **accepted limitation of this assurance model**, correctly scoped as:

> **Passing a result contract establishes agreement with its declared checks. It
> does not independently establish the correctness of the reference data, the
> adequacy of the methodology, or the truth of the scientific conclusion.**

Earlier drafts of this review called the limitation "honestly unsolvable" and said
the gap was "not solvable by this architecture". **That wording is withdrawn.** It
overreached: it implied independent scientific validation is impossible in
general, when the accurate claim is narrower — *this* evidence is insufficient to
establish it. Independent validation is achievable by means outside contract
conformance (independent reimplementation, held-out replication, adversarial
re-analysis, peer review of the method rather than the run). RETRACE does not
provide those, and must not be read as a substitute for them.

It is **not** currently safe to show a verification outcome to a third party,
because control 1 is unimplemented (no UI exists) and control 2 is only partially
enforced. Those are implementation gaps, not reasons to reword the limitation.

Release implication: **REVISE**, not STOP. T10 does not block development; it
blocks any claim of validation, and it blocks a user-facing verification badge
until controls 1 and 2 exist.

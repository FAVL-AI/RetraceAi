/* The gate that decides whether an outcome may be SHOWN at all (RX-11, RX-12,
 * RX-17, RX-25).
 *
 * docs/security/T10_REVIEW.md does not only constrain the wording of an
 * outcome; while RX-18 (notebook self-report ignored) and RX-14 (methodology
 * delta forces CHANGED_RESULT) are unimplemented it states a deployment
 * restriction in plain terms: "No verification outcome may be displayed,
 * exported, or returned by an API to any party, including the author", and
 * "REPRODUCED_WITHIN_CONTRACT must be unreachable in the product until the
 * verifier implements the delta check and its tests pass". It also says those
 * restrictions "must be enforced as gates when those arrive, not re-derived
 * then". A browser workspace is exactly such an arrival, so the gate lives
 * here, in front of the badge.
 *
 * The honest consequence, stated so nobody has to discover it: in the profile
 * this build ships, no verifier capability record exists, so the five badges in
 * `outcome.js` are NOT reachable from the running application. The check-results
 * surface renders a refusal that names the missing control instead. That is the
 * specified behaviour, not an unfinished view.
 *
 * A second refusal comes from the frozen contract vocabulary rather than from
 * T10: `NO_REFERENCE` can never yield `REPRODUCED_WITHIN_CONTRACT`
 * (docs/evidence/SPEC_RECONCILIATION_CLOSURE.md section 4). The gate refuses
 * that pairing even if a server sends it, because a display layer that renders
 * whatever it is handed is not a control.
 */

import { el } from './dom.js';
import { renderOutcome } from './outcome.js';
import { renderSurfaceState } from './states.js';

/** Refusal codes. Each one names what is missing, never a generic failure. */
export const OUTCOME_REFUSAL = Object.freeze({
  VERIFIER_CAPABILITY_UNKNOWN: 'VERIFIER_CAPABILITY_UNKNOWN',
  VERIFIER_CONTROLS_INCOMPLETE: 'VERIFIER_CONTROLS_INCOMPLETE',
  NO_REFERENCE_CANNOT_REPRODUCE: 'NO_REFERENCE_CANNOT_REPRODUCE',
  UNKNOWN_OUTCOME: 'UNKNOWN_OUTCOME',
});

/**
 * The two controls T10 requires before any outcome may be shown, by the RX id
 * each one closes. A capability record must assert both.
 */
export const REQUIRED_VERIFIER_CONTROLS = Object.freeze({
  independent_recomputation: 'RX-18',
  methodology_delta: 'RX-14',
});

/** @typedef {{independent_recomputation?: boolean, methodology_delta?: boolean}} VerifierCapability */

/**
 * @param {{
 *   outcome?: string | null,
 *   referenceKind?: string | null,
 *   verifierCapability?: VerifierCapability | null,
 * }} input
 * @returns {{allowed: boolean, code?: string, reason?: string, surfaceState?: string}}
 */
export function outcomeDisplayDecision(input) {
  const { outcome, referenceKind, verifierCapability } = input ?? {};
  if (!verifierCapability) {
    return {
      allowed: false,
      code: OUTCOME_REFUSAL.VERIFIER_CAPABILITY_UNKNOWN,
      surfaceState: 'needs-configuration',
      reason:
        'No verifier capability record. docs/security/T10_REVIEW.md forbids displaying any ' +
        'verification outcome until the verifier implements independent recomputation (RX-18) ' +
        'and the methodology-delta check (RX-14). Nothing is being withheld from you that the ' +
        'system knows.',
    };
  }
  const missing = Object.entries(REQUIRED_VERIFIER_CONTROLS)
    .filter(([key]) => verifierCapability[key] !== true)
    .map(([key, rx]) => `${key} (${rx})`);
  if (missing.length > 0) {
    return {
      allowed: false,
      code: OUTCOME_REFUSAL.VERIFIER_CONTROLS_INCOMPLETE,
      surfaceState: 'needs-configuration',
      reason: `The verifier does not yet assert: ${missing.join(', ')}. No outcome may be shown.`,
    };
  }
  if (!outcome) {
    return {
      allowed: false,
      code: OUTCOME_REFUSAL.UNKNOWN_OUTCOME,
      surfaceState: 'empty',
      reason: 'No verification outcome has been recorded for this run.',
    };
  }
  if (referenceKind === 'NO_REFERENCE' && outcome === 'REPRODUCED_WITHIN_CONTRACT') {
    return {
      allowed: false,
      code: OUTCOME_REFUSAL.NO_REFERENCE_CANNOT_REPRODUCE,
      surfaceState: 'error',
      reason:
        'A NO_REFERENCE contract can never yield REPRODUCED_WITHIN_CONTRACT. The server sent a ' +
        'pairing the contract vocabulary forbids; it is refused rather than rendered.',
    };
  }
  return { allowed: true };
}

/**
 * Render the badge, or the refusal that replaces it.
 *
 * @param {{
 *   outcome?: string | null,
 *   referenceKind?: string | null,
 *   verifierCapability?: VerifierCapability | null,
 *   contractRef?: string,
 *   contractVersion?: string | number,
 * }} input
 * @returns {HTMLElement}
 */
export function renderGatedOutcome(input) {
  const decision = outcomeDisplayDecision(input);
  if (!decision.allowed) {
    return el('div', { dataset: { region: 'truthfulness-labels', refusal: decision.code } }, [
      renderSurfaceState(decision.surfaceState ?? 'needs-configuration', {
        title: 'Verification outcome not shown',
        reason: decision.reason ?? '',
      }),
    ]);
  }
  return renderOutcome(String(input.outcome), {
    contractRef: String(input.contractRef ?? 'contract unidentified'),
    contractVersion: input.contractVersion,
  });
}

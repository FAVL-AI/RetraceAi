/* The verification-outcome badge - icon + text + colour (RX-11, RX-12, RX-25).
 *
 * This module is the ONLY place in the workspace that may turn a
 * `VerificationOutcome` into something a person reads. That is a deliberate
 * chokepoint, for the reason docs/security/T10_REVIEW.md states in control 1:
 * the real exposure is a reader taking `REPRODUCED_WITHIN_CONTRACT` to mean
 * "the science is right", and THE STRING IS THE ATTACK SURFACE. Shortening it
 * to "Reproduced", or rendering it as a bare tick, converts a statement about
 * conformance with a declared contract into a correctness claim RETRACE never
 * makes.
 *
 * Three properties follow, and all three are tested:
 *   1. the label text comes from this table and nowhere else, so no view can
 *      invent a shorter one (tests/web/test_outcome_labels.py);
 *   2. every badge emits geometry, text and colour together - the colour is
 *      applied through `--rx-outcome-colour` on the badge element, and
 *      `var(--state-*)` is confined to the `.rx-outcome` namespace in CSS;
 *   3. the contract identity is rendered ADJACENT to the label, because
 *      "within contract" is meaningless without naming which contract.
 *
 * The five label strings are quoted from the docs/UX.md verification-state
 * table; `tests/web/conftest.py` parses that table and compares, so a change to
 * the document fails here instead of drifting.
 */

import { el, srOnly } from './dom.js';
import { icon } from './icons.js';

/**
 * Presentation for each of the five outcomes. `label` is the complete,
 * unshortenable text. `qualifier` is the standing scope sentence, not a
 * per-run message.
 */
export const OUTCOME_PRESENTATION = Object.freeze({
  REPRODUCED_WITHIN_CONTRACT: Object.freeze({
    label: 'Reproduced within contract',
    icon: 'contract-check',
    token: '--state-reproduced',
    qualifier: 'Agreement with this contract’s declared checks. Not a correctness claim.',
  }),
  EXECUTED_NOT_VERIFIED: Object.freeze({
    label: 'Executed — not verified',
    icon: 'ran-unconcluded',
    token: '--state-unverified',
    qualifier: 'The run finished. No verification conclusion was reached.',
  }),
  CHANGED_RESULT: Object.freeze({
    label: 'Changed result',
    icon: 'diverged',
    token: '--state-changed',
    qualifier: 'Output or declared methodology differs from the reference.',
  }),
  BLOCKED_MISSING_EVIDENCE: Object.freeze({
    label: 'Blocked — missing evidence',
    icon: 'blocked-evidence',
    token: '--state-blocked',
    qualifier: 'Required evidence was absent. Abstention, not a pass.',
  }),
  FAILED_EXECUTION: Object.freeze({
    label: 'Failed execution',
    icon: 'execution-failed',
    token: '--state-failed',
    qualifier: 'The process did not complete. Nothing was verified.',
  }),
});

/** The five outcome ids, in the order docs/UX.md lists them. */
export const OUTCOMES = Object.freeze(Object.keys(OUTCOME_PRESENTATION));

/**
 * The full label for an outcome. Throws on an unknown value rather than
 * falling back to the raw enum name, because a raw name on screen is also an
 * unreviewed label.
 *
 * @param {string} outcome
 * @returns {string}
 */
export function outcomeLabel(outcome) {
  const entry = OUTCOME_PRESENTATION[outcome];
  if (!entry) throw new Error(`unknown verification outcome: ${outcome}`);
  return entry.label;
}

/**
 * Render the badge.
 *
 * `contractRef` is required and is rendered beside the label: T10 control 1
 * requires the contract identity to be adjacent. Passing nothing is a
 * programming error, not a layout choice, so it throws.
 *
 * @param {string} outcome one of OUTCOMES
 * @param {{contractRef: string, contractVersion?: string|number}} context
 * @returns {HTMLElement}
 */
export function renderOutcome(outcome, context) {
  const entry = OUTCOME_PRESENTATION[outcome];
  if (!entry) throw new Error(`unknown verification outcome: ${outcome}`);
  if (!context || !context.contractRef) {
    throw new Error(
      `renderOutcome(${outcome}) needs contractRef: "within contract" names no contract without it`,
    );
  }
  const version = context.contractVersion === undefined ? '' : ` v${context.contractVersion}`;
  return el(
    'span',
    {
      class: 'rx-outcome',
      dataset: { outcome, region: 'truthfulness-labels' },
      attrs: { role: 'group', 'aria-label': `${entry.label}. ${entry.qualifier}` },
    },
    [
      el('span', { class: 'rx-outcome__icon' }, [icon(entry.icon, { size: 18 })]),
      el('span', { class: 'rx-outcome__label', text: entry.label }),
      srOnly(entry.qualifier),
      el('span', {
        class: 'rx-outcome__qualifier rx-mono',
        text: `${context.contractRef}${version}`,
      }),
    ],
  );
}

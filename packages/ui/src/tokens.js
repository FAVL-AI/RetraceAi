/* The token name registry (RX-19).
 *
 * The VALUES live in `packages/ui/tokens/tokens.css`, which is the single
 * authority. This module names them so JavaScript can reference a token without
 * spelling a hex code, and so tests/web/test_tokens.py can assert the CSS
 * declares every name the code uses - a token referenced from JS but absent
 * from the stylesheet resolves to nothing, which is a silent blank panel.
 */

/** Colour tokens that must appear in all three theme forms. */
export const THEMED_COLOUR_TOKENS = Object.freeze([
  '--surface-canvas',
  '--surface-panel',
  '--surface-raised',
  '--surface-sunken',
  '--border-subtle',
  '--border-strong',
  '--text-primary',
  '--text-secondary',
  '--text-tertiary',
  '--accent',
  '--focus-ring',
  '--state-reproduced',
  '--state-unverified',
  '--state-changed',
  '--state-blocked',
  '--state-failed',
]);

/** The five verification-state colour tokens, keyed by outcome. */
export const STATE_COLOUR_TOKENS = Object.freeze({
  REPRODUCED_WITHIN_CONTRACT: '--state-reproduced',
  EXECUTED_NOT_VERIFIED: '--state-unverified',
  CHANGED_RESULT: '--state-changed',
  BLOCKED_MISSING_EVIDENCE: '--state-blocked',
  FAILED_EXECUTION: '--state-failed',
});

/** Density values docs/UX.md defines, with their row heights. */
export const DENSITIES = Object.freeze(['comfortable', 'compact']);

/** Theme values. `system` sets no attribute, so the media query decides. */
export const THEMES = Object.freeze(['light', 'dark', 'system']);

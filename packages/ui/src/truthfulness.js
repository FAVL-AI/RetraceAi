/* The nine truthfulness chips (RX-25, RX-30).
 *
 * docs/UX.md fixes the TOKEN spellings, mixed case included, and
 * `packages/i18n/retrace_i18n/labels.py` carries the same nine as the
 * authority for translation: the token itself is a protected span (RX-29), so a
 * translation pass may localise the gloss around it but never the token.
 * This module mirrors that spelling exactly; tests/web/test_tokens.py compares
 * the two lists so a drift fails rather than silently diverging.
 *
 * A chip is a bordered element carrying the token as TEXT plus a gloss. It is
 * never colour-only and never animated - an animated "live" chip implies
 * activity the system may not be observing.
 */

import { el, srOnly } from './dom.js';
import { icon } from './icons.js';

/** The nine tokens, spelled as docs/UX.md spells them. */
export const TRUTHFULNESS_TOKENS = Object.freeze([
  'STALE',
  'UNAVAILABLE',
  'REPLAY',
  'DEMO',
  'beta',
  'NEEDS_CONFIGURATION',
  'SYNTHETIC',
  'injected',
  'machine-translated',
]);

/** The standing gloss for each token. Short, and about the data, not the mood. */
export const TRUTHFULNESS_GLOSS = Object.freeze({
  STALE: 'the stream stopped; this is the last frame received, not the current state',
  UNAVAILABLE: 'this surface has no data and is not waiting for any',
  REPLAY: 'recorded events being re-played, not observed now',
  DEMO: 'fixture content shipped with the build',
  beta: 'present but unreviewed',
  NEEDS_CONFIGURATION: 'not configured; nothing was attempted',
  SYNTHETIC: 'generated data, not a recorded observation',
  injected: 'a fault placed deliberately by a fixture',
  'machine-translated': 'translated without human linguistic review',
});

/**
 * @param {string} token one of TRUTHFULNESS_TOKENS
 * @param {{glyph?: string, detail?: string}} [options]
 * @returns {HTMLElement}
 */
export function renderTruthfulnessChip(token, options = {}) {
  if (!TRUTHFULNESS_TOKENS.includes(token)) {
    throw new Error(`not a truthfulness token: ${token}`);
  }
  const gloss = TRUTHFULNESS_GLOSS[token];
  const children = [];
  if (options.glyph) {
    children.push(el('span', { class: 'rx-chip__glyph' }, [icon(options.glyph, { size: 14 })]));
  }
  children.push(el('span', { text: token }));
  children.push(srOnly(` — ${gloss}`));
  if (options.detail) {
    children.push(el('span', { class: 'rx-chip__gloss', text: options.detail }));
  }
  return el(
    'span',
    {
      class: 'rx-chip',
      dataset: { truthToken: token, region: 'truthfulness-labels' },
      attrs: { title: gloss },
    },
    children,
  );
}

/**
 * A labelled group of chips. The legend is mandatory: an unlabelled row of
 * chips leaves the reader to guess WHICH attribute they describe, which is how
 * two different attributes get read as one.
 *
 * @param {string} legend
 * @param {HTMLElement[]} chips
 * @param {{attribute: string}} meta
 * @returns {HTMLElement}
 */
export function renderChipGroup(legend, chips, meta) {
  if (!meta || !meta.attribute) throw new Error('a chip group must name its attribute');
  return el(
    'div',
    {
      class: 'rx-chip-group',
      dataset: { attribute: meta.attribute },
      attrs: { role: 'group', 'aria-label': legend },
    },
    [el('span', { class: 'rx-chip-group__legend', text: legend }), ...chips],
  );
}

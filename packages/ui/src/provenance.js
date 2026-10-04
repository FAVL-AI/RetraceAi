/* DATA PROVENANCE - where the bytes came from (RX-25, RX-56).
 *
 * This module answers exactly one question: was this data recorded, or was it
 * generated? It deliberately knows NOTHING about how recently it arrived. That
 * is `freshness.js`, a separate attribute with a separate vocabulary and a
 * separate chip group, and the two are never merged into one status.
 *
 * Why the separation is a correctness property and not tidiness: "live" says an
 * event is current, "real" says it was observed. A synthetic fixture can stream
 * at full rate and be perfectly fresh while describing nothing that happened; a
 * genuine recorded measurement can be hours stale and still be real evidence.
 * Collapsing them into one green dot loses whichever half the reader needed.
 * `docs/evidence/SPEC_RECONCILIATION_CLOSURE.md` section 4 makes the same point
 * in the contract layer: data provenance, proposal provenance, execution state
 * and verification outcome stay four separate attributes.
 *
 * tests/web/test_provenance_freshness.py asserts the two vocabularies are
 * disjoint, that neither module imports the other, and that no string anywhere
 * in the workspace mixes a token from both.
 */

import { renderChipGroup, renderTruthfulnessChip } from './truthfulness.js';
import { el } from './dom.js';
import { icon } from './icons.js';

/** The attribute name used in `data-attribute` and in the group legend. */
export const PROVENANCE_ATTRIBUTE = 'data-provenance';

/** The legend shown to the reader. */
export const PROVENANCE_LEGEND = 'Data provenance';

/**
 * The provenance vocabulary. `truthToken` names the docs/UX.md chip to render,
 * or null when the value needs no warning chip.
 */
export const DATA_PROVENANCE = Object.freeze({
  REAL_RECORDED: Object.freeze({
    label: 'Recorded source',
    truthToken: null,
    icon: 'real-source',
    detail: 'imported from a named source and content-addressed',
  }),
  SYNTHETIC: Object.freeze({
    label: 'Synthetic',
    truthToken: 'SYNTHETIC',
    icon: 'synthetic',
    detail: 'generated, not observed',
  }),
  DEMO_FIXTURE: Object.freeze({
    label: 'Demo fixture',
    truthToken: 'DEMO',
    icon: 'synthetic',
    detail: 'shipped with the build',
  }),
  INJECTED_FAULT: Object.freeze({
    label: 'Injected fault',
    truthToken: 'injected',
    icon: 'synthetic',
    detail: 'placed deliberately; never a defect in third-party software',
  }),
});

/** @type {readonly string[]} */
export const PROVENANCE_VALUES = Object.freeze(Object.keys(DATA_PROVENANCE));

/**
 * Render the provenance group for one or more values.
 *
 * @param {string[]} values
 * @returns {HTMLElement}
 */
export function renderProvenance(values) {
  if (!Array.isArray(values) || values.length === 0) {
    throw new Error('provenance is never absent: pass at least one value');
  }
  const chips = values.map((value) => {
    const entry = DATA_PROVENANCE[value];
    if (!entry) throw new Error(`unknown data provenance: ${value}`);
    if (entry.truthToken) {
      return renderTruthfulnessChip(entry.truthToken, {
        glyph: entry.icon,
        detail: entry.detail,
      });
    }
    return el(
      'span',
      { class: 'rx-chip', dataset: { provenance: value } },
      [
        el('span', { class: 'rx-chip__glyph' }, [icon(entry.icon, { size: 14 })]),
        el('span', { text: entry.label }),
        el('span', { class: 'rx-chip__gloss', text: entry.detail }),
      ],
    );
  });
  return renderChipGroup(PROVENANCE_LEGEND, chips, { attribute: PROVENANCE_ATTRIBUTE });
}

/* EVENT FRESHNESS - how current this frame is (RX-25).
 *
 * This module answers exactly one question: is what you are looking at being
 * observed now, was it observed and then the stream stopped, is it a recording
 * being re-played, or is there no stream at all? It knows NOTHING about whether
 * the underlying data was recorded or generated - that is `provenance.js`, a
 * separate attribute with a separate vocabulary and a separate chip group.
 *
 * The rule that costs the most to get wrong: when a stream disconnects, the
 * last frame must stop being presented as the current state. docs/UX.md: "a
 * disconnected stream must say so rather than keep showing the last frame as
 * current". `renderStaleFrame` below is the only sanctioned way to keep showing
 * old content, and it brands the content and names the time it was received.
 */

import { renderChipGroup, renderTruthfulnessChip } from './truthfulness.js';
import { el } from './dom.js';
import { icon } from './icons.js';

/** The attribute name used in `data-attribute` and in the group legend. */
export const FRESHNESS_ATTRIBUTE = 'event-freshness';

/** The legend shown to the reader. */
export const FRESHNESS_LEGEND = 'Event freshness';

/** The freshness vocabulary. Disjoint from the provenance vocabulary by design. */
export const EVENT_FRESHNESS = Object.freeze({
  LIVE: Object.freeze({
    label: 'Live',
    truthToken: null,
    icon: 'stream-live',
    detail: 'events are arriving',
  }),
  STALE: Object.freeze({
    label: 'Stale',
    truthToken: 'STALE',
    icon: 'stream-stale',
    detail: 'the stream stopped; this is not the current state',
  }),
  REPLAY: Object.freeze({
    label: 'Replay',
    truthToken: 'REPLAY',
    icon: 'stream-replay',
    detail: 're-playing recorded events',
  }),
  UNAVAILABLE: Object.freeze({
    label: 'Unavailable',
    truthToken: 'UNAVAILABLE',
    icon: 'unavailable',
    detail: 'no stream; nothing is being observed',
  }),
});

/** @type {readonly string[]} */
export const FRESHNESS_VALUES = Object.freeze(Object.keys(EVENT_FRESHNESS));

/**
 * Render the freshness group.
 *
 * @param {string} value one of FRESHNESS_VALUES
 * @param {{asOf?: string}} [options] an ISO-8601 instant for the last frame
 * @returns {HTMLElement}
 */
export function renderFreshness(value, options = {}) {
  const entry = EVENT_FRESHNESS[value];
  if (!entry) throw new Error(`unknown event freshness: ${value}`);
  const chips = [];
  if (entry.truthToken) {
    chips.push(renderTruthfulnessChip(entry.truthToken, { glyph: entry.icon, detail: entry.detail }));
  } else {
    chips.push(
      el('span', { class: 'rx-chip', dataset: { freshness: value } }, [
        el('span', { class: 'rx-chip__glyph' }, [icon(entry.icon, { size: 14 })]),
        el('span', { text: entry.label }),
        el('span', { class: 'rx-chip__gloss', text: entry.detail }),
      ]),
    );
  }
  if (options.asOf) {
    chips.push(
      el('span', { class: 'rx-chip__gloss rx-mono', text: `last frame ${options.asOf}` }),
    );
  }
  return renderChipGroup(FRESHNESS_LEGEND, chips, { attribute: FRESHNESS_ATTRIBUTE });
}

/**
 * Wrap content that is no longer current. The banner is part of the frame, not
 * an adjacent hint, so the content cannot be screenshotted without it.
 *
 * @param {Node} content
 * @param {{value?: string, asOf?: string}} state
 * @returns {HTMLElement}
 */
export function renderStaleFrame(content, state) {
  const value = state && state.value ? state.value : 'STALE';
  const entry = EVENT_FRESHNESS[value];
  if (!entry || entry.truthToken === null) {
    throw new Error(`renderStaleFrame needs a non-current freshness value, got: ${value}`);
  }
  return el('div', { class: 'rx-stale-frame', dataset: { freshness: value } }, [
    el('div', { class: 'rx-stale-frame__banner' }, [
      renderFreshness(value, { asOf: state ? state.asOf : undefined }),
      el('span', {
        text: 'Content below is the last frame received. It is not the current state.',
      }),
    ]),
    el('div', { class: 'rx-stale-frame__content' }, [content]),
  ]);
}

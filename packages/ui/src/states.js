/* The nine required surface states (docs/UX.md "Required states for every data
 * surface", RX-25, RX-40).
 *
 * empty, loading, error, offline, stale, replay, partial, permission-denied,
 * needs-configuration. A surface that can only render content is incomplete:
 * the absence of data is itself information, and the WHY is the part the reader
 * needs. Every state therefore carries a reason string, and
 * tests/web/test_shell_routes_panels.py refuses a view that renders a state
 * without one.
 *
 * `needs-configuration` exists for the whole class of features that depend on
 * something this build has not got - a model provider, a connector credential,
 * a configured API origin. RX-40 is explicit that absence reports
 * NEEDS_CONFIGURATION and never a simulated success, so there is no
 * placeholder-content branch in this module to fall back to.
 */

import { el } from './dom.js';
import { icon } from './icons.js';
import { renderTruthfulnessChip } from './truthfulness.js';

/** The nine states, with the chip (if any) each one must display. */
export const SURFACE_STATES = Object.freeze({
  empty: Object.freeze({ title: 'Nothing here yet', truthToken: null, icon: 'chevron' }),
  loading: Object.freeze({ title: 'Loading', truthToken: null, icon: 'chevron' }),
  error: Object.freeze({ title: 'Request failed', truthToken: null, icon: 'execution-failed' }),
  offline: Object.freeze({ title: 'Offline', truthToken: 'UNAVAILABLE', icon: 'unavailable' }),
  stale: Object.freeze({ title: 'Not current', truthToken: 'STALE', icon: 'stream-stale' }),
  replay: Object.freeze({ title: 'Replaying', truthToken: 'REPLAY', icon: 'stream-replay' }),
  partial: Object.freeze({ title: 'Partial result', truthToken: null, icon: 'chevron' }),
  'permission-denied': Object.freeze({
    title: 'Not permitted',
    truthToken: null,
    icon: 'blocked-evidence',
  }),
  'needs-configuration': Object.freeze({
    title: 'Not configured',
    truthToken: 'NEEDS_CONFIGURATION',
    icon: 'needs-configuration',
  }),
});

/** @type {readonly string[]} */
export const SURFACE_STATE_NAMES = Object.freeze(Object.keys(SURFACE_STATES));

/**
 * @param {string} state one of SURFACE_STATE_NAMES
 * @param {{title?: string, reason: string, actions?: HTMLElement[]}} detail
 * @returns {HTMLElement}
 */
export function renderSurfaceState(state, detail) {
  const entry = SURFACE_STATES[state];
  if (!entry) throw new Error(`unknown surface state: ${state}`);
  if (!detail || !detail.reason) {
    throw new Error(`surface state "${state}" needs a reason: an unexplained blank panel is a bug`);
  }
  const chips = entry.truthToken ? [renderTruthfulnessChip(entry.truthToken)] : [];
  return el('div', { class: 'rx-surface-state', dataset: { state }, attrs: { role: 'status' } }, [
    el('div', { class: 'rx-surface-state__title' }, [
      icon(entry.icon, { size: 16 }),
      el('span', { text: detail.title ?? entry.title }),
    ]),
    ...chips,
    el('p', { class: 'rx-surface-state__reason', text: detail.reason }),
    ...(detail.actions ?? []),
  ]);
}

/**
 * A feature that depends on something absent. The reason is mandatory and is
 * shown, not logged: "never a simulated success" (RX-40) means the reader must
 * be able to see WHY nothing happened.
 *
 * @param {{feature: string, reason: string, requirement?: string}} detail
 * @returns {HTMLElement}
 */
export function renderUnavailableFeature(detail) {
  if (!detail || !detail.feature || !detail.reason) {
    throw new Error('renderUnavailableFeature needs a feature name and a reason');
  }
  const suffix = detail.requirement ? ` (${detail.requirement})` : '';
  return renderSurfaceState('needs-configuration', {
    title: `${detail.feature} — unavailable`,
    reason: `${detail.reason}${suffix}`,
  });
}

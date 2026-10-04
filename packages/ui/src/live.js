/* The single polite live region (RX-21).
 *
 * Layout operations driven from the keyboard produce no visible focus change -
 * a panel grows, or swaps place with its neighbour, somewhere the user may not
 * be looking. Without an announcement the keyboard path "works" and tells the
 * operator nothing, which is operable but not usable. One shared region is used
 * rather than per-panel regions: several live regions compete and the
 * announcements interleave.
 */

import { el } from './dom.js';

let region = null;

/**
 * @param {{document?: Document}} [options]
 * @returns {HTMLElement}
 */
export function liveRegion(options = {}) {
  const doc = options.document ?? document;
  if (region && region.isConnected) return region;
  region = el('div', {
    class: 'rx-visually-hidden',
    id: 'rx-live-region',
    attrs: { 'aria-live': 'polite', 'aria-atomic': 'true', role: 'status' },
  });
  doc.body.appendChild(region);
  return region;
}

/**
 * @param {string} message
 * @returns {void}
 */
export function announce(message) {
  const node = liveRegion();
  node.textContent = message;
}

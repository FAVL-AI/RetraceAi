/* Icon geometry (RX-19, RX-25).
 *
 * Every verification state and every stream-freshness state needs a shape that
 * differs from the others by GEOMETRY, not by colour: docs/UX.md forbids colour
 * as the sole carrier, and a reader with a colour-vision deficiency, a
 * monochrome display or a high-contrast forced-colours mode sees shape and text
 * only. The five outcome paths below are therefore deliberately dissimilar in
 * outline, and tests/web/test_outcome_labels.py asserts no two are equal.
 *
 * The icons are decorative in the accessibility tree (`aria-hidden`): the text
 * label beside them carries the meaning, so a missing icon degrades to text
 * rather than to nothing.
 */

import { svg } from './dom.js';

/** 24x24 path geometry, one entry per icon id. */
export const ICON_PATHS = Object.freeze({
  /* a document with a tick INSIDE it: conformance to a declared contract */
  'contract-check': 'M6 2h9l5 5v15H6zM15 2v5h5M9 14l3 3 5-6',
  /* a filled square with a hollow centre: it ran, nothing was concluded */
  'ran-unconcluded': 'M4 4h16v16H4zM9 9h6v6H9z',
  /* a forked arrow: the result diverged from the reference */
  'diverged': 'M4 6h5l6 12h5M20 18l-3-3M20 18l-3 3M4 18h5l3-6',
  /* a padlock body with a gap: blocked for want of evidence */
  'blocked-evidence': 'M5 11h14v10H5zM8 11V7a4 4 0 0 1 8 0M12 15v3',
  /* a broken diagonal: execution failed */
  'execution-failed': 'M4 20 10 4M14 20 20 4M3 12h7M14 12h7',
  /* concentric arcs: a live stream */
  'stream-live': 'M12 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4M7 14a7 7 0 0 1 10 0M3 10a12 12 0 0 1 18 0',
  /* a clock with a slash: the frame is not current */
  'stream-stale': 'M12 3a9 9 0 1 0 9 9M12 7v5l4 2M4 4l16 16',
  /* a rewind triangle pair: replay */
  'stream-replay': 'M11 6 4 12l7 6zM20 6l-7 6 7 6z',
  /* a hollow circle with a bar: unavailable */
  'unavailable': 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18M7 12h10',
  /* a wrench outline: needs configuration */
  'needs-configuration': 'M14 3a5 5 0 0 0-4 8L4 17v3h3l6-6a5 5 0 0 0 6-7l-3 3-3-1-1-3z',
  /* a flask: synthetic data */
  'synthetic': 'M9 3h6M10 3v6L5 19h14L14 9V3M7 15h10',
  /* an archive box: real recorded source */
  'real-source': 'M3 7h18v13H3zM3 7l2-4h14l2 4M12 11v5M9 13h6',
  /* a grip of two dot columns: a drag handle */
  'grip': 'M9 6h.01M9 12h.01M9 18h.01M15 6h.01M15 12h.01M15 18h.01',
  /* a vertical ellipsis: a menu */
  'menu': 'M12 5h.01M12 12h.01M12 19h.01',
  /* a chevron: disclosure */
  'chevron': 'M9 6l6 6-6 6',
});

/**
 * Render an icon as inline SVG. Unknown ids throw: a silently missing icon is
 * how an "icon + text + colour" state decays into text-and-colour.
 *
 * @param {string} id
 * @param {{size?: number, className?: string}} [options]
 * @returns {SVGElement}
 */
export function icon(id, options = {}) {
  const path = ICON_PATHS[id];
  if (!path) throw new Error(`unknown icon id: ${id}`);
  const size = String(options.size ?? 16);
  const node = svg(
    'svg',
    {
      width: size,
      height: size,
      viewBox: '0 0 24 24',
      fill: 'none',
      stroke: 'currentColor',
      'stroke-width': '1.75',
      'stroke-linecap': 'round',
      'stroke-linejoin': 'round',
      'aria-hidden': 'true',
      focusable: 'false',
      class: options.className ?? '',
    },
    [svg('path', { d: path })],
  );
  return node;
}

/* Entry point.
 *
 * SOURCE SELECTION IS EXPLICIT AND VISIBLE. The default is the HTTP client,
 * which with no configured origin reports NEEDS_CONFIGURATION on every call.
 * `?data=demo` selects the synthetic fixture instead, and when it is selected a
 * banner appears that cannot be dismissed, because a reader arriving at a
 * screenshot has no other way to know the content is a fixture.
 *
 * There is no third option and no fallback between them: a client that quietly
 * served fixture data when the API was unreachable would be the single most
 * dangerous line of code in this workspace.
 */

import { el, renderTruthfulnessChip } from '../../../packages/ui/src/index.js';
import { createClient } from './api/client.js';
import { createDemoSource } from './api/demo-source.js';
import { DEMO_IDS, createShell, entityIds } from './shell.js';

/**
 * @param {{search?: string, root?: HTMLElement}} [options]
 * @returns {{element: HTMLElement, destroy: () => void}}
 */
export function start(options = {}) {
  const search = options.search ?? window.location.search;
  const params = new URLSearchParams(search);
  const wantsDemo = params.get('data') === 'demo';
  const source = wantsDemo ? createDemoSource() : createClient();
  const ids = wantsDemo ? { ...DEMO_IDS, ...stripEmpty(entityIds(search)) } : entityIds(search);
  const timeZone = params.get('tz') || resolveZone();

  const shell = createShell({ source, ids, timeZone });
  const root = options.root ?? document.getElementById('rx-root');
  if (!root) throw new Error('no #rx-root element to mount into');

  if (wantsDemo) {
    root.appendChild(
      el('div', { class: 'rx-banner', attrs: { role: 'note' } }, [
        renderTruthfulnessChip('DEMO'),
        renderTruthfulnessChip('SYNTHETIC'),
        el('span', {
          text:
            'Every value on this screen is fixture content shipped with the build. It is not a ' +
            'recording, not evidence, and not a verification result.',
        }),
      ]),
    );
  }
  root.appendChild(shell.element);
  return shell;
}

/**
 * @param {Record<string, string>} values
 * @returns {Record<string, string>}
 */
function stripEmpty(values) {
  const out = {};
  for (const [key, value] of Object.entries(values)) {
    if (value !== '') out[key] = value;
  }
  return out;
}

/** @returns {string} */
function resolveZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

if (typeof window !== 'undefined' && document.getElementById('rx-root')) {
  start();
}

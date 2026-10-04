/* The bottom bar: timeline, execution console, checks, warnings, task status
 * (RX-25).
 *
 * The timeline is populated from the event stream and from nothing else. With
 * no stream there are no entries, and the surface says UNAVAILABLE with the
 * reason rather than showing a plausible history - a fabricated timeline is
 * indistinguishable from a real one at a glance, which is what makes it
 * dangerous rather than merely untidy.
 *
 * Nothing in here animates. An idle spinner or a pulsing "live" dot would imply
 * activity that the workspace may not be observing at all.
 */

import { el, renderSurfaceState } from '../../../packages/ui/src/index.js';
import { table } from './views/common.js';

/**
 * @returns {{
 *   element: HTMLElement,
 *   record: (entry: {at: string, kind: string, detail: string}) => void,
 *   setUnavailable: (reason: string) => void,
 * }}
 */
export function renderConsole() {
  /** @type {{at: string, kind: string, detail: string}[]} */
  const entries = [];
  const host = el('div', { class: 'rx-console__body' });
  const draw = () => {
    host.replaceChildren(
      entries.length === 0
        ? renderSurfaceState('empty', {
            title: 'No events recorded',
            reason: 'Entries appear here as the event stream delivers them.',
          })
        : table(
            [
              { key: 'at', label: 'At', mono: true },
              { key: 'kind', label: 'Kind' },
              { key: 'detail', label: 'Detail' },
            ],
            entries.slice(-200).reverse(),
          ),
    );
  };
  draw();

  const element = el('section', { class: 'rx-console', attrs: { 'aria-label': 'Timeline and console' } }, [
    el('h2', { class: 'rx-panel__title', text: 'Timeline · console · checks · warnings' }),
    host,
  ]);

  return {
    element,
    record: (entry) => {
      entries.push(entry);
      draw();
    },
    setUnavailable: (reason) => {
      host.replaceChildren(
        renderSurfaceState('needs-configuration', { title: 'No event stream', reason }),
      );
    },
  };
}

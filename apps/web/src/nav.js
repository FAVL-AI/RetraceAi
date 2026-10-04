/* Left navigation over the thirteen routes (RX-20, RX-21).
 *
 * Every route in `ROUTES` gets an entry, and every entry navigates: RX-20's
 * acceptance condition is "each route renders; no dead nav entry". The current
 * route carries `aria-current="page"` as well as a visual treatment, because a
 * selected item indicated only by background colour is not conveyed to a screen
 * reader or in forced-colours mode.
 */

import { el } from '../../../packages/ui/src/index.js';
import { ROUTES } from './routes.js';

/**
 * @param {{current: string}} ctx
 * @returns {HTMLElement}
 */
export function renderNav(ctx) {
  return el('nav', { class: 'rx-nav', attrs: { 'aria-label': 'Workspace sections' } }, [
    el(
      'ul',
      { class: 'rx-nav__list' },
      ROUTES.map((route) =>
        el('li', {}, [
          el('a', {
            class: 'rx-nav__link',
            href: `#/${route.id}`,
            text: route.title,
            dataset: { route: route.id },
            attrs: route.id === ctx.current
              ? { 'aria-current': 'page', title: route.note }
              : { title: route.note },
          }),
        ]),
      ),
    ),
  ]);
}

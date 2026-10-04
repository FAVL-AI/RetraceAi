/* An accessible menu (RX-21).
 *
 * This is the "menu path" half of the RX-21 obligation, and it is the half that
 * also discharges WCAG 2.5.7: a pointer user who cannot perform a drag reaches
 * every drag operation here with a single click. It is therefore not a
 * convenience - removing it would break a conformance requirement, which is
 * why tests/web/test_drag_alternatives.py asserts a menu item exists for every
 * drag operation.
 */

import { clear, el } from './dom.js';

/**
 * @typedef {{id: string, label: string, keys?: readonly string[], onSelect: () => void}} MenuItem
 */

let openPanelMenu = null;

/** @returns {void} */
export function closeMenu() {
  if (openPanelMenu && openPanelMenu.isConnected) openPanelMenu.remove();
  openPanelMenu = null;
}

/**
 * @param {HTMLElement} anchor the button that owns the menu
 * @param {MenuItem[]} items
 * @returns {HTMLElement}
 */
export function openMenu(anchor, items) {
  closeMenu();
  const list = el('ul', {
    class: 'rx-menu',
    attrs: { role: 'menu', 'aria-label': anchor.getAttribute('aria-label') ?? 'Panel actions' },
  });
  /** @type {HTMLElement[]} */
  const buttons = [];
  items.forEach((item) => {
    const button = el(
      'button',
      {
        type: 'button',
        class: 'rx-menu__item',
        dataset: { operation: item.id },
        attrs: { role: 'menuitem', tabindex: '-1' },
        onClick: () => {
          closeMenu();
          anchor.focus();
          item.onSelect();
        },
      },
      [
        el('span', { text: item.label }),
        item.keys && item.keys.length > 0
          ? el('span', { class: 'rx-menu__keys', text: item.keys.join(' / ') })
          : null,
      ],
    );
    buttons.push(button);
    list.appendChild(el('li', { attrs: { role: 'none' } }, [button]));
  });

  let index = 0;
  const focusAt = (next) => {
    index = (next + buttons.length) % buttons.length;
    buttons[index].focus();
  };
  list.addEventListener('keydown', (event) => {
    const key = /** @type {KeyboardEvent} */ (event).key;
    if (key === 'ArrowDown') {
      event.preventDefault();
      focusAt(index + 1);
    } else if (key === 'ArrowUp') {
      event.preventDefault();
      focusAt(index - 1);
    } else if (key === 'Home') {
      event.preventDefault();
      focusAt(0);
    } else if (key === 'End') {
      event.preventDefault();
      focusAt(buttons.length - 1);
    } else if (key === 'Escape' || key === 'Tab') {
      closeMenu();
      anchor.focus();
    }
  });

  const host = anchor.parentElement ?? anchor;
  host.appendChild(list);
  openPanelMenu = list;
  if (buttons.length > 0) focusAt(0);
  return list;
}

/**
 * Replace a container's children with a menu-shaped list. Used by the header
 * overflow menus, which are always rendered rather than opened on demand.
 *
 * @param {HTMLElement} container
 * @param {MenuItem[]} items
 * @returns {HTMLElement}
 */
export function renderMenuInto(container, items) {
  clear(container);
  for (const item of items) {
    container.appendChild(
      el('button', {
        type: 'button',
        class: 'rx-menu__item',
        dataset: { operation: item.id },
        text: item.label,
        onClick: item.onSelect,
      }),
    );
  }
  return container;
}

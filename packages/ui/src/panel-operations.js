/* The panel operation table - the authority for RX-21.
 *
 * TWO SEPARATE OBLIGATIONS, deliberately represented as two separate fields:
 *
 *   `keys`  - WCAG 2.1.1 Keyboard. Every operation must be completable from the
 *             keyboard alone.
 *   `menu`  - WCAG 2.5.7 Dragging Movements. Every operation available by
 *             dragging must ALSO be available through a single-pointer action
 *             that is not a drag. A keyboard path does not discharge this: a
 *             pointer user who cannot drag is not thereby a keyboard user.
 *
 * docs/UX.md states the same thing ("both apply"). They are checked separately
 * in tests/web/test_drag_alternatives.py, so satisfying one can never be
 * mistaken for satisfying the other.
 *
 * `pointer: 'drag'` marks the operations whose pointer affordance is a drag.
 * Those are the ones 2.5.7 constrains; `pointer: 'click'` operations are
 * already single-action.
 */

/**
 * @typedef {{
 *   id: string,
 *   label: string,
 *   pointer: 'drag' | 'click',
 *   keys: readonly string[],
 *   menu: boolean,
 *   method: string,
 *   describe: string,
 * }} PanelOperation
 */

/** @type {Readonly<Record<string, PanelOperation>>} */
export const PANEL_OPERATIONS = Object.freeze({
  reorder: Object.freeze({
    id: 'reorder',
    label: 'Move panel earlier / later',
    pointer: 'drag',
    keys: Object.freeze(['Alt+ArrowUp', 'Alt+ArrowDown']),
    menu: true,
    method: 'reorder',
    describe: 'changes the panel order within its slot',
  }),
  resize: Object.freeze({
    id: 'resize',
    label: 'Grow / shrink panel',
    pointer: 'drag',
    keys: Object.freeze(['Alt+Shift+ArrowUp', 'Alt+Shift+ArrowDown']),
    menu: true,
    method: 'resize',
    describe: 'changes the panel size in its slot',
  }),
  dock: Object.freeze({
    id: 'dock',
    label: 'Dock panel',
    pointer: 'drag',
    keys: Object.freeze(['Alt+D']),
    menu: true,
    method: 'dock',
    describe: 'returns a floating panel to its slot',
  }),
  float: Object.freeze({
    id: 'float',
    label: 'Float panel',
    pointer: 'drag',
    keys: Object.freeze(['Alt+F']),
    menu: true,
    method: 'float',
    describe: 'lifts the panel out of its slot',
  }),
  collapse: Object.freeze({
    id: 'collapse',
    label: 'Collapse / expand panel',
    pointer: 'click',
    keys: Object.freeze(['Alt+C']),
    menu: true,
    method: 'collapse',
    describe: 'hides the panel body, keeping its bar',
  }),
  pin: Object.freeze({
    id: 'pin',
    label: 'Pin / unpin panel',
    pointer: 'click',
    keys: Object.freeze(['Alt+P']),
    menu: true,
    method: 'pin',
    describe: 'keeps the panel across route changes',
  }),
  restore: Object.freeze({
    id: 'restore',
    label: 'Restore default layout',
    pointer: 'click',
    keys: Object.freeze(['Alt+R']),
    menu: true,
    method: 'restore',
    describe: 'discards the saved layout for this route',
  }),
});

/** @type {readonly string[]} */
export const PANEL_OPERATION_IDS = Object.freeze(Object.keys(PANEL_OPERATIONS));

/** The operations whose pointer affordance is a drag - the 2.5.7 set. */
export const DRAG_OPERATION_IDS = Object.freeze(
  PANEL_OPERATION_IDS.filter((id) => PANEL_OPERATIONS[id].pointer === 'drag'),
);

/**
 * Canonical key-combination string for a keyboard event, in the same spelling
 * the table uses. Built here so the table and the handler cannot disagree.
 *
 * @param {KeyboardEvent} event
 * @returns {string}
 */
export function keyCombination(event) {
  const parts = [];
  if (event.ctrlKey) parts.push('Ctrl');
  if (event.altKey) parts.push('Alt');
  if (event.shiftKey) parts.push('Shift');
  if (event.metaKey) parts.push('Meta');
  const key = event.key.length === 1 ? event.key.toUpperCase() : event.key;
  parts.push(key);
  return parts.join('+');
}

/**
 * Resolve a key combination to an operation and a direction.
 *
 * @param {string} combination
 * @returns {{operation: PanelOperation, direction: number} | null}
 */
export function operationForKeys(combination) {
  for (const id of PANEL_OPERATION_IDS) {
    const operation = PANEL_OPERATIONS[id];
    const index = operation.keys.indexOf(combination);
    if (index >= 0) {
      const direction = operation.keys.length > 1 && index === 1 ? -1 : 1;
      return { operation, direction };
    }
  }
  return null;
}

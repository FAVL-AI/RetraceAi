/* Panel chrome: three input routes to one model (RX-21, RX-23).
 *
 * Every operation in `PANEL_OPERATIONS` is reachable here by all of:
 *   - POINTER DRAG, for the operations whose affordance is a drag (the grip and
 *     the resizer);
 *   - SINGLE CLICK, through the panel menu - this is the WCAG 2.5.7 path, and
 *     it exists for every drag operation without exception;
 *   - KEYBOARD, through the key combinations the table declares, handled on the
 *     panel root so the panel only needs focus somewhere inside it.
 *
 * All three call `model.apply(...)`, so they cannot drift apart in behaviour.
 * `LayoutRefused` is caught and announced rather than thrown into the console:
 * when RX-23 refuses to collapse the security context, the operator is told
 * why, which is the difference between a control and a dead key.
 */

import { el, srOnly } from './dom.js';
import { icon } from './icons.js';
import { announce } from './live.js';
import { openMenu } from './menu.js';
import { LayoutRefused } from './layout.js';
import { PANEL_OPERATIONS, PANEL_OPERATION_IDS, keyCombination, operationForKeys } from './panel-operations.js';

/**
 * @param {import('./layout.js').LayoutModel} model
 * @param {string} operationId
 * @param {string} panelId
 * @param {number} direction
 * @returns {void}
 */
function applyOperation(model, operationId, panelId, direction) {
  const operation = PANEL_OPERATIONS[operationId];
  try {
    model.apply(operationId, panelId, direction);
    announce(`${operation ? operation.label : operationId}: applied to ${panelId}`);
  } catch (error) {
    if (error instanceof LayoutRefused) {
      announce(`Refused: ${error.message}`);
      return;
    }
    throw error;
  }
}

/**
 * @param {import('./layout.js').LayoutModel} model
 * @param {string} panelId
 * @returns {import('./menu.js').MenuItem[]}
 */
export function panelMenuItems(model, panelId) {
  return PANEL_OPERATION_IDS.map((id) => {
    const operation = PANEL_OPERATIONS[id];
    return {
      id,
      label: operation.label,
      keys: operation.keys,
      onSelect: () => applyOperation(model, id, panelId, 1),
    };
  });
}

/**
 * @param {{
 *   state: import('./layout.js').PanelState,
 *   model: import('./layout.js').LayoutModel,
 *   body: Node,
 *   onDropBefore?: (dragged: string, target: string) => void,
 * }} spec
 * @returns {HTMLElement}
 */
export function renderPanel(spec) {
  const { state, model, body } = spec;
  const titleId = `panel-title-${state.id}`;

  const grip = el('button', {
    type: 'button',
    class: 'rx-panel__grip',
    dataset: { operation: 'reorder', dragHandle: 'true' },
    attrs: {
      'aria-label': `${PANEL_OPERATIONS.reorder.label}: ${state.title}. ` +
        `Keyboard ${PANEL_OPERATIONS.reorder.keys.join(' or ')}, or use the panel menu.`,
      draggable: 'true',
    },
  }, [icon('grip', { size: 14 })]);

  grip.addEventListener('dragstart', (event) => {
    const transfer = /** @type {DragEvent} */ (event).dataTransfer;
    if (transfer) {
      transfer.setData('text/plain', state.id);
      transfer.effectAllowed = 'move';
    }
  });

  const menuButton = el('button', {
    type: 'button',
    class: 'rx-panel__grip',
    dataset: { panelMenu: 'true' },
    attrs: { 'aria-haspopup': 'menu', 'aria-label': `Panel actions: ${state.title}` },
    onClick: () => openMenu(menuButton, panelMenuItems(model, state.id)),
  }, [icon('menu', { size: 14 })]);

  const collapseButton = el('button', {
    type: 'button',
    class: 'rx-panel__grip',
    dataset: { operation: 'collapse' },
    attrs: {
      'aria-expanded': state.collapsed ? 'false' : 'true',
      'aria-controls': `panel-body-${state.id}`,
      'aria-label': `${PANEL_OPERATIONS.collapse.label}: ${state.title}`,
    },
    onClick: () => applyOperation(model, 'collapse', state.id, 1),
  }, [icon('chevron', { size: 14 })]);

  const resizer = el('div', {
    class: 'rx-panel__resizer',
    dataset: { operation: 'resize', dragHandle: 'true' },
    attrs: {
      role: 'separator',
      tabindex: '0',
      'aria-orientation': 'horizontal',
      'aria-label': `${PANEL_OPERATIONS.resize.label}: ${state.title}. ` +
        `Keyboard ${PANEL_OPERATIONS.resize.keys.join(' or ')}, or use the panel menu.`,
      'aria-valuenow': String(state.size),
      'aria-valuemin': '1',
      'aria-valuemax': '8',
    },
  });

  let dragging = false;
  let origin = 0;
  resizer.addEventListener('pointerdown', (event) => {
    dragging = true;
    origin = /** @type {PointerEvent} */ (event).clientY;
    resizer.setPointerCapture(/** @type {PointerEvent} */ (event).pointerId);
  });
  resizer.addEventListener('pointermove', (event) => {
    if (!dragging) return;
    const delta = /** @type {PointerEvent} */ (event).clientY - origin;
    if (Math.abs(delta) < 24) return;
    origin = /** @type {PointerEvent} */ (event).clientY;
    applyOperation(model, 'resize', state.id, delta > 0 ? 1 : -1);
  });
  resizer.addEventListener('pointerup', () => {
    dragging = false;
  });
  resizer.addEventListener('keydown', (event) => {
    const key = /** @type {KeyboardEvent} */ (event).key;
    if (key === 'ArrowUp' || key === 'ArrowDown') {
      event.preventDefault();
      applyOperation(model, 'resize', state.id, key === 'ArrowUp' ? 1 : -1);
    }
  });

  const root = el('section', {
    class: 'rx-panel',
    dataset: {
      panel: state.id,
      kind: state.kind,
      slot: state.slot,
      collapsed: String(state.collapsed),
      pinned: String(state.pinned),
      floating: String(state.floating),
      region: state.region ?? '',
      size: String(state.size),
    },
    attrs: { 'aria-labelledby': titleId, tabindex: '-1' },
  }, [
    el('header', { class: 'rx-panel__bar' }, [
      grip,
      el('h2', { class: 'rx-panel__title', id: titleId, text: state.title }),
      state.region
        ? el('span', { class: 'rx-chip', text: 'protected', attrs: { title: `region ${state.region} cannot be hidden (RX-23)` } })
        : null,
      collapseButton,
      menuButton,
    ]),
    el('div', { class: 'rx-panel__body', id: `panel-body-${state.id}` }, [body]),
    resizer,
    srOnly(
      `Panel operations: ${PANEL_OPERATION_IDS.map((id) => `${PANEL_OPERATIONS[id].label} (${PANEL_OPERATIONS[id].keys.join(' or ')})`).join('; ')}.`,
    ),
  ]);

  root.addEventListener('keydown', (event) => {
    const resolved = operationForKeys(keyCombination(/** @type {KeyboardEvent} */ (event)));
    if (!resolved) return;
    event.preventDefault();
    applyOperation(model, resolved.operation.id, state.id, resolved.direction);
  });

  root.addEventListener('dragover', (event) => {
    event.preventDefault();
  });
  root.addEventListener('drop', (event) => {
    event.preventDefault();
    const transfer = /** @type {DragEvent} */ (event).dataTransfer;
    const draggedId = transfer ? transfer.getData('text/plain') : '';
    if (!draggedId || draggedId === state.id) return;
    const dragged = model.panels.find((entry) => entry.id === draggedId);
    const target = model.panels.find((entry) => entry.id === state.id);
    if (!dragged || !target || dragged.slot !== target.slot) return;
    applyOperation(model, 'reorder', draggedId, dragged.order > target.order ? 1 : -1);
  });

  return root;
}

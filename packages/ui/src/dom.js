/* Element construction helpers (RX-19, RX-23).
 *
 * WHY NO `innerHTML` ANYWHERE IN THIS PACKAGE. Panel titles, check names,
 * contract ids and connector reasons all arrive from a tenant's own data or
 * from a prompt-generated UIPlan, which `packages/contracts` treats as hostile
 * input. A single `innerHTML` assignment on that path turns a label into script
 * execution, so the whole UI package builds nodes and sets `textContent`.
 * tests/web/test_client_boundary.py refuses `innerHTML`,
 * `insertAdjacentHTML`, `document.write` and `eval` in every source file.
 */

/** @typedef {string | number | Node | null | undefined} Child */

/**
 * Build an element. `props` keys are DOM properties except `dataset`, `attrs`,
 * `class` and `text`, which are handled explicitly.
 *
 * @param {string} tag
 * @param {Record<string, unknown>} [props]
 * @param {Child[]} [children]
 * @returns {HTMLElement}
 */
export function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    if (key === 'class') {
      node.className = String(value);
    } else if (key === 'text') {
      node.textContent = String(value);
    } else if (key === 'dataset') {
      for (const [dk, dv] of Object.entries(/** @type {object} */ (value))) {
        if (dv !== null && dv !== undefined) node.dataset[dk] = String(dv);
      }
    } else if (key === 'attrs') {
      for (const [ak, av] of Object.entries(/** @type {object} */ (value))) {
        if (av !== null && av !== undefined) node.setAttribute(ak, String(av));
      }
    } else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), /** @type {EventListener} */ (value));
    } else {
      // @ts-expect-error - property assignment is intentional and tag-dependent
      node[key] = value;
    }
  }
  append(node, children);
  return node;
}

/**
 * Build an SVG element. SVG needs its own namespace, so `el` cannot serve it.
 *
 * @param {string} tag
 * @param {Record<string, string>} [attrs]
 * @param {Element[]} [children]
 * @returns {SVGElement}
 */
export function svg(tag, attrs = {}, children = []) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  for (const child of children) node.appendChild(child);
  return node;
}

/**
 * @param {Node} parent
 * @param {Child[]} children
 * @returns {Node}
 */
export function append(parent, children) {
  for (const child of children) {
    if (child === null || child === undefined) continue;
    parent.appendChild(
      typeof child === 'string' || typeof child === 'number'
        ? document.createTextNode(String(child))
        : child,
    );
  }
  return parent;
}

/**
 * @param {Node} node
 * @returns {Node}
 */
export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/**
 * A screen-reader-only text node carrying meaning the visual layout implies.
 *
 * @param {string} text
 * @returns {HTMLElement}
 */
export function srOnly(text) {
  return el('span', { class: 'rx-visually-hidden', text });
}

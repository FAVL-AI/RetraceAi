/* The layout model: panel state, persistence, and the protected regions
 * (RX-21, RX-23).
 *
 * The model is deliberately separate from the DOM. Every operation is a pure
 * transition over a serialisable record, so the keyboard path, the menu path and
 * the pointer path all call the SAME function - which is the only way "every
 * drag has a keyboard and a menu equivalent" can be true rather than
 * approximately true. `panel.js` binds the three input routes; nothing in it
 * mutates layout state directly.
 *
 * `PROTECTED_REGION_IDS` mirrors `retrace_contracts.ui_plan.PROTECTED_REGION_IDS`
 * (RX-23): security context, approval controls and truthfulness labels may not
 * be hidden, collapsed, floated away or dropped by any layout, preset or
 * generated plan. The refusal is raised here, in the model, because a guard
 * that only lives in the menu rendering is bypassed by the keyboard path.
 */

/** Regions no layout, preset or generated plan may hide (RX-23). */
export const PROTECTED_REGION_IDS = Object.freeze([
  'security-context',
  'approval-controls',
  'truthfulness-labels',
]);

/** Slots the shell provides. */
export const SLOTS = Object.freeze(['left', 'centre', 'right', 'bottom']);

const MIN_SIZE = 1;
const MAX_SIZE = 8;

/** Raised when an operation would breach RX-23 or the model's invariants. */
export class LayoutRefused extends Error {
  /**
   * @param {string} code
   * @param {string} message
   */
  constructor(code, message) {
    super(message);
    this.name = 'LayoutRefused';
    this.code = code;
  }
}

/**
 * @typedef {{
 *   id: string,
 *   kind: string,
 *   title: string,
 *   slot: string,
 *   order: number,
 *   size: number,
 *   collapsed: boolean,
 *   pinned: boolean,
 *   floating: boolean,
 *   region: string | null,
 * }} PanelState
 */

/**
 * @param {Partial<PanelState> & {id: string, kind: string, title: string}} spec
 * @returns {PanelState}
 */
export function panelState(spec) {
  return {
    id: spec.id,
    kind: spec.kind,
    title: spec.title,
    slot: spec.slot ?? 'centre',
    order: spec.order ?? 0,
    size: spec.size ?? 2,
    collapsed: spec.collapsed ?? false,
    pinned: spec.pinned ?? false,
    floating: spec.floating ?? false,
    region: spec.region ?? null,
  };
}

export class LayoutModel {
  /**
   * @param {string} routeId
   * @param {PanelState[]} panels
   * @param {{storage?: Storage}} [options]
   */
  constructor(routeId, panels, options = {}) {
    this.routeId = routeId;
    this.defaults = panels.map((panel) => ({ ...panel }));
    this.panels = panels.map((panel) => ({ ...panel }));
    this.storage = options.storage;
    /** @type {((model: LayoutModel) => void)[]} */
    this.listeners = [];
  }

  /** @returns {string} */
  get storageKey() {
    return `retrace.layout.${this.routeId}`;
  }

  /**
   * @param {(model: LayoutModel) => void} listener
   * @returns {() => void}
   */
  subscribe(listener) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter((entry) => entry !== listener);
    };
  }

  /** @returns {void} */
  notify() {
    for (const listener of this.listeners) listener(this);
  }

  /**
   * @param {string} panelId
   * @returns {PanelState}
   */
  panel(panelId) {
    const found = this.panels.find((entry) => entry.id === panelId);
    if (!found) throw new LayoutRefused('UNKNOWN_PANEL', `no panel named ${panelId}`);
    return found;
  }

  /**
   * @param {PanelState} panel
   * @param {string} operation
   * @returns {void}
   */
  assertNotProtected(panel, operation) {
    if (panel.region && PROTECTED_REGION_IDS.includes(panel.region)) {
      throw new LayoutRefused(
        'PROTECTED_REGION_HIDDEN',
        `${operation} would hide the protected region "${panel.region}" (RX-23). ` +
          'Security context, approval controls and truthfulness labels stay visible.',
      );
    }
  }

  /**
   * The single entry point every input route uses.
   *
   * @param {string} operationId
   * @param {string} panelId
   * @param {number} [direction] +1 or -1
   * @returns {LayoutModel}
   */
  apply(operationId, panelId, direction = 1) {
    switch (operationId) {
      case 'reorder':
        return this.reorder(panelId, direction);
      case 'resize':
        return this.resize(panelId, direction);
      case 'collapse':
        return this.collapse(panelId);
      case 'pin':
        return this.pin(panelId);
      case 'dock':
        return this.dock(panelId);
      case 'float':
        return this.float(panelId);
      case 'restore':
        return this.restore();
      default:
        throw new LayoutRefused('UNKNOWN_OPERATION', `no layout operation named ${operationId}`);
    }
  }

  /**
   * @param {string} panelId
   * @param {number} direction
   * @returns {LayoutModel}
   */
  reorder(panelId, direction) {
    const panel = this.panel(panelId);
    const siblings = this.panels
      .filter((entry) => entry.slot === panel.slot)
      .sort((a, b) => a.order - b.order);
    const index = siblings.indexOf(panel);
    const target = index + (direction >= 0 ? -1 : 1);
    if (target < 0 || target >= siblings.length) return this;
    const other = siblings[target];
    const swap = panel.order;
    panel.order = other.order;
    other.order = swap;
    this.persist();
    this.notify();
    return this;
  }

  /**
   * @param {string} panelId
   * @param {number} direction
   * @returns {LayoutModel}
   */
  resize(panelId, direction) {
    const panel = this.panel(panelId);
    const next = panel.size + (direction >= 0 ? 1 : -1);
    panel.size = Math.min(MAX_SIZE, Math.max(MIN_SIZE, next));
    this.persist();
    this.notify();
    return this;
  }

  /**
   * @param {string} panelId
   * @returns {LayoutModel}
   */
  collapse(panelId) {
    const panel = this.panel(panelId);
    if (!panel.collapsed) this.assertNotProtected(panel, 'collapse');
    panel.collapsed = !panel.collapsed;
    this.persist();
    this.notify();
    return this;
  }

  /**
   * @param {string} panelId
   * @returns {LayoutModel}
   */
  pin(panelId) {
    const panel = this.panel(panelId);
    panel.pinned = !panel.pinned;
    this.persist();
    this.notify();
    return this;
  }

  /**
   * @param {string} panelId
   * @returns {LayoutModel}
   */
  float(panelId) {
    const panel = this.panel(panelId);
    this.assertNotProtected(panel, 'float');
    panel.floating = true;
    this.persist();
    this.notify();
    return this;
  }

  /**
   * @param {string} panelId
   * @returns {LayoutModel}
   */
  dock(panelId) {
    const panel = this.panel(panelId);
    panel.floating = false;
    this.persist();
    this.notify();
    return this;
  }

  /** @returns {LayoutModel} */
  restore() {
    this.panels = this.defaults.map((panel) => ({ ...panel }));
    this.clearPersisted();
    this.notify();
    return this;
  }

  /** @returns {{routeId: string, panels: PanelState[]}} */
  toJSON() {
    return { routeId: this.routeId, panels: this.panels.map((panel) => ({ ...panel })) };
  }

  /** @returns {boolean} whether the layout was written */
  persist() {
    const storage = this.storage;
    if (!storage) return false;
    try {
      storage.setItem(this.storageKey, JSON.stringify(this.toJSON()));
      return true;
    } catch {
      return false;
    }
  }

  /** @returns {void} */
  clearPersisted() {
    const storage = this.storage;
    if (!storage) return;
    try {
      storage.removeItem(this.storageKey);
    } catch {
      /* a preference that cannot be cleared must not break the workspace */
    }
  }

  /**
   * Re-apply a stored layout over the defaults. Unknown panel ids in storage are
   * DISCARDED rather than trusted: a stale saved layout must not resurrect a
   * panel the build no longer has, and must not be able to introduce one.
   *
   * @returns {LayoutModel}
   */
  hydrate() {
    const storage = this.storage;
    if (!storage) return this;
    let raw = null;
    try {
      raw = storage.getItem(this.storageKey);
    } catch {
      return this;
    }
    if (!raw) return this;
    let parsed = null;
    try {
      parsed = JSON.parse(raw);
    } catch {
      return this;
    }
    const saved = parsed && Array.isArray(parsed.panels) ? parsed.panels : [];
    for (const entry of saved) {
      if (!entry || typeof entry.id !== 'string') continue;
      const panel = this.panels.find((candidate) => candidate.id === entry.id);
      if (!panel) continue;
      if (SLOTS.includes(entry.slot)) panel.slot = entry.slot;
      if (Number.isFinite(entry.order)) panel.order = Number(entry.order);
      if (Number.isFinite(entry.size)) {
        panel.size = Math.min(MAX_SIZE, Math.max(MIN_SIZE, Number(entry.size)));
      }
      panel.pinned = entry.pinned === true;
      const wantsHidden = entry.collapsed === true || entry.floating === true;
      if (wantsHidden && panel.region && PROTECTED_REGION_IDS.includes(panel.region)) {
        // A saved layout is untrusted input. RX-23 is enforced on the way IN.
        panel.collapsed = false;
        panel.floating = false;
        continue;
      }
      panel.collapsed = entry.collapsed === true;
      panel.floating = entry.floating === true;
    }
    this.notify();
    return this;
  }
}

/**
 * Refuse a generated plan that hides, drops or restyles away a protected region
 * (RX-23). Mirrors the server-side gate so a plan cannot be applied in the
 * browser that the API would have rejected.
 *
 * @param {{components?: {id?: string, hidden?: boolean}[], hidden_region_ids?: string[]}} plan
 * @returns {void}
 */
export function refuseProtectedRegionHiding(plan) {
  const hidden = new Set(plan && Array.isArray(plan.hidden_region_ids) ? plan.hidden_region_ids : []);
  for (const component of (plan && plan.components) || []) {
    if (component && component.hidden === true && component.id) hidden.add(component.id);
  }
  const breached = PROTECTED_REGION_IDS.filter((region) => hidden.has(region));
  if (breached.length > 0) {
    throw new LayoutRefused(
      'PROTECTED_REGION_HIDDEN',
      `plan hides protected region(s): ${breached.join(', ')} (RX-23)`,
    );
  }
  const present = new Set();
  for (const component of (plan && plan.components) || []) {
    if (component && component.id) present.add(component.id);
  }
  if (present.size > 0) {
    const missing = PROTECTED_REGION_IDS.filter((region) => !present.has(region));
    if (missing.length === PROTECTED_REGION_IDS.length) {
      throw new LayoutRefused(
        'PROTECTED_REGION_MISSING',
        `plan omits every protected region: ${missing.join(', ')} (RX-23)`,
      );
    }
  }
}

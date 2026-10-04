/* The workspace shell: header, left nav, centre surface, right inspector,
 * bottom timeline (docs/UX.md "Workspace", RX-19, RX-20, RX-21, RX-23).
 *
 * The shell owns the layout model and nothing else owns layout state. Panels
 * are rendered from `LayoutModel.panels` on every change, so the keyboard path,
 * the menu path and the pointer path all produce the same re-render - there is
 * no second code path that only the mouse can reach.
 *
 * ENTITY IDS COME FROM THE URL, not from a guess. With no API origin and no
 * `?contract=` parameter there is nothing to load, and the panels say so with
 * the reason. The shell never invents an id to make a panel look populated.
 */

import {
  LayoutModel,
  el,
  panelState,
  renderPanel,
  restorePreferences,
  applyTheme,
  currentTheme,
  THEMES,
} from '../../../packages/ui/src/index.js';
import { renderConsole } from './console.js';
import { renderHeader } from './header.js';
import { renderInspector } from './inspector.js';
import { renderNav } from './nav.js';
import { ROUTES, route, routeFromHash } from './routes.js';
import { renderPanelBody } from './views/registry.js';

/**
 * Read entity ids from the query string. Returns empty strings when absent;
 * views then render a reason rather than content.
 *
 * @param {string} search
 * @returns {Record<string, string>}
 */
export function entityIds(search) {
  const params = new URLSearchParams(search || '');
  return {
    projectId: params.get('project') ?? '',
    contractId: params.get('contract') ?? '',
    snapshotId: params.get('snapshot') ?? '',
    runId: params.get('run') ?? '',
    proposalId: params.get('proposal') ?? '',
    bundleId: params.get('bundle') ?? '',
  };
}

/** The ids the demo fixture answers to, used only when the fixture is chosen. */
export const DEMO_IDS = Object.freeze({
  projectId: 'demo-project',
  contractId: 'demo-contract-1',
  snapshotId: 'demo-snapshot-1',
  runId: 'demo-run-1',
  proposalId: 'demo-proposal-1',
  bundleId: 'demo-bundle-1',
});

/**
 * @param {{source: any, ids: Record<string, string>, timeZone: string}} options
 * @returns {{element: HTMLElement, destroy: () => void}}
 */
export function createShell(options) {
  const { source, ids } = options;
  const timeZone = options.timeZone || 'UTC';
  restorePreferences();

  const storage = (() => {
    try {
      return window.localStorage;
    } catch {
      return undefined;
    }
  })();

  const consolePane = renderConsole();
  const centre = el('div', { class: 'rx-slot rx-slot--centre', attrs: { 'aria-label': 'Panels' } });
  const right = el('aside', { class: 'rx-slot rx-slot--right' });
  const bottom = el('div', { class: 'rx-slot rx-slot--bottom' });
  const navHost = el('div', { class: 'rx-shell__nav' });
  const headerHost = el('div', { class: 'rx-shell__header' });

  /** @type {{stop: () => void} | null} */
  let headerHandle = null;
  /** @type {LayoutModel | null} */
  let model = null;
  let currentRoute = '';

  const themeControl = el(
    'label',
    { class: 'rx-header__theme' },
    [
      el('span', { class: 'rx-chip-group__legend', text: 'Theme' }),
      el(
        'select',
        {
          class: 'rx-button',
          attrs: { 'aria-label': 'Theme' },
          onChange: (event) => applyTheme(String(event.target.value)),
        },
        THEMES.map((value) =>
          el('option', { value, text: value, selected: value === currentTheme() }),
        ),
      ),
    ],
  );

  /**
   * @param {string} kind
   * @returns {any}
   */
  function viewContext(kind) {
    return {
      source,
      kind,
      projectId: ids.projectId,
      contractId: ids.contractId,
      snapshotId: ids.snapshotId,
      runId: ids.runId,
      proposalId: ids.proposalId,
      bundleId: ids.bundleId,
      timeZone,
      onRestoreLayout: () => {
        if (model) model.restore();
      },
    };
  }

  /** @returns {void} */
  function drawPanels() {
    if (!model) return;
    const bySlot = { centre: [], right: [], bottom: [], left: [] };
    for (const panel of [...model.panels].sort((a, b) => a.order - b.order)) {
      const host = bySlot[panel.slot] ?? bySlot.centre;
      host.push(
        renderPanel({
          state: panel,
          model,
          body: panel.collapsed
            ? el('div', {})
            : renderPanelBody(panel.kind, viewContext(panel.kind)),
        }),
      );
    }
    centre.replaceChildren(...bySlot.centre);
    right.replaceChildren(
      ...bySlot.right,
      renderInspector({
        entity: ids.contractId
          ? { kind: 'ResultContract', id: ids.contractId }
          : null,
        permissions: [],
        relationships: [],
      }),
    );
    bottom.replaceChildren(...bySlot.bottom, consolePane.element);
  }

  /** @returns {void} */
  function drawRoute() {
    const routeId = routeFromHash(window.location.hash);
    if (routeId === currentRoute && model) {
      drawPanels();
      return;
    }
    currentRoute = routeId;
    const definition = route(routeId);
    model = new LayoutModel(
      routeId,
      definition.panels.map((spec) => panelState(spec)),
      { storage },
    );
    model.subscribe(() => drawPanels());
    model.hydrate();
    navHost.replaceChildren(renderNav({ current: routeId }));
    drawPanels();
  }

  /** @returns {Promise<void>} */
  async function drawHeader() {
    const session = await source.session();
    const projects = await source.projects();
    if (headerHandle) headerHandle.stop();
    const handle = renderHeader({
      source,
      projects: projects.status === 'OK' && Array.isArray(projects.data) ? projects.data : [],
      projectId: ids.projectId,
      onProject: (id) => {
        const next = new URLSearchParams(window.location.search);
        next.set('project', id);
        window.location.search = next.toString();
      },
      timeZone,
      principal:
        session.status === 'OK' && session.data
          ? String(session.data.principal)
          : 'not signed in',
      themeControl,
    });
    headerHandle = handle;
    headerHost.replaceChildren(handle.element);
  }

  const onHashChange = () => drawRoute();
  window.addEventListener('hashchange', onHashChange);

  const stream = source.openEventStream((event) => {
    consolePane.record({
      at: new Date().toISOString(),
      kind: event.type,
      detail: event.data.slice(0, 400),
    });
  });
  const connectionUnsubscribe = source.subscribeConnection((state) => {
    if (state.state === 'NEEDS_CONFIGURATION' || state.state === 'UNAVAILABLE') {
      consolePane.setUnavailable(
        state.reason ||
          'No event stream is connected, so no timeline entries exist. Nothing is being hidden.',
      );
    }
  });

  drawHeader();
  drawRoute();

  const element = el('div', { class: 'rx-shell' }, [
    headerHost,
    navHost,
    centre,
    right,
    bottom,
  ]);

  return {
    element,
    destroy: () => {
      window.removeEventListener('hashchange', onHashChange);
      if (headerHandle) headerHandle.stop();
      connectionUnsubscribe();
      stream.close();
    },
  };
}

/** Route ids, re-exported so a caller does not import two modules for one list. */
export const SHELL_ROUTES = ROUTES;

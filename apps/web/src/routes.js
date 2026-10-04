/* The thirteen routes (RX-20).
 *
 * docs/REQUIREMENTS.md RX-20 names them: workspaces, projects, sources, studio,
 * lineage, repairs, contracts, runs, evidence, wiki, connectors, calendar,
 * settings. All thirteen are here, each with the panels it renders, and the
 * acceptance condition is "each route renders; no dead nav entry" - so a route
 * with nothing to show declares a panel whose view explains what is missing
 * rather than being quietly dropped from the navigation.
 *
 * EVERY route carries the three protected regions (RX-23). They are appended by
 * `withProtectedRegions` rather than repeated by hand, so a new route cannot be
 * added without them - the kind of invariant that survives a hurried edit.
 */

import { PROTECTED_REGION_IDS } from '../../../packages/ui/src/index.js';

/**
 * @typedef {{
 *   id: string,
 *   kind: string,
 *   title: string,
 *   slot: string,
 *   order: number,
 *   size: number,
 *   region?: string,
 * }} PanelSpec
 */

/**
 * @param {PanelSpec[]} panels
 * @returns {PanelSpec[]}
 */
function withProtectedRegions(panels) {
  return [
    ...panels,
    {
      id: 'security-context',
      kind: 'security-context',
      title: 'Security context',
      slot: 'right',
      order: 0,
      size: 2,
      region: 'security-context',
    },
    {
      id: 'approval-controls',
      kind: 'approval-controls',
      title: 'Approval',
      slot: 'right',
      order: 1,
      size: 2,
      region: 'approval-controls',
    },
    {
      id: 'truthfulness-labels',
      kind: 'truthfulness-labels',
      title: 'Labels in effect',
      slot: 'bottom',
      order: 0,
      size: 2,
      region: 'truthfulness-labels',
    },
  ];
}

/** @type {readonly {id: string, title: string, note: string, panels: PanelSpec[]}[]} */
export const ROUTES = Object.freeze([
  {
    id: 'workspaces',
    title: 'Workspaces',
    note: 'Tenancy and membership',
    panels: withProtectedRegions([
      { id: 'workspaces', kind: 'workspaces', title: 'Workspaces', slot: 'centre', order: 0, size: 3 },
    ]),
  },
  {
    id: 'projects',
    title: 'Projects',
    note: 'Projects in the effective tenant',
    panels: withProtectedRegions([
      { id: 'projects', kind: 'projects', title: 'Projects', slot: 'centre', order: 0, size: 3 },
    ]),
  },
  {
    id: 'sources',
    title: 'Sources',
    note: 'Import and content-address a source',
    panels: withProtectedRegions([
      { id: 'source-import', kind: 'source-import', title: 'Source import', slot: 'centre', order: 0, size: 3 },
      { id: 'snapshot', kind: 'snapshot', title: 'Snapshot', slot: 'centre', order: 1, size: 3 },
    ]),
  },
  {
    id: 'studio',
    title: 'Studio',
    note: 'The central journey, end to end',
    panels: withProtectedRegions([
      { id: 'contract-checklist', kind: 'contract-checklist', title: 'Contract checklist', slot: 'centre', order: 0, size: 3 },
      { id: 'comparison', kind: 'comparison', title: 'Original vs candidate', slot: 'centre', order: 1, size: 3 },
      { id: 'repair-review', kind: 'repair-review', title: 'Repair review', slot: 'centre', order: 2, size: 3 },
      { id: 'run-state', kind: 'run-state', title: 'Run state', slot: 'centre', order: 3, size: 2 },
      { id: 'check-results', kind: 'check-results', title: 'Independent checks', slot: 'centre', order: 4, size: 3 },
    ]),
  },
  {
    id: 'lineage',
    title: 'Lineage',
    note: 'Observed vs proposed relationships',
    panels: withProtectedRegions([
      { id: 'lineage', kind: 'lineage', title: 'Lineage', slot: 'centre', order: 0, size: 3 },
    ]),
  },
  {
    id: 'repairs',
    title: 'Repairs',
    note: 'Proposals awaiting review',
    panels: withProtectedRegions([
      { id: 'repairs-list', kind: 'repairs-list', title: 'Proposals', slot: 'centre', order: 0, size: 2 },
      { id: 'repair-review', kind: 'repair-review', title: 'Repair review', slot: 'centre', order: 1, size: 3 },
    ]),
  },
  {
    id: 'contracts',
    title: 'Contracts',
    note: 'Declarations and their approval state',
    panels: withProtectedRegions([
      { id: 'contracts-list', kind: 'contracts-list', title: 'Contracts', slot: 'centre', order: 0, size: 2 },
      { id: 'contract-checklist', kind: 'contract-checklist', title: 'Contract checklist', slot: 'centre', order: 1, size: 3 },
    ]),
  },
  {
    id: 'runs',
    title: 'Runs',
    note: 'What processes did, separately from what was verified',
    panels: withProtectedRegions([
      { id: 'runs-list', kind: 'runs-list', title: 'Runs', slot: 'centre', order: 0, size: 2 },
      { id: 'run-state', kind: 'run-state', title: 'Run state', slot: 'centre', order: 1, size: 3 },
      { id: 'check-results', kind: 'check-results', title: 'Independent checks', slot: 'centre', order: 2, size: 3 },
    ]),
  },
  {
    id: 'evidence',
    title: 'Evidence',
    note: 'Portable bundles for handover',
    panels: withProtectedRegions([
      { id: 'evidence-inspector', kind: 'evidence-inspector', title: 'Evidence bundle', slot: 'centre', order: 0, size: 3 },
    ]),
  },
  {
    id: 'wiki',
    title: 'Wiki',
    note: 'Source-grounded pages with resolvable anchors',
    panels: withProtectedRegions([
      { id: 'wiki', kind: 'wiki', title: 'Wiki', slot: 'centre', order: 0, size: 3 },
    ]),
  },
  {
    id: 'connectors',
    title: 'Connectors',
    note: 'External systems and their configuration state',
    panels: withProtectedRegions([
      { id: 'connectors', kind: 'connectors', title: 'Connectors', slot: 'centre', order: 0, size: 3 },
    ]),
  },
  {
    id: 'calendar',
    title: 'Calendar',
    note: 'Scheduling, zones and DST',
    panels: withProtectedRegions([
      { id: 'calendar', kind: 'calendar', title: 'Calendar', slot: 'centre', order: 0, size: 3 },
    ]),
  },
  {
    id: 'settings',
    title: 'Settings',
    note: 'Theme, density, layout',
    panels: withProtectedRegions([
      { id: 'settings', kind: 'settings', title: 'Settings', slot: 'centre', order: 0, size: 3 },
    ]),
  },
]);

/** @type {readonly string[]} */
export const ROUTE_IDS = Object.freeze(ROUTES.map((route) => route.id));

/** The regions every route must carry. Re-exported so tests read one source. */
export const REQUIRED_REGIONS = PROTECTED_REGION_IDS;

/**
 * @param {string} id
 * @returns {{id: string, title: string, note: string, panels: PanelSpec[]}}
 */
export function route(id) {
  const found = ROUTES.find((entry) => entry.id === id);
  if (!found) throw new Error(`unknown route: ${id}`);
  return found;
}

/**
 * Read the route from the location hash. An unknown hash resolves to the first
 * route rather than rendering nothing.
 *
 * @param {string} hash
 * @returns {string}
 */
export function routeFromHash(hash) {
  const candidate = String(hash || '').replace(/^#\/?/, '').split('/')[0];
  return ROUTE_IDS.includes(candidate) ? candidate : 'studio';
}

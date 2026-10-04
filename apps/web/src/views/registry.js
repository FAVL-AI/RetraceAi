/* Panel-kind registry (RX-20).
 *
 * A route declares panel KINDS; this maps each kind to the factory that renders
 * it. The indirection is what makes "no dead nav entry" testable:
 * tests/web/test_shell_routes_panels.py asserts every kind named by every route
 * resolves here, and that every journey view is reachable from at least one
 * route. A typo in a route definition fails a test instead of rendering a blank
 * panel.
 */

import { checkResultsView } from './check-results.js';
import { comparisonView } from './comparison.js';
import { contractChecklistView } from './contract-checklist.js';
import { evidenceInspectorView } from './evidence-inspector.js';
import { repairReviewView } from './repair-review.js';
import { runStateView } from './run-state.js';
import { settingsView } from './settings.js';
import { snapshotView } from './snapshot.js';
import { sourceImportView } from './source-import.js';
import {
  approvalControlsView,
  securityContextView,
  truthfulnessLabelsView,
} from './protected-regions.js';
import {
  calendarView,
  connectorsView,
  contractsListView,
  lineageView,
  projectsView,
  repairsListView,
  runsListView,
  wikiView,
  workspacesView,
} from './support.js';

/** The eight journey views, in the order the central journey visits them. */
export const JOURNEY_KINDS = Object.freeze([
  'source-import',
  'snapshot',
  'contract-checklist',
  'comparison',
  'repair-review',
  'run-state',
  'check-results',
  'evidence-inspector',
]);

/** @type {Readonly<Record<string, (ctx: any) => HTMLElement>>} */
export const PANEL_VIEWS = Object.freeze({
  'source-import': sourceImportView,
  snapshot: snapshotView,
  'contract-checklist': contractChecklistView,
  comparison: comparisonView,
  'repair-review': repairReviewView,
  'run-state': runStateView,
  'check-results': checkResultsView,
  'evidence-inspector': evidenceInspectorView,
  'security-context': securityContextView,
  'approval-controls': approvalControlsView,
  'truthfulness-labels': truthfulnessLabelsView,
  workspaces: workspacesView,
  projects: projectsView,
  'contracts-list': contractsListView,
  'runs-list': runsListView,
  'repairs-list': repairsListView,
  lineage: lineageView,
  wiki: wikiView,
  connectors: connectorsView,
  calendar: calendarView,
  settings: settingsView,
});

/** @type {readonly string[]} */
export const PANEL_KINDS = Object.freeze(Object.keys(PANEL_VIEWS));

/**
 * @param {string} kind
 * @param {any} ctx
 * @returns {HTMLElement}
 */
export function renderPanelBody(kind, ctx) {
  const factory = PANEL_VIEWS[kind];
  if (!factory) throw new Error(`no view registered for panel kind: ${kind}`);
  return factory(ctx);
}

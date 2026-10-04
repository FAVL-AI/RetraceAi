/* The remaining route surfaces (RX-20, RX-24, RX-32, RX-37, RX-40, RX-59).
 *
 * RX-20 requires every one of the thirteen routes to render with no dead nav
 * entry. "Renders" does not mean "has a feature": several of these areas depend
 * on something this build has not got - a model provider, a connector
 * credential, a retrieval layer - and the honest render for those is the
 * unavailable surface WITH THE REASON, not an empty page and not a mock. Each
 * view below therefore either shows real data from the source or names exactly
 * what is missing.
 */

import { el, renderSurfaceState, renderUnavailableFeature } from '../../../../packages/ui/src/index.js';
import { asyncBody, definitions, sectionNote, table } from './common.js';

/**
 * @param {{source: any}} ctx
 * @returns {HTMLElement}
 */
export function workspacesView(ctx) {
  return el('div', {}, [
    sectionNote('Workspaces', 'A workspace scopes projects to one tenant.'),
    asyncBody(
      () => ctx.source.session(),
      (data) =>
        definitions([
          ['Effective tenant', data.tenant_label ?? data.tenant_id],
          ['Principal', data.principal],
        ]),
    ),
    renderUnavailableFeature({
      feature: 'Create or switch workspace',
      reason: 'Workspace membership is server-side and needs an authenticated session',
      requirement: 'RX-45, RX-46',
    }),
  ]);
}

/**
 * @param {{source: any}} ctx
 * @returns {HTMLElement}
 */
export function projectsView(ctx) {
  return el('div', {}, [
    sectionNote('Projects', 'Each project owns its sources, contracts, runs and evidence.'),
    asyncBody(
      () => ctx.source.projects(),
      (data) =>
        table(
          [
            { key: 'project_id', label: 'Project id', mono: true },
            { key: 'title', label: 'Title' },
          ],
          Array.isArray(data) ? data : [data],
        ),
    ),
  ]);
}

/**
 * @param {{source: any, projectId: string}} ctx
 * @returns {HTMLElement}
 */
export function contractsListView(ctx) {
  return el('div', {}, [
    sectionNote('Contracts', 'Versioned declarations. Status comes from the approval ledger.'),
    asyncBody(
      () => ctx.source.contracts(ctx.projectId),
      (data) =>
        table(
          [
            { key: 'contract_id', label: 'Contract', mono: true },
            { key: 'version', label: 'Version', numeric: true },
            { key: 'status', label: 'Status' },
            { key: 'reference_kind', label: 'Reference category' },
          ],
          Array.isArray(data) ? data : [data],
        ),
    ),
  ]);
}

/**
 * @param {{source: any, runId: string}} ctx
 * @returns {HTMLElement}
 */
export function runsListView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Runs',
      'Execution records. A run is listed by what the process did, never by a verdict.',
    ),
    asyncBody(
      () => ctx.source.run(ctx.runId),
      (data) =>
        table(
          [
            { key: 'run_id', label: 'Run', mono: true },
            { key: 'execution_status', label: 'Execution status' },
            { key: 'exit_code', label: 'Exit', numeric: true },
            { key: 'wall_clock_ms', label: 'Wall clock (ms)', numeric: true },
          ],
          Array.isArray(data) ? data : [data],
        ),
    ),
  ]);
}

/**
 * @param {{source: any}} _ctx
 * @returns {HTMLElement}
 */
export function lineageView(_ctx) {
  return el('div', {}, [
    sectionNote(
      'Lineage',
      'A graph must distinguish observed and approved relationships from proposed and inferred ' +
        'ones, and must offer a table alternative listing the identical edges (RX-24).',
    ),
    renderSurfaceState('needs-configuration', {
      title: 'Graph not built',
      reason:
        'No lineage edges are available: the retrieval and projection layer is not implemented ' +
        'in this build (THREAT_MODEL T6). Rendering an empty graph canvas would imply a graph ' +
        'with no edges, which is a different claim from having no graph.',
    }),
  ]);
}

/**
 * @param {{source: any}} _ctx
 * @returns {HTMLElement}
 */
export function wikiView(_ctx) {
  return el('div', {}, [
    sectionNote(
      'Wiki',
      'Pages must cite a resolvable source anchor - a page, line or cell at an exact source ' +
        'version. A claim with no anchor is not published (RX-37).',
    ),
    renderUnavailableFeature({
      feature: 'Source-grounded pages',
      reason:
        'No model provider is configured and no retrieval layer exists, so no page can be ' +
        'generated and no anchor can be resolved. Generated text is never promoted to primary ' +
        'evidence (RX-38)',
      requirement: 'RX-32, RX-37',
    }),
  ]);
}

/**
 * @param {{source: any}} ctx
 * @returns {HTMLElement}
 */
export function connectorsView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Connectors',
      'An absent connector reports NEEDS_CONFIGURATION. There is no simulated-success path ' +
        'anywhere in this build (RX-40).',
    ),
    asyncBody(
      () => ctx.source.connectors(),
      (data) =>
        table(
          [
            { key: 'connector_id', label: 'Connector' },
            { key: 'status', label: 'Status' },
            { key: 'reason', label: 'Reason' },
          ],
          Array.isArray(data) ? data : [data],
        ),
    ),
  ]);
}

/**
 * @param {{source: any, timeZone: string}} ctx
 * @returns {HTMLElement}
 */
export function calendarView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Calendar',
      'Scheduling must name both time zones on an invitation and resolve ambiguous local times ' +
        'explicitly rather than guessing (RX-31, RX-59).',
    ),
    definitions([
      ['Display zone', ctx.timeZone],
      ['Storage', 'UTC. Local display is a rendering, never the stored value.'],
    ]),
    renderUnavailableFeature({
      feature: 'Scheduling and ICS',
      reason:
        'No calendar connector is configured and no OAuth consent exists. Free-busy access ' +
        'would be read outside an authorised scope, so nothing is attempted',
      requirement: 'RX-59',
    }),
  ]);
}

/**
 * @param {{source: any, runId: string}} ctx
 * @returns {HTMLElement}
 */
export function repairsListView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Repairs',
      'Proposals awaiting review. A proposal is a diff; nothing here has been applied.',
    ),
    asyncBody(
      () => ctx.source.proposal(ctx.runId),
      (data) =>
        table(
          [
            { key: 'proposal_id', label: 'Proposal', mono: true },
            { key: 'target_path', label: 'Target', mono: true },
            { key: 'provider', label: 'Proposed by' },
            { key: 'injected', label: 'Injected fault' },
          ],
          Array.isArray(data) ? data : [data],
        ),
    ),
  ]);
}

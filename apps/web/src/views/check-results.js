/* Independent check results (RX-11, RX-12, RX-17, RX-18, T10 control 1).
 *
 * This is the surface the T10 review is about, so it is the surface with the
 * least room for interpretation. Two separate things are rendered:
 *
 *   1. the PER-CHECK results - each check's id, status, expected, observed,
 *      differences and units. These are statements about individual checks and
 *      carry no summary verdict;
 *   2. the OUTCOME, and only through `renderGatedOutcome`. The gate asks the
 *      source for a verifier capability record and refuses to display any
 *      outcome unless that record asserts independent recomputation (RX-18) and
 *      the methodology-delta check (RX-14). In the profile this build ships, no
 *      such record exists, so what appears here is a refusal naming the missing
 *      control - not a blank space, and not a cautious green tick.
 *
 * A unit mismatch is a FAILURE, not a conversion (RX-13), so the expected and
 * observed units are separate columns and are never reconciled in this view.
 */

import { el, renderGatedOutcome, renderSurfaceState } from '../../../../packages/ui/src/index.js';
import { asyncBody, sectionNote, table } from './common.js';

/**
 * @param {{source: any, runId: string, contractId: string, referenceKind?: string}} ctx
 * @returns {HTMLElement}
 */
export function checkResultsView(ctx) {
  const outcomeHost = el('div', {}, [
    renderSurfaceState('loading', { reason: 'Asking the source whether an outcome may be shown.' }),
  ]);

  Promise.all([ctx.source.verifierCapability(), ctx.source.checkResults(ctx.runId)]).then(
    ([capability, results]) => {
      const record = capability.status === 'OK' ? capability.data : null;
      const report = results.status === 'OK' ? results.data : null;
      outcomeHost.replaceChildren(
        renderGatedOutcome({
          outcome: report && report.outcome ? String(report.outcome) : null,
          referenceKind: ctx.referenceKind ?? null,
          verifierCapability: /** @type {any} */ (record),
          contractRef: ctx.contractId,
          contractVersion: report && report.contract_version,
        }),
        el('p', {
          text:
            capability.status === 'OK'
              ? 'A verifier capability record was returned; the gate above judged it.'
              : `No verifier capability record: ${capability.reason}`,
        }),
      );
    },
    (error) => {
      outcomeHost.replaceChildren(
        renderSurfaceState('error', { reason: `The capability request threw: ${String(error)}` }),
      );
    },
  );

  return el('div', {}, [
    sectionNote(
      'Verification',
      'Checks are recomputed from stored inputs. The outcome is shown only when the verifier ' +
        'asserts the controls that make it meaningful.',
    ),
    outcomeHost,
    el('h3', { text: 'Per-check results' }),
    asyncBody(
      () => ctx.source.checkResults(ctx.runId),
      (data) =>
        table(
          [
            { key: 'check_id', label: 'Check', mono: true },
            { key: 'status', label: 'Status' },
            { key: 'output_name', label: 'Output' },
            { key: 'expected', label: 'Expected', numeric: true, mono: true },
            { key: 'observed', label: 'Observed', numeric: true, mono: true },
            { key: 'abs_diff', label: 'Abs diff', numeric: true, mono: true },
            { key: 'rel_diff', label: 'Rel diff', numeric: true, mono: true },
            { key: 'unit_expected', label: 'Unit expected' },
            { key: 'unit_observed', label: 'Unit observed' },
            { key: 'summary', label: 'Summary' },
          ],
          Array.isArray(data) ? data : Array.isArray(data.check_results) ? data.check_results : [],
        ),
    ),
  ]);
}

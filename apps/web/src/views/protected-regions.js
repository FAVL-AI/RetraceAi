/* The three protected regions (RX-23).
 *
 * `security-context`, `approval-controls` and `truthfulness-labels` are the
 * regions no layout, preset or generated `UIPlan` may hide. They are rendered
 * as ordinary panels so they participate in the layout, and the layout model
 * refuses every operation that would hide one - which is why the refusal lives
 * in `packages/ui/src/layout.js` and not in these views.
 *
 * The truthfulness strip carries the four attributes the brief requires to be
 * always visible: the EFFECTIVE TENANT, the REFERENCE CATEGORY, the EXECUTION
 * STATUS and the VERIFICATION OUTCOME. They are four separate rows because they
 * are four separate attributes - a design that merged them into one "status"
 * would be the exact conflation docs/evidence/SPEC_RECONCILIATION_CLOSURE.md
 * section 4 warns about.
 */

import {
  el,
  renderFreshness,
  renderGatedOutcome,
  renderProvenance,
  renderSurfaceState,
  renderTruthfulnessChip,
  renderUnavailableFeature,
} from '../../../../packages/ui/src/index.js';
import { REFERENCE_KIND_LABELS, REFERENCE_KIND_NOTES } from '../api/shapes.js';
import { asyncBody, definitions } from './common.js';

/**
 * @param {{source: any}} ctx
 * @returns {HTMLElement}
 */
export function securityContextView(ctx) {
  return el('div', { dataset: { region: 'security-context' } }, [
    asyncBody(
      () => ctx.source.session(),
      (data) =>
        definitions(
          [
            ['Effective tenant', data.tenant_label ?? data.tenant_id],
            ['Tenant id', data.tenant_id],
            ['Principal', data.principal],
            ['Entitlements', Array.isArray(data.entitlements) ? data.entitlements.join(', ') : null],
            ['Data source', ctx.source.sourceName],
          ],
          { mono: ['Tenant id'] },
        ),
    ),
    el('p', {
      text:
        'Shown as reported by the source. The browser cannot establish tenancy; it displays the ' +
        'tenant the server says is in effect.',
    }),
  ]);
}

/**
 * @param {{source: any, contractId: string}} ctx
 * @returns {HTMLElement}
 */
export function approvalControlsView(ctx) {
  return el('div', { dataset: { region: 'approval-controls' } }, [
    asyncBody(
      () => ctx.source.contract(ctx.contractId),
      (contract) =>
        el('div', {}, [
          definitions([
            ['Contract', contract.contract_id],
            ['Status', contract.status],
            ['Approval reference', contract.approval_ref ?? null],
          ], { mono: ['Contract', 'Approval reference'] }),
          contract.status === 'APPROVED'
            ? el('p', { text: 'An approval record is named. Its binding is verified server-side.' })
            : renderSurfaceState('empty', {
                title: 'No approval',
                reason:
                  'Nothing may be accepted against an unapproved contract (RX-04). An approval ' +
                  'binds the candidate, the declaration, the input snapshot and the policy.',
              }),
        ]),
    ),
    renderUnavailableFeature({
      feature: 'Approve / revoke',
      reason:
        'A governed server-side action requiring an authenticated approver and a five-field ' +
        'binding. No session exists in this profile',
      requirement: 'RX-05',
    }),
  ]);
}

/**
 * The always-visible truthfulness strip.
 *
 * @param {{source: any, runId: string, contractId: string}} ctx
 * @returns {HTMLElement}
 */
export function truthfulnessLabelsView(ctx) {
  const host = el('div', { dataset: { region: 'truthfulness-labels' } });
  const rows = el('div', {});
  host.appendChild(rows);

  Promise.all([
    ctx.source.session(),
    ctx.source.contract(ctx.contractId),
    ctx.source.run(ctx.runId),
    ctx.source.checkResults(ctx.runId),
    ctx.source.verifierCapability(),
  ]).then(
    ([session, contract, run, checks, capability]) => {
      const kind = contract.status === 'OK' && contract.data ? String(contract.data.reference_kind) : null;
      const outcomeRecord = checks.status === 'OK' ? checks.data : null;
      rows.replaceChildren(
        el('div', { class: 'rx-strip' }, [
          el('div', { class: 'rx-strip__cell' }, [
            el('span', { class: 'rx-chip-group__legend', text: 'Effective tenant' }),
            el('span', {
              class: 'rx-mono',
              text:
                session.status === 'OK' && session.data
                  ? String(session.data.tenant_label ?? session.data.tenant_id)
                  : 'unknown — no session',
            }),
          ]),
          el('div', { class: 'rx-strip__cell' }, [
            el('span', { class: 'rx-chip-group__legend', text: 'Reference category' }),
            el('span', {
              text: kind
                ? `${REFERENCE_KIND_LABELS[kind] ?? kind} — ${REFERENCE_KIND_NOTES[kind] ?? ''}`
                : 'unknown — no contract loaded',
            }),
          ]),
          el('div', { class: 'rx-strip__cell' }, [
            el('span', { class: 'rx-chip-group__legend', text: 'Execution status' }),
            el('span', {
              text:
                run.status === 'OK' && run.data
                  ? String(run.data.execution_status)
                  : 'unknown — no run',
            }),
          ]),
          el('div', { class: 'rx-strip__cell' }, [
            el('span', { class: 'rx-chip-group__legend', text: 'Verification outcome' }),
            renderGatedOutcome({
              outcome: outcomeRecord && outcomeRecord.outcome ? String(outcomeRecord.outcome) : null,
              referenceKind: kind,
              verifierCapability: capability.status === 'OK' ? capability.data : null,
              contractRef: ctx.contractId,
            }),
          ]),
        ]),
        el('div', { class: 'rx-strip' }, [
          renderProvenance([...(session.provenance.length > 0 ? session.provenance : ['REAL_RECORDED'])]),
          renderFreshness(session.freshness, { asOf: session.receivedAt ?? undefined }),
        ]),
      );
    },
    (error) => {
      rows.replaceChildren(
        renderSurfaceState('error', { reason: `The strip could not load: ${String(error)}` }),
      );
    },
  );

  host.appendChild(
    el('details', {}, [
      el('summary', { text: 'What each label means' }),
      el('div', { class: 'rx-chip-group' }, [
        renderTruthfulnessChip('STALE'),
        renderTruthfulnessChip('UNAVAILABLE'),
        renderTruthfulnessChip('REPLAY'),
        renderTruthfulnessChip('DEMO'),
        renderTruthfulnessChip('beta'),
        renderTruthfulnessChip('NEEDS_CONFIGURATION'),
        renderTruthfulnessChip('SYNTHETIC'),
        renderTruthfulnessChip('injected'),
        renderTruthfulnessChip('machine-translated'),
      ]),
    ]),
  );
  return host;
}

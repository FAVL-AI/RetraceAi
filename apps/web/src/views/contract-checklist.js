/* Contract checklist (RX-03, RX-04, RX-12, RX-17).
 *
 * The contract is the declaration a reproduction attempt is judged against, so
 * this view shows the whole declaration and refuses to summarise it into a
 * score. Three things are rendered deliberately rather than incidentally:
 *
 *   - the REFERENCE CATEGORY, with the note that says what it permits. A
 *     `NO_REFERENCE` contract can never yield reproduction within contract, and
 *     a reader must be able to see that from the contract page itself;
 *   - `limitations`, in full. A contract with an empty limitations block is
 *     refused at construction; showing them collapsed would undo that;
 *   - the APPROVAL state, read from the server-set `status` and
 *     `approval_ref`. The browser never infers approval from the presence of a
 *     contract, because status is established by the approval ledger.
 */

import { el, renderTruthfulnessChip, renderUnavailableFeature } from '../../../../packages/ui/src/index.js';
import { REFERENCE_KIND_LABELS, REFERENCE_KIND_NOTES } from '../api/shapes.js';
import { asyncBody, definitions, sectionNote, table } from './common.js';

/**
 * @param {any} contract
 * @returns {HTMLElement}
 */
function approvalBlock(contract) {
  const status = String(contract.status ?? 'DRAFT');
  const ref = contract.approval_ref;
  const rows = [
    ['Contract status', status],
    ['Approval reference', ref ?? null],
  ];
  const note =
    status === 'APPROVED'
      ? 'An approval ledger record is named above. The binding is verified server-side; this ' +
        'view repeats the reference and does not re-check it.'
      : 'Not approved. No candidate repair may be accepted against this contract (RX-04).';
  return el('div', { dataset: { region: 'approval-controls' } }, [
    definitions(rows, { mono: ['Approval reference'] }),
    el('p', { text: note }),
  ]);
}

/**
 * @param {{source: any, contractId: string}} ctx
 * @returns {HTMLElement}
 */
export function contractChecklistView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Result contract',
      'The declaration, in full. Nothing here is a verdict; it is what a verdict would be ' +
        'measured against.',
    ),
    asyncBody(
      () => ctx.source.contract(ctx.contractId),
      (contract) => {
        const kind = String(contract.reference_kind ?? 'NO_REFERENCE');
        return el('div', {}, [
          definitions(
            [
              ['Contract id', contract.contract_id],
              ['Effective tenant', contract.tenant_id],
              ['Project', contract.project_id],
              ['Version', contract.version],
              ['Created by', contract.created_by],
              ['Comparison algorithm', contract.comparison && contract.comparison.algorithm],
              [
                'Population',
                contract.population
                  ? `${contract.population.expected_count} — ${contract.population.selection_rule}`
                  : null,
              ],
              ['Seed', contract.seed],
            ],
            { mono: ['Contract id', 'Seed'] },
          ),
          el('div', { class: 'rx-section-note' }, [
            el('h3', { text: 'Reference category' }),
            el('p', { text: `${REFERENCE_KIND_LABELS[kind] ?? kind} — ${REFERENCE_KIND_NOTES[kind] ?? 'unknown category'}` }),
          ]),
          approvalBlock(contract),
          el('h3', { text: 'Required checks' }),
          table(
            [{ key: 'check', label: 'Check id', mono: true }],
            (contract.required_checks ?? []).map((check) => ({ check })),
          ),
          el('h3', { text: 'Declared inputs' }),
          table(
            [
              { key: 'id', label: 'Input', mono: true },
              { key: 'role', label: 'Role' },
              { key: 'sha256', label: 'SHA-256', mono: true },
            ],
            contract.inputs ?? [],
          ),
          el('h3', { text: 'Output definitions' }),
          table(
            [
              { key: 'name', label: 'Output' },
              { key: 'kind', label: 'Kind' },
              { key: 'unit', label: 'Unit' },
              { key: 'dtype', label: 'Dtype', mono: true },
            ],
            contract.output_definitions ?? [],
          ),
          el('h3', { text: 'Declared limitations' }),
          el(
            'ul',
            {},
            (contract.limitations ?? []).map((line) => el('li', { text: String(line) })),
          ),
          el('div', { class: 'rx-chip-group' }, [
            renderTruthfulnessChip('beta', {
              detail: 'the per-check tolerance form in closure §3 is decided but not implemented',
            }),
          ]),
          renderUnavailableFeature({
            feature: 'Approve this contract',
            reason:
              'Approval is a governed server-side action binding five fields, and it requires an ' +
              'authenticated approver. No session and no API origin exist in this profile, so ' +
              'the control is absent rather than inert',
            requirement: 'RX-04, RX-05',
          }),
        ]);
      },
    ),
  ]);
}

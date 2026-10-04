/* Repair review (RX-06, RX-07, RX-56).
 *
 * What a reviewer needs is the patch, its rationale, and - the part that is easy
 * to omit - WHO OR WHAT PROPOSED IT. A deterministic script and a model are not
 * the same evidential object, and a fault placed by a fixture is not a defect
 * found in someone else's software. The proposal's `provider` and its
 * `injected` flag are therefore rendered as first-class fields, with the
 * `injected` chip when the flag is set.
 *
 * Accepting a repair is a governed server-side action requiring an approved
 * contract. It is not offered here when no API origin exists, because a button
 * that cannot do what it says is worse than no button.
 */

import { el, renderTruthfulnessChip, renderUnavailableFeature } from '../../../../packages/ui/src/index.js';
import { asyncBody, definitions, sectionNote } from './common.js';

/**
 * @param {{source: any, proposalId: string}} ctx
 * @returns {HTMLElement}
 */
export function repairReviewView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Repair proposal',
      'A patch to review, not a change that has happened. Nothing on this screen has been ' +
        'applied to any snapshot.',
    ),
    asyncBody(
      () => ctx.source.proposal(ctx.proposalId),
      (data) =>
        el('div', {}, [
          definitions(
            [
              ['Proposal id', data.proposal_id],
              ['Snapshot', data.snapshot_id],
              ['Target path', data.target_path],
              ['Candidate hash', data.candidate_hash],
              ['Proposed by', data.provider],
            ],
            { mono: ['Proposal id', 'Snapshot', 'Target path', 'Candidate hash'] },
          ),
          data.injected === true
            ? el('div', { class: 'rx-chip-group' }, [
                renderTruthfulnessChip('injected', {
                  detail: 'this fault was placed by a fixture, not found in third-party software',
                }),
              ])
            : null,
          el('h3', { text: 'Rationale' }),
          el('p', { text: String(data.rationale ?? '') }),
          el('h3', { text: 'Unified diff' }),
          el('pre', { class: 'rx-diff', text: String(data.unified_diff ?? '') }),
          renderUnavailableFeature({
            feature: 'Accept this proposal',
            reason:
              'Acceptance requires an approved contract and a server-side approval binding the ' +
              'candidate hash. Neither a session nor an API origin exists in this profile',
            requirement: 'RX-04, RX-05',
          }),
        ]),
    ),
  ]);
}

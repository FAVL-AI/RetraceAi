/* Original vs candidate, read-only (RX-06).
 *
 * A repair in RETRACE is a PROPOSAL, and a proposal is a diff against a named
 * snapshot. This view is read-only by construction - there is no editor, no
 * save, no apply - because an in-place edit would destroy the baseline the
 * comparison exists to preserve. The diff is rendered with an explicit sigil
 * per line as well as a border treatment, so an added line is distinguishable
 * without relying on colour.
 */

import { el } from '../../../../packages/ui/src/index.js';
import { asyncBody, definitions, sectionNote } from './common.js';

const SIGIL = Object.freeze({ added: '+', removed: '-', context: ' ' });

/**
 * @param {{kind: string, text: string}} line
 * @returns {HTMLElement}
 */
function diffLine(line) {
  const kind = SIGIL[line.kind] === undefined ? 'context' : line.kind;
  return el('span', { class: 'rx-diff__line', dataset: { kind } }, [
    el('span', { class: 'rx-diff__sigil', text: SIGIL[kind] }),
    el('span', { text: line.text }),
  ]);
}

/**
 * @param {{source: any, runId: string}} ctx
 * @returns {HTMLElement}
 */
export function comparisonView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Original vs candidate',
      'Read-only. The candidate is a proposed patch against the snapshot named below; the ' +
        'snapshot bytes are unchanged by anything on this screen.',
    ),
    asyncBody(
      () => ctx.source.comparison(ctx.runId),
      (data) =>
        el('div', {}, [
          definitions(
            [
              ['Snapshot', data.snapshot_id],
              ['Target path', data.target_path],
              ['Candidate hash', data.candidate_hash],
            ],
            { mono: ['Snapshot', 'Target path', 'Candidate hash'] },
          ),
          ...(data.hunks ?? []).map((hunk) =>
            el('pre', { class: 'rx-diff' }, [
              el('span', { class: 'rx-diff__line', dataset: { kind: 'header' } }, [
                el('span', { text: hunk.header }),
              ]),
              ...(hunk.lines ?? []).map(diffLine),
            ]),
          ),
        ]),
    ),
  ]);
}

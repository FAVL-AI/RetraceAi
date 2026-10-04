/* Run state (RX-08, RX-11, RX-18).
 *
 * THE DISTINCTION THIS VIEW EXISTS TO PROTECT: execution status is not
 * verification status. A process that exits 0 has told us it exited 0. This
 * panel shows only what the PROCESS did - status, exit code, wall clock, peak
 * memory, the isolation policy it ran under - and links to the check results
 * rather than summarising them.
 *
 * The notebook's own self-reported verdict is displayed as an UNTRUSTED field,
 * labelled as such, because RX-18 requires it to be ignored as evidence. It is
 * shown rather than hidden so a reviewer can see the claim the notebook made
 * and compare it with what was independently recomputed - which is exactly the
 * comparison T10 is about.
 *
 * The isolation fields are reported, not asserted: if the run executed with
 * `filesystem_confinement: NONE`, that is displayed plainly, because
 * docs/security/THREAT_MODEL.md T2 names the unconfined default a release
 * blocker and hiding it in the UI would be the same defect one layer up.
 */

import { el, renderTruthfulnessChip, renderSurfaceState } from '../../../../packages/ui/src/index.js';
import { EXECUTION_STATUSES } from '../api/shapes.js';
import { asyncBody, definitions, sectionNote } from './common.js';

/**
 * @param {{source: any, runId: string}} ctx
 * @returns {HTMLElement}
 */
export function runStateView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Execution',
      'What the process did. This is not a verification result: a run that finished is not a ' +
        'result that reproduced.',
    ),
    asyncBody(
      () => ctx.source.run(ctx.runId),
      (data) => {
        const status = String(data.execution_status ?? '');
        const known = EXECUTION_STATUSES.includes(status);
        const confinement = String(data.filesystem_confinement ?? 'unreported');
        return el('div', {}, [
          definitions(
            [
              ['Run id', data.run_id],
              ['Execution status', known ? status : `${status} (not a declared status)`],
              ['Exit code', data.exit_code],
              ['Started', data.started_at],
              ['Finished', data.finished_at],
              ['Wall clock (ms)', data.wall_clock_ms],
              ['Peak memory (bytes)', data.peak_memory_bytes],
              ['Policy digest', data.policy_digest],
              ['Filesystem confinement', confinement],
              ['Network', data.network],
            ],
            { mono: ['Run id', 'Policy digest'] },
          ),
          confinement === 'NONE'
            ? renderSurfaceState('error', {
                title: 'This run was not filesystem-confined',
                reason:
                  'The run executed with filesystem_confinement NONE. THREAT_MODEL.md T2 records ' +
                  'that an unconfined child reached every protected artefact in a measurement, ' +
                  'and names the unconfined default a release blocker for execution endpoints.',
              })
            : null,
          el('h3', { text: 'Notebook self-report' }),
          el('div', { class: 'rx-chip-group' }, [
            renderTruthfulnessChip('UNAVAILABLE', {
              detail: 'as evidence: a notebook’s own verdict is not read by the verifier',
            }),
          ]),
          definitions([['Printed by the notebook', data.notebook_self_reported]]),
          el('p', {
            text:
              'Shown for comparison only. RX-18 requires the outcome to be recomputed from ' +
              'stored inputs; whatever the notebook printed about itself carries no weight.',
          }),
        ]);
      },
    ),
  ]);
}

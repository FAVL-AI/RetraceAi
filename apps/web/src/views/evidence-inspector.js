/* Evidence bundle inspector (RX-15, RX-16, RX-54).
 *
 * The bundle is the handover artefact, so this view shows what a second
 * researcher would receive: the snapshot reference, the patch, the environment
 * manifest, the check results, the limitations and the attestation.
 *
 * TWO HONESTY REQUIREMENTS ARE VISIBLE HERE RATHER THAN IMPLIED.
 * The `limitations` block is rendered in full and never collapsed: a bundle is
 * more persuasive than a bare claim, which makes a bundle wrapped around a
 * flawed method MORE dangerous than no bundle, and the limitations are the only
 * part of it that says so. And the attestation's
 * `non_certification_statement` is rendered beside the attestation itself,
 * because an unsigned attestation establishes authorship of a statement, not
 * the truth of it - no signing key is provisioned in this build (T7).
 */

import { el, renderSurfaceState } from '../../../../packages/ui/src/index.js';
import { asyncBody, definitions, sectionNote, table } from './common.js';

/**
 * @param {{source: any, bundleId: string}} ctx
 * @returns {HTMLElement}
 */
export function evidenceInspectorView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Evidence bundle',
      'What a second researcher receives. Read it as "this ran, and conformed to this declared ' +
        'contract" - never as a certificate.',
    ),
    asyncBody(
      () => ctx.source.evidenceBundle(ctx.bundleId),
      (data) => {
        const attestation = data.attestation ?? {};
        const limitations = Array.isArray(data.limitations) ? data.limitations : [];
        return el('div', {}, [
          definitions(
            [
              ['Bundle id', data.bundle_id],
              ['Bundle version', data.bundle_version],
              ['Created', data.created_at],
              ['Created by', data.created_by],
              ['Contract hash', data.contract_hash],
              ['Snapshot ref', data.snapshot_ref && data.snapshot_ref.ref_id],
              ['Patch ref', data.patch_ref && data.patch_ref.ref_id],
              ['Conforms to', data.conforms_to],
            ],
            { mono: ['Bundle id', 'Contract hash', 'Snapshot ref', 'Patch ref'] },
          ),
          el('h3', { text: 'Environment manifest' }),
          definitions(
            [
              ['Python', data.environment_manifest && data.environment_manifest.python_version],
              ['Platform', data.environment_manifest && data.environment_manifest.platform],
              ['Policy digest', data.environment_manifest && data.environment_manifest.policy_digest],
              ['Captured', data.environment_manifest && data.environment_manifest.captured_at],
            ],
            { mono: ['Policy digest'] },
          ),
          el('h3', { text: 'Limitations' }),
          limitations.length === 0
            ? renderSurfaceState('error', {
                title: 'Empty limitations block',
                reason:
                  'A bundle must carry a non-empty limitations block (RX-15). An empty one means ' +
                  'this bundle should not have been issued.',
              })
            : el('ul', {}, limitations.map((line) => el('li', { text: String(line) }))),
          el('h3', { text: 'Attestation' }),
          definitions([
            ['Attested by', attestation.attested_by],
            ['Attested at', attestation.attested_at],
            ['Method', attestation.method],
            ['Signature', attestation.signature ? 'present' : 'none provisioned'],
            ['Signature algorithm', attestation.signature_algorithm],
          ]),
          el('p', { text: String(attestation.statement ?? '') }),
          el('p', { text: String(attestation.non_certification_statement ?? '') }),
          el('h3', { text: 'Check results carried by the bundle' }),
          table(
            [
              { key: 'check_id', label: 'Check', mono: true },
              { key: 'status', label: 'Status' },
              { key: 'summary', label: 'Summary' },
            ],
            Array.isArray(data.check_results) ? data.check_results : [],
          ),
        ]);
      },
    ),
  ]);
}

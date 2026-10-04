/* Snapshot inspector (RX-01, RX-02).
 *
 * A snapshot is the content-addressed, immutable record an analysis is judged
 * against. The manifest digest is shown first and in monospace, because it is
 * the identity of everything below it: two snapshots with the same manifest
 * digest are the same bytes, and a single changed byte changes it.
 *
 * This view does not claim the stored bytes have been re-verified. Tamper
 * evidence (RX-02) is a server-side read-back; the browser can only repeat what
 * the server reported, and says so.
 */

import { el } from '../../../../packages/ui/src/index.js';
import { asyncBody, definitions, sectionNote, table } from './common.js';

/**
 * @param {{source: any, snapshotId: string}} ctx
 * @returns {HTMLElement}
 */
export function snapshotView(ctx) {
  return el('div', {}, [
    sectionNote(
      'Snapshot',
      'Digests as reported by the source. The browser does not re-hash the bytes, so this view ' +
        'repeats an integrity claim rather than establishing one.',
    ),
    asyncBody(
      () => ctx.source.snapshot(ctx.snapshotId),
      (data) =>
        el('div', {}, [
          definitions(
            [
              ['Snapshot id', data.snapshot_id],
              ['Manifest digest', data.manifest_digest],
              ['Created', data.created_at],
              ['Files', Array.isArray(data.files) ? data.files.length : 0],
            ],
            { mono: ['Manifest digest', 'Snapshot id'] },
          ),
          table(
            [
              { key: 'path', label: 'Path', mono: true },
              { key: 'bytes_count', label: 'Bytes', numeric: true },
              { key: 'sha256', label: 'SHA-256', mono: true },
            ],
            Array.isArray(data.files) ? data.files : [],
          ),
        ]),
    ),
  ]);
}

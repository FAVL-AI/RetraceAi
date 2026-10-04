/* Source import (RX-01, RX-40, RX-41, RX-42).
 *
 * The first step of the journey: name a source, and have its bytes
 * content-addressed. The import CONTROLS are model- and connector-dependent, so
 * in a profile with no configured origin they render as unavailable with the
 * reason, never as a button that appears to work. RX-40 is the rule being
 * honoured: absence reports NEEDS_CONFIGURATION and never a simulated success.
 */

import { el, renderUnavailableFeature } from '../../../../packages/ui/src/index.js';
import { asyncBody, sectionNote, table } from './common.js';

/**
 * @param {{source: any, projectId: string}} ctx
 * @returns {HTMLElement}
 */
export function sourceImportView(ctx) {
  const configured = Boolean(ctx.source.baseUrl);
  return el('div', {}, [
    sectionNote(
      'Imported sources',
      'Every file is hashed on import and the digest is what everything downstream refers to. ' +
        'Nothing here is editable: an import is a recording, not a working copy.',
    ),
    asyncBody(
      () => ctx.source.sources(ctx.projectId),
      (data) =>
        table(
          [
            { key: 'path', label: 'Path', mono: true },
            { key: 'kind', label: 'Kind' },
            { key: 'bytes_count', label: 'Bytes', numeric: true },
            { key: 'sha256', label: 'SHA-256', mono: true },
          ],
          Array.isArray(data) ? data : [data],
        ),
    ),
    configured
      ? el('div', { class: 'rx-section-note' }, [
          el('p', {
            text:
              'Import is performed by the API. This build has never exercised that endpoint, so ' +
              'its status here is NOT_RUN rather than working.',
          }),
        ])
      : renderUnavailableFeature({
          feature: 'Import a new source',
          reason:
            'No API origin is configured, so there is nowhere to send an upload and no ' +
            'quarantine to send it to. Upload validation, decompression limits and isolated ' +
            'parsing all live server-side',
          requirement: 'RX-42',
        }),
    renderUnavailableFeature({
      feature: 'Import from a repository',
      reason:
        'No connector is installed. A connector with no credential reports ' +
        'NEEDS_CONFIGURATION rather than offering a browse dialogue that cannot list anything',
      requirement: 'RX-40, RX-41',
    }),
  ]);
}

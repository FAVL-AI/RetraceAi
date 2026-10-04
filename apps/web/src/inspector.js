/* The right-hand context inspector (RX-23, RX-24).
 *
 * docs/UX.md asks for five things about the selected entity: provenance,
 * permissions, relationships, actions, and the entity itself. The protected
 * regions (security context and approval controls) are layout PANELS in this
 * column, so they are rendered by the shell; this module adds the selection
 * block beneath them.
 *
 * RELATIONSHIPS ARE SHOWN AS A TABLE, not only as a graph. RX-24 requires a
 * table alternative listing the identical edges, and requires proposed or
 * inferred edges to be distinguishable from observed or approved ones - so the
 * edge kind is a column, in words, rather than a line style.
 */

import { el, renderSurfaceState } from '../../../packages/ui/src/index.js';
import { definitions, table } from './views/common.js';

/**
 * @param {{
 *   entity: {kind: string, id: string, digest?: string} | null,
 *   permissions: string[],
 *   relationships: {from: string, to: string, relation: string, edge_kind: string}[],
 * }} ctx
 * @returns {HTMLElement}
 */
export function renderInspector(ctx) {
  const body = ctx.entity
    ? el('div', {}, [
        definitions(
          [
            ['Kind', ctx.entity.kind],
            ['Id', ctx.entity.id],
            ['Digest', ctx.entity.digest ?? null],
          ],
          { mono: ['Id', 'Digest'] },
        ),
        el('h3', { text: 'Permissions' }),
        ctx.permissions.length > 0
          ? el('ul', {}, ctx.permissions.map((line) => el('li', { text: line })))
          : renderSurfaceState('empty', {
              title: 'No entitlements reported',
              reason: 'The session carries no entitlement list, so none is shown.',
            }),
        el('h3', { text: 'Relationships' }),
        ctx.relationships.length > 0
          ? table(
              [
                { key: 'from', label: 'From', mono: true },
                { key: 'relation', label: 'Relation' },
                { key: 'to', label: 'To', mono: true },
                { key: 'edge_kind', label: 'Edge kind' },
              ],
              ctx.relationships,
            )
          : renderSurfaceState('needs-configuration', {
              title: 'No relationship projection',
              reason:
                'Lineage edges come from a projection layer that is not implemented in this ' +
                'build. An empty graph would assert there are no relationships, which is a ' +
                'different statement from having no projection.',
            }),
      ])
    : renderSurfaceState('empty', {
        title: 'Nothing selected',
        reason: 'Select an entity in the centre panels to inspect it.',
      });

  return el('section', { class: 'rx-inspector', attrs: { 'aria-label': 'Context inspector' } }, [
    el('h2', { class: 'rx-panel__title', text: 'Inspector' }),
    body,
  ]);
}

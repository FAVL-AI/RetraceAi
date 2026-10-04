/* Shared view scaffolding (RX-25, RX-40).
 *
 * `renderEnvelope` is where the honest-labelling rules stop being a convention
 * and become the only available code path. Every view renders its content
 * through it, and it always emits, as SEPARATE elements:
 *
 *   - the DATA PROVENANCE group (recorded / synthetic / fixture / injected);
 *   - the EVENT FRESHNESS group (live / stale / replay / unavailable);
 *   - for anything other than OK, a surface state carrying the REASON.
 *
 * A view therefore cannot render content without declaring both attributes, and
 * cannot render emptiness without saying why. When the envelope is STALE the
 * content is wrapped in `renderStaleFrame`, which brands it as the last frame
 * received - the shell never keeps presenting an old frame as the current one.
 */

import {
  el,
  renderFreshness,
  renderProvenance,
  renderStaleFrame,
  renderSurfaceState,
} from '../../../../packages/ui/src/index.js';

/** Envelope status -> the surface state that represents it. */
const STATUS_STATE = Object.freeze({
  NEEDS_CONFIGURATION: 'needs-configuration',
  ERROR: 'error',
  PERMISSION_DENIED: 'permission-denied',
});

/**
 * @param {import('../api/client.js').Envelope} envelope
 * @param {(data: any) => Node} renderOk
 * @returns {HTMLElement}
 */
export function renderEnvelope(envelope, renderOk) {
  const header = el('div', { class: 'rx-attributes' }, [
    renderProvenance([...(envelope.provenance.length > 0 ? envelope.provenance : ['REAL_RECORDED'])]),
    renderFreshness(envelope.freshness, { asOf: envelope.receivedAt ?? undefined }),
  ]);

  if (envelope.status !== 'OK' && envelope.status !== 'STALE') {
    const state = STATUS_STATE[envelope.status] ?? 'error';
    return el('div', {}, [
      header,
      renderSurfaceState(state, {
        reason: envelope.reason || 'The source gave no reason, which is itself a defect.',
      }),
    ]);
  }

  if (envelope.data === null || envelope.data === undefined) {
    return el('div', {}, [
      header,
      renderSurfaceState('empty', { reason: envelope.reason || 'The source returned no record.' }),
    ]);
  }

  const content = renderOk(envelope.data);
  if (envelope.status === 'STALE' || envelope.freshness === 'STALE') {
    return el('div', {}, [header, renderStaleFrame(content, {
      value: 'STALE',
      asOf: envelope.receivedAt ?? undefined,
    })]);
  }
  return el('div', {}, [header, content]);
}

/**
 * A panel body that loads asynchronously. Renders `loading` first - the honest
 * state while a request is in flight - and replaces it with the envelope.
 *
 * @param {() => Promise<import('../api/client.js').Envelope>} load
 * @param {(data: any) => Node} renderOk
 * @returns {HTMLElement}
 */
export function asyncBody(load, renderOk) {
  const host = el('div', {}, [
    renderSurfaceState('loading', { reason: 'Waiting for the source to answer.' }),
  ]);
  load().then(
    (envelope) => {
      host.replaceChildren(renderEnvelope(envelope, renderOk));
    },
    (error) => {
      host.replaceChildren(
        renderSurfaceState('error', { reason: `The request threw: ${String(error)}` }),
      );
    },
  );
  return host;
}

/**
 * A definition list. Values are rendered as text, never as markup.
 *
 * @param {[string, string | number | null | undefined][]} rows
 * @param {{mono?: string[]}} [options]
 * @returns {HTMLElement}
 */
export function definitions(rows, options = {}) {
  const mono = new Set(options.mono ?? []);
  const nodes = [];
  for (const [label, value] of rows) {
    nodes.push(el('dt', { text: label }));
    nodes.push(
      el('dd', {
        class: mono.has(label) ? 'rx-mono' : '',
        text: value === null || value === undefined || value === '' ? '—' : String(value),
      }),
    );
  }
  return el('dl', { class: 'rx-definition' }, nodes);
}

/**
 * A table. `columns` entries may declare `numeric: true`, which applies the
 * tabular-numeral class docs/UX.md mandates for every numeric column.
 *
 * @param {{key: string, label: string, numeric?: boolean, mono?: boolean}[]} columns
 * @param {Record<string, unknown>[]} rows
 * @returns {HTMLElement}
 */
export function table(columns, rows) {
  const head = el('tr', {}, columns.map((column) =>
    el('th', { class: column.numeric ? 'rx-num' : '', text: column.label, attrs: { scope: 'col' } }),
  ));
  const body = rows.map((row) =>
    el('tr', {}, columns.map((column) => {
      const value = row[column.key];
      const classes = [column.numeric ? 'rx-num' : '', column.mono ? 'rx-mono' : '']
        .filter(Boolean)
        .join(' ');
      return el('td', {
        class: classes,
        text: value === null || value === undefined ? '—' : String(value),
      });
    })),
  );
  return el('div', { class: 'rx-table__scroll' }, [
    el('table', { class: 'rx-table' }, [el('thead', {}, [head]), el('tbody', {}, body)]),
  ]);
}

/**
 * A heading plus an explanatory line. Views use it rather than a bare heading:
 * every surface in this workspace says what it is showing and what it is not.
 *
 * @param {string} title
 * @param {string} note
 * @returns {HTMLElement}
 */
export function sectionNote(title, note) {
  return el('div', { class: 'rx-section-note' }, [
    el('h3', { text: title }),
    el('p', { text: note }),
  ]);
}

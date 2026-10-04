/* The ONE typed client. Every network call in the workspace is here.
 *
 * WHY A SINGLE MODULE. Two reasons, both practical. First, `services/api` is
 * moving in parallel with this workspace, so the integrator needs exactly one
 * file to repoint and one file to review - this one, plus the endpoint map it
 * imports. Second, a confined network surface is checkable: every other source
 * file in `apps/web` and `packages/ui` is forbidden `fetch`, `XMLHttpRequest`,
 * `WebSocket`, `EventSource` and `sendBeacon`, and
 * `tests/web/test_client_boundary.py` fails if one appears. A view that cannot
 * reach the network cannot invent a response.
 *
 * EVERY CALL RETURNS AN ENVELOPE, never a bare payload and never a throw on the
 * expected failures. The envelope carries four things the views are required to
 * display and which are deliberately four separate fields:
 *
 *   status      - OK | NEEDS_CONFIGURATION | ERROR | PERMISSION_DENIED | STALE
 *   provenance  - where the DATA came from (recorded / synthetic / fixture)
 *   freshness   - how CURRENT the frame is (live / stale / replay / none)
 *   reason      - why there is nothing, in words, whenever there is nothing
 *
 * Provenance and freshness are not merged, here or anywhere downstream: a
 * synthetic frame can be perfectly fresh and a recorded one long stale.
 *
 * NO FALLBACK, NO FIXTURE, NO RETRY-INTO-SUCCESS. With no configured origin the
 * client reports NEEDS_CONFIGURATION (RX-40). It never substitutes demo data:
 * the demo fixture is a separate source module the user must select explicitly,
 * and it labels itself.
 */

import { checkShape, serverEstablishedFieldsIn } from './shapes.js';
import { ENDPOINTS, endpointPath, resolveBaseUrl } from './endpoints.js';

/** Envelope statuses. */
export const RESULT_STATUS = Object.freeze({
  OK: 'OK',
  NEEDS_CONFIGURATION: 'NEEDS_CONFIGURATION',
  ERROR: 'ERROR',
  PERMISSION_DENIED: 'PERMISSION_DENIED',
  STALE: 'STALE',
});

/** Connection states shown in the header. */
export const CONNECTION_STATE = Object.freeze({
  NEEDS_CONFIGURATION: 'NEEDS_CONFIGURATION',
  CONNECTING: 'CONNECTING',
  OPEN: 'OPEN',
  STALE: 'STALE',
  UNAVAILABLE: 'UNAVAILABLE',
});

/** How long without an event before the stream is declared STALE (RX-25). */
export const STALE_AFTER_MS = 15_000;

/**
 * @typedef {{
 *   status: string,
 *   data: unknown,
 *   reason: string,
 *   provenance: readonly string[],
 *   freshness: string,
 *   receivedAt: string | null,
 *   shape: {ok: boolean, missing: string[], unexpected: string[]} | null,
 * }} Envelope
 */

/**
 * @param {Partial<Envelope> & {status: string}} fields
 * @returns {Envelope}
 */
function envelope(fields) {
  return {
    status: fields.status,
    data: fields.data ?? null,
    reason: fields.reason ?? '',
    provenance: fields.provenance ?? Object.freeze([]),
    freshness: fields.freshness ?? 'UNAVAILABLE',
    receivedAt: fields.receivedAt ?? null,
    shape: fields.shape ?? null,
  };
}

const NOT_CONFIGURED_REASON =
  'No API origin is configured. Set <meta name="retrace-api-base" content="https://..."> or ' +
  'pass baseUrl to createClient. Nothing was attempted and nothing is being guessed.';

/**
 * Create the client.
 *
 * @param {{
 *   baseUrl?: string | null,
 *   fetchImpl?: typeof fetch,
 *   now?: () => Date,
 *   eventSourceImpl?: typeof EventSource,
 *   staleAfterMs?: number,
 * }} [options]
 */
export function createClient(options = {}) {
  const baseUrl = resolveBaseUrl(options);
  const doFetch = options.fetchImpl ?? (typeof fetch === 'function' ? fetch : null);
  const now = options.now ?? (() => new Date());
  const staleAfterMs = options.staleAfterMs ?? STALE_AFTER_MS;

  let connection = baseUrl
    ? CONNECTION_STATE.CONNECTING
    : CONNECTION_STATE.NEEDS_CONFIGURATION;
  let lastEventAt = null;
  /** @type {((state: {state: string, lastEventAt: string | null, reason: string}) => void)[]} */
  const listeners = [];
  let connectionReason = baseUrl ? '' : NOT_CONFIGURED_REASON;

  /**
   * @param {string} next
   * @param {string} [reason]
   */
  function setConnection(next, reason = '') {
    connection = next;
    connectionReason = reason;
    const snapshot = {
      state: connection,
      lastEventAt: lastEventAt ? lastEventAt.toISOString() : null,
      reason: connectionReason,
    };
    for (const listener of listeners) listener(snapshot);
  }

  /**
   * @param {string} name endpoint name
   * @param {Record<string, string | number>} [params]
   * @param {{body?: unknown, shape?: string}} [extra]
   * @returns {Promise<Envelope>}
   */
  async function call(name, params = {}, extra = {}) {
    const endpoint = ENDPOINTS[name];
    if (!endpoint) throw new Error(`unknown endpoint: ${name}`);
    if (!baseUrl) {
      return envelope({
        status: RESULT_STATUS.NEEDS_CONFIGURATION,
        reason: NOT_CONFIGURED_REASON,
        freshness: 'UNAVAILABLE',
      });
    }
    if (!doFetch) {
      return envelope({
        status: RESULT_STATUS.NEEDS_CONFIGURATION,
        reason: 'This runtime provides no fetch implementation.',
        freshness: 'UNAVAILABLE',
      });
    }
    let url;
    try {
      url = `${baseUrl}${endpointPath(name, params)}`;
    } catch (error) {
      /* A missing path parameter is a caller error, but returning it as an
       * envelope keeps every surface on one failure path: the view renders the
       * reason instead of an exception trace. */
      return envelope({
        status: RESULT_STATUS.ERROR,
        reason: `The request could not be addressed: ${String(error)}`,
        freshness: 'UNAVAILABLE',
      });
    }
    let response;
    try {
      response = await doFetch(url, {
        method: endpoint.method,
        credentials: 'include',
        headers: Object.assign(
          { accept: 'application/json' },
          extra.body ? { 'content-type': 'application/json' } : {},
        ),
        body: extra.body ? JSON.stringify(extra.body) : undefined,
      });
    } catch (error) {
      setConnection(CONNECTION_STATE.UNAVAILABLE, String(error));
      return envelope({
        status: RESULT_STATUS.ERROR,
        reason: `${endpoint.method} ${url} did not complete: ${String(error)}`,
        freshness: 'UNAVAILABLE',
      });
    }
    const receivedAt = now().toISOString();
    if (response.status === 401 || response.status === 403) {
      return envelope({
        status: RESULT_STATUS.PERMISSION_DENIED,
        reason: `The server refused this request (HTTP ${response.status}).`,
        receivedAt,
        freshness: 'UNAVAILABLE',
      });
    }
    if (!response.ok) {
      return envelope({
        status: RESULT_STATUS.ERROR,
        reason: `The server returned HTTP ${response.status}.`,
        receivedAt,
        freshness: 'UNAVAILABLE',
      });
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      return envelope({
        status: RESULT_STATUS.ERROR,
        reason: `The response was not JSON: ${String(error)}`,
        receivedAt,
        freshness: 'UNAVAILABLE',
      });
    }
    setConnection(CONNECTION_STATE.OPEN);
    const shape = extra.shape ? checkShape(extra.shape, payload) : null;
    return envelope({
      status: RESULT_STATUS.OK,
      data: payload,
      receivedAt,
      /* A response from the configured API describes recorded material. The
       * server may still mark a particular record synthetic or injected; that
       * marking travels in the record and the views render it. */
      provenance: Object.freeze(['REAL_RECORDED']),
      freshness: connection === CONNECTION_STATE.STALE ? 'STALE' : 'LIVE',
      shape,
    });
  }

  return {
    /** A name the inspector can show, so the reader knows which source is live. */
    sourceName: 'RETRACE API',
    baseUrl,

    /** @returns {{state: string, lastEventAt: string | null, reason: string}} */
    connectionState() {
      return {
        state: connection,
        lastEventAt: lastEventAt ? lastEventAt.toISOString() : null,
        reason: connectionReason,
      };
    },

    /**
     * @param {(state: {state: string, lastEventAt: string | null, reason: string}) => void} listener
     * @returns {() => void}
     */
    subscribeConnection(listener) {
      listeners.push(listener);
      listener(this.connectionState());
      return () => {
        const index = listeners.indexOf(listener);
        if (index >= 0) listeners.splice(index, 1);
      };
    },

    session: () => call('session'),
    projects: () => call('projects'),
    /** @param {string} projectId */
    sources: (projectId) => call('sources', { projectId }),
    /** @param {string} snapshotId */
    snapshot: (snapshotId) => call('snapshot', { snapshotId }),
    /** @param {string} contractId */
    contract: (contractId) => call('contract', { contractId }, { shape: 'ResultContract' }),
    /** @param {string} projectId */
    contracts: (projectId) => call('contracts', { projectId }),
    /** @param {string} runId */
    comparison: (runId) => call('comparison', { runId }),
    /** @param {string} proposalId */
    proposal: (proposalId) => call('proposal', { proposalId }, { shape: 'RepairProposal' }),
    /** @param {string} runId */
    run: (runId) => call('run', { runId }),
    /** @param {string} runId */
    checkResults: (runId) => call('checkResults', { runId }),
    /** @param {string} bundleId */
    evidenceBundle: (bundleId) =>
      call('evidenceBundle', { bundleId }, { shape: 'EvidenceBundleManifest' }),
    verifierCapability: () => call('verifierCapability'),
    connectors: () => call('connectors'),

    /**
     * Create a contract draft. Refuses locally if the draft carries a
     * server-established field, so the request is never sent (closure §6).
     *
     * @param {string} projectId
     * @param {Record<string, unknown>} draft
     * @returns {Promise<Envelope>}
     */
    async createContractDraft(projectId, draft) {
      const offending = serverEstablishedFieldsIn(draft);
      if (offending.length > 0) {
        return envelope({
          status: RESULT_STATUS.ERROR,
          reason:
            `A draft may not carry server-established field(s): ${offending.join(', ')}. ` +
            'Tenancy comes from the session and status comes from the approval ledger.',
          freshness: 'UNAVAILABLE',
        });
      }
      const shapeCheck = checkShape('ResultContractDraft', draft);
      if (!shapeCheck.ok) {
        return envelope({
          status: RESULT_STATUS.ERROR,
          reason:
            `The draft does not match result_contract_draft.schema.json. Missing: ` +
            `${shapeCheck.missing.join(', ') || 'none'}. Not declared by the schema: ` +
            `${shapeCheck.unexpected.join(', ') || 'none'}.`,
          freshness: 'UNAVAILABLE',
          shape: shapeCheck,
        });
      }
      return call('importSource', { projectId }, { body: draft });
    },

    /**
     * Open the event stream. Declares STALE when no event arrives within the
     * declared interval; the views then brand their content as not current
     * rather than continuing to present the last frame (RX-25).
     *
     * @param {(event: {type: string, data: string}) => void} onEvent
     * @returns {{close: () => void}}
     */
    openEventStream(onEvent) {
      const Impl = options.eventSourceImpl ?? (typeof EventSource === 'function' ? EventSource : null);
      if (!baseUrl || !Impl) {
        setConnection(
          baseUrl ? CONNECTION_STATE.UNAVAILABLE : CONNECTION_STATE.NEEDS_CONFIGURATION,
          baseUrl ? 'This runtime provides no EventSource.' : NOT_CONFIGURED_REASON,
        );
        return { close: () => {} };
      }
      const source = new Impl(`${baseUrl}${endpointPath('events')}`, { withCredentials: true });
      let timer = null;
      const arm = () => {
        if (timer !== null) clearTimeout(timer);
        timer = setTimeout(() => {
          setConnection(
            CONNECTION_STATE.STALE,
            `No event for ${staleAfterMs} ms. What you see is the last frame received.`,
          );
        }, staleAfterMs);
      };
      source.addEventListener('open', () => {
        setConnection(CONNECTION_STATE.OPEN);
        arm();
      });
      source.addEventListener('message', (event) => {
        lastEventAt = now();
        setConnection(CONNECTION_STATE.OPEN);
        arm();
        onEvent({ type: 'message', data: String(/** @type {MessageEvent} */ (event).data ?? '') });
      });
      source.addEventListener('error', () => {
        setConnection(
          CONNECTION_STATE.STALE,
          'The event stream disconnected. What you see is the last frame received.',
        );
      });
      return {
        close: () => {
          if (timer !== null) clearTimeout(timer);
          source.close();
          setConnection(CONNECTION_STATE.UNAVAILABLE, 'The event stream was closed.');
        },
      };
    },
  };
}

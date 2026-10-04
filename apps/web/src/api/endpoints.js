/* The endpoint map - the one file an integrator edits to repoint the workspace.
 *
 * `services/api` is being built and tested in parallel with this workspace, so
 * these paths are declared from the journey and the contract vocabulary, NOT
 * read from that service's modules. They are a stated integration point, not a
 * discovered fact: nothing here has been exercised against a running API, and
 * `docs/evidence` carries no record that it has. The honest status of every
 * endpoint below is therefore NOT_RUN.
 *
 * Because the workspace ships with no configured origin, an unconfigured base
 * URL is a first-class state rather than an error: every call returns
 * NEEDS_CONFIGURATION with a reason (RX-40), and no view ever renders content
 * that did not come from a response.
 */

/** Nothing is configured by default. A default origin would be a guess. */
export const DEFAULT_BASE_URL = null;

/** @typedef {{method: string, path: string, note?: string}} Endpoint */

/** @type {Readonly<Record<string, Endpoint>>} */
export const ENDPOINTS = Object.freeze({
  session: Object.freeze({
    method: 'GET',
    path: '/v1/session',
    note: 'effective tenant and principal; the header security context shows exactly this',
  }),
  projects: Object.freeze({ method: 'GET', path: '/v1/projects' }),
  sources: Object.freeze({ method: 'GET', path: '/v1/projects/{projectId}/sources' }),
  importSource: Object.freeze({ method: 'POST', path: '/v1/projects/{projectId}/sources' }),
  snapshot: Object.freeze({ method: 'GET', path: '/v1/snapshots/{snapshotId}' }),
  contract: Object.freeze({ method: 'GET', path: '/v1/contracts/{contractId}' }),
  contracts: Object.freeze({ method: 'GET', path: '/v1/projects/{projectId}/contracts' }),
  comparison: Object.freeze({
    method: 'GET',
    path: '/v1/runs/{runId}/comparison',
    note: 'read-only: the workspace never edits a candidate',
  }),
  proposal: Object.freeze({ method: 'GET', path: '/v1/proposals/{proposalId}' }),
  run: Object.freeze({ method: 'GET', path: '/v1/runs/{runId}' }),
  checkResults: Object.freeze({ method: 'GET', path: '/v1/runs/{runId}/checks' }),
  evidenceBundle: Object.freeze({ method: 'GET', path: '/v1/evidence/{bundleId}' }),
  verifierCapability: Object.freeze({
    method: 'GET',
    path: '/v1/verifier/capability',
    note: 'must assert RX-18 and RX-14 before any outcome may be displayed',
  }),
  connectors: Object.freeze({ method: 'GET', path: '/v1/connectors' }),
  events: Object.freeze({ method: 'GET', path: '/v1/events' }),
});

/** @type {readonly string[]} */
export const ENDPOINT_NAMES = Object.freeze(Object.keys(ENDPOINTS));

/**
 * Build a path, substituting `{placeholder}` segments. Every value is
 * percent-encoded, and a leftover placeholder throws: a URL containing a
 * literal `{runId}` would reach the server as a real, wrong request.
 *
 * @param {string} name
 * @param {Record<string, string | number>} [params]
 * @returns {string}
 */
export function endpointPath(name, params = {}) {
  const endpoint = ENDPOINTS[name];
  if (!endpoint) throw new Error(`unknown endpoint: ${name}`);
  const path = endpoint.path.replace(/\{(\w+)\}/g, (_match, key) => {
    const value = params[key];
    if (value === undefined || value === null || value === '') {
      throw new Error(`endpoint ${name} needs the ${key} parameter`);
    }
    return encodeURIComponent(String(value));
  });
  if (path.includes('{') || path.includes('}')) {
    throw new Error(`endpoint ${name} left an unsubstituted placeholder: ${path}`);
  }
  return path;
}

/**
 * Read the configured origin. Order: an explicit option, then a
 * `<meta name="retrace-api-base">` tag, then nothing. There is deliberately no
 * localhost fallback - a workspace that quietly talks to whatever is on port
 * 8000 is how a tenant's data reaches the wrong server.
 *
 * @param {{baseUrl?: string | null, document?: Document}} [options]
 * @returns {string | null}
 */
export function resolveBaseUrl(options = {}) {
  if (options.baseUrl) return String(options.baseUrl).replace(/\/+$/, '');
  const doc = options.document ?? (typeof document === 'undefined' ? null : document);
  const meta = doc ? doc.querySelector('meta[name="retrace-api-base"]') : null;
  const content = meta ? meta.getAttribute('content') : null;
  if (content && content.trim() !== '') return content.trim().replace(/\/+$/, '');
  return DEFAULT_BASE_URL;
}

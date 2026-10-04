/* An explicitly selected, explicitly labelled fixture source (RX-25, RX-56).
 *
 * READ THIS BEFORE USING ANY VALUE BELOW. This module contains SYNTHETIC data.
 * It is not a recording of anything, it is not evidence, and it is not a
 * verification result. It exists so the workspace can be opened and operated
 * with no API, because a shell with every panel empty cannot be reviewed for
 * the thing that matters here - whether the labelling is honest when there IS
 * content on screen.
 *
 * Four properties keep it from becoming a fake success, and each is tested in
 * tests/web/test_client_boundary.py:
 *   1. it is never the default. The user must ask for it (`?data=demo`), and
 *      `main.js` otherwise constructs the HTTP client;
 *   2. every envelope it returns carries provenance DEMO_FIXTURE and SYNTHETIC,
 *      so every panel renders both chips;
 *   3. its freshness is always UNAVAILABLE. Nothing is being observed. It never
 *      claims LIVE, and there is no timer in this file to make it look busy;
 *   4. `verifierCapability()` returns NEEDS_CONFIGURATION, so the outcome gate
 *      in `packages/ui/src/outcome-gate.js` refuses to display a verification
 *      outcome. A fixture cannot talk its way past the T10 control.
 *
 * The digests are real SHA-256 values of the literal strings named in the
 * comment beside each one, so a reader can recompute them and see for
 * themselves that they describe nothing but this fixture.
 */

const PROVENANCE = Object.freeze(['DEMO_FIXTURE', 'SYNTHETIC']);

/* sha256("demo-fixture/analysis.ipynb@v1") */
const NOTEBOOK_SHA = 'c62363d790de0c4100c193dd6ff5030600ab9bd366eaff5bf20314c3dc5e54b4';
/* sha256("demo-fixture/reference_outputs.json@v1") */
const REFERENCE_SHA = 'c6210e2356697898b4cd14303f48b3a12f406f4ab727bca985efbb14917d3a3c';
/* sha256("demo-fixture/cohort.csv@v1") */
const COHORT_SHA = 'da2552615ff0d2f7a3a88aaaca8016f209e11cfedecdefe6c5bed7ee289b1de7';
/* sha256("demo-fixture/snapshot-manifest@v1") */
const MANIFEST_SHA = 'c49af7b9c5950c8495730b27879d24787a168046039cee0bb8a4b4b4f3df2620';
/* sha256("demo-fixture/candidate-analysis.ipynb@v1") */
const CANDIDATE_SHA = '10f1305c00d6372e3ba2966e7bc3e87edd559a0b353605b0c23f2c3fcbef5eb3';
/* sha256("demo-fixture/environment-policy@v1") */
const POLICY_SHA = '42241c9a150d1bb6a3d9ae9010d2b4a43fa9908607e8c5c622362af9442b8ab2';

/**
 * @param {unknown} data
 * @returns {import('./client.js').Envelope}
 */
function fixture(data) {
  return {
    status: 'OK',
    data,
    reason: 'Fixture content shipped with the build. Not a recording and not evidence.',
    provenance: PROVENANCE,
    freshness: 'UNAVAILABLE',
    receivedAt: null,
    shape: null,
  };
}

/**
 * @param {string} reason
 * @returns {import('./client.js').Envelope}
 */
function unconfigured(reason) {
  return {
    status: 'NEEDS_CONFIGURATION',
    data: null,
    reason,
    provenance: PROVENANCE,
    freshness: 'UNAVAILABLE',
    receivedAt: null,
    shape: null,
  };
}

/** The fixture contract. A NEW_TEACHING_REFERENCE, which is what a fixture is. */
export const DEMO_CONTRACT = Object.freeze({
  contract_id: 'demo-contract-1',
  tenant_id: 'demo-tenant',
  project_id: 'demo-project',
  version: 1,
  status: 'DRAFT',
  reference_kind: 'NEW_TEACHING_REFERENCE',
  inputs: Object.freeze([
    Object.freeze({ id: 'cohort.csv', sha256: COHORT_SHA, role: 'INPUT' }),
    Object.freeze({ id: 'reference_outputs.json', sha256: REFERENCE_SHA, role: 'REFERENCE' }),
  ]),
  output_definitions: Object.freeze([
    Object.freeze({ name: 'mean_response', kind: 'SCALAR', unit: 'mg/L', dtype: 'float64' }),
    Object.freeze({ name: 'cohort_table', kind: 'TABLE', unit: null, dtype: null }),
  ]),
  population: Object.freeze({ expected_count: 412, selection_rule: 'all enrolled, pre-exclusion' }),
  comparison: Object.freeze({
    algorithm: 'elementwise-abs-rel',
    tolerances: Object.freeze({
      mean_response: Object.freeze({ abs_tol: 0.01, rel_tol: 0.001 }),
    }),
  }),
  required_checks: Object.freeze(['INPUT_IDENTITY', 'SCHEMA', 'POPULATION', 'UNITS', 'NUMERIC']),
  limitations: Object.freeze([
    'Passing this contract establishes agreement with its declared checks only.',
    'It does not establish the correctness of the reference data or the methodology.',
    'This contract and its inputs are a synthetic fixture.',
  ]),
  created_by: 'demo-fixture',
  exclusions: Object.freeze([
    Object.freeze({
      rule_id: 'EX-1',
      description: 'withdrawn consent records removed before analysis',
      expression: null,
    }),
  ]),
  units: Object.freeze({ mean_response: 'mg/L' }),
  seed: 20_240_101,
  split: Object.freeze({ strategy: 'stratified', train_fraction: 0.8, seed: 20_240_101 }),
  approval_ref: null,
});

/**
 * Build the fixture source. It exposes the SAME method surface as the HTTP
 * client, so `shell.js` cannot tell them apart and therefore cannot treat
 * fixture content specially.
 *
 * @returns {ReturnType<typeof import('./client.js').createClient>}
 */
export function createDemoSource() {
  const connection = {
    state: 'UNAVAILABLE',
    lastEventAt: null,
    reason:
      'The demo fixture is static. There is no stream, so nothing is being observed and ' +
      'nothing is live.',
  };
  return /** @type {any} */ ({
    sourceName: 'Demo fixture (synthetic)',
    baseUrl: null,
    connectionState: () => connection,
    subscribeConnection(listener) {
      listener(connection);
      return () => {};
    },
    session: async () =>
      fixture({
        tenant_id: 'demo-tenant',
        tenant_label: 'Demo tenant (fixture)',
        principal: 'demo-operator',
        entitlements: ['read'],
      }),
    projects: async () =>
      fixture([{ project_id: 'demo-project', title: 'Cohort re-analysis (fixture)' }]),
    sources: async () =>
      fixture([
        {
          source_id: 'demo-source-1',
          kind: 'NOTEBOOK',
          path: 'analysis.ipynb',
          sha256: NOTEBOOK_SHA,
          bytes_count: 18_204,
        },
        {
          source_id: 'demo-source-2',
          kind: 'DATA',
          path: 'cohort.csv',
          sha256: COHORT_SHA,
          bytes_count: 96_512,
        },
      ]),
    snapshot: async () =>
      fixture({
        snapshot_id: 'demo-snapshot-1',
        manifest_digest: MANIFEST_SHA,
        created_at: '2026-01-04T09:12:00Z',
        files: [
          { path: 'analysis.ipynb', sha256: NOTEBOOK_SHA, bytes_count: 18_204 },
          { path: 'cohort.csv', sha256: COHORT_SHA, bytes_count: 96_512 },
          { path: 'reference_outputs.json', sha256: REFERENCE_SHA, bytes_count: 1_104 },
        ],
      }),
    contract: async () => fixture(DEMO_CONTRACT),
    contracts: async () => fixture([DEMO_CONTRACT]),
    comparison: async () =>
      fixture({
        snapshot_id: 'demo-snapshot-1',
        candidate_hash: CANDIDATE_SHA,
        target_path: 'analysis.ipynb',
        hunks: [
          {
            header: '@@ -42,7 +42,7 @@ def summarise(frame):',
            lines: [
              { kind: 'context', text: '    frame = frame.dropna(subset=["response"])' },
              { kind: 'removed', text: '    return frame["response"].mean()' },
              { kind: 'added', text: '    return frame["response"].astype("float64").mean()' },
              { kind: 'context', text: '' },
            ],
          },
        ],
      }),
    proposal: async () =>
      fixture({
        proposal_id: 'demo-proposal-1',
        snapshot_id: 'demo-snapshot-1',
        target_path: 'analysis.ipynb',
        unified_diff:
          '--- a/analysis.ipynb\n+++ b/analysis.ipynb\n@@ -42,7 +42,7 @@\n' +
          '-    return frame["response"].mean()\n' +
          '+    return frame["response"].astype("float64").mean()\n',
        candidate_hash: CANDIDATE_SHA,
        rationale:
          'The reference pins float64; the original relies on the pandas default dtype, which ' +
          'differs between the recorded environment and this one.',
        provider: 'deterministic-script',
        injected: false,
      }),
    run: async () =>
      fixture({
        run_id: 'demo-run-1',
        execution_status: 'SUCCEEDED',
        exit_code: 0,
        started_at: '2026-01-04T09:20:11Z',
        finished_at: '2026-01-04T09:21:46Z',
        wall_clock_ms: 95_412,
        peak_memory_bytes: 412_664_832,
        policy_digest: POLICY_SHA,
        filesystem_confinement: 'NONE',
        network: 'DENIED',
        notebook_self_reported: 'PASS',
      }),
    checkResults: async () =>
      unconfigured(
        'The fixture carries no verification report. No verifier is configured, and ' +
          'docs/security/T10_REVIEW.md forbids displaying a verification outcome until the ' +
          'verifier implements RX-18 and RX-14. A fixture outcome here would be a fabricated ' +
          'result wearing the product’s own vocabulary.',
      ),
    evidenceBundle: async () =>
      unconfigured(
        'No evidence bundle is issued in this profile: a bundle asserts an outcome, and no ' +
          'outcome may be asserted yet (T10_REVIEW controls 1 and 2).',
      ),
    verifierCapability: async () =>
      unconfigured(
        'No verifier capability record exists. The fixture cannot assert one on the ' +
          'verifier’s behalf.',
      ),
    connectors: async () =>
      fixture([
        { connector_id: 'github', status: 'NEEDS_CONFIGURATION', reason: 'no app installation' },
        { connector_id: 'slack', status: 'NEEDS_CONFIGURATION', reason: 'no workspace install' },
        { connector_id: 'calendar', status: 'NEEDS_CONFIGURATION', reason: 'no OAuth consent' },
        { connector_id: 'colab', status: 'NEEDS_CONFIGURATION', reason: 'no local bridge' },
      ]),
    createContractDraft: async () =>
      unconfigured('The fixture is read-only. Nothing can be created against it.'),
    openEventStream: () => ({ close: () => {} }),
  });
}

/* The contract shapes, mirrored for the browser (RX-03, RX-12, RX-22).
 *
 * WHY A MIRROR AND NOT AN IMPORT. `packages/contracts` is pydantic; the browser
 * cannot import it. The JSON Schemas in `specs/schemas/` are GENERATED from
 * those models and are frozen, so they are the authority this file is held
 * against: `tests/web/test_client_boundary.py` loads every schema and asserts
 * the `required` and `properties` lists below match it exactly, and compares the
 * enum vocabularies against the frozen `retrace_contracts.enums` members. A
 * field added to a contract therefore fails this file rather than silently
 * reaching a view that cannot render it.
 *
 * THE DISTINCTION THAT MATTERS MOST HERE. `ResultContractDraft` is the EXTERNAL
 * create payload and does not carry `tenant_id`, `contract_id`, `status` or
 * `approval_ref`. Those four are server-established: tenancy from the session,
 * identity from the server, status from the approval ledger. A browser that
 * could send `status: "APPROVED"` would be asking to be believed about an
 * approval, and `docs/evidence/SPEC_RECONCILIATION_CLOSURE.md` section 6 is
 * explicit that a client-supplied status establishes nothing. The draft shape
 * below cannot express those fields, so the mistake is unavailable rather than
 * merely discouraged.
 */

/** Fields a client may never send on a draft; the server establishes each. */
export const SERVER_ESTABLISHED_FIELDS = Object.freeze([
  'contract_id',
  'tenant_id',
  'status',
  'approval_ref',
]);

/**
 * Shape definitions, keyed by the generated schema file they mirror.
 * `required` and `properties` are sorted exactly as the schema sorts them.
 */
export const CONTRACT_SHAPES = Object.freeze({
  ResultContractDraft: Object.freeze({
    schema: 'result_contract_draft.schema.json',
    required: Object.freeze([
      'project_id',
      'version',
      'reference_kind',
      'inputs',
      'output_definitions',
      'population',
      'comparison',
      'required_checks',
      'limitations',
      'created_by',
    ]),
    properties: Object.freeze([
      'comparison',
      'created_by',
      'exclusions',
      'inputs',
      'limitations',
      'output_definitions',
      'population',
      'project_id',
      'reference_kind',
      'required_checks',
      'seed',
      'split',
      'units',
      'version',
    ]),
  }),
  ResultContract: Object.freeze({
    schema: 'result_contract.schema.json',
    required: Object.freeze([
      'contract_id',
      'tenant_id',
      'project_id',
      'version',
      'status',
      'reference_kind',
      'inputs',
      'output_definitions',
      'population',
      'comparison',
      'required_checks',
      'limitations',
      'created_by',
    ]),
    properties: Object.freeze([
      'approval_ref',
      'comparison',
      'contract_id',
      'created_by',
      'exclusions',
      'inputs',
      'limitations',
      'output_definitions',
      'population',
      'project_id',
      'reference_kind',
      'required_checks',
      'seed',
      'split',
      'status',
      'tenant_id',
      'units',
      'version',
    ]),
  }),
  Approval: Object.freeze({
    schema: 'approval.schema.json',
    required: Object.freeze([
      'approval_id',
      'contract_hash',
      'candidate_hash',
      'input_snapshot_id',
      'environment_policy_digest',
      'action_digest',
      'approved_by',
      'approved_at',
    ]),
    properties: Object.freeze([
      'action_digest',
      'approval_id',
      'approved_at',
      'approved_by',
      'candidate_hash',
      'contract_hash',
      'environment_policy_digest',
      'input_snapshot_id',
    ]),
  }),
  RepairProposal: Object.freeze({
    schema: 'repair_proposal.schema.json',
    required: Object.freeze([
      'proposal_id',
      'snapshot_id',
      'target_path',
      'unified_diff',
      'candidate_hash',
      'rationale',
      'provider',
    ]),
    properties: Object.freeze([
      'candidate_hash',
      'injected',
      'proposal_id',
      'provider',
      'rationale',
      'snapshot_id',
      'target_path',
      'unified_diff',
    ]),
  }),
  EvidenceBundleManifest: Object.freeze({
    schema: 'evidence_bundle_manifest.schema.json',
    required: Object.freeze([
      'bundle_id',
      'created_at',
      'created_by',
      'contract_hash',
      'snapshot_ref',
      'environment_manifest',
      'outcome',
      'limitations',
      'attestation',
    ]),
    properties: Object.freeze([
      'attestation',
      'bundle_id',
      'bundle_version',
      'check_results',
      'conforms_to',
      'contract_hash',
      'created_at',
      'created_by',
      'environment_manifest',
      'limitations',
      'logs_refs',
      'outcome',
      'patch_ref',
      'snapshot_ref',
    ]),
  }),
  UIPlan: Object.freeze({
    schema: 'ui_plan.schema.json',
    required: Object.freeze(['plan_id', 'title', 'created_by']),
    properties: Object.freeze([
      'components',
      'created_by',
      'hidden_region_ids',
      'plan_id',
      'plan_version',
      'source_prompt',
      'title',
    ]),
  }),
});

/* --- the closed vocabularies ------------------------------------------- */

/** RX-12: exactly five, and no sixth value is representable. */
export const VERIFICATION_OUTCOMES = Object.freeze([
  'REPRODUCED_WITHIN_CONTRACT',
  'EXECUTED_NOT_VERIFIED',
  'CHANGED_RESULT',
  'BLOCKED_MISSING_EVIDENCE',
  'FAILED_EXECUTION',
]);

/** RX-11: what the PROCESS did. A different type from the outcome above. */
export const EXECUTION_STATUSES = Object.freeze(['SUCCEEDED', 'FAILED', 'TIMEOUT', 'KILLED']);

/** Per-check status inside a verification report. */
export const CHECK_STATUSES = Object.freeze(['PASSED', 'FAILED', 'ERRORED', 'SKIPPED', 'BLOCKED']);

/** Contract lifecycle. Server-set from the approval ledger. */
export const CONTRACT_STATUSES = Object.freeze(['DRAFT', 'APPROVED', 'SUPERSEDED']);

/** The reference category. `NO_REFERENCE` can never reproduce within contract. */
export const REFERENCE_KINDS = Object.freeze([
  'HISTORICAL_REFERENCE',
  'NEW_TEACHING_REFERENCE',
  'NO_REFERENCE',
]);

/** Human-readable reference categories. The category is always shown. */
export const REFERENCE_KIND_LABELS = Object.freeze({
  HISTORICAL_REFERENCE: 'Historical reference',
  NEW_TEACHING_REFERENCE: 'New teaching reference',
  NO_REFERENCE: 'No reference',
});

/** What each reference category permits, shown beside it so it is not folklore. */
export const REFERENCE_KIND_NOTES = Object.freeze({
  HISTORICAL_REFERENCE: 'identified prior evidence; provenance must be resolvable and approved',
  NEW_TEACHING_REFERENCE: 'an established teaching baseline; not a published result',
  NO_REFERENCE: 'no numerical reference exists; cannot yield reproduction within contract',
});

/**
 * Structural check of a payload against a mirrored shape. This is a SHAPE check,
 * not validation: it reports missing required keys and keys the schema does not
 * declare. It cannot judge values, and says so rather than implying it does.
 *
 * @param {string} shapeName
 * @param {unknown} payload
 * @returns {{ok: boolean, missing: string[], unexpected: string[]}}
 */
export function checkShape(shapeName, payload) {
  const shape = CONTRACT_SHAPES[shapeName];
  if (!shape) throw new Error(`unknown contract shape: ${shapeName}`);
  if (payload === null || typeof payload !== 'object') {
    return { ok: false, missing: [...shape.required], unexpected: [] };
  }
  const keys = Object.keys(/** @type {object} */ (payload));
  const missing = shape.required.filter((name) => !keys.includes(name));
  const unexpected = keys.filter((name) => !shape.properties.includes(name));
  return { ok: missing.length === 0 && unexpected.length === 0, missing, unexpected };
}

/**
 * Refuse a draft that carries a server-established field (RX-04, closure §6).
 *
 * @param {Record<string, unknown>} draft
 * @returns {string[]} the offending field names, empty when the draft is clean
 */
export function serverEstablishedFieldsIn(draft) {
  const keys = draft && typeof draft === 'object' ? Object.keys(draft) : [];
  return SERVER_ESTABLISHED_FIELDS.filter((name) => keys.includes(name));
}

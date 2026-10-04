/* The RETRACE UI package surface.
 *
 * `apps/web` imports from here and never reaches into a module path directly,
 * so the package can be reorganised without touching the application. Nothing
 * in this package performs I/O: no fetch, no storage read outside `theme.js`
 * and `layout.js` (both guarded), no clock read except where a caller passes
 * the instant in.
 */

export { append, clear, el, srOnly, svg } from './dom.js';
export { ICON_PATHS, icon } from './icons.js';
export { DENSITIES, STATE_COLOUR_TOKENS, THEMED_COLOUR_TOKENS, THEMES } from './tokens.js';
export { OUTCOMES, OUTCOME_PRESENTATION, outcomeLabel, renderOutcome } from './outcome.js';
export {
  OUTCOME_REFUSAL,
  REQUIRED_VERIFIER_CONTROLS,
  outcomeDisplayDecision,
  renderGatedOutcome,
} from './outcome-gate.js';
export {
  DATA_PROVENANCE,
  PROVENANCE_ATTRIBUTE,
  PROVENANCE_LEGEND,
  PROVENANCE_VALUES,
  renderProvenance,
} from './provenance.js';
export {
  EVENT_FRESHNESS,
  FRESHNESS_ATTRIBUTE,
  FRESHNESS_LEGEND,
  FRESHNESS_VALUES,
  renderFreshness,
  renderStaleFrame,
} from './freshness.js';
export {
  TRUTHFULNESS_GLOSS,
  TRUTHFULNESS_TOKENS,
  renderChipGroup,
  renderTruthfulnessChip,
} from './truthfulness.js';
export {
  SURFACE_STATES,
  SURFACE_STATE_NAMES,
  renderSurfaceState,
  renderUnavailableFeature,
} from './states.js';
export { applyDensity, applyTheme, currentDensity, currentTheme, restorePreferences } from './theme.js';
export {
  LayoutModel,
  LayoutRefused,
  PROTECTED_REGION_IDS,
  SLOTS,
  panelState,
  refuseProtectedRegionHiding,
} from './layout.js';
export {
  DRAG_OPERATION_IDS,
  PANEL_OPERATIONS,
  PANEL_OPERATION_IDS,
  keyCombination,
  operationForKeys,
} from './panel-operations.js';
export { panelMenuItems, renderPanel } from './panel.js';
export { closeMenu, openMenu, renderMenuInto } from './menu.js';
export { announce, liveRegion } from './live.js';

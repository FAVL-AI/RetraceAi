# RETRACE AI — interface specification and design tokens

**RECONSTRUCTED.** The packaged `docs/02-UX.md` and its tokens were unavailable
(PRECHECK B1). These values are authored here as starting values and **must be adjusted
to pass real accessibility tests** — the tests are the authority, not this file.

## Identity

An original RETRACE identity. Palantir's object-and-relationship orientation is an
*architectural* reference; Apple's hierarchy and interaction consistency are *interaction*
references. **No proprietary asset, icon, typeface, brand mark or copy is reproduced, and
no affiliation is implied.**

Principles: restrained neutral surfaces; precise typography; controlled density;
semantic colour reserved for state; subtle depth; motion that can be fully disabled.
Explicitly rejected: neon dashboards, gratuitous glass, decorative gradients, animated
"activity" that is not driven by a live event.

## Tokens

Defined as CSS custom properties on `:root` (complete light palette), redefined under
`@media (prefers-color-scheme: dark)` guarded `:root:not([data-theme="light"])`, and
again under `:root[data-theme="dark"]` so an explicit toggle wins in both directions.
No colour may have its only definition inside a media or `[data-theme]` block.

### Surface and text (light / dark)

| Token | Light | Dark | Use |
|---|---|---|---|
| `--surface-canvas` | `#f7f7f5` | `#121314` | app ground |
| `--surface-panel` | `#ffffff` | `#1a1c1e` | panels, cards |
| `--surface-raised` | `#ffffff` | `#212426` | floating panel, menu |
| `--surface-sunken` | `#eeeeec` | `#0e0f10` | wells, code blocks |
| `--border-subtle` | `#e2e2de` | `#2a2d30` | panel edges |
| `--border-strong` | `#c4c4be` | `#3d4145` | focused container |
| `--text-primary` | `#16181a` | `#f0f1f2` | body |
| `--text-secondary` | `#54585c` | `#a8adb3` | labels, metadata |
| `--text-tertiary` | `#74797e` | `#82878d` | hints — **large text only** |
| `--accent` | `#2d5d8f` | `#7aa7d4` | selection, primary action |
| `--focus-ring` | `#2d5d8f` | `#9cc2e8` | 2px outline + 2px offset |

Contrast intent: `--text-primary` on `--surface-canvas` and `--surface-panel` targets
≥ 7:1; `--text-secondary` ≥ 4.5:1; `--text-tertiary` ≥ 3:1 and is permitted only at
≥ 18.66px bold / 24px regular. **These are intents; the axe/contrast test decides.**

### Verification state (semantic — never colour-only)

Every state renders as **icon + text label + colour**. Colour alone is never the carrier.

| Outcome | Token | Light | Label shown |
|---|---|---|---|
| `REPRODUCED_WITHIN_CONTRACT` | `--state-reproduced` | `#1f6b4a` | "Reproduced within contract" |
| `EXECUTED_NOT_VERIFIED` | `--state-unverified` | `#8a6a1f` | "Executed — not verified" |
| `CHANGED_RESULT` | `--state-changed` | `#9c4221` | "Changed result" |
| `BLOCKED_MISSING_EVIDENCE` | `--state-blocked` | `#5a4b8a` | "Blocked — missing evidence" |
| `FAILED_EXECUTION` | `--state-failed` | `#8c2f39` | "Failed execution" |

### Truthfulness labels (RX-25) — must never be hidden or restyled away

`STALE`, `UNAVAILABLE`, `REPLAY`, `DEMO`, `beta`, `NEEDS_CONFIGURATION`,
`SYNTHETIC`, `injected`, `machine-translated`. Rendered as a bordered chip with
`--text-primary` on `--surface-panel`; never as colour-only, never animated.

### Typography / space / depth / motion

Type scale (1.2 ratio): 12, 13, 14, 16, 19, 23, 28px. Body 14px. UI font: system
stack. Tabular numerals mandatory for every numeric column, digest and tolerance.
Monospace for digests, diffs, code, identifiers — **never** translated or
reflowed (RX-29).

Space: 4px base — 4, 8, 12, 16, 24, 32, 48. Density `comfortable` = row 40px;
`compact` = row 30px; both must keep a ≥ 24×24px pointer target.

Radii: 4px controls, 6px panels, 2px chips. Elevation: 3 levels only, via a
single-direction soft shadow; no inner glow.

Motion: 120ms (state), 180ms (panel), 240ms (overlay), ease-out. **Everything inside
`@media (prefers-reduced-motion: reduce)` collapses to 0ms.** No looping or idle
animation anywhere — an animation implies live activity and must be driven by a real event.

## Workspace

Header: project selector · prompt bar · connection state · world clock · user.
Left: navigation (13 routes). Centre: configurable panel surface. Right: context
inspector (selected entity, provenance, permissions, relationships, actions).
Bottom: timeline · execution console · checks · warnings · task status.

Panels: drag, resize, dock, float, collapse, pin, reorder, restore; freeform and
snapped; saved presets; undo/redo; shareable views. **Every drag operation must also
have a keyboard path and a menu/click path** (RX-21) — WCAG's non-drag pointer
requirement and keyboard operability are separate obligations and both apply.

Protected regions that no layout, preset or generated `UIPlan` may hide (RX-23):
`security-context`, `approval-controls`, `truthfulness-labels`.

## Required states for every data surface

empty · loading · error · offline · stale · replay · partial · permission-denied ·
needs-configuration. A surface with no `stale`/`offline` treatment is incomplete:
a disconnected stream must say so rather than keep showing the last frame as current.

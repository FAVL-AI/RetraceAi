/* Settings: theme, density, layout (RX-19, RX-21).
 *
 * These are the controls that actually work with no API, so they are also the
 * ones that must not overstate themselves. `applyTheme` and `applyDensity`
 * report whether the preference was PERSISTED, and this view shows that: in a
 * private window, or with site data blocked, `localStorage` throws and the
 * choice applies for this session only. Claiming "saved" when the write failed
 * is a small lie that costs the user their next session.
 */

import {
  applyDensity,
  applyTheme,
  currentDensity,
  currentTheme,
  el,
  DENSITIES,
  THEMES,
} from '../../../../packages/ui/src/index.js';
import { definitions, sectionNote } from './common.js';

/**
 * @param {{
 *   name: string,
 *   legend: string,
 *   values: readonly string[],
 *   current: string,
 *   onChoose: (value: string) => boolean,
 *   note: HTMLElement,
 * }} spec
 * @returns {HTMLElement}
 */
function choiceGroup(spec) {
  const options = spec.values.map((value) =>
    el('label', { class: 'rx-choice' }, [
      el('input', {
        type: 'radio',
        name: spec.name,
        value,
        checked: value === spec.current,
        onChange: () => {
          const persisted = spec.onChoose(value);
          spec.note.textContent = persisted
            ? `Saved: ${value}.`
            : `Applied for this session only: ${value}. The preference could not be written to ` +
              'browser storage, so it will not survive a reload.';
        },
      }),
      el('span', { text: value }),
    ]),
  );
  return el('fieldset', { class: 'rx-fieldset' }, [
    el('legend', { text: spec.legend }),
    ...options,
    spec.note,
  ]);
}

/**
 * @param {{onRestoreLayout?: () => void}} [ctx]
 * @returns {HTMLElement}
 */
export function settingsView(ctx = {}) {
  const themeNote = el('p', { class: 'rx-surface-state__reason', text: '' });
  const densityNote = el('p', { class: 'rx-surface-state__reason', text: '' });
  return el('div', {}, [
    sectionNote(
      'Appearance',
      'Three themes. "system" writes no attribute, so the operating-system preference decides; ' +
        'light and dark are explicit and win over it in both directions.',
    ),
    choiceGroup({
      name: 'rx-theme',
      legend: 'Theme',
      values: THEMES,
      current: currentTheme(),
      onChoose: (value) => applyTheme(value).persisted,
      note: themeNote,
    }),
    choiceGroup({
      name: 'rx-density',
      legend: 'Density',
      values: DENSITIES,
      current: currentDensity(),
      onChoose: (value) => applyDensity(value).persisted,
      note: densityNote,
    }),
    sectionNote(
      'Layout',
      'Panel positions, sizes, collapse and pin state are saved per route. A saved layout is ' +
        'treated as untrusted input on the way back in: it can never hide a protected region.',
    ),
    el('button', {
      type: 'button',
      class: 'rx-button',
      text: 'Restore the default layout for this route',
      onClick: () => {
        if (ctx.onRestoreLayout) ctx.onRestoreLayout();
      },
    }),
    sectionNote('Reduced motion', 'Honoured from the operating system, with no override here.'),
    definitions([
      ['Motion', 'All transitions collapse to 0ms under prefers-reduced-motion: reduce.'],
      ['Idle animation', 'None. An animation would imply activity that may not be observed.'],
    ]),
  ]);
}

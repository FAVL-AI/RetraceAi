/* Theme and density, both persisted (RX-19).
 *
 * Three theme values: `light`, `dark`, `system`. `system` writes NO attribute,
 * which is what makes the media-query form in tokens.css authoritative; the
 * other two write `data-theme`, which is what makes an explicit choice win over
 * the system preference in both directions.
 *
 * Storage is wrapped in try/catch because `localStorage` throws, not returns,
 * in a private window or with site data blocked. A preference that cannot be
 * saved must still apply for this session - losing the whole workspace because
 * a preference could not be written would be the wrong failure.
 */

import { DENSITIES, THEMES } from './tokens.js';

const THEME_KEY = 'retrace.theme';
const DENSITY_KEY = 'retrace.density';

/**
 * @param {string} key
 * @returns {string | null}
 */
function readStored(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

/**
 * @param {string} key
 * @param {string} value
 * @returns {boolean} whether the value was persisted
 */
function writeStored(key, value) {
  try {
    window.localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

/** @returns {string} */
export function currentTheme() {
  const stored = readStored(THEME_KEY);
  return stored && THEMES.includes(stored) ? stored : 'system';
}

/** @returns {string} */
export function currentDensity() {
  const stored = readStored(DENSITY_KEY);
  return stored && DENSITIES.includes(stored) ? stored : 'comfortable';
}

/**
 * @param {string} theme
 * @param {{root?: HTMLElement}} [options]
 * @returns {{theme: string, persisted: boolean}}
 */
export function applyTheme(theme, options = {}) {
  if (!THEMES.includes(theme)) throw new Error(`unknown theme: ${theme}`);
  const root = options.root ?? document.documentElement;
  if (theme === 'system') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', theme);
  }
  return { theme, persisted: writeStored(THEME_KEY, theme) };
}

/**
 * @param {string} density
 * @param {{root?: HTMLElement}} [options]
 * @returns {{density: string, persisted: boolean}}
 */
export function applyDensity(density, options = {}) {
  if (!DENSITIES.includes(density)) throw new Error(`unknown density: ${density}`);
  const root = options.root ?? document.documentElement;
  root.setAttribute('data-density', density);
  return { density, persisted: writeStored(DENSITY_KEY, density) };
}

/**
 * Apply whatever was stored. Called once at start-up.
 *
 * @param {{root?: HTMLElement}} [options]
 * @returns {{theme: string, density: string}}
 */
export function restorePreferences(options = {}) {
  const theme = currentTheme();
  const density = currentDensity();
  applyTheme(theme, options);
  applyDensity(density, options);
  return { theme, density };
}

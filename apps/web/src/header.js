/* The workspace header (RX-19, RX-22, RX-25, RX-31).
 *
 * Five things, in the order docs/UX.md lists them: project selector, prompt bar,
 * connection state, world clock, user.
 *
 * THE CONNECTION INDICATOR IS NOT DECORATION. It is the surface that tells the
 * reader whether anything they are looking at is current, so it renders the
 * transport state as text plus the matching truthfulness chip, and never as a
 * coloured dot alone. When the stream drops it says STALE and names the last
 * event time; it does not fade a dot from green to amber and leave the panels
 * looking live.
 *
 * THE PROMPT BAR IS PRESENT AND UNAVAILABLE. Prompt-generated layout needs a
 * model provider, and a generated plan must be validated against the component
 * allowlist, previewed, and then applied reversibly (RX-22). No provider is
 * configured in this build, so the input is disabled and carries the reason. A
 * prompt box that accepted text and did nothing would be the worst of the
 * available options.
 *
 * THE WORLD CLOCK updates once a second by writing text. That is driven by time
 * passing, which is a real event; it is not an animation, and there is no
 * looping animation anywhere in this workspace.
 */

import { el, renderTruthfulnessChip, renderUnavailableFeature, srOnly } from '../../../packages/ui/src/index.js';

/** Connection state -> the truthfulness token that describes it, if any. */
const CONNECTION_TOKEN = Object.freeze({
  NEEDS_CONFIGURATION: 'NEEDS_CONFIGURATION',
  CONNECTING: null,
  OPEN: null,
  STALE: 'STALE',
  UNAVAILABLE: 'UNAVAILABLE',
});

/** Plain-language text for each connection state. */
const CONNECTION_TEXT = Object.freeze({
  NEEDS_CONFIGURATION: 'No API origin configured',
  CONNECTING: 'Connecting',
  OPEN: 'Connected',
  STALE: 'Disconnected — showing the last frame received',
  UNAVAILABLE: 'No stream',
});

/**
 * @param {{timeZone: string, now?: () => Date}} options
 * @returns {{element: HTMLElement, stop: () => void}}
 */
export function worldClock(options) {
  const now = options.now ?? (() => new Date());
  const utc = el('span', { class: 'rx-mono' });
  const local = el('span', { class: 'rx-mono' });
  const element = el('div', { class: 'rx-header__clock', attrs: { role: 'group', 'aria-label': 'World clock' } }, [
    el('span', { class: 'rx-chip-group__legend', text: 'UTC' }),
    utc,
    el('span', { class: 'rx-chip-group__legend', text: options.timeZone }),
    local,
  ]);
  const tick = () => {
    const instant = now();
    utc.textContent = instant.toISOString().slice(11, 19);
    try {
      local.textContent = new Intl.DateTimeFormat(undefined, {
        timeZone: options.timeZone,
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }).format(instant);
    } catch {
      local.textContent = 'zone unavailable';
    }
  };
  tick();
  const timer = setInterval(tick, 1000);
  return { element, stop: () => clearInterval(timer) };
}

/**
 * @param {{
 *   source: any,
 *   projects: {project_id: string, title: string}[],
 *   projectId: string,
 *   onProject: (id: string) => void,
 *   timeZone: string,
 *   principal: string,
 *   themeControl: HTMLElement,
 * }} ctx
 * @returns {{element: HTMLElement, stop: () => void}}
 */
export function renderHeader(ctx) {
  const connection = el('div', { class: 'rx-header__connection', attrs: { role: 'status', 'aria-live': 'polite' } });
  const unsubscribe = ctx.source.subscribeConnection((state) => {
    const token = CONNECTION_TOKEN[state.state] ?? null;
    connection.replaceChildren(
      el('span', { class: 'rx-chip-group__legend', text: 'Connection' }),
      el('span', { text: CONNECTION_TEXT[state.state] ?? state.state }),
      ...(token ? [renderTruthfulnessChip(token)] : []),
      ...(state.lastEventAt
        ? [el('span', { class: 'rx-mono rx-chip__gloss', text: `last event ${state.lastEventAt}` })]
        : []),
      ...(state.reason ? [el('span', { class: 'rx-chip__gloss', text: state.reason })] : []),
    );
  });

  const selector = el(
    'select',
    {
      class: 'rx-button',
      attrs: { 'aria-label': 'Project' },
      onChange: (event) => ctx.onProject(String(event.target.value)),
    },
    ctx.projects.length > 0
      ? ctx.projects.map((project) =>
          el('option', {
            value: project.project_id,
            text: project.title || project.project_id,
            selected: project.project_id === ctx.projectId,
          }),
        )
      : [el('option', { value: '', text: 'No project available' })],
  );

  const clock = worldClock({ timeZone: ctx.timeZone });

  const element = el('header', { class: 'rx-header', attrs: { 'aria-label': 'Workspace header' } }, [
    el('div', { class: 'rx-header__brand' }, [
      el('span', { class: 'rx-header__mark', text: 'RETRACE' }),
      srOnly('RETRACE AI workspace'),
    ]),
    el('div', { class: 'rx-header__project' }, [
      el('span', { class: 'rx-chip-group__legend', text: 'Project' }),
      selector,
    ]),
    el('div', { class: 'rx-header__prompt' }, [
      renderUnavailableFeature({
        feature: 'Prompt bar',
        reason:
          'Prompt-generated layout needs a model provider, and a generated plan must be ' +
          'validated against the component allowlist and previewed before it is applied. No ' +
          'provider is configured, so no plan can be produced and none is simulated',
        requirement: 'RX-22, RX-32',
      }),
    ]),
    connection,
    clock.element,
    el('div', { class: 'rx-header__user' }, [
      el('span', { class: 'rx-chip-group__legend', text: 'Signed in as' }),
      el('span', { class: 'rx-mono', text: ctx.principal }),
    ]),
    ctx.themeControl,
  ]);

  return {
    element,
    stop: () => {
      clock.stop();
      unsubscribe();
    },
  };
}

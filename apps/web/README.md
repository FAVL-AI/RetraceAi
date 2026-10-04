# RETRACE AI browser workspace

Standards-based ES modules and CSS custom properties, loaded directly by the
browser. **No bundler, no framework, no npm dependency** — nothing is installed
and nothing needs to be.

## Running it

ES modules cannot be loaded over `file://` (the browser applies CORS to module
requests), so serve the repository root over HTTP and open the page from there:

```
python3 -m http.server 8080        # from the repository root
# then open http://localhost:8080/apps/web/index.html
```

The stylesheets and the UI package are referenced by relative path from the
repository root, so serving any other directory will not resolve them.

## What you will see, and why

With **no API origin configured** — the shipped default — every panel reports
`NEEDS_CONFIGURATION` and names what is missing. That is the honest state of
this build, not an unfinished view: there is no fallback to fixture data, and
the client never substitutes content it did not receive.

To see the surfaces populated, select the fixture explicitly:

```
http://localhost:8080/apps/web/index.html?data=demo
```

The fixture is labelled `DEMO` and `SYNTHETIC` on every panel and carries an
undismissable banner. It cannot produce a verification outcome: its
`verifierCapability()` reports `NEEDS_CONFIGURATION`, and the outcome gate
refuses to display an outcome without that record.

Useful parameters: `?project=`, `?contract=`, `?snapshot=`, `?run=`,
`?proposal=`, `?bundle=` select the entities to load; `?tz=Europe/Amsterdam`
pins the second clock zone.

## Connecting it to the API

Two files, and only two:

* `src/api/endpoints.js` — the path map. Paths were declared from the journey
  and the frozen contract vocabulary, **not** read from `services/api`, which
  was being changed in parallel. Nothing here has been exercised against a
  running server: the status of every endpoint is `NOT_RUN`.
* `src/api/client.js` — the only module in the workspace that performs a network
  call. `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource` and `sendBeacon`
  appear nowhere else, and `tests/web/test_client_boundary.py` fails if they do.

Set the origin with `<meta name="retrace-api-base" content="…">` in
`index.html`, or pass `baseUrl` to `createClient`. There is deliberately no
localhost default.

## The parts that are load-bearing rather than decorative

* **`packages/ui/tokens/tokens.css`** — the complete light palette on bare
  `:root`, dark redefined under a `prefers-color-scheme` media query guarded by
  `:root:not([data-theme="light"])`, and again under `:root[data-theme="dark"]`.
  No colour has its only definition inside a media or `[data-theme]` block.
* **`packages/ui/src/outcome.js`** — the only module that may turn a
  `VerificationOutcome` into readable text. `REPRODUCED_WITHIN_CONTRACT` always
  renders as "Reproduced within contract", never shortened and never a bare tick
  (`docs/security/T10_REVIEW.md` control 1).
* **`packages/ui/src/outcome-gate.js`** — refuses to display ANY outcome until a
  verifier capability record asserts RX-18 and RX-14. In this build no such
  record exists, so the five badges are not reachable from the running
  application. That is the specified behaviour.
* **`packages/ui/src/provenance.js` and `src/freshness.js`** — two separate
  attributes, two vocabularies, two chip groups. Data provenance (recorded /
  synthetic) is never merged with event freshness (live / stale / replay).
* **`packages/ui/src/panel-operations.js`** — every operation declares its
  keyboard combinations AND its menu availability, as separate fields, because
  WCAG 2.1.1 and 2.5.7 are separate obligations.

## What is not here

* **No browser test runs.** No headless driver, no axe, no npm package is
  installed and none may be. `tests/web/` parses and lints these sources, checks
  structure and token usage, and syntax-checks every module with the system
  `node`. It cannot click anything, cannot compute a rendered contrast ratio and
  cannot prove the keyboard path actually moves a panel on screen.
* **No localisation wiring.** `packages/i18n` holds 36 catalogues; this
  workspace renders English source strings and does not yet read them. The
  `machine-translated` and `beta` chips exist and are rendered where they apply,
  but no translation pass runs here.
* **No lineage graph.** The projection layer does not exist, so the route says
  so rather than drawing an empty canvas.

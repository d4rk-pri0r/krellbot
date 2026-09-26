# Dashboard

`krellbot ui` binds a tiny dashboard to `127.0.0.1` on a random (or
user-chosen) port and prints a one-shot URL like:

```
Dashboard running at http://127.0.0.1:53182/264a3861588691fc018fb24d303ce081530fc2593be9fb2b2781992930ab4d42/
```

The 64-hex-char path is a 32-byte token from `secrets.token_hex(32)`. The
same token becomes the `krellbot_session` cookie on the first GET. There
is no DNS, no public bind, no remote call: the only thing the dashboard
talks to is the disk under `$KRELLBOT_HOME`.

```sh
krellbot ui             # random port, prints URL, no browser launch
krellbot ui --port 8080 # fixed port (still loopback)
krellbot ui --open      # random port + open the URL in your default browser
```

`Ctrl-C` stops the server and returns 0.

## What the server does

The server is a `ThreadingHTTPServer` from the standard library, bound to
`127.0.0.1` only. There is no host argument that can widen it. A request
with a `Host` header other than `127.0.0.1:<port>` or `localhost:<port>`
is rejected with `403 Forbidden` and sets no cookie.

The first page is `/{token}/`. That response sets two cookies:

* `krellbot_session` — the gate token. `HttpOnly; SameSite=Strict; Path=/`.
* `krellbot_csrf`    — a CSRF token. `HttpOnly; SameSite=Strict; Path=/`.

Both cookies are issued on the first good GET. They are not `Secure`
because the page is served over plain HTTP on the loopback address. The
session cookie's value matches the URL token; that match is checked with
`hmac.compare_digest`. A request whose path token does not match the
server's token is `403` and sets no cookie.

POSTs require:

1. The `krellbot_session` cookie to equal the URL token.
2. The `Origin` header to be `http://127.0.0.1:<port>` or
   `http://localhost:<port>`.
3. A `csrf` form field whose value matches the `krellbot_csrf` cookie.

Any of those three failing is `403` and changes no state.

## Where the dashboard talks

The dashboard reads only from disk under `$KRELLBOT_HOME`. It does
**not** call Kraken, Coinbase, or `krellbot.dev` at any point. The
gate token is the URL the CLI prints and the matching
`krellbot_session` cookie; it is never written to disk and never
sent over the network.

## Views

The dashboard reads only from disk under `$KRELLBOT_HOME`:

* Armed packs — `config.json`, with mode, cap, version, pending version,
  resting stop, and owned qty.
* Paper state — `run/paper-<venue>.json`, with balances and resting
  stops.
* Journal tail — `journal/*.jsonl`, the most-recent 20 records.
* License cache — `catalog/license-cache.json`, or `missing`.
* Receipts — file listing of `receipts/`.

No call to Kraken, Coinbase, or krellbot.dev happens at any point.

The dashboard also surfaces a read-only **Local status** card at the
top of the page: the detected keychain backend, the bind address
(`127.0.0.1`), and a one-line "live arm from the UI is refused" rail.
The status block is the dashboard's expression of the same trust
snapshot the wizard shows on `/<token>/security`; both are computed
server-side from `trust_snapshot()` and never include raw credentials.

## Actions

* **Arm paper** — submits `pack_path`, `venue`, `paper_balance`, and
  `mode=paper`. Live arm from the page is `403`; the typed confirmation
  for live is a CLI-only path.
* **Disarm** — submits `venue` + `pair`; removes the armed record.
* **Stop all** — disarms every armed pack and, for each paper pack that
  still owns quantity, sells that qty at the last fill (or the resting stop)
  minus the paper fee and slippage. It does not sell coins the pack does not
  own, and it does not invent a price. `GET /` is 403. The gate token is only
  in the URL the CLI prints.
* **Adopt pending** — moves `pending_version` into `pack_version`. Refused
  while the pack still owns quantity.

Every action submits to a relative URL (`arm`, `disarm`, `stop_all`,
`adopt`) and the server reads the form body itself. There is no external
HTTP, no JSON-only path, no third-party CDN, and no Google font.

## First-run wizard

A fresh install renders the wizard at `/<token>/welcome` instead of the
dashboard. The wizard has three steps: Welcome, Security, Next. Each
step is a plain HTML page with sibling-relative `<a>` links, so a
browser with JavaScript disabled can still navigate the wizard by
following the links. A visible `<ol class="stepper">` shows the user
where they are; the active step is `aria-current="step"` and the
active nav link is `aria-current="page"`. The body carries
`data-route="welcome|security|next"` so the JS hydrator can set
highlights without rewriting hrefs.

* **Welcome** states three truthful things: the engine is free and
  open-source, exchange keys stay on this machine, and official packs
  are optional and recommended. The page exposes only sibling-relative
  `<a href="security">` / `<a href="next">` links — there is **no
  Continue button** that posts a preference. Step 1 of 3.
* **Security** shows the local trust posture (keychain backend name,
  resolved data home, home mode, bind address, live-arm rail, key
  permissions) plus a fail-closed **aggregate** diagnostic. The
  diagnostic is computed from BOTH the backend and the home mode: a
  persistent keychain on a 0o755 home, or a 0o700 home with no
  persistent keychain, is still fail-closed. The diagnostic names
  `krellbot doctor` as the next CLI action — a null backend or a
  permissive mode is never reported as a green check. The
  "Key permissions" line is a REQUIREMENT statement ("Trade-only
  permission required, withdraw permission never granted. No
  exchange key is probed from this page."), not a validated
  connection.
* **Next** lists exchange connection (slice C) and pack adoption
  (slice D) as **future slices**, not as completed steps. The free
  path today is the CLI (`krellbot ui`) and `krellbot doctor`. Step
  3 of 3 carries an explicit **Enter dashboard** button that POSTs
  to `/<token>/enter-dashboard` through the existing
  token/session/CSRF/Origin gate; the server responds 303 to
  `/<token>/dashboard` (PRG). Until that POST happens, the
  preference is untouched.

The dashboard itself is unchanged for users who reach it directly or
who revisit `/<token>/`. A "Resume setup" link in the header returns
to `/<token>/welcome` for users who want to revisit the wizard.

Browser back/forward and wizard Back do not mutate trading state. A
direct GET to `/<token>/dashboard` does not mark the preference:
the dashboard is the explicit goal of the wizard, not a side effect
of visiting the home URL. Reaching the dashboard for the first time
through Next's Enter dashboard button records a single
`ui-preferences.json` flag (mode `0600`) inside `$KRELLBOT_HOME`. That
flag records that the user **entered** the dashboard; it does not
claim onboarding is complete.

## Static assets

`src/krellbot/ui/static/` contains only relative references: `index.html`
loads `static/style.css` and `static/app.js`. The HTML, CSS, and JS files
contain no `http://`, no `https://`, and no protocol-relative `//` URLs.
The wizard templates in `src/krellbot/ui/server.py` likewise never
emit an external URL — `out/docs` and `out/source` are server-internal
302 redirects to fixed allowlisted targets. The repository enforces
this with `rg -n "https?://" src/krellbot/ui/static`, which must come
back empty.

Visual contract:

* Canvas `#07090d`, ink `#e7f4f8`, single primary interactive accent
  `#5ce1ff`. Lime `#C6FF3D` is a status token only, not a second CTA
  palette.
* `color-scheme: dark` declared on `:root` so the browser does not
  flash a light theme before the stylesheet loads.
* `:focus-visible` is a 2px cyan outline with 3px offset; the rule is
  present on every interactive element.
* `@media (prefers-reduced-motion: reduce)` collapses animations and
  transitions to `.01ms` so motion-sensitive users get a still UI.
* Tabular figures and a monospace stack render numeric columns so
  prices, qty, and cap align under each other.

## Tests

`tests/test_ui_server.py` covers the seven contract points in one shot:
foreign host header rejection, CSRF enforcement, loopback bind, no
external URLs in static, stop-all disarming, live-arm refusal, and
adopt-while-long refusal. Every test starts a `DashboardServer` on a
thread with `port=0`, reads the bound port back, talks to it over
`http.client`, and tears the server down in `finally`. No sleep-to-poll.

`tests/test_ui_first_run.py` covers the first-run visit preference
(`has_visited_dashboard`, `mark_visited_dashboard`), the trust snapshot
(`trust_snapshot`), and the B2/B3 wizard route contracts: each
`/welcome`, `/security`, `/next`, `/dashboard` route is exercised
against the real `DashboardServer` with the trust snapshot rendered
server-side and no external URL leaks.

`tests/test_ui_static.py` covers the local-asset contract: shipped
HTML/CSS/JS contains no `http://`, `https://`, or protocol-relative
URLs; CSS declares `prefers-reduced-motion` and `:focus-visible`; the
dashboard's existing paper-action forms keep their field names and
hidden CSRF; the visible markup on `/<token>/security` contains the
actual backend path and home (no JS-only hydration as the no-JS
fallback); the no-JS route fallback exposes every wizard route as a
plain `<a href>`.

## Threat model

* The bind address is fixed at `127.0.0.1`. The OS will not deliver a
  packet to it from another host.
* The gate token is 32 bytes from `secrets.token_hex(32)`. Brute-forcing
  the URL is `2**256` of work, and `hmac.compare_digest` makes timing
  oracles useless.
* The `Host` header check rejects requests that name a different host,
  even with the right port, so a DNS rebinding attacker cannot trick a
  browser into sending a request to a hostile origin and reading the
  response.
* The CSRF check on POSTs stops a malicious site from submitting forms
  to the dashboard when the user's browser has a session cookie, because
  the malicious site cannot set the matching `krellbot_csrf` cookie on
  the loopback origin.
* Live arm from the page is forbidden by construction. The CLI's typed
  `LIVE` confirmation stays the only path to a live-armed pack.
* `krellbot doctor --json` reports `install_ready` and `trading_ready`.
  `trading_ready` only goes true when an exchange key was probed with
  `trade=True` AND `withdraw=False`. The dashboard cannot bypass this
  check; live arm POSTs are 403 before any state change.
* Static assets never reach outside the loopback. The wizard templates
  embed `window.__KB_VIEW__` as an inline `<script>`; every value is
  escaped by `_embed_json` so a journal string or trust value with
  `<` cannot close the script tag. The dashboard view includes the
  same trust snapshot, but only the values from `trust_snapshot()` —
  no raw secrets, no credentials, no API keys.

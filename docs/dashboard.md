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

```
krellbot ui             # random port, prints URL
krellbot ui --port 8080 # fixed port (still loopback)
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

## Static assets

`src/krellbot/ui/static/` contains only relative references: `index.html`
loads `static/style.css` and `static/app.js`. The HTML, CSS, and JS files
contain no `http://`, no `https://`, and no protocol-relative `//` URLs.
The repository enforces this with `rg -n "https?://" src/krellbot/ui/static`,
which must come back empty.

## Tests

`tests/test_ui_server.py` covers the seven contract points in one shot:
foreign host header rejection, CSRF enforcement, loopback bind, no
external URLs in static, stop-all disarming, live-arm refusal, and
adopt-while-long refusal. Every test starts a `DashboardServer` on a
thread with `port=0`, reads the bound port back, talks to it over
`http.client`, and tears the server down in `finally`. No sleep-to-poll.

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

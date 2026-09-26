"""Dashboard UI server: stdlib `http.server`, loopback only, token-gated.

The server binds to `127.0.0.1` (no host argument can widen it) on a port
that is either user-supplied or random (`0`). A 32-byte hex token gates
access. The first page is `/{token}/`, which sets the session and CSRF
cookies and renders the dashboard. POSTs are CSRF-protected via the
`krellbot_csrf` cookie + form field plus an `Origin` check.

Reads only from local disk under `$KRELLBOT_HOME`. No call to Kraken,
Coinbase, or krellbot.dev.

Views (read-only):

    * armed packs: mode, cap, version, pending update, owned qty, resting stop
    * paper positions and resting stops: `$KRELLBOT_HOME/run/paper-<venue>.json`
    * journal tail: `$KRELLBOT_HOME/journal/*.jsonl`
    * license cache: `$KRELLBOT_HOME/catalog/license-cache.json`
    * receipts: `$KRELLBOT_HOME/receipts/` listing

Actions:

    * arm    : paper only. Live arm from the page is 403.
    * disarm : one pack by venue + pair.
    * stop_all: disarm every armed pack and, for each paper pack that owns
                qty, flatten it. Does not call `cmd_stop`.
    * adopt  : move `pending_version` into `pack_version`. Refused while the
               pack still owns qty.
"""

from __future__ import annotations

import hmac
import http.server
import json
import secrets
import threading
import urllib.parse
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from krellbot import config as kb_config
from krellbot import journal as kb_journal
from krellbot import license as kb_license
from krellbot import paths as kb_paths

from . import first_run
from . import trust

# ---- constants -----------------------------------------------------------

_BIND_HOST = "127.0.0.1"  # The only bind address. No override.
_TOKEN_BYTES = 32  # 32 bytes -> 64 hex chars
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Fixed user-initiated exits. These are the ONLY external URLs the server
# ever links to; the browser initiates the navigation and the server never
# fetches them. Anything else under /out/* is 404 with no Location header.
_EXITS: dict[str, str] = {
    "out/docs": "https://krellbot.dev/docs/",
    "out/source": "https://github.com/d4rk-pri0r/krellbot",
}

# Content-Security-Policy. `unsafe-inline` is permitted only because the
# HTML currently inlines a JSON bootstrap script; tightening (nonce or JSON
# script from a `/__kb_view__` endpoint) is B3's job, not B2's.
_CSP = (
    "default-src 'none'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self'; "
    "img-src 'self'; "
    "form-action 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'"
)

# Security headers applied to every HTML and redirect response from this
# server. The dashboard is loopback-only and the wizard does not cache.
_HTML_SECURITY_HEADERS = (
    ("Content-Security-Policy", _CSP),
    ("Referrer-Policy", "no-referrer"),
    ("X-Content-Type-Options", "nosniff"),
    ("Cache-Control", "no-store"),
)

# Wizard route names. Each maps to a server-rendered shell that embeds
# a small `__KB_VIEW__` JSON bootstrap (escaped via `_embed_json`).
_WIZARD_ROUTES = frozenset({"welcome", "security", "next"})


# ---- helpers -------------------------------------------------------------


def _constant_time_eq(a: str, b: str) -> bool:
    """Compare two strings with constant-time equality. Empty vs empty is False
    so callers can distinguish 'no cookie' from 'wrong cookie'."""
    if not a or not b:
        return False
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def _allowed_hosts(port: int) -> frozenset[str]:
    return frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})


def _allowed_origins(port: int) -> frozenset[str]:
    return frozenset({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})


def _parse_cookies(header: str) -> dict[str, str]:
    """Return a name->value map of every cookie in a Cookie request header."""
    out: dict[str, str] = {}
    if not header:
        return out
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if name:
            out[name] = value.strip()
    return out


def _session_cookie(token: str, port: int) -> str:
    return f"krellbot_session={token}; Path=/; HttpOnly; SameSite=Strict"


def _csrf_cookie(csrf: str, port: int) -> str:
    return f"krellbot_csrf={csrf}; Path=/; HttpOnly; SameSite=Strict"


def _content_type_for(name: str) -> str:
    if name.endswith(".html"):
        return "text/html; charset=utf-8"
    if name.endswith(".css"):
        return "text/css; charset=utf-8"
    if name.endswith(".js"):
        return "application/javascript; charset=utf-8"
    if name.endswith(".json"):
        return "application/json; charset=utf-8"
    if name.endswith(".svg"):
        return "image/svg+xml"
    return "application/octet-stream"


# ---- view layer ----------------------------------------------------------


def _read_paper_state(home: Path, venue: str) -> dict:
    """Read the paper venue's state file, or return a blank state."""
    path = Path(home) / "run" / f"paper-{venue}.json"
    if not path.is_file():
        return {"venue": venue, "balances": {}, "open_orders": [], "recent_fills": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"venue": venue, "balances": {}, "open_orders": [], "recent_fills": []}


def _read_receipts(home: Path) -> list[dict]:
    """Return a brief listing of files under $KRELLBOT_HOME/receipts/."""
    receipts_dir = Path(home) / "receipts"
    if not receipts_dir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(receipts_dir.iterdir()):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        out.append({"name": path.name, "size": stat.st_size})
    return out


def _read_journal_tail(home: Path, n: int = 20) -> list[dict]:
    """Return the most-recent `n` tick records across all journal files."""
    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return []
    lines: list[str] = []
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip():
                lines.append(line)
    records: list[dict] = []
    for line in lines[-n:]:
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        records.append(rec)
    return records


def _view_snapshot(home: Path) -> dict:
    """Build the dashboard view: armed packs, paper state, license, journal."""
    home = Path(home)
    config = kb_config.load_config(home)
    armed_view: list[dict] = []
    seen_venues: set[str] = set()
    for a in config.armed:
        seen_venues.add(a.venue)
        armed_view.append(
            {
                "pack_id": a.pack_id,
                "pack_version": a.pack_version,
                "pending_version": a.pending_version,
                "venue": a.venue,
                "pair": a.pair,
                "cap": str(a.cap),
                "stop": str(a.stop),
                "mode": a.mode,
                "owned_qty": str(a.owned_qty),
                "requires_license": a.requires_license,
            }
        )
    paper_by_venue: dict[str, dict] = {}
    for venue in sorted(seen_venues):
        paper_by_venue[venue] = _read_paper_state(home, venue)
    license_cache = kb_license.read_cache(home)
    # Embed the trust snapshot too so the dashboard's status grid can
    # show the actual backend name. The snapshot is presentation-only;
    # no secrets are read.
    snap = trust.trust_snapshot(home)
    return {
        "armed": armed_view,
        "paper": paper_by_venue,
        "license": license_cache,
        "journal_tail": _read_journal_tail(home),
        "receipts": _read_receipts(home),
        "trust": snap,
    }


def _render_dashboard(home: Path, csrf: str) -> bytes:
    """Render the dashboard HTML, embedding the view as JSON and the CSRF field."""
    view = _view_snapshot(home)
    payload = _embed_json(view)
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        return b"<!doctype html><title>krellbot</title><p>Static assets missing.</p>"
    template = index.read_text(encoding="utf-8")
    rendered = template.replace("__VIEW_JSON__", payload)
    rendered = rendered.replace('name="csrf"', f'name="csrf" value="{csrf}"')
    return rendered.encode("utf-8")


def _render_welcome(home: Path, csrf: str) -> bytes:
    """Render the wizard Welcome shell.

    The view embedded here is the trust snapshot (no raw credentials)
    plus the routes the wizard exposes. The browser submits the
    visit-dashboard POST via a hidden form.

    B3: the three truthful statements and the Continue affordance are
    rendered server-side so the no-JS path is honest. JS may add a
    Progress affordance / nav highlighting but is not required to see
    the truth.
    """
    snap = trust.trust_snapshot(home)
    view = {
        "view": "wizard.welcome",
        "trust": snap,
        "home_mode": snap.get("home_mode"),
        "next_routes": ["welcome", "security", "next", "dashboard"],
        "exits": {"docs": "https://krellbot.dev/docs/", "source": "https://github.com/d4rk-pri0r/krellbot"},
    }
    payload = _embed_json(view)
    body = _WELCOME_TEMPLATE
    body = body.replace("__VIEW_JSON__", payload)
    body = body.replace('name="csrf"', f'name="csrf" value="{csrf}"')
    return body.encode("utf-8")


def _render_security(home: Path, csrf: str) -> bytes:
    """Render the wizard Security shell — trust posture, no secrets.

    B3: the trust posture is rendered **server-side** into the
    ``<dl id="trust-list">`` so a no-JS user sees the actual backend
    name, home path, permission rails, and fail-closed diagnostic.
    The bootstrap JSON (window.__KB_VIEW__) carries the same data
    for JS-driven enhancement (Progress highlights, etc.) but is
    never the only path.

    B3 round 1: the diagnostic is computed from the AGGREGATE posture
    (backend + home mode) rather than just the backend. A 0o755 home
    with a persistent keychain is still fail-closed — we never show an
    "all green" banner when one row is failing. The diagnostic names
    ``krellbot doctor`` as the next CLI action.
    """
    snap = trust.trust_snapshot(home)
    backend = str(snap.get("keychain_backend") or "(unknown)")
    home_str = str(snap.get("home") or "(unset)")
    home_mode = str(snap.get("home_mode") or "unknown on this OS")
    posture_ok = bool(snap.get("posture_ok"))
    posture_warning = str(snap.get("posture_warning") or "")
    body = _SECURITY_TEMPLATE
    body = body.replace("__BACKEND__", _h(backend))
    body = body.replace("__HOME__", _h(home_str))
    body = body.replace("__HOME_MODE__", _h(home_mode))
    if posture_ok:
        diag_class = "trust-ok"
        diag_text = "All posture checks passed."
        body = body.replace("__DIAGNOSTIC__", _h(diag_text))
        body = body.replace("__DIAGNOSTIC_CLASS__", diag_class)
        body = body.replace("__DIAGNOSTIC_HIDDEN__", "")
    else:
        diag_class = "trust-fail"
        # Always name `krellbot doctor` as the next CLI action; surface
        # the aggregate warning verbatim.
        diag_text = (
            f"{posture_warning} Run `krellbot doctor` for a real "
            "diagnostic."
        )
        body = body.replace("__DIAGNOSTIC__", _h(diag_text))
        body = body.replace("__DIAGNOSTIC_CLASS__", diag_class)
        # Fail-closed: the diagnostic is visible by default.
        body = body.replace("__DIAGNOSTIC_HIDDEN__", "")
    view = {
        "view": "wizard.security",
        "trust": snap,
        "ok": posture_ok,
    }
    payload = _embed_json(view)
    body = body.replace("__VIEW_JSON__", payload)
    body = body.replace('name="csrf"', f'name="csrf" value="{csrf}"')
    return body.encode("utf-8")


def _render_next(home: Path, csrf: str) -> bytes:
    """Render the wizard Next-step shell — Exit Plan + Adopt.

    The exit links point at the server's own fixed-exit routes
    (/out/docs, /out/source), not at the external URLs, so the server
    remains the only component that decides what may leave the box.

    B3: the exchange (slice C) and pack adoption (slice D) flows are
    explicitly labelled as future slices, never as completed. The CLI
    / free path is always exposed so the user is not funnelled toward
    a fake-success button.
    """
    snap = trust.trust_snapshot(home)
    view = {
        "view": "wizard.next",
        "trust": snap,
        "exit_routes": {"docs": "out/docs", "source": "out/source"},
    }
    payload = _embed_json(view)
    body = _NEXT_TEMPLATE
    body = body.replace("__VIEW_JSON__", payload)
    body = body.replace('name="csrf"', f'name="csrf" value="{csrf}"')
    return body.encode("utf-8")


def _wizard_html(wrapper: str, route: str = "") -> str:
    """Wrap a per-route main block in the wizard shell.

    The shell ships a strict CSP, no-referrer, no-store, and the wizard's
    own navigation. The bootstrap JSON is escaped by `_embed_json`; the
    template itself only contains literal markup, so there is no
    untrusted content path here.

    B3: the shell carries a ``<nav class="wizard-nav">`` with the four
    routes as sibling-relative ``<a>`` tags. ``href`` is plain text so
    the no-JS path navigates the wizard by following the link. A
    ``data-wizard-progress`` attribute on the nav lets the JS hydrator
    highlight the active step without rewriting hrefs.

    B3 round 1: the active route is server-rendered into ``aria-current``
    on the matching nav link AND into ``<body data-route="…">`` so the
    JS hydrator and a no-JS user both see the active affordance.
    ``route`` must be the literal step name (welcome / security / next).
    """
    # Server-set aria-current on the active nav link. We do this by
    # rendering the active link with an extra attribute; the JS hydrator
    # is then a no-op.
    def _nav_link(step: str, label: str) -> str:
        attrs = f'href="{step}" data-step="{step}"'
        if step == route:
            attrs += ' aria-current="page"'
        return f'<a {attrs}>{label}</a>'

    nav_active = (
        f'{_nav_link("welcome", "Welcome")}'
        f'{_nav_link("security", "Security")}'
        f'{_nav_link("next", "Next")}'
        f'{_nav_link("dashboard", "Dashboard")}'
        f'<a href="out/docs">Docs</a>'
        f'<a href="out/source">Source</a>'
    )

    # Build a stepper with 3 numbered dots showing past/current/upcoming.
    # The current step carries the `aria-current="step"` attribute so a
    # screen reader announces it.
    stepper_steps = ["welcome", "security", "next"]
    stepper_html = '<ol class="stepper" aria-label="Wizard progress">'
    for i, step in enumerate(stepper_steps, start=1):
        attrs = f'class="stepper-step" data-step="{step}"'
        if step == route:
            attrs += ' aria-current="step"'
        stepper_html += f'<li {attrs}>{i}</li>'
    stepper_html += "</ol>"

    body_attrs = 'class="wizard"'
    if route:
        body_attrs += f' data-route="{route}"'

    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '  <meta name="referrer" content="no-referrer">\n'
        "  <title>krellbot first-run wizard</title>\n"
        # Sibling-relative: resolves to /<token>/static/style.css whether
        # the document is /<token>/ (root) or /<token>/<page>. A `../`
        # prefix would drop the token and 403 on every nav + CSS fetch.
        '  <link rel="stylesheet" href="static/style.css">\n'
        "</head>\n"
        f"<body {body_attrs}>\n"
        "<header>\n"
        "  <h1>krellbot first-run wizard</h1>\n"
        '  <p class="muted">loopback only. no call leaves this machine.</p>\n'
        f"  {stepper_html}\n"
        "</header>\n"
        # Each link is sibling-relative so no-JS navigation works without
        # the JS hydrator rewriting hrefs. The active route is flagged
        # server-side with aria-current so a no-JS user sees it too.
        f'<nav class="wizard-nav" aria-label="Wizard steps">\n'
        f"  {nav_active}\n"
        "</nav>\n"
        "<main>\n"
        f"{wrapper}\n"
        "</main>\n"
        "<footer>\n"
        '  <p class="muted">Static assets are local. No CDN, no Google font, no external script.</p>\n'
        "</footer>\n"
        "<script>window.__KB_VIEW__ = __VIEW_JSON__;</script>\n"
        "</body>\n"
        "</html>\n"
    )


_WELCOME_TEMPLATE = _wizard_html(
    "  <section id=\"welcome-section\">\n"
    "    <h2>Welcome</h2>\n"
    "    <p>You are running krellbot for the first time on this loopback port.</p>\n"
    "    <ol class=\"truth-list\" aria-label=\"What krellbot is\">\n"
    "      <li><strong>Free, open-source local engine.</strong> The code you have runs on this machine; krellbot.dev does not host a service.</li>\n"
    "      <li><strong>Keys stay on this machine.</strong> Exchange API keys are stored in the local keychain; they are never sent to krellbot.dev.</li>\n"
    "      <li><strong>Official packs are optional and recommended.</strong> You can run any pack file you trust; official packs are not required.</li>\n"
    "    </ol>\n"
    "    <p class=\"muted\">Step 1 of 3 &middot; <a href=\"security\">Continue to security</a> &middot; <a href=\"next\">Skip to next</a></p>\n"
    "  </section>\n",
    route="welcome",
)


_SECURITY_TEMPLATE = _wizard_html(
    "  <section id=\"wizard-security-section\">\n"
    "    <h2>Security posture</h2>\n"
    "    <p>This is read-only. No keys, no balances, no orders leave the box.</p>\n"
    "    <dl id=\"trust-list\">\n"
    "      <dt>Keychain backend</dt>\n"
    '      <dd id="trust-backend">__BACKEND__</dd>\n'
    "      <dt>Data home</dt>\n"
    '      <dd id="trust-home">__HOME__</dd>\n'
    "      <dt>Home mode</dt>\n"
    '      <dd id="trust-home-mode">__HOME_MODE__</dd>\n'
    "      <dt>UI bind</dt>\n"
    '      <dd id="trust-bind">127.0.0.1 (loopback only)</dd>\n'
    "      <dt>Live arm from the UI</dt>\n"
    '      <dd id="trust-live-arm">Refused. Live arm is CLI-only.</dd>\n'
    "      <dt>Key permissions <span class=\"muted\">(required, not validated)</span></dt>\n"
    '      <dd id="trust-permissions">Trade-only permission required, withdraw permission never granted. No exchange key is probed from this page.</dd>\n'
    "    </dl>\n"
    '    <p id="trust-diagnostic" class="__DIAGNOSTIC_CLASS__" __DIAGNOSTIC_HIDDEN__>__DIAGNOSTIC__</p>\n'
    '    <p><a href="welcome">Back</a> &middot; <a href="next">Continue to next</a></p>\n'
    "  </section>\n",
    route="security",
)


_NEXT_TEMPLATE = _wizard_html(
    "  <section id=\"wizard-next-section\">\n"
    "    <h2>Next steps</h2>\n"
    "    <p>When you are ready, enter the dashboard.</p>\n"
    "    <form id=\"form-enter-dashboard\" action=\"enter-dashboard\" method=\"POST\" class=\"enter-form\">\n"
    "      <input type=\"hidden\" name=\"csrf\">\n"
    "      <button type=\"submit\">Enter dashboard</button>\n"
    "    </form>\n"
    "    <h3>Coming in future slices</h3>\n"
    "    <p class=\"muted\">The following steps belong to later slices and are NOT available in this release:</p>\n"
    '    <ul class="future-list" aria-label="Future slices">\n'
    "      <li><strong>Slice C &mdash; exchange connection.</strong> Adding or rotating an exchange API key from this UI is a future slice; today the CLI is the only path.</li>\n"
    "      <li><strong>Slice D &mdash; pack adoption.</strong> A guided pack picker / scheduler installer is a future slice; today you run <code>krellbot pack lint</code> and <code>krellbot arm</code> from the CLI.</li>\n"
    "    </ul>\n"
    "    <h3>The free path today</h3>\n"
    "    <ul>\n"
    "      <li>Run <code>krellbot ui</code> from a terminal at any time to relaunch this UI.</li>\n"
    "      <li>Run <code>krellbot doctor</code> for a complete readiness check.</li>\n"
    "    </ul>\n"
    '    <p class="muted">Step 3 of 3 &middot; <a href="security">Back</a></p>\n'
    "  </section>\n",
    route="next",
)



def _embed_json(view: dict) -> str:
    """JSON for an inline script. `<` is escaped so a journal string cannot close the tag."""
    payload = json.dumps(view, default=str)
    return (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _h(value: str) -> str:
    """HTML-escape a string for safe insertion into the wizard shell.

    The trust snapshot's values are paths and class names from the
    local machine — the snapshot module never reads raw secrets — but
    we still escape on the way into HTML so a keychain backend whose
    class path somehow contains ``<`` cannot inject markup into the
    visible page.
    """
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---- stop_all action -----------------------------------------------------


def _stop_all(home: Path) -> dict:
    """Disarm every armed pack and flatten paper positions.

    For each armed pack:
        * if paper and owned_qty > 0, mark the paper state as flat (zero
          the base balance, add proceeds at the resting stop price if any,
          cancel any resting stop on the pair, journal the exit);
        * always disarm.

    Does NOT call `cmd_stop`. Raises nothing: caller renders the outcome.
    Returns a summary dict for logging/debugging.
    """
    home = Path(home)
    config = kb_config.load_config(home)
    summary = {
        "disarmed": [],
        "flattened": [],
        "skipped": [],
    }
    for armed in list(config.armed):
        if armed.mode == "paper" and armed.owned_qty > 0:
            if _flatten_paper_position(home, armed):
                summary["flattened"].append({"pack_id": armed.pack_id, "venue": armed.venue, "pair": armed.pair})
            else:
                summary["skipped"].append({"pack_id": armed.pack_id, "venue": armed.venue, "pair": armed.pair})
        config.armed = [a for a in config.armed if not (a.venue == armed.venue and a.pair == armed.pair)]
        summary["disarmed"].append({"pack_id": armed.pack_id, "venue": armed.venue, "pair": armed.pair})
    kb_config.save_config(home, config)
    return summary


_SLIP = Decimal("0.0005")
_FEE_BPS = {"kraken": 40, "coinbase": 120}
_PRICE_QUANT = Decimal("0.00000001")


def _flatten_paper_position(home: Path, armed: kb_config.ArmedPack) -> bool:
    """Sell the pack's owned qty on the paper book. Do not touch other coins.

    Price is the last fill on the pair, else the resting stop. No price means
    no fill: inventing one would credit cash the book never had.
    """
    home = Path(home)
    venue = armed.venue
    pair = armed.pair
    if armed.owned_qty <= 0:
        return False
    base, quote = _base_quote(pair)
    state_path = home / "run" / f"paper-{venue}.json"
    if not state_path.is_file():
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    balances = state.get("balances") or {}
    base_qty = _optional_decimal(balances.get(base))
    if base_qty is None or base_qty <= 0:
        return False
    qty = min(armed.owned_qty, base_qty)
    mark = _exit_mark(state, pair)
    if mark is None:
        return False
    sell_price = (mark * (Decimal(1) - _SLIP)).quantize(_PRICE_QUANT, rounding=ROUND_DOWN)
    if sell_price <= 0:
        return False
    proceeds = qty * sell_price
    fee = (proceeds * Decimal(_FEE_BPS.get(venue, 40)) / Decimal(10000)).quantize(_PRICE_QUANT, rounding=ROUND_DOWN)
    current_quote = _optional_decimal(balances.get(quote)) or Decimal(0)
    balances[base] = format(base_qty - qty, "f")
    if quote:
        balances[quote] = format(current_quote + proceeds - fee, "f")
    state["open_orders"] = [o for o in state.get("open_orders", []) if o.get("pair") != pair]
    fills = state.setdefault("recent_fills", [])
    fills.append(
        {
            "id": f"stop-all-{secrets.token_hex(8)}",
            "coid": f"stop-all-{secrets.token_hex(8)}",
            "pair": pair,
            "side": "sell",
            "qty": format(qty, "f"),
            "price": format(sell_price, "f"),
            "ts_ms": int(_now_seconds() * 1000),
            "reason": "stop_all",
        }
    )
    state["balances"] = balances
    try:
        kb_paths.atomic_write(state_path, (json.dumps(state, default=str) + "\n").encode("utf-8"))
    except OSError:
        return False
    try:
        kb_journal.append(
            {
                "ts": int(_now_seconds()),
                "kind": "stop_all",
                "venue": venue,
                "pack": armed.pack_id,
                "bar_ts": 0,
                "detail": {
                    "pair": pair,
                    "qty": format(qty, "f"),
                    "price": format(sell_price, "f"),
                },
            }
        )
    except (ValueError, OSError):
        pass
    return True


def _optional_decimal(raw: object) -> Decimal | None:
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ValueError, ArithmeticError):
        return None


def _exit_mark(state: dict, pair: str) -> Decimal | None:
    """Last fill on the pair, else the resting stop. Never a made-up price."""
    for fill in reversed(state.get("recent_fills") or []):
        if not isinstance(fill, dict) or fill.get("pair") != pair:
            continue
        mark = _optional_decimal(fill.get("price"))
        if mark is not None and mark > 0:
            return mark
    for order in state.get("open_orders") or []:
        if not isinstance(order, dict) or order.get("pair") != pair:
            continue
        mark = _optional_decimal(order.get("stop_price"))
        if mark is not None and mark > 0:
            return mark
    return None


def _base_quote(pair: str) -> tuple[str, str]:
    if not pair:
        return ("", "")
    if pair.endswith("USD"):
        return pair[: -len("USD")], "USD"
    if len(pair) >= 6:
        return pair[:-3], pair[-3:]
    return pair, ""


def _now_seconds() -> float:
    import time

    return time.time()


# ---- handler -------------------------------------------------------------


class _ServerConfig:
    """Per-server config injected into the handler class."""

    __slots__ = ("csrf", "home", "token")

    def __init__(self, token: str, csrf: str, home: Path) -> None:
        self.token = token
        self.csrf = csrf
        self.home = Path(home)


def _make_handler(server_config: _ServerConfig):
    """Build a BaseHTTPRequestHandler subclass bound to the server's config."""

    class DashboardHandler(http.server.BaseHTTPRequestHandler):
        # Silence the default stderr access log.
        def log_message(self, format: str, *args: Any) -> None:
            return

        server_version = "krellbot-ui/1"

        # Expose server_config to the methods below without touching instance
        # __dict__ (BaseHTTPRequestHandler has many special attributes).
        @property
        def cfg(self) -> _ServerConfig:
            return server_config

        # ---- routing ----------------------------------------------------

        def do_GET(self) -> None:
            self._handle("GET")

        def do_POST(self) -> None:
            self._handle("POST")

        def _handle(self, method: str) -> None:
            port = self.server.server_address[1]

            # 1. Host header must be loopback with the bound port.
            host = self.headers.get("Host", "")
            if host not in _allowed_hosts(port):
                self._send_status(403, "Forbidden")
                return

            # 2. Parse the path.
            raw_path = self.path.split("?", 1)[0]
            stripped = raw_path.strip("/")
            parts = stripped.split("/", 1)
            path_token = parts[0] if parts else ""
            rest = parts[1] if len(parts) > 1 else ""

            # 3. Bare / has no path token. Do not redirect: that would disclose it.
            if path_token == "":
                self._send_status(403, "Forbidden")
                return

            # 4. Token-in-path check.
            if not _constant_time_eq(path_token, server_config.token):
                self._send_status(403, "Forbidden")
                return

            # 5. POST: cookie + CSRF + Origin.
            if method == "POST":
                cookies = _parse_cookies(self.headers.get("Cookie", ""))
                session = cookies.get("krellbot_session", "")
                csrf = cookies.get("krellbot_csrf", "")
                if not _constant_time_eq(session, server_config.token):
                    self._send_status(403, "Forbidden")
                    return
                if not csrf:
                    self._send_status(403, "Forbidden")
                    return
                origin = self.headers.get("Origin", "")
                if origin not in _allowed_origins(port):
                    self._send_status(403, "Forbidden")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    self._send_status(400, "Bad Request")
                    return
                if length < 0 or length > 65536:
                    self._send_status(400, "Bad Request")
                    return
                body = self.rfile.read(length) if length > 0 else b""
                form = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True)
                form_csrf = (form.get("csrf") or [""])[0]
                if not _constant_time_eq(form_csrf, server_config.csrf) or not _constant_time_eq(
                    csrf, server_config.csrf
                ):
                    self._send_status(403, "Forbidden")
                    return
            else:
                form = {}

            # 6. Route.
            if method == "GET":
                self._route_get(rest, port)
            else:
                self._route_post(rest, form)

        # ---- GET routes -------------------------------------------------

        def _route_get(self, rest: str, port: int) -> None:
            # Strip a leading slash for clean comparison.
            route = rest.lstrip("/")
            # Wizard routes: welcome / security / next.
            if route in _WIZARD_ROUTES:
                self._serve_wizard(route, port)
                return
            # Index route (`/`) chooses welcome or dashboard based on the
            # recorded visit preference — never redirects to a URL missing
            # the token.
            if route in ("", "/"):
                self._serve_index(port)
                return
            # Direct /dashboard always renders the dashboard shell. The
            # visit preference only governs what the *index* shows; if the
            # user types /dashboard explicitly they get the dashboard.
            if route == "dashboard":
                self._send_html(
                    _render_dashboard(server_config.home, server_config.csrf),
                    port,
                )
                return
            # Fixed user-initiated exits. Only the allowlisted slugs are
            # honored; caller-controlled targets (query string, etc.) are
            # never reflected.
            if route in _EXITS:
                self._serve_exit(_EXITS[route])
                return
            # Static asset fallback (existing behavior).
            if route.startswith("static/"):
                self._serve_static(route[len("static/") :])
                return
            # Anything else inside the token gate is 404 with no Location,
            # so a guessed path cannot echo a redirect target.
            self._send_status(404, "Not Found")

        def _serve_index(self, port: int) -> None:
            """Serve the welcome OR the dashboard shell.

            The choice depends on the recorded visit preference:
                * visited_dashboard == True → dashboard
                * any other case (missing, corrupt, non-bool) → welcome

            We never redirect to a URL missing the token, so the same
            route here serves both shells without disclosing the gate.
            """
            home = server_config.home
            if first_run.has_visited_dashboard(home):
                body = _render_dashboard(home, server_config.csrf)
            else:
                body = _render_welcome(home, server_config.csrf)
            self._send_html(body, port)

        def _serve_wizard(self, route: str, port: int) -> None:
            """Serve a wizard view by name. Sets cookies so the wizard's
            POST /visit-dashboard can satisfy the existing CSRF gate.
            """
            home = server_config.home
            csrf = server_config.csrf
            if route == "welcome":
                body = _render_welcome(home, csrf)
            elif route == "security":
                body = _render_security(home, csrf)
            elif route == "next":
                body = _render_next(home, csrf)
            else:  # pragma: no cover — _WIZARD_ROUTES is fixed
                self._send_status(404, "Not Found")
                return
            self._send_html(body, port)

        def _send_html(self, body: bytes, port: int) -> None:
            """Write a 200 HTML response with the wizard/dashboard security
            headers and the session+CSRF cookies. Shared by every HTML
            response the server emits so the policy lives in exactly one
            place.
            """
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Set-Cookie", _session_cookie(server_config.token, port))
            self.send_header("Set-Cookie", _csrf_cookie(server_config.csrf, port))
            self.send_header("Content-Length", str(len(body)))
            for name, value in _HTML_SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _serve_exit(self, target: str) -> None:
            """302 to a fixed, allowlisted external URL. Browser-initiated.

            The brief requires the same security-header set on redirects
            as on HTML responses (CSP, Referrer-Policy, X-Content-Type-
            Options, Cache-Control). The header loop is shared with the
            HTML path so the policy lives in exactly one place.
            """
            self.send_response(302)
            self.send_header("Location", target)
            for name, value in _HTML_SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        def _serve_static(self, rel: str) -> None:
            # Reject path traversal: no .., no leading slash.
            if ".." in rel or rel.startswith("/"):
                self._send_status(404, "Not Found")
                return
            target = (_STATIC_DIR / rel).resolve()
            base = _STATIC_DIR.resolve()
            try:
                target.relative_to(base)
            except ValueError:
                self._send_status(404, "Not Found")
                return
            if not target.is_file():
                self._send_status(404, "Not Found")
                return
            data = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _content_type_for(target.name))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        # ---- POST routes ------------------------------------------------

        def _route_post(self, rest: str, form: dict) -> None:
            if rest == "arm":
                self._do_arm(form)
            elif rest == "disarm":
                self._do_disarm(form)
            elif rest == "stop_all":
                self._do_stop_all()
            elif rest == "adopt":
                self._do_adopt(form)
            elif rest == "visit-dashboard":
                self._do_visit_dashboard()
            elif rest == "enter-dashboard":
                self._do_enter_dashboard()
            else:
                self._send_status(404, "Not Found")

        def _do_visit_dashboard(self) -> None:
            """Legacy alias kept for backward compatibility. Returns 303
            to the token-scoped dashboard via the same PRG contract as
            enter-dashboard. New code should hit /enter-dashboard.
            """
            self._do_enter_dashboard()

        def _do_enter_dashboard(self) -> None:
            """Record the visit preference so future root GETs render the
            dashboard shell instead of the wizard welcome.

            The cookie/CSRF/Origin gate is enforced upstream in `_handle`;
            by the time we get here the request is already authenticated.
            On success we 303 to /<token>/dashboard (PRG). The response
            never echoes an absolute URL or anything outside the gate.
            """
            try:
                first_run.mark_visited_dashboard(server_config.home)
            except OSError:
                self._send_status(500, "Internal Server Error")
                return
            self.send_response(303, "See Other")
            self.send_header("Location", f"/{server_config.token}/dashboard")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            for name, value in _HTML_SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        def _do_arm(self, form: dict) -> None:
            mode = (form.get("mode") or [""])[0]
            if mode != "paper":
                # Live arm from the page is forbidden. No state change.
                self._send_status(403, "Forbidden")
                return
            pack_path = (form.get("pack_path") or [""])[0]
            venue = (form.get("venue") or [""])[0]
            paper_balance_raw = (form.get("paper_balance") or [""])[0]
            if not pack_path or not venue:
                self._send_status(400, "Bad Request")
                return
            try:
                paper_balance = Decimal(paper_balance_raw)
            except (ValueError, ArithmeticError):
                self._send_status(400, "Bad Request")
                return
            from krellbot.run import arm_pack

            rc = arm_pack(
                Path(pack_path),
                venue=venue,
                mode="paper",
                paper_balance=paper_balance,
                home=server_config.home,
            )
            if rc == 0:
                self._send_text(200, "armed")
            else:
                self._send_status(400, "Bad Request")

        def _do_disarm(self, form: dict) -> None:
            from krellbot.run import disarm_pack

            venue = (form.get("venue") or [""])[0]
            pair = (form.get("pair") or [""])[0]
            if not venue or not pair:
                self._send_status(400, "Bad Request")
                return
            rc = disarm_pack(venue=venue, pair=pair, home=server_config.home)
            if rc == 0:
                self._send_text(200, "disarmed")
            else:
                self._send_status(400, "Bad Request")

        def _do_stop_all(self) -> None:
            summary = _stop_all(server_config.home)
            self._send_json(200, summary)

        def _do_adopt(self, form: dict) -> None:
            pack_id = (form.get("pack_id") or [""])[0]
            if not pack_id:
                self._send_status(400, "Bad Request")
                return
            config = kb_config.load_config(server_config.home)
            armed = kb_config.find_armed_by_id(config, pack_id)
            if armed is None:
                self._send_status(404, "Not Found")
                return
            if armed.owned_qty > 0 or armed.pending_version is None:
                # Refused while long, or nothing to adopt.
                self._send_status(403, "Forbidden")
                return
            kb_config.adopt_pending_version(armed)
            kb_config.save_config(server_config.home, config)
            self._send_text(200, "adopted")

        # ---- response helpers -------------------------------------------

        def _send_status(self, code: int, message: str) -> None:
            self.send_response(code, message)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            body = message.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_text(self, code: int, text: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            body = text.encode("utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, code: int, payload: Any) -> None:
            body = json.dumps(payload, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return DashboardHandler


# ---- server wrapper ------------------------------------------------------


class DashboardServer:
    """Threaded loopback HTTP server.

    `start()` spins up a daemon thread on `serve_forever`. `stop()` shuts
    down the server and joins the thread. Tests use `port=0` and read the
    bound port back from `bound_port`.
    """

    def __init__(self, *, home: Path, port: int = 0) -> None:
        self._requested_port = port
        self._home = Path(home)
        self.token: str = secrets.token_hex(_TOKEN_BYTES)
        self.csrf: str = secrets.token_hex(_TOKEN_BYTES)
        self.bound_host: str = _BIND_HOST
        self.bound_port: int = 0
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        # Defer socket bind to start() so a failed start doesn't leak.

    def start(self) -> None:
        if self._server is not None:
            return
        config = _ServerConfig(self.token, self.csrf, self._home)
        handler_cls = _make_handler(config)
        self._server = http.server.ThreadingHTTPServer((_BIND_HOST, self._requested_port), handler_cls)
        # Block reuse so a tight test loop can rebind to the same port.
        self._server.allow_reuse_address = False
        self.bound_port = int(self._server.server_address[1])
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="krellbot-ui",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self.bound_port = 0

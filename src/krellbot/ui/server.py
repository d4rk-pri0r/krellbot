"""Dashboard UI server: stdlib `http.server`, loopback only, token-gated.

The server binds to `127.0.0.1` (no host argument can widen it) on a port
that is either user-supplied or random (`0`). A 32-byte hex token gates
access. The first page is `/{token}/`, which sets the session and CSRF
cookies and renders the dashboard. POSTs are CSRF-protected via the
`krellbot_csrf` cookie + form field plus an `Origin` check.

GET status reads only local metadata under `$KRELLBOT_HOME`, without a
credential read or venue probe. The Exchange form POST makes an authenticated
HTTPS permission request to the selected Kraken or Coinbase venue before
storing a trade-only pair in the native OS keychain. No exchange credentials
go to krellbot.dev.

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
import html
import http.server
import json
import secrets
import socketserver
import sys
import threading
import time
import urllib.parse
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

from krellbot import config as kb_config
from krellbot import journal as kb_journal
from krellbot import license as kb_license
from krellbot import paths as kb_paths

from . import activate as kb_activate
from . import first_run, keys_status, trust
from . import packs as ui_packs


# ---- dashboard view layer -------------------------------------------------
#
# The command-center overview builds a single read-only snapshot of the local
# posture: install readiness (no permission probe, no clock probe, no venue
# probe), per-venue key verification from the durable metadata only, license
# cache summary (not raw JSON), scheduler installation flag from the local
# service-unit directory, paper state, armed packs, journal tail, receipts,
# and installed packs.
#
# Every field is presentation-only. No keyring read on GET. No invented
# performance, balances, equity, sparklines. As-of timestamps are the
# dashboard render time so the page can show "snapshot at …" honestly.

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
_WIZARD_ROUTES = frozenset({"welcome", "security", "next", "keys"})


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
    """Build the dashboard view: armed packs, paper state, license, journal.

    The command-center overview adds a small, closed set of derived fields
    on top of the slice-D view so the top-level page can show real
    readiness, real key-verification metadata (no keyring read), real
    license summary, and real scheduler state. Every derivation reads
    only local metadata; nothing here probes a venue or reads a
    credential. ``as_of`` is the dashboard render time so a no-JS user
    still sees when the snapshot was taken.
    """
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
                "starting_cash": str(a.starting_cash) if a.starting_cash is not None else None,
                "requires_license": a.requires_license,
                "armed_at_ts": int(a.armed_at_ts),
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
    # Closed-shape view block. Every key here is documented; new fields
    # must be added explicitly and the static-asset tests updated to
    # reflect the change. The dashboard renders ONLY these keys.
    return {
        # Slice-D core view (preserved verbatim so existing tests stay
        # green). ``license`` here is sanitized to the canonical
        # three-key shape so a stale cache with extra fields cannot
        # leak through the bootstrap JSON; the new ``license_summary``
        # below exposes the same three scalars in a stricter closed
        # form for the command-center renderer.
        "armed": armed_view,
        "paper": paper_by_venue,
        "license": _sanitize_license_cache(license_cache),
        "journal_tail": _read_journal_tail(home),
        "receipts": _read_receipts(home),
        "trust": snap,
        # Installed packs listing for the dashboard. Built from local
        # metadata only: no invented performance numbers, no equity
        # curves, no paid-catalog reads. Legacy packs render with
        # ``runnable: false`` so the dashboard's arm affordance stays
        # hidden for them. The arm route refuses them with 403 anyway.
        "packs": ui_packs.list_installed(home),
        # ---- command-center additions ----
        # ``as_of`` is the dashboard render time. Pages do not claim a
        # live probe happened on GET; the as-of timestamp is the only
        # honesty a no-JS user gets about when the snapshot was taken.
        "as_of": _now_iso_seconds(),
        # Install readiness: the runtime can serve the local UI. Derived
        # locally without a permission probe, clock probe, or venue
        # probe. Trading readiness is the stricter gate (it requires a
        # real permission probe, which a GET never runs); we report
        # "not evaluated on this page" for trading so the user is not
        # misled by an unverified claim.
        "readiness": _install_readiness(home),
        "trading_readiness": "not evaluated on this page; run `krellbot doctor`",
        # Per-venue key status, derived from durable metadata only.
        # The values are exactly what ``keys_status.read_status``
        # produces: a historical "last stored at <ts>; current presence
        # not checked" row, or "unknown; not currently verified" if no
        # row exists. No keyring read on GET.
        "keys_status": keys_status.read_status(home),
        # License summary: closed shape, three scalars only. We never
        # expose raw license-cache JSON to the dashboard so a stale or
        # unexpected field cannot leak through the renderer.
        "license_summary": _license_summary(license_cache),
        # Whether the OS scheduler unit exists for this platform. The
        # dashboard never installs one; it only reports what is on disk
        # under the user's write root. ``None`` means the platform is
        # unsupported (no recognisable scheduler unit), ``False`` means
        # the unit is absent, ``True`` means the unit file is present.
        "scheduler_installed": _scheduler_installed(home),
        # Whether a tick journal record exists at all. The dashboard
        # does not invent "running"; the page shows a static "stopped"
        # / "never started" state until a real tick lands.
        "tick_state": _tick_state(home),
    }


def _sanitize_license_cache(cache: object) -> dict | None:
    """Return the canonical three-key license cache, or None.

    ``license_cache`` is read from disk; a stale or seeded file could
    carry extra keys (``secret_token``, ``admin_url``, etc.) that must
    not reach the dashboard bootstrap. We hand-pick the closed
    three-key shape here so the renderer sees only the canonical
    fields. Invalid values fall back to ``None`` so the dashboard
    reports "missing" honestly rather than echoing a stale fragment.
    """
    if not isinstance(cache, dict):
        return None
    raw_status = cache.get("status")
    if not isinstance(raw_status, str) or not raw_status:
        return None
    try:
        period_end = int(cache.get("period_end", 0))
    except (TypeError, ValueError):
        return None
    try:
        grace_until = int(cache.get("grace_until", 0))
    except (TypeError, ValueError):
        return None
    return {"status": raw_status, "period_end": period_end, "grace_until": grace_until}


def _render_dashboard(home: Path, csrf: str) -> bytes:
    """Render the dashboard HTML, embedding the view as JSON and the CSRF field."""
    view = _view_snapshot(home)
    payload = _embed_json(view)
    index = _STATIC_DIR / "index.html"
    if not index.is_file():
        return b"<!doctype html><title>krellbot</title><p>Static assets missing.</p>"
    template = index.read_text(encoding="utf-8")
    rendered = template.replace("__VIEW_JSON__", payload)
    rendered = rendered.replace("__PACK_LIST__", _render_pack_forms(view.get("packs") or [], csrf))
    rendered = rendered.replace('name="csrf"', f'name="csrf" value="{csrf}"')
    return rendered.encode("utf-8")


# ---- command-center view helpers -----------------------------------------
#
# Every helper here is a closed, presentation-only derivation. None of
# them touch a credential, the network, or the live process tree.


def _now_iso_seconds() -> str:
    """Return the dashboard render time as a strict ISO-8601 UTC timestamp.

    Matches the shape ``keys_status._now_iso`` writes, so the same
    validation rules apply if the renderer ever feeds it back into a
    parser. Microseconds are dropped so the renderer shows a stable
    string; the dashboard never relies on sub-second precision.
    """
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc)
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _install_readiness(home: Path) -> dict:
    """Compute install readiness from local metadata only.

    Mirrors the same fields ``krellbot doctor`` checks for install
    readiness WITHOUT performing a permission probe, clock probe, or
    venue probe. The result is a closed dict the dashboard renders
    directly: each row has ``label``, ``ok``, and a one-line ``why``.
    The dashboard never claims "trading ready" here; that is the
    ``trading_readiness`` field, which is always "not evaluated on this
    page" for a GET.
    """
    snap = trust.trust_snapshot(home)
    rows: list[dict] = []
    home_mode = snap.get("home_mode")
    home_mode_ok = bool(snap.get("home_mode_ok"))
    if home_mode_ok:
        rows.append({"label": "data home mode 0o700", "ok": True, "why": str(home_mode)})
    elif home_mode is None:
        rows.append(
            {
                "label": "data home",
                "ok": home.is_dir() and sys.platform == "win32",
                "why": "DACL not checked on Windows" if sys.platform == "win32" else "home mode not checkable",
            }
        )
    else:
        rows.append(
            {
                "label": "data home mode 0o700",
                "ok": False,
                "why": f"home mode is {home_mode}",
            }
        )
    backend = snap.get("keychain_backend")
    backend_ok = bool(snap.get("keychain_ok"))
    if backend_ok:
        rows.append({"label": "keychain backend", "ok": True, "why": str(backend)})
    else:
        rows.append(
            {
                "label": "keychain backend",
                "ok": False,
                "why": str(backend) if backend else "no persistent backend detected",
            }
        )
    # Bind availability: a one-shot loopback bind probe on 127.0.0.1:0.
    # No remote address is ever touched. The probe is local to the
    # dashboard render so a no-network box still gets a real answer.
    bind_ok = _loopback_bind_available()
    rows.append(
        {
            "label": "loopback bind 127.0.0.1",
            "ok": bind_ok,
            "why": "ok" if bind_ok else "bind refused",
        }
    )
    # Doctor permits an existing Windows home even though POSIX modes do
    # not model Windows DACLs. Preserve that distinction in this summary.
    install_ready = home.is_dir() and all(r["ok"] for r in rows)
    return {"install_ready": install_ready, "rows": rows}


def _loopback_bind_available() -> bool:
    """Return True when a loopback bind probe succeeds.

    Same shape as ``doctor._ui_bind_available`` but kept here so the
    dashboard module does not depend on the doctor module. The
    function opens ``127.0.0.1:0`` (kernel-assigned ephemeral port),
    closes the socket, and returns the result. No remote address is
    touched.
    """
    import socket as _socket

    sock = None
    try:
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _license_summary(cache: dict | None) -> dict:
    """Return a closed, presentation-only license summary.

    The dashboard never exposes the raw ``license-cache.json`` shape;
    a stale or unexpected field cannot leak through the renderer
    because we hand-pick three scalars: ``status``, ``period_end``,
    ``grace_until``. Each scalar is type-coerced and dropped on
    invalid input. A missing cache becomes ``status == "missing"``.
    """
    if not isinstance(cache, dict):
        return {"status": "missing", "period_end": None, "grace_until": None}
    raw_status = cache.get("status")
    if not isinstance(raw_status, str) or not raw_status:
        return {"status": "missing", "period_end": None, "grace_until": None}
    try:
        period_end = int(cache.get("period_end", 0))
    except (TypeError, ValueError):
        period_end = None
    try:
        grace_until = int(cache.get("grace_until", 0))
    except (TypeError, ValueError):
        grace_until = None
    return {"status": raw_status, "period_end": period_end, "grace_until": grace_until}


def _scheduler_installed(home: Path) -> bool | None:
    """Report whether the OS scheduler unit exists for this platform.

    The dashboard never installs a unit; it only reports what is on
    disk under ``<home>`` (the same root the user sees in the wizard).
    ``None`` means the platform has no recognisable scheduler
    primitive; ``False`` means the unit is absent; ``True`` means the
    unit file is present.
    """
    import sys as _sys

    if _sys.platform == "darwin":
        target = home / "Library" / "LaunchAgents" / "dev.krellbot.tick.plist"
        return target.exists()
    if _sys.platform.startswith("linux"):
        d = home / ".config" / "systemd" / "user"
        return (d / "krellbot-tick.timer").exists() and (d / "krellbot-tick.service").exists()
    if _sys.platform == "win32":
        target = home / "Tasks" / "krellbot-tick.xml"
        return target.exists()
    return None


def _tick_state(home: Path) -> dict:
    """Return a closed, honest tick state derived from the journal.

    The dashboard does not invent a "running" indicator. It reports the
    presence (or absence) of any ``kind=tick`` record in the journal
    directory, plus the most-recent tick timestamp if one exists. No
    field here is invented: a missing journal is ``present=False``;
    a journal without a tick is the same.
    """
    import json as _json

    journal_dir = home / "journal"
    if not journal_dir.is_dir():
        return {"present": False, "last_ts": None, "age_seconds": None}
    latest_ts = 0
    found = False
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("kind") == "tick":
                found = True
                try:
                    ts = int(rec.get("ts", 0) or 0)
                except (TypeError, ValueError):
                    continue
                latest_ts = max(latest_ts, ts)
    if not found or latest_ts <= 0:
        return {"present": False, "last_ts": None, "age_seconds": None}
    import time as _time

    now = int(_time.time())
    return {
        "present": True,
        "last_ts": latest_ts,
        "age_seconds": max(0, now - latest_ts),
    }


def _render_pack_forms(packs: list, csrf: str) -> str:
    """Server-render paper-arm forms. No pack path, no catalog stats."""
    if not packs:
        return '<p class="muted">No packs installed.</p>'
    parts: list[str] = []
    for pack in packs:
        if not isinstance(pack, dict):
            continue
        label = html.escape(str(pack.get("label") or pack.get("public_label") or pack.get("id") or "pack"))
        if not pack.get("runnable"):
            reason = html.escape(str(pack.get("not_runnable_reason") or "not runnable"))
            parts.append(f'<p>{label} <span class="muted">{reason}</span></p>')
            continue
        pack_id = html.escape(str(pack.get("id") or ""), quote=True)
        parts.append(
            '<form action="paper-arm" method="POST" class="card">'
            f'<input type="hidden" name="pack_id" value="{pack_id}">'
            f'<input type="hidden" name="csrf" value="{html.escape(csrf, quote=True)}">'
            '<label>Venue <select name="venue">'
            '<option value="kraken">kraken</option>'
            '<option value="coinbase">coinbase</option>'
            "</select></label>"
            "<label>Paper balance (USD) "
            '<input type="number" name="paper_balance" step="any" min="1" value="1000" required>'
            "</label>"
            f'<button type="submit">Paper-arm {label}</button>'
            "</form>"
        )
    return "\n".join(parts) or '<p class="muted">No packs installed.</p>'


def _render_welcome(home: Path, csrf: str) -> bytes:
    """Render the wizard Welcome shell.

    The view embedded here is the trust snapshot (no raw credentials)
    plus the routes the wizard exposes. Continue navigates to Security;
    only Next's CSRF-protected POST records the dashboard visit.

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
        diag_text = f"{posture_warning} Run `krellbot doctor` for a real diagnostic."
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


def _render_next(home: Path, csrf: str, *, status_message: str | None = None) -> bytes:
    """Render the wizard Next page, including the activation form."""
    snap = trust.trust_snapshot(home)
    view = {
        "view": "wizard.next",
        "trust": snap,
        "exit_routes": {"docs": "out/docs", "source": "out/source"},
    }
    payload = _embed_json(view)
    shown = status_message if status_message in kb_activate.SAFE_MESSAGES else ""
    body = _NEXT_TEMPLATE
    body = body.replace("__VIEW_JSON__", payload)
    body = body.replace("__ACTIVATE_STATUS__", html.escape(shown))
    body = body.replace('name="csrf"', f'name="csrf" value="{csrf}"')
    return body.encode("utf-8")


def _render_keys(home: Path, csrf: str, *, status_message: str | None = None) -> bytes:
    """Render the wizard Exchange-key page and its honest status block.

    The page is the GET target for the slice-C exchange step. It renders
    server-side so a no-JS user sees the same affordances. The status
    block is built from ``keys_status.read_status`` — that helper NEVER
    probes a venue and NEVER reads the keyring (not even a presence
    check); it reports only the durable, nonsecret metadata recorded by
    an earlier POST. The claim is HISTORICAL: "last stored through wizard
    at <timestamp>; current key presence not checked". A missing or
    invalid row renders "unknown; not currently verified" — never a
    live-connection framing and never "no key stored" (current keyring
    presence is deliberately not checked on GET).

    ``status_message`` is set when the GET follows a 303 PRG from the
    POST handler; it carries one of the closed per-outcome safe messages
    (or ``None``). The message is server-rendered into HTML only after
    it is validated against the closed safe-message set; raw form input
    is never echoed here.
    """
    snap = trust.trust_snapshot(home)
    raw_status = keys_status.read_status(home)
    # Build a presentation-only status dict for the bootstrap JSON. We do
    # NOT include the raw key/secret bytes — only booleans, timestamps,
    # and the closed per-outcome message (all validated by keys_status at
    # the read boundary: closed status enum, closed safe-message set,
    # strict ISO-8601 UTC timestamp).
    safe_status: dict[str, dict[str, object | None]] = {}
    for venue, row in raw_status.items():
        safe_status[venue] = {
            "stored": bool(row.get("stored")),
            "verified_at": row.get("verified_at"),
            "last_status": row.get("last_status"),
            "last_message": row.get("last_message"),
        }

    from krellbot import keys_onboarding

    validated_status_message: str | None = None
    if status_message is not None and status_message in keys_onboarding.SAFE_MESSAGES:
        validated_status_message = status_message

    def _row_text(venue: str) -> str:
        row = raw_status.get(venue, {})
        stored = bool(row.get("stored"))
        verified_at = row.get("verified_at")
        if not stored or not isinstance(verified_at, str) or not verified_at:
            # Unknown / not currently verified. We deliberately do NOT
            # render "no key stored": that would assert current keyring
            # absence, which a credential-free GET never established.
            return "unknown; not currently verified"
        return f"last stored through wizard at {_h(verified_at)}; current key presence not checked"

    # Compute a short, human-readable summary of the local trust
    # posture so the page can honestly report the backend and home mode
    # alongside the per-venue key status. The summary is built from
    # the existing trust snapshot — no secrets, no key bytes.
    backend_name = str(snap.get("keychain_backend") or "(unknown)")
    home_path = str(snap.get("home") or "(unset)")
    home_mode = str(snap.get("home_mode") or "unknown on this OS")
    posture_ok = bool(snap.get("posture_ok"))
    posture_warning = str(snap.get("posture_warning") or "")
    if posture_ok:
        posture_summary = "All posture checks passed."
        posture_class = "trust-ok"
    else:
        posture_summary = (
            f"{posture_warning} Run `krellbot doctor` for a real diagnostic."
            if posture_warning
            else "Run `krellbot doctor` for a real diagnostic."
        )
        posture_class = "trust-fail"

    body = _KEYS_TEMPLATE
    body = body.replace("__STATUS_KRAKEN__", _h(_row_text("kraken")))
    body = body.replace("__STATUS_COINBASE__", _h(_row_text("coinbase")))
    body = body.replace("__STATUS_BACKEND__", _h(backend_name))
    body = body.replace("__STATUS_HOME__", _h(home_path))
    body = body.replace("__STATUS_HOME_MODE__", _h(home_mode))
    body = body.replace("__STATUS_POSTURE_SUMMARY__", _h(posture_summary))
    body = body.replace("__STATUS_POSTURE_CLASS__", posture_class)
    if validated_status_message is not None:
        body = body.replace("__STATUS_MESSAGE__", _h(validated_status_message))
        body = body.replace("__STATUS_MESSAGE_HIDDEN__", "")
    else:
        body = body.replace("__STATUS_MESSAGE__", "")
        body = body.replace("__STATUS_MESSAGE_HIDDEN__", "hidden")
    body = body.replace('name="csrf"', f'name="csrf" value="{csrf}"')

    view = {
        "view": "wizard.keys",
        "trust": snap,
        "status": safe_status,
        "status_message": validated_status_message,
    }
    payload = _embed_json(view)
    body = body.replace("__VIEW_JSON__", payload)
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
        return f"<a {attrs}>{label}</a>"

    nav_active = (
        f"{_nav_link('welcome', 'Welcome')}"
        f"{_nav_link('security', 'Security')}"
        f"{_nav_link('keys', 'Exchange')}"
        f"{_nav_link('next', 'Next')}"
        f"{_nav_link('dashboard', 'Dashboard')}"
        f'<a href="out/docs">Docs</a>'
        f'<a href="out/source">Source</a>'
    )

    # Build a stepper with 4 numbered dots showing past/current/upcoming.
    # The current step carries the `aria-current="step"` attribute so a
    # screen reader announces it.
    stepper_steps = ["welcome", "security", "keys", "next"]
    stepper_html = '<ol class="stepper" aria-label="Wizard progress">'
    for i, step in enumerate(stepper_steps, start=1):
        attrs = f'class="stepper-step" data-step="{step}"'
        if step == route:
            attrs += ' aria-current="step"'
        stepper_html += f"<li {attrs}>{i}</li>"
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
        '  <p class="muted">Local dashboard on loopback. Submitting the Exchange form contacts only the selected venue.</p>\n'
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
    '  <section id="welcome-section">\n'
    "    <h2>Welcome</h2>\n"
    "    <p>You are running krellbot for the first time on this loopback port.</p>\n"
    '    <ol class="truth-list" aria-label="What krellbot is">\n'
    "      <li><strong>Free, open-source local engine.</strong> The code you have runs on this machine; krellbot.dev does not host a service.</li>\n"
    "      <li><strong>Keys stay on this machine.</strong> Exchange API keys are stored in the local keychain; they are never sent to krellbot.dev.</li>\n"
    "      <li><strong>Official packs are optional and recommended.</strong> You can run any pack file you trust; official packs are not required.</li>\n"
    "    </ol>\n"
    '    <p class="muted">Step 1 of 4 &middot; <a href="security">Continue to security</a> &middot; <a href="next">Skip to next</a></p>\n'
    "  </section>\n",
    route="welcome",
)


_SECURITY_TEMPLATE = _wizard_html(
    '  <section id="wizard-security-section">\n'
    "    <h2>Security posture</h2>\n"
    "    <p>This is read-only. No keys, no balances, no orders leave the box.</p>\n"
    '    <dl id="trust-list">\n'
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
    '      <dt>Key permissions <span class="muted">(required, not validated)</span></dt>\n'
    '      <dd id="trust-permissions">Trade-only permission required, withdraw permission never granted. No exchange key is probed from this page.</dd>\n'
    "    </dl>\n"
    '    <p id="trust-diagnostic" class="__DIAGNOSTIC_CLASS__" __DIAGNOSTIC_HIDDEN__>__DIAGNOSTIC__</p>\n'
    '    <p class="muted">Step 2 of 4 &middot; <a href="welcome">Back</a> &middot; <a href="keys">Continue to exchange</a> &middot; <a href="next">Skip to next</a></p>\n'
    "  </section>\n",
    route="security",
)


_NEXT_TEMPLATE = _wizard_html(
    '  <section id="wizard-next-section">\n'
    "    <h2>Next steps</h2>\n"
    "    <p>When you are ready, enter the dashboard.</p>\n"
    '    <form id="form-enter-dashboard" action="enter-dashboard" method="POST" class="enter-form">\n'
    '      <input type="hidden" name="csrf">\n'
    '      <button type="submit">Enter dashboard</button>\n'
    "    </form>\n"
    "    <h3>Activation key</h3>\n"
    '    <p id="activate-status">__ACTIVATE_STATUS__</p>\n'
    '    <form id="form-activate" action="activate" method="POST">\n'
    '      <label for="activation-key">Activation key\n'
    '        <input id="activation-key" type="password" name="activation_key" autocomplete="off" required>\n'
    "      </label>\n"
    '      <input type="hidden" name="csrf">\n'
    '      <button type="submit">Redeem key</button>\n'
    "    </form>\n"
    '    <p class="muted">Redeem sends the activation key in one HTTPS POST body to '
    "krellbot.dev/api/license, then one more POST body to krellbot.dev/api/catalog "
    "if the license verifies. The key is not placed in a URL. Exchange API keys "
    "are not sent.</p>\n"
    "    <h3>Not in this release</h3>\n"
    '    <ul aria-label="What this release does not do">\n'
    "      <li>An OS scheduler installer. Today, install the existing service unit with "
    "<code>krellbot service install</code>. The dashboard does not schedule ticks.</li>\n"
    "    </ul>\n"
    "    <h3>The free path today</h3>\n"
    "    <ul>\n"
    "      <li>Run <code>krellbot ui</code> from a terminal at any time to relaunch this UI.</li>\n"
    "      <li>Run <code>krellbot doctor</code> for a complete readiness check.</li>\n"
    "    </ul>\n"
    '    <p class="muted">Step 4 of 4 &middot; <a href="keys">Back</a></p>\n'
    "  </section>\n",
    route="next",
)


_KEYS_TEMPLATE = _wizard_html(
    '  <section id="wizard-keys-section">\n'
    "    <h2>Exchange keys</h2>\n"
    "    <p>Add or rotate an exchange API key from this page. The form below "
    "sends one credential-bearing POST; the server probes the venue and "
    "stores the result only if the venue confirms trade-only permissions.</p>\n"
    "    <h3>Instructions</h3>\n"
    '    <ol class="keys-instructions" aria-label="How to add an exchange key">\n'
    "      <li>Create a <strong>read-only / trade-only</strong> API key on your "
    "exchange (Kraken or Coinbase). <strong>Withdraw</strong> and "
    "<strong>transfer</strong> permissions must stay off.</li>\n"
    "      <li>Paste the API key and the API secret into the form below. "
    "The browser posts to this loopback dashboard. krellbot.dev never receives "
    "your exchange credentials.</li>\n"
    "      <li>The server sends an authenticated HTTPS request to the selected "
    "venue (Kraken or Coinbase) to check trade-only permissions. On success, "
    "it stores the pair in your local OS keychain. The page never echoes "
    "your secret back.</li>\n"
    "      <li>If a complete venue credential pair is also set in environment "
    "variables, that pair takes precedence over the keychain when trading. "
    "The live gate still checks the loaded key's permissions.</li>\n"
    "      <li>If the venue refuses (withdraw, trade-off, invalid, etc.), the "
    "keyring is left unchanged and the failure is shown below.</li>\n"
    "    </ol>\n"
    '    <form id="form-keys-add" action="keys/add" method="POST" autocomplete="off">\n'
    '      <input type="hidden" name="csrf">\n'
    '      <label for="keys-venue">Venue\n'
    '        <select id="keys-venue" name="venue" required>\n'
    '          <option value="kraken">Kraken</option>\n'
    '          <option value="coinbase">Coinbase</option>\n'
    "        </select>\n"
    "      </label>\n"
    '      <label for="keys-api-key">API key\n'
    '        <input id="keys-api-key" type="text" name="api_key" autocomplete="off" required>\n'
    "      </label>\n"
    '      <label for="keys-api-secret">API secret\n'
    '        <input id="keys-api-secret" type="password" name="api_secret" autocomplete="off" required>\n'
    "      </label>\n"
    '      <button type="submit">Add / rotate key</button>\n'
    "    </form>\n"
    "    <h3>Local trust posture</h3>\n"
    '    <dl id="keys-trust" aria-label="Local trust posture">\n'
    "      <dt>Keychain backend</dt>\n"
    '      <dd id="keys-trust-backend">__STATUS_BACKEND__</dd>\n'
    "      <dt>Data home</dt>\n"
    '      <dd id="keys-trust-home">__STATUS_HOME__</dd>\n'
    "      <dt>Home mode</dt>\n"
    '      <dd id="keys-trust-home-mode">__STATUS_HOME_MODE__</dd>\n'
    "    </dl>\n"
    '    <p id="keys-trust-summary" class="__STATUS_POSTURE_CLASS__">__STATUS_POSTURE_SUMMARY__</p>\n'
    "    <h3>Per-venue status</h3>\n"
    '    <dl id="keys-status" aria-label="Key onboarding status">\n'
    "      <dt>Kraken</dt>\n"
    '      <dd id="keys-status-kraken">__STATUS_KRAKEN__</dd>\n'
    "      <dt>Coinbase</dt>\n"
    '      <dd id="keys-status-coinbase">__STATUS_COINBASE__</dd>\n'
    "    </dl>\n"
    '    <p id="keys-status-message" class="status-message" __STATUS_MESSAGE_HIDDEN__>__STATUS_MESSAGE__</p>\n'
    "    <h3>What this page does not do</h3>\n"
    "    <ul>\n"
    "      <li>It does not run a live venue probe on every load. The status "
    "block reads the durable timestamp from the last POST, never a fresh "
    "request to Kraken or Coinbase.</li>\n"
    "      <li>It does not claim a live-connection state. With a durable "
    "timestamp, the row reads 'last stored through wizard at &lt;ts&gt;; "
    "current key presence not checked'. Without one, it reads 'unknown; "
    "not currently verified'. It never says 'currently connected' and "
    "never claims a key is absent (CLI-side rotation is not detectable "
    "without a credential read).</li>\n"
    "      <li>It does not echo credentials, errors, or stack traces back to "
    "the page.</li>\n"
    "    </ul>\n"
    '    <p class="muted">Step 3 of 4 &middot; <a href="security">Back</a> &middot; <a href="next">Continue to next</a></p>\n'
    "  </section>\n",
    route="keys",
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


def _activate_status_from_query(raw_query: str) -> str | None:
    """Return an activation safe-message, or None. Never echoes a key."""
    if not raw_query:
        return None
    pairs = urllib.parse.parse_qs(raw_query, keep_blank_values=False)
    candidates = pairs.get("status") or []
    if not candidates:
        return None
    candidate = candidates[0]
    if candidate in kb_activate.SAFE_MESSAGES:
        return candidate
    return None


def _status_from_query(raw_query: str) -> str | None:
    """Return the closed safe-message `status` value from a query string.

    The 303 PRG from ``POST /<token>/keys/add`` carries the closed
    status message in the URL so the GET can render it. Anything outside
    ``keys_onboarding.SAFE_MESSAGES`` is rejected at this boundary so an
    arbitrary `?status=...` value (e.g. a tampered URL or a leftover from
    a previous build) cannot reach the renderer.
    """
    from krellbot import keys_onboarding

    if not raw_query:
        return None
    pairs = urllib.parse.parse_qs(raw_query, keep_blank_values=False)
    candidates = pairs.get("status") or []
    if not candidates:
        return None
    candidate = candidates[0]
    if candidate in keys_onboarding.SAFE_MESSAGES:
        return candidate
    return None


def _h(value: str) -> str:
    """HTML-escape a string for safe insertion into the wizard shell.

    The trust snapshot's values are paths and class names from the
    local machine — the snapshot module never reads raw secrets — but
    we still escape on the way into HTML so a keychain backend whose
    class path somehow contains ``<`` cannot inject markup into the
    visible page.
    """
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


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
            raw_query = self.path.split("?", 1)[1] if "?" in self.path else ""
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
                self._route_get(rest, port, raw_query)
            else:
                self._route_post(rest, form)

        # ---- GET routes -------------------------------------------------

        def _route_get(self, rest: str, port: int, raw_query: str = "") -> None:
            # Strip a leading slash for clean comparison.
            route = rest.lstrip("/")
            # Wizard routes: welcome / security / next / keys.
            if route in _WIZARD_ROUTES:
                self._serve_wizard(route, port, raw_query)
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

        def _serve_wizard(self, route: str, port: int, raw_query: str = "") -> None:
            """Serve a wizard view by name. Sets cookies so the wizard's
            POST /enter-dashboard can satisfy the existing CSRF gate.
            """
            home = server_config.home
            csrf = server_config.csrf
            if route == "welcome":
                body = _render_welcome(home, csrf)
            elif route == "security":
                body = _render_security(home, csrf)
            elif route == "next":
                body = _render_next(
                    home,
                    csrf,
                    status_message=_activate_status_from_query(raw_query),
                )
            elif route == "keys":
                # The keys page may carry a closed `?status=<safe_message>`
                # query after a 303 PRG. Parse it here; the renderer
                # validates against SAFE_MESSAGES so an arbitrary value
                # is dropped.
                body = _render_keys(home, csrf, status_message=_status_from_query(raw_query))
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
            elif rest == "paper-arm":
                self._do_paper_arm(form)
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
            elif rest == "keys/add":
                self._do_keys_add(form)
            elif rest == "activate":
                self._do_activate(form)
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

        def _do_keys_add(self, form: dict) -> None:
            """One-shot credential-bearing POST → probe-and-store → PRG 303.

            The cookie/CSRF/Origin/Host gate is enforced upstream in
            ``_handle``; by the time we reach here the request is
            already authenticated. The flow:

                1. Validate venue ∈ {kraken, coinbase}; missing/blank
                   fields → 400 (still 303 PRG so a no-JS browser
                   bounces back to the status page, never echoes the
                   form value).
                2. Resolve the active keyring backend. Native OS
                   keychains only — anything else (null / fail /
                   plaintext / FakeKeyring in production) is rejected
                   via the UNSUPPORTED_BACKEND result.
                3. Call ``keys_onboarding.probe_and_store`` with
                   ``probe=None`` so the canonical CLI probe is the
                   single authority for the trade-only claim. We
                   deliberately do NOT honour any caller-supplied probe
                   callable; the wizard layer is a closed entry point.
                4. Persist the outcome via ``keys_status.record_outcome``
                   so a later GET (no live probe) can render the historical
                   ``last stored through wizard at <ts>; current key
                   presence not checked`` claim — never a live
                   ``currently connected`` framing.
                5. 303 PRG to ``/<token>/keys``. The Location carries a
                   fragment-style status_message that survives the
                   redirect (query string is logged by some upstreams,
                   so we use the path with a query token — a closed
                   per-outcome safe message).

            On any error path the response body is empty and the
            Location does not include the form values. The CSRF/Origin/
            Host rejections happen upstream and never reach this method.
            """
            venue = (form.get("venue") or [""])[0].strip().lower()
            api_key = (form.get("api_key") or [""])[0]
            api_secret = (form.get("api_secret") or [""])[0]
            # Use a sentinel so a bad input becomes a 303 with the
            # INVALID_ARGUMENT safe message rather than a 400 that
            # leaves the user on a dead-end error page.
            self._process_keys_add(venue, api_key, api_secret)

        def _process_keys_add(self, venue: str, api_key: str, api_secret: str) -> None:
            """Run the probe-and-store pipeline and 303 PRG to the
            credential-free status page."""
            from krellbot import keys_onboarding

            home = server_config.home

            # Resolve the active keyring backend (production: native
            # OS only; tests inject FakeKeyring via the env var that
            # conftest.py sets). We deliberately do NOT honour the
            # ``allow_injected_fake_backend`` opt-in here — the wizard
            # path is closed.
            import keyring as _keyring

            backend = _keyring.get_keyring()
            # The wizard is the canonical closed entry point: probe=None,
            # allow_injected_fake_backend=False. An injected callable or
            # a forged fake-keyring backend cannot bypass the gate.
            result = keys_onboarding.probe_and_store(
                venue,
                api_key,
                api_secret,
                keyring_backend=backend,
                probe=None,
                allow_injected_fake_backend=False,
            )

            # Persist the durable status so the next GET (no live
            # probe) can render the historical
            # ``last stored through wizard at <ts>; current key
            # presence not checked`` claim — never a live
            # ``currently connected`` framing.
            try:
                keys_status.record_outcome(
                    home,
                    venue,
                    status=result.status.value,
                    message=result.message,
                )
            except OSError:
                # OSError on record_outcome does NOT undo a successful
                # store — the keyring is already authoritative. The
                # status snapshot is presentation-only; a failure to
                # write it surfaces as "unknown; not currently verified" on the
                # next GET, which is honest about the gap.
                pass

            # 303 PRG. Location carries the closed status_message via
            # the query string so the GET can render it. ``message``
            # is one of SAFE_MESSAGES (enforced inside the result
            # dataclass), so it is safe to embed in a URL.
            location = f"/{server_config.token}/keys?status={urllib.parse.quote(result.message)}"
            self._send_keys_redirect(location)

        def _send_keys_redirect(self, location: str) -> None:
            """Send a 303 PRG with the wizard security headers and a
            ``Cache-Control: no-store`` so no intermediate cache will
            replay the credential-bearing POST body."""
            self.send_response(303, "See Other")
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            for name, value in _HTML_SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        def _do_activate(self, form: dict) -> None:
            """Token-gated activation-key redeem.

            The cookie/CSRF/Origin/Host gate is enforced upstream in
            ``_handle``; by the time we reach here the request is
            already authenticated.

            The flow is intentionally minimal:

                1. Read ``activation_key`` once. A blank value is
                   rejected with 400 (no PRG — the form is invalid).
                2. Delegate to :func:`krellbot.ui.activate.redeem`,
                   which composes ``cli.check_license`` and
                   ``cli.download_catalog`` (no shelling out, no second
                   license format). The key never appears in any
                   helper exception message or local frame after the
                   call returns.
                3. 303 PRG to ``/<token>/next`` with a closed safe
                   message in the query string. The key is NOT in the
                   query string, NOT in any header value, and NOT in
                   the (empty) response body.

            On a blank key we 400 instead of 303 — the brief requires
            the key not to be echoed, and a 400 makes the failure
            surface unambiguous to the operator without a misleading
            PRG to a status page.
            """
            activation_key = (form.get("activation_key") or [""])[0]
            if not isinstance(activation_key, str) or not activation_key.strip():
                self._send_status(400, "Bad Request")
                return

            outcome = kb_activate.redeem(
                activation_key.strip(),
                home=server_config.home,
                now=int(time.time()),
            )

            # 303 PRG. The closed safe message rides in the query
            # string; the renderer validates against SAFE_MESSAGES so
            # an attacker-controlled value cannot reach the page.
            location = f"/{server_config.token}/next?status={urllib.parse.quote(outcome.message)}"
            self.send_response(303, "See Other")
            self.send_header("Location", location)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            for name, value in _HTML_SECURITY_HEADERS:
                self.send_header(name, value)
            self.end_headers()

        def _do_paper_arm(self, form: dict) -> None:
            """Paper-arm a pack from the dashboard.

            The cookie/CSRF/Origin/Host gate is enforced upstream in
            ``_handle``. This route:

              * resolves ``pack_id`` to an on-disk pack path via the
                local ``<home>/packs/`` tree (legacy packs are
                refused with 403);
              * rejects anything that is not paper (live arm from the
                UI is a CLI-only gate, unchanged from slice B);
              * delegates to :func:`krellbot.run.arm_pack`, which is
                the single authority for cap/costmin checks and
                config persistence. The dashboard does not have its
                own arm logic — it MUST route through the engine so
                every existing guarantee applies uniformly.

            Missing/blank inputs are 400. The engine's own refusal
            contract (cap cannot meet costmin, second pack on same
            venue+pair) surfaces as 400 here because the engine prints
            refusal prose to stdout; a 200 with engine prose in the
            body would be a misleading happy path.

            The brief is explicit: a missing license cache MUST NOT
            block paper-arm of a local custom pack. We do not call
            ``license.entries_allowed`` here, and we do not require a
            key in ``state.json``. The engine's existing
            ``requires_license`` flag is read from the pack on disk
            and only enforced inside ``tick`` (where it gates
            entries, not the arm itself).
            """
            pack_id = (form.get("pack_id") or [""])[0].strip()
            venue = (form.get("venue") or [""])[0].strip().lower()
            paper_balance_raw = (form.get("paper_balance") or [""])[0].strip()
            if not pack_id or not venue or not paper_balance_raw:
                self._send_status(400, "Bad Request")
                return
            if venue not in {"kraken", "coinbase"}:
                self._send_status(400, "Bad Request")
                return

            pack_path = ui_packs.resolve_pack_path(server_config.home, pack_id)
            if pack_path is None:
                # Either the id has no on-disk match or it is a
                # legacy pack. ``resolve_pack_path`` skips legacy
                # packs by design; this also serves as the 404 for
                # unknown ids.
                self._send_status(404, "Not Found")
                return

            # Legacy-pack sanity: ``resolve_pack_path`` already skips
            # them, but we defend the route against future schema
            # changes by re-checking at the route boundary.
            try:
                peek = json.loads(pack_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._send_status(400, "Bad Request")
                return
            from krellbot.pack import lint as _pack_lint

            if not isinstance(peek, dict) or _pack_lint.is_legacy(peek):
                self._send_status(403, "Forbidden")
                return

            try:
                paper_balance = Decimal(paper_balance_raw)
            except (ValueError, ArithmeticError):
                self._send_status(400, "Bad Request")
                return

            from krellbot.run import arm_pack as _arm_pack

            rc = _arm_pack(
                pack_path,
                venue=venue,
                mode="paper",
                paper_balance=paper_balance,
                home=server_config.home,
            )
            if rc == 0:
                self._send_text(200, "armed")
                return
            # Engine refusal (costmin, second pack, etc.). 400 keeps
            # the contract honest — the arm did not happen.
            self._send_status(400, "Bad Request")

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


class _LoopbackHTTPServer(http.server.ThreadingHTTPServer):
    """Bind locally without HTTPServer's unnecessary reverse DNS lookup."""

    def server_bind(self) -> None:
        # HTTPServer.server_bind calls socket.getfqdn(127.0.0.1), which can
        # block on a misconfigured resolver even though we never use the
        # resolved name. Preserve TCPServer's bind and HTTPServer's fields.
        socketserver.TCPServer.server_bind(self)
        self.server_name = _BIND_HOST
        self.server_port = self.server_address[1]


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
        self._server: _LoopbackHTTPServer | None = None
        self._thread: threading.Thread | None = None
        # Defer socket bind to start() so a failed start doesn't leak.

    def start(self) -> None:
        if self._server is not None:
            return
        config = _ServerConfig(self.token, self.csrf, self._home)
        handler_cls = _make_handler(config)
        self._server = _LoopbackHTTPServer((_BIND_HOST, self._requested_port), handler_cls)
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

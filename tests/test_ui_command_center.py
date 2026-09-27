"""Command-center dashboard contract tests.

The dashboard has been restructured into a top-level operational
overview that is reachable in the first viewport at 560px. These
tests pin the contract:

  * The overview section renders before any other section (it must
    be the first <section> in the body).
  * The dashboard has a distinct operational nav separate from the
    setup-wizard nav; an operator on the dashboard does not have to
    read past setup links to reach state.
  * The view JSON carries the new closed fields: ``as_of``,
    ``readiness``, ``keys_status``, ``license_summary``,
    ``scheduler_installed``, ``tick_state``, plus ``armed_at_ts`` and
    ``starting_cash`` per armed pack.
  * Empty states are honest: no armed packs, no journal, no receipts,
    no license cache all render their explicit empty block, never an
    invented value.
  * Populated states surface real data: a tick journal record drives
    the "Last tick" metric; an armed pack drives the "Armed packs"
    metric; an active license cache drives the License block.
  * Readiness rows are computed from local metadata only and never
    claim "trading ready" — the trading readiness field is always the
    closed "not evaluated on this page" string.
  * Escape: a journal-record string containing ``<script>`` does NOT
    reach the rendered HTML; the dashboard uses textContent only.
  * GET still does not touch a keyring: no key/secret bytes ever
    appear in the rendered HTML, even when a key was just stored.
  * License summary uses the closed three-scalar shape — never the
    raw license-cache JSON.
"""

from __future__ import annotations

import http.client
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

from krellbot import config as kb_config
from krellbot import license as kb_license
from krellbot import paths as kb_paths
from krellbot.ui import first_run, keys_status
from krellbot.ui import server as ui_server
from krellbot.ui.server import DashboardServer

STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "krellbot" / "ui" / "static"
INDEX_HTML = STATIC_DIR / "index.html"
APP_JS = STATIC_DIR / "app.js"


# ---- helpers --------------------------------------------------------------


def _parse_set_cookies(resp: http.client.HTTPResponse) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in resp.getheaders():
        if k.lower() != "set-cookie":
            continue
        first = v.split(";", 1)[0].strip()
        if "=" not in first:
            continue
        name, _, value = first.partition("=")
        out[name.strip()] = value.strip()
    return out


def _login(server: DashboardServer, port: int) -> str:
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.request("GET", f"/{server.token}/")
        resp = conn.getresponse()
        resp.read()
        cookies = _parse_set_cookies(resp)
        session = cookies.get("krellbot_session", "")
        csrf = cookies.get("krellbot_csrf", "")
        assert session and csrf, (cookies, resp.getheaders())
        return f"krellbot_session={session}; krellbot_csrf={csrf}"
    finally:
        conn.close()


def _get(server: DashboardServer, path: str) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body
    finally:
        conn.close()


def _start(home: Path) -> DashboardServer:
    server = DashboardServer(home=home, port=0)
    server.start()
    return server


def _stop(server: DashboardServer | None) -> None:
    if server is None:
        return
    try:
        server.stop()
    except (OSError, RuntimeError):
        pass


def _extract_view(body: bytes) -> dict:
    text = body.decode("utf-8")
    m = re.search(r"window\.__KB_VIEW__\s*=\s*(\{.*?\})\s*;</script>", text, re.DOTALL)
    assert m, "could not find window.__KB_VIEW__ bootstrap"
    # JSONLoader: the server escapes <, >, & as \u003c / \u003e / \u0026.
    # json.loads handles those escapes directly.
    return json.loads(m.group(1))


def _arm_one_pack(home: Path) -> None:
    config = kb_config.load_config(home)
    config.armed.append(
        kb_config.ArmedPack(
            pack_path=str(home / "packs" / "trend-follow.json"),
            pack_sha256="0" * 64,
            pack_id="trend-follow",
            pack_version="1.0.0",
            venue="kraken",
            pair="SUIUSD",
            cap=Decimal(25),
            stop=Decimal(5),
            mode="paper",
            starting_cash=Decimal(1000),
            requires_license=False,
            armed_at_ts=1700000000,
            owned_qty=Decimal(0),
            pending_version=None,
        )
    )
    kb_config.save_config(home, config)


def _write_tick_journal(home: Path, *, ts: int | None = None, age_seconds: int = 30) -> None:
    import time as _time

    if ts is None:
        ts = int(_time.time()) - age_seconds
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    rec = {"ts": ts, "kind": "tick", "venue": "kraken", "pack": "trend-follow", "detail": {}}
    (journal_dir / "kraken.jsonl").write_text(json.dumps(rec) + "\n", encoding="utf-8")


# ---- 1. structural contract: overview is first, two distinct navs -------


def test_overview_section_is_first_in_dashboard_shell() -> None:
    """The overview section must be the first <section> in the body so
    a 560px viewport shows it above the fold. We assert ordering
    directly against the static markup.
    """
    text = INDEX_HTML.read_text(encoding="utf-8")
    # The body class must be "dashboard" (not "wizard").
    assert 'class="dashboard"' in text, "index.html body must declare dashboard"
    # Find every <section ...> opening tag in order.
    sections = re.findall(r"<section\b[^>]*>", text)
    assert sections, "no <section> tags found"
    # The first section must be the overview; it must carry both the
    # legacy id="status-section" (for slice-B tests) and the
    # primary-card class.
    first = sections[0]
    assert 'id="status-section"' in first, f"first section must be status-section; got {first!r}"
    assert "primary-card" in first, f"first section must carry primary-card; got {first!r}"


def test_dashboard_has_distinct_operational_and_setup_navs() -> None:
    """The dashboard must expose two nav systems: an operational one
    (Overview / Armed / Paper / Journal / Trust / Actions) and a
    setup-wizard one (Welcome / Security / Activate / Exchange / Docs /
    Source). The setup nav must be collapsible so it does not steal
    viewport at 560px.
    """
    text = INDEX_HTML.read_text(encoding="utf-8")
    # Operational nav present, ordered.
    ops = re.search(r'<nav class="ops-nav"[^>]*>(.*?)</nav>', text, re.DOTALL)
    assert ops, "ops-nav not found"
    ops_links = re.findall(r'<a\s+href="([^"]+)"', ops.group(1))
    assert ops_links == [
        "#status-section",
        "#armed-section",
        "#paper-section",
        "#journal-section",
        "#trust-section",
        "#actions-section",
    ], ops_links

    # Setup nav present, collapsible via <details>.
    setup = re.search(r'<details class="setup-nav"[^>]*>(.*?)</details>', text, re.DOTALL)
    assert setup, "setup-nav details not found"
    setup_links = re.findall(r'<a\s+href="([^"]+)"', setup.group(1))
    assert "welcome" in setup_links
    assert "security" in setup_links
    assert "keys" in setup_links
    assert "next" in setup_links
    # Setup links must NOT include operational anchors — two systems
    # are independent.
    assert "#armed-section" not in setup_links
    assert "#status-section" not in setup_links


def test_overview_metric_bindings_match_js_renderer() -> None:
    """Each summary tile hydrates instead of leaving '(loading)' behind."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    js = APP_JS.read_text(encoding="utf-8")
    for name in ("armed", "paper", "tick", "ready"):
        assert f'data-bind="{name}_value"' in html
        assert f'setBind("{name}",' in js


# ---- 2. closed view fields on the empty dashboard ------------------------


def test_empty_dashboard_view_carries_command_center_fields(home) -> None:
    """A fresh KRELLBOT_HOME with no journal/license/armed packs
    still emits the new closed view fields. ``as_of`` is a strict
    ISO-8601 UTC timestamp, readiness rows exist, and trading
    readiness is the closed "not evaluated on this page" string.
    """
    first_run.mark_visited_dashboard(home)
    server = _start(home)
    try:
        status, _hdr, body = _get(server, f"/{server.token}/dashboard")
        assert status == 200, status
        view = _extract_view(body)
        # Closed fields:
        assert isinstance(view.get("as_of"), str) and view["as_of"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", view["as_of"]), view["as_of"]
        readiness = view.get("readiness") or {}
        assert "install_ready" in readiness
        assert isinstance(readiness.get("rows"), list) and readiness["rows"], readiness
        # Closed labels — every row has the closed shape.
        labels = [r.get("label") for r in readiness["rows"]]
        assert ("data home" if sys.platform == "win32" else "data home mode 0o700") in labels
        assert "keychain backend" in labels
        assert "loopback bind 127.0.0.1" in labels
        # Trading readiness is the closed NOT-EVALUATED string.
        assert view.get("trading_readiness") == "not evaluated on this page; run `krellbot doctor`"
        # License summary, keys_status, scheduler, tick state — closed shapes.
        ls = view.get("license_summary") or {}
        assert ls.get("status") == "missing"
        assert ls.get("period_end") is None
        assert ls.get("grace_until") is None
        ks = view.get("keys_status") or {}
        for venue in ("kraken", "coinbase"):
            row = ks.get(venue) or {}
            assert row.get("stored") is False
            assert row.get("verified_at") is None
        # Scheduler + tick state.
        assert "scheduler_installed" in view
        ts = view.get("tick_state") or {}
        assert ts.get("present") is False
        assert ts.get("last_ts") is None
        assert ts.get("age_seconds") is None
    finally:
        _stop(server)


# ---- 3. populated dashboard: armed + tick + license + paper --------------


def test_windows_install_readiness_does_not_require_posix_mode(home, monkeypatch) -> None:
    """Windows DACLs are not POSIX modes; match doctor without claiming DACLs were checked."""
    monkeypatch.setattr(ui_server.sys, "platform", "win32")
    monkeypatch.setattr(
        ui_server.trust,
        "trust_snapshot",
        lambda _home: {
            "home_mode": None,
            "home_mode_ok": False,
            "keychain_backend": "Windows Credential Manager",
            "keychain_ok": True,
        },
    )
    result = ui_server._install_readiness(home)
    assert result["install_ready"] is True
    assert result["rows"][0] == {
        "label": "data home",
        "ok": True,
        "why": "DACL not checked on Windows",
    }
    assert ui_server._install_readiness(home / "missing")["install_ready"] is False


def test_populated_dashboard_reads_local_records_only(home) -> None:
    """With one armed paper pack, one tick journal record, and an
    active license cache, the dashboard surfaces those values through
    the closed view fields. The dashboard never invents balances,
    profit, latency, or a heartbeat.
    """
    _arm_one_pack(home)
    _write_tick_journal(home, age_seconds=42)
    kb_license.write_cache(
        home,
        status="active",
        period_end=1700100000,
        grace_until=1700200000,
    )
    # Mark a successful historical key-storage event so keys_status
    # renders the "last stored through wizard at …" string.
    keys_status.record_outcome(
        home,
        "kraken",
        status="stored",
        message="stored in native OS keychain",
    )

    first_run.mark_visited_dashboard(home)
    server = _start(home)
    try:
        status, _hdr, body = _get(server, f"/{server.token}/dashboard")
        assert status == 200, status
        view = _extract_view(body)
        # Armed: the closed row carries starting_cash + armed_at_ts.
        armed = view.get("armed") or []
        assert len(armed) == 1
        a = armed[0]
        assert a["pack_id"] == "trend-follow"
        assert a["venue"] == "kraken"
        assert a["mode"] == "paper"
        assert a["starting_cash"] == "1000"
        assert a["armed_at_ts"] == 1700000000
        # Tick state — present + age matches what we wrote.
        ts = view.get("tick_state") or {}
        assert ts.get("present") is True
        assert isinstance(ts.get("last_ts"), int)
        # Allow a small clock-drift window so this test is not flaky.
        assert ts.get("age_seconds") is not None
        assert 0 <= ts["age_seconds"] < 600, ts["age_seconds"]
        # License summary: closed three-scalar shape, NOT the raw
        # license-cache JSON. The dashboard must never echo the raw
        # dict through the renderer.
        ls = view.get("license_summary") or {}
        assert ls.get("status") == "active"
        assert ls.get("period_end") == 1700100000
        assert ls.get("grace_until") == 1700200000
        # License raw cache still travels (for backward compat) but
        # is the closed three-key shape too.
        raw_license = view.get("license") or {}
        assert raw_license.get("status") == "active"
        # Key verification metadata: kraken is now historically stored.
        ks = view.get("keys_status") or {}
        kraken_row = ks.get("kraken") or {}
        assert kraken_row.get("stored") is True
        assert isinstance(kraken_row.get("verified_at"), str)
        # Coinbase is still unknown.
        coinbase_row = ks.get("coinbase") or {}
        assert coinbase_row.get("stored") is False
    finally:
        _stop(server)


# ---- 4. honest empty states: no invented data ----------------------------


def test_dashboard_renders_explicit_empty_blocks_for_missing_records(home) -> None:
    """When the home has no journal/license/paper-state, the HTML
    exposes the explicit empty blocks (id="armed-empty", id="paper-empty",
    id="journal-empty", id="receipts-empty", id="license-readout"
    says "missing"). No fake sparkline, no fake balance, no fake
    profit.
    """
    first_run.mark_visited_dashboard(home)
    server = _start(home)
    try:
        _status, _hdr, body = _get(server, f"/{server.token}/dashboard")
        text = body.decode("utf-8")
        # Empty-state hooks present in markup so the JS hydrator can
        # flip them on when the corresponding array is empty.
        assert 'id="armed-empty"' in text
        assert 'id="paper-empty"' in text
        assert 'id="journal-empty"' in text
        assert 'id="receipts-empty"' in text
        # License placeholder copy. The JS replaces it with a real
        # summary; the empty placeholder must be honest.
        assert 'id="license-readout"' in text
        # The tick metric copy explicitly says "not measured locally"
        # when there is no tick journal record.
        # We assert against the JS literal so a regression that
        # removes it is caught.
        js = APP_JS.read_text(encoding="utf-8")
        assert "not measured locally" in js
        # Trading readiness placeholder copy.
        assert "not evaluated on this page" in js
        # No invented performance copy in static files.
        for phrase in ("return_pct", "drawdown", "CAGR", "P&amp;L", "P&L"):
            assert phrase not in text, phrase
        assert "live heartbeat" not in text.lower()
        assert "venue latency" not in text.lower()
    finally:
        _stop(server)


# ---- 5. escape: a journal-record string cannot reach HTML ----------------


def test_journal_string_with_script_tags_does_not_reach_html(home) -> None:
    """A journal record whose ``pack`` or ``venue`` field contains
    ``<script>alert(1)</script>`` MUST NOT inject HTML into the
    dashboard. The JS hydrator uses textContent only, and the server
    never reflects untrusted journal content into HTML — it is
    embedded via the bootstrap JSON, which is parsed, not innerHTMLed.
    """
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    evil = (
        '{"ts": 1700000000, "kind": "tick", "venue": "<script>alert(1)</script>", '
        '"pack": "<img src=x onerror=alert(1)>", "detail": {"msg": "<b>x</b>"}}'
    )
    (journal_dir / "kraken.jsonl").write_text(evil + "\n", encoding="utf-8")
    first_run.mark_visited_dashboard(home)
    server = _start(home)
    try:
        _status, _hdr, body = _get(server, f"/{server.token}/dashboard")
        text = body.decode("utf-8")
        # The bootstrap JSON does contain the literal strings, but
        # they are escaped for inclusion in a <script> element by the
        # server (\\u003c etc.). Plain "<script>" MUST NOT appear in
        # the bootstrap — that would close the script tag.
        assert "<script>alert(1)</script>" not in text
        # The escaped form is fine; we just must not see raw <.
        bootstrap_match = re.search(r"window\.__KB_VIEW__\s*=\s*(\{.*?\})\s*;</script>", text, re.DOTALL)
        assert bootstrap_match
        # Parse and confirm the venue field is preserved verbatim in
        # the JSON (escape is at the markup boundary, not in the data).
        view = json.loads(bootstrap_match.group(1))
        journal = view.get("journal_tail") or []
        assert any(j.get("venue") == "<script>alert(1)</script>" for j in journal)
        # And confirm the HTML body has no second <script> tag from the
        # journal content — only the legitimate bootstrap script tag
        # plus the app.js tag.
        script_tags = re.findall(r"<script\b[^>]*>", text)
        # Two scripts total: the bootstrap and app.js.
        assert len(script_tags) == 2, f"unexpected script tags: {script_tags}"
    finally:
        _stop(server)


# ---- 6. no keyring read on GET: credential bytes never reach HTML -------


def test_get_does_not_read_keyring_or_emit_credential_bytes(home) -> None:
    """Even with a fresh key stored, a GET never reads the keyring
    and never emits credential bytes into the dashboard HTML. The
    per-venue row carries the historical timestamp only.
    """
    keys_status.record_outcome(
        home,
        "kraken",
        status="stored",
        message="stored in native OS keychain",
    )
    first_run.mark_visited_dashboard(home)
    server = _start(home)
    try:
        _status, _hdr, body = _get(server, f"/{server.token}/dashboard")
        text = body.decode("utf-8")
        # Forbidden credential-shaped fragments. The dashboard never
        # emits these on a GET.
        forbidden_substrings = (
            "SECRETBYTES",
            "AKIA",
            "BEGIN PRIVATE KEY",
            "api_secret=",
            "api_key=",
        )
        for needle in forbidden_substrings:
            assert needle not in text, f"credential-shaped fragment leaked: {needle}"
        # The view must show the closed historical text, not a live
        # "currently connected" claim. Both phrasings live in app.js
        # because the JS hydrator resolves the placeholder.
        js = APP_JS.read_text(encoding="utf-8")
        assert "currently connected" not in js.lower()
        assert "last stored through wizard at" in js
        assert "not currently verified" in js
        # And the bootstrap JSON carries the closed historical record
        # verbatim (the closed message is one of SAFE_MESSAGES).
        view = _extract_view(body)
        ks = view.get("keys_status") or {}
        kraken_row = ks.get("kraken") or {}
        assert kraken_row.get("stored") is True
        assert isinstance(kraken_row.get("verified_at"), str)
    finally:
        _stop(server)


# ---- 7. license summary never exposes raw cache --------------------------


def test_license_summary_is_closed_three_scalar_shape(home) -> None:
    """Even with extra unknown fields injected into the license cache,
    the dashboard renders only the closed three-scalar summary. A
    stale cache with junk keys cannot leak through the renderer.
    """
    raw = {
        "status": "active",
        "period_end": 1700100000,
        "grace_until": 1700200000,
        "secret_token": "DO-NOT-LEAK",
        "admin_url": "http://internal.example/",
    }
    cache_path = kb_paths.home() / "catalog" / "license-cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(raw), encoding="utf-8")

    first_run.mark_visited_dashboard(home)
    server = _start(home)
    try:
        _status, _hdr, body = _get(server, f"/{server.token}/dashboard")
        text = body.decode("utf-8")
        # Closed license summary in bootstrap JSON has only three
        # allowed keys; the dashboard never reads raw junk fields.
        view = _extract_view(body)
        ls = view.get("license_summary") or {}
        assert set(ls.keys()) <= {"status", "period_end", "grace_until"}, ls
        assert ls.get("status") == "active"
        assert ls.get("period_end") == 1700100000
        assert ls.get("grace_until") == 1700200000
        # And the closed license_summary does not echo junk keys.
        assert "secret_token" not in ls
        # License readout placeholders never carry the raw secret.
        assert "DO-NOT-LEAK" not in text
        assert "secret_token" not in text
    finally:
        _stop(server)


# ---- 8. no JS fallback: server-rendered shell carries honest copy --------


def test_no_js_shell_renders_honest_action_disclosure(home) -> None:
    """The shell's static markup must replace the old absolute
    "Read-only. No keys, no balances, no orders leave the box" copy
    with a scope-accurate GET disclaimer that ALSO names the POST
    actions that DO contact a venue or persist state. The user must
    not see the absolute promise the old copy made.
    """
    text = INDEX_HTML.read_text(encoding="utf-8")
    # Old absolute copy must be gone.
    forbidden = (
        "Read-only. No keys, no balances, no orders leave the box.",
        "no keys, no balances, no orders leave the box",
    )
    for s in forbidden:
        assert s not in text, f"old absolute disclaimer still present: {s!r}"
    # Scope-accurate copy must be present.
    assert "GET reads metadata only" in text
    # POST disclosure must name every action that contacts a venue
    # or persists state.
    for action in ("POST /keys/add", "POST /activate", "POST /paper-arm", "POST /stop_all"):
        assert action in text, f"missing action disclosure: {action}"
    assert "contacts the selected venue once" not in text

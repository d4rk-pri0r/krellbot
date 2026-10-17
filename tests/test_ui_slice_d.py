"""Slice D tests: activation-key redeem, installed-pack listing, paper-arm.

The brief is explicit:
  * Reuse ``cli.check_license`` and ``cli.download_catalog`` from the
    wizard. Do not shell out to the CLI, do not invent a second license
    format. The activation-key POST must validate + verify + download the
    catalog via the existing helpers, never echo the key back, and PRG 303.
  * List installed packs from ``<home>/packs/`` via ``catalog.discover``
    (and friends). Legacy packs (no schema_version) render "not runnable".
  * Paper-arm from the UI reuses ``run.arm_pack``. Live arm stays 403.
  * A missing license must NOT block paper-arm of a local custom pack.
  * No new scheduler: the UI points at the existing
    ``krellbot service install`` command as the next step.

Tests run against a real in-process ``DashboardServer`` (port=0) so the
cookie/CSRF/Origin/Host gates are exercised end-to-end. ``cli.check_license``
and ``cli.download_catalog`` are monkeypatched in every test so no real
network call ever happens.
"""

from __future__ import annotations

import http.client
import json
import urllib.parse
from pathlib import Path

from krellbot import config as kb_config
from krellbot import paths as kb_paths
from krellbot.ui.server import DashboardServer

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


def _login(server: DashboardServer, port: int) -> tuple[str, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.request("GET", f"/{server.token}/")
        resp = conn.getresponse()
        resp.read()
        cookies = _parse_set_cookies(resp)
        session = cookies.get("krellbot_session", "")
        csrf = cookies.get("krellbot_csrf", "")
        assert session, f"krellbot_session cookie missing; headers={resp.getheaders()}"
        assert csrf, f"krellbot_csrf cookie missing; headers={resp.getheaders()}"
        header = f"krellbot_session={session}; krellbot_csrf={csrf}"
        return header, csrf
    finally:
        conn.close()


def _post(
    server: DashboardServer,
    path: str,
    body: str,
    *,
    cookies: str,
    origin: str | None = None,
) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
    try:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookies,
        }
        if origin is not None:
            headers["Origin"] = origin
        conn.request("POST", path, body=body, headers=headers)
        resp = conn.getresponse()
        body_bytes = resp.read()
        # ``http.client`` preserves header case, but we case-fold here so
        # ``headers.get("location")`` works regardless of the underlying
        # server's casing.
        headers_map = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, headers_map, body_bytes
    finally:
        conn.close()


def _get(server: DashboardServer, path: str) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body_bytes = resp.read()
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body_bytes
    finally:
        conn.close()


def _start(home: Path) -> tuple[DashboardServer, int]:
    server = DashboardServer(home=home, port=0)
    server.start()
    return server, server.bound_port


def _stop(server: DashboardServer | None) -> None:
    if server is None:
        return
    try:
        server.stop()
    except (OSError, RuntimeError):
        pass


def _write_pack(packs_dir: Path, name: str, body: dict | str, *, sub: str = "") -> Path:
    target_dir = packs_dir if not sub else (packs_dir / sub)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{name}.json"
    if isinstance(body, str):
        path.write_text(body, encoding="utf-8")
    else:
        path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _valid_dsl_pack(*, pack_id: str = "trend-follow") -> dict:
    return {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


def _legacy_pack() -> dict:
    return {
        "id": "old-style",
        "public_label": "Old Reliable",
        "rule": "Plain English.",
        "timeframe": "1h",
    }


# ---- 1. activation-key POST: reuse existing helpers, never echo key ------


def test_activate_refreshes_signed_cache_and_does_not_echo_key(home, monkeypatch) -> None:
    """Activate POSTs through license.refresh, not the legacy paid/grace helper."""
    from krellbot import cli as kb_cli
    from krellbot import license as kb_license
    from krellbot.ui import activate as kb_activate

    calls: list[tuple[str, str]] = []

    def fake_refresh(home_path, key, *, now, transport=None, url=None):
        calls.append(("refresh", key))
        assert url is None or key not in url
        kb_license.write_cache(
            home_path,
            status="active",
            period_end=int(now) + 100,
            grace_until=int(now) + 100,
        )
        return {"status": "active", "period_end": int(now) + 100, "grace_until": int(now) + 100}

    def fake_install(home_path, key, *, transport=None, url=None):
        calls.append(("catalog", key))
        assert url is None or key not in url
        return True

    def fail_check(*_args, **_kwargs):
        raise AssertionError("legacy check_license must not run")

    monkeypatch.setattr(kb_activate, "refresh_license", fake_refresh)
    monkeypatch.setattr(kb_activate, "install_catalog", fake_install)
    monkeypatch.setattr(kb_cli, "check_license", fail_check)
    monkeypatch.setattr(kb_cli, "cmd_setup", fail_check)

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&activation_key=ACTIVATE-ME-NOW"
        status, headers, body_bytes = _post(
            server,
            f"/{server.token}/activate",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 303, (status, headers, body_bytes[:200])
        assert calls == [("refresh", "ACTIVATE-ME-NOW"), ("catalog", "ACTIVATE-ME-NOW")]
        for k, v in headers.items():
            assert "ACTIVATE-ME-NOW" not in v, (k, v)
        assert b"ACTIVATE-ME-NOW" not in body_bytes
        loc = headers.get("location", "")
        assert loc.startswith(f"/{server.token}/")
        assert "license+verified" in loc or "license%20verified" in loc
        cache = kb_license.read_cache(home)
        assert cache is not None
        assert cache["status"] == "active"
    finally:
        _stop(server)


def test_activate_does_not_shell_out_to_cli(home, monkeypatch) -> None:
    """The activate POST must not call cmd_setup or the legacy download helper."""
    from krellbot import cli as kb_cli
    from krellbot.ui import activate as kb_activate

    def fail_cmd_setup(*_args, **_kwargs):
        raise AssertionError("cmd_setup must not be called from the activate POST")

    monkeypatch.setattr(kb_cli, "cmd_setup", fail_cmd_setup)
    monkeypatch.setattr(kb_cli, "download_catalog", fail_cmd_setup)
    monkeypatch.setattr(
        kb_activate,
        "refresh_license",
        lambda home_path, key, *, now, transport=None, url=None: {
            "status": "active",
            "period_end": int(now) + 10,
            "grace_until": int(now) + 10,
        },
    )
    monkeypatch.setattr(
        kb_activate,
        "install_catalog",
        lambda home_path, key, *, transport=None, url=None: False,
    )

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&activation_key=ANYKEY"
        status, headers, _body = _post(
            server,
            f"/{server.token}/activate",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 303, status
        assert "ANYKEY" not in headers.get("location", "")
    finally:
        _stop(server)


def test_refresh_license_posts_key_in_body_not_url(home) -> None:
    """The production refresh helper uses the signed-cache transport contract."""
    from krellbot import license as kb_license
    from krellbot.ui.activate import refresh_license

    payload = b'{"grace_until":300,"issued_at":10,"period_end":40,"status":"active"}'
    sig = "TTXgZ8bcSSDhJ8oH0ncnLf1POog_PL7jsj9uLM8mT_Qe5_iYRsfannXhTVq036_djL02pD7eCclP2zWPhLFLCw"
    seen: list[dict] = []

    class _Transport:
        def post(self, url, body, headers):
            seen.append({"url": url, "body": body})
            return {"payload": payload.decode("utf-8"), "sig": sig}

    key = "kb_test_key_not_in_url"
    verified = refresh_license(home, key, now=10, transport=_Transport(), url="https://krellbot.dev/api/license")
    assert verified["status"] == "active"
    assert seen[0]["body"] == {"key": key}
    assert key not in seen[0]["url"]
    cache = kb_license.read_cache(home)
    assert cache["status"] == "active"
    assert cache["grace_until"] == 300


def test_activate_refused_license_still_prg_with_closed_message(home, monkeypatch) -> None:
    """A rejected signature still 303s with a closed message and does not install packs."""
    from krellbot.ui import activate as kb_activate

    def fail_refresh(*_args, **_kwargs):
        raise ValueError("license signature rejected")

    def no_install(*_args, **_kwargs):
        raise AssertionError("catalog install must not run when the license is refused")

    monkeypatch.setattr(kb_activate, "refresh_license", fail_refresh)
    monkeypatch.setattr(kb_activate, "install_catalog", no_install)

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&activation_key=KEY-WHATEVER"
        status, headers, body_bytes = _post(
            server,
            f"/{server.token}/activate",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 303, status
        assert b"KEY-WHATEVER" not in body_bytes
        for k, v in headers.items():
            assert "KEY-WHATEVER" not in v, (k, v)
        loc = headers.get("location", "")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(loc).query))
        assert q.get("status") == "license not accepted"
    finally:
        _stop(server)


def test_cmd_setup_uses_signed_refresh_not_query_string(home, monkeypatch, capsys) -> None:
    """`krellbot setup` must write the signed cache and must not put the key in a URL."""
    from krellbot import cli as kb_cli
    from krellbot.ui import activate as kb_activate

    seen: list[str] = []

    def fake_refresh(home_path, key, *, now, transport=None, url=None):
        seen.append(key)
        assert url is None or key not in url
        from krellbot import license as kb_license

        kb_license.write_cache(home_path, status="active", period_end=int(now) + 5, grace_until=int(now) + 5)
        return {"status": "active", "period_end": int(now) + 5, "grace_until": int(now) + 5}

    monkeypatch.setattr(kb_activate, "refresh_license", fake_refresh)
    monkeypatch.setattr(kb_activate, "install_catalog", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        kb_cli, "download_catalog", lambda key: (_ for _ in ()).throw(AssertionError("key in URL helper"))
    )
    rc = kb_cli.cmd_setup("kb_setup_key")
    assert rc == 0
    assert seen == ["kb_setup_key"]
    out = capsys.readouterr().out
    assert "kb_setup_key" not in out
    assert "license verified" in out


def test_activate_missing_or_blank_key_is_400_without_echo(home, monkeypatch) -> None:
    """An empty activation key is rejected at the form boundary with 400."""
    from krellbot import cli as kb_cli

    monkeypatch.setattr(kb_cli, "check_license", lambda key: {"status": "paid", "message": "ok"})

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        # Empty activation_key field.
        body = f"csrf={csrf}&activation_key="
        status, _headers, _body_bytes = _post(
            server,
            f"/{server.token}/activate",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 400, status
        # And the catalog file must NOT have been written.
        assert not (kb_paths.home() / "catalog.json").exists()
    finally:
        _stop(server)


# ---- 2. install-pack listing on the dashboard -----------------------------


def test_dashboard_lists_installed_packs(home) -> None:
    """The dashboard view must include every runnable pack from packs/
    AND the legacy (not runnable) pack, classified correctly.

    The dashboard embeds the listing as JSON inside ``window.__KB_VIEW__``.
    We read that JSON rather than grep the HTML because the structured
    data is what the JS hydrator (and any future test) consumes. Legacy
    packs must carry ``runnable: false`` so the JS hydrator can hide
    the arm affordance; we never invent performance numbers or an
    equity curve on their behalf.
    """
    packs_dir = kb_paths.home() / "packs"
    _write_pack(packs_dir, "valid", _valid_dsl_pack(pack_id="trend-follow"))
    _write_pack(packs_dir, "valid_atr", _valid_dsl_pack(pack_id="atr-pack"))
    _write_pack(packs_dir, "legacy", _legacy_pack())

    from krellbot.ui.first_run import mark_visited_dashboard

    mark_visited_dashboard(home)
    server, _port = _start(home)
    try:
        status, _hdr, body_bytes = _get(server, f"/{server.token}/")
        assert status == 200
        pack_ids = _extract_pack_ids(body_bytes.decode("utf-8"))
        by_id = {p["id"]: p for p in _extract_pack_list(body_bytes.decode("utf-8"))}
        # Both runnable IDs are present…
        assert {"trend-follow", "atr-pack"} <= pack_ids
        # …and the legacy pack renders with runnable=false (and is NOT in
        # the armable set the JS hydrator consumes).
        assert "old-style" in by_id
        legacy = by_id["old-style"]
        assert legacy["runnable"] is False
        assert isinstance(legacy.get("not_runnable_reason"), str)
        assert legacy["not_runnable_reason"]
        # Rendered text must not invent performance numbers, equity
        # curves, or paid-catalog fragments.
        body = body_bytes.decode("utf-8")
        for forbidden in ("return_pct", "drawdown", "CAGR"):
            assert forbidden not in body, forbidden
        # No paid-catalog data leaks into the dashboard view.
        assert "paid" not in body.lower().split("__kb_view__")[0]
    finally:
        _stop(server)


def _extract_pack_list(body: str) -> list[dict]:
    """Return the structured ``packs`` list from ``window.__KB_VIEW__``."""
    import re

    m = re.search(r"window\.__KB_VIEW__\s*=\s*(\{.*?\})\s*;</script>", body, re.DOTALL)
    if not m:
        return []
    try:
        view = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    packs = view.get("packs", [])
    return [p for p in packs if isinstance(p, dict)]


def _extract_pack_ids(body: str) -> set[str]:
    return {p.get("id", "") for p in _extract_pack_list(body)}


# ---- 3. paper-arm from the UI uses the existing arm_pack -----------------


def test_paper_arm_from_ui_uses_existing_arm_pack(home, monkeypatch) -> None:
    """POST /paper-arm with a valid pack_id + paper_balance + venue calls
    ``run.arm_pack`` with mode='paper', writes to config.armed, and 200s.

    The dashboard does NOT have its own arm logic: it MUST route through
    the engine's ``arm_pack`` so all engine guarantees (costmin, second
    pack on same venue+pair, etc.) apply uniformly.
    """
    packs_dir = kb_paths.home() / "packs"
    _write_pack(packs_dir, "valid", _valid_dsl_pack(pack_id="trend-follow"))

    from krellbot import run as kb_run

    calls: list[dict] = []

    def spy_arm_pack(pack_path, *, venue, mode, paper_balance=None, **_kwargs):
        calls.append(
            {
                "pack_path": str(pack_path),
                "venue": venue,
                "mode": mode,
                "paper_balance": paper_balance,
            }
        )
        # Mirror the real return contract.
        return 0

    monkeypatch.setattr(kb_run, "arm_pack", spy_arm_pack)

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&pack_id=trend-follow&venue=kraken&paper_balance=1000"
        status, headers, body_bytes = _post(
            server,
            f"/{server.token}/paper-arm",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 200, (status, headers, body_bytes[:200])
        # The engine's arm_pack was called exactly once with paper mode.
        assert len(calls) == 1
        call = calls[0]
        assert call["venue"] == "kraken"
        assert call["mode"] == "paper"
        assert call["paper_balance"] is not None
        # The pack path resolved to the on-disk file we wrote.
        assert Path(call["pack_path"]).name == "valid.json"
    finally:
        _stop(server)


def test_paper_arm_unknown_pack_id_is_404(home) -> None:
    """A POST that names a pack_id with no on-disk match returns 404."""
    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&pack_id=nonexistent&venue=kraken&paper_balance=1000"
        status, _headers, _body = _post(
            server,
            f"/{server.token}/paper-arm",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 404, status
    finally:
        _stop(server)


def test_paper_arm_legacy_pack_refused(home) -> None:
    """A legacy (no schema_version) pack must NOT arm.

    The route refuses by responding with a non-200 status. We accept
    403 (the engine's own legacy refusal, surfaced verbatim) or 404
    (the resolver's ``no runnable pack`` result) — both are honest
    refusals. What the test MUST guarantee is that ``config.armed`` is
    left empty, i.e. no arm happened.
    """
    packs_dir = kb_paths.home() / "packs"
    _write_pack(packs_dir, "legacy", _legacy_pack())

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&pack_id=old-style&venue=kraken&paper_balance=1000"
        status, _headers, _body = _post(
            server,
            f"/{server.token}/paper-arm",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status in {403, 404}, status
        # No arm happened.
        cfg = kb_config.load_config(home)
        assert cfg.armed == [], cfg.armed
    finally:
        _stop(server)


def test_live_arm_route_remains_403(home) -> None:
    """The existing /arm route must STILL refuse live arm with 403.

    The brief is explicit: 'Live arm from the UI stays 403. Do not weaken
    the typed LIVE CLI gate.' We add a sibling /paper-arm route; the /arm
    route remains exactly as it is.
    """
    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&mode=live&pack_path=anywhere&venue=kraken&paper_balance=1000"
        status, _headers, _body = _post(
            server,
            f"/{server.token}/arm",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 403, status
    finally:
        _stop(server)


def test_paper_arm_does_not_open_venue_socket_or_cancel_orders(home, monkeypatch) -> None:
    """The UI's paper-arm path must NEVER open a venue socket. In
    particular, the brief forbids calling ``CancelAllOrdersAfter`` or
    any other venue order-management endpoint — ``arm_pack`` only
    persists config, so the UI must route through it and stop there.

    We assert the contract two ways:

      1. ``krellbot.run.arm_pack`` is invoked exactly once (the only
         side effect the UI is allowed to trigger).
      2. No Kraken or Coinbase transport method is called. A spy on
         the ``HttpTransport`` class catches any accidental
         ``post``/``get`` that would have hit a venue.
    """
    packs_dir = kb_paths.home() / "packs"
    _write_pack(packs_dir, "valid", _valid_dsl_pack(pack_id="trend-follow"))

    from krellbot import run as kb_run
    from krellbot.venues import kraken as kb_kraken

    class _TransportSpy(kb_kraken.HttpTransport):
        def __init__(self) -> None:
            self.calls = []

        def post(self, url, body=None, headers=None):  # type: ignore[override]
            self.calls.append(("post", url))
            raise AssertionError("UI paper-arm must not POST to a venue")

        def get(self, url, headers=None):  # type: ignore[override]
            self.calls.append(("get", url))
            raise AssertionError("UI paper-arm must not GET from a venue")

    spy = _TransportSpy()
    monkeypatch.setattr(kb_kraken, "HttpTransport", lambda: spy)

    arm_calls: list[dict] = []

    def spy_arm(pack_path, *, venue, mode, paper_balance=None, **_kwargs):
        arm_calls.append({"venue": venue, "mode": mode, "paper_balance": paper_balance})
        return 0

    monkeypatch.setattr(kb_run, "arm_pack", spy_arm)

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&pack_id=trend-follow&venue=kraken&paper_balance=1000"
        status, _headers, _body = _post(
            server,
            f"/{server.token}/paper-arm",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 200, status
        assert len(arm_calls) == 1
        assert spy.calls == [], spy.calls
    finally:
        _stop(server)


# ---- 4. missing license must not block paper-arm of a local pack ----------


def test_paper_arm_without_license_succeeds_for_local_pack(home, monkeypatch) -> None:
    """A missing license cache MUST NOT block paper mode for a local pack
    the user wrote themselves. The dashboard never asks the user to
    redeem a key before arming a paper pack.
    """
    packs_dir = kb_paths.home() / "packs"
    _write_pack(packs_dir, "valid", _valid_dsl_pack(pack_id="trend-follow"))

    # No license cache on disk.
    from krellbot import license as kb_license

    monkeypatch.setattr(kb_license, "read_cache", lambda _home: None)

    from krellbot import run as kb_run

    calls = {"n": 0}

    def spy(_pack_path, *, venue, mode, paper_balance=None, **_kwargs):
        calls["n"] += 1
        assert mode == "paper"
        return 0

    monkeypatch.setattr(kb_run, "arm_pack", spy)

    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&pack_id=trend-follow&venue=kraken&paper_balance=1000"
        status, _headers, _body = _post(
            server,
            f"/{server.token}/paper-arm",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 200, status
        assert calls["n"] == 1
    finally:
        _stop(server)


# ---- 5. next-step copy: no new scheduler, point at CLI -------------------


def test_wizard_next_page_does_not_advertise_a_new_scheduler(home) -> None:
    """The wizard's Next page must NOT introduce a new OS scheduler.

    The brief is explicit: 'If OS scheduler install is not already a
    tested function, do not add a new scheduler. Show the existing
    `krellbot service install` command as the next step instead.' The
    existing ``krellbot service install`` is the tested function;
    the wizard simply points at it.

    Concretely the page must:
      * name ``krellbot service install`` (the CLI command that
        installs the existing scheduler unit), and
      * not promise any UI-driven scheduler-install button or
        wizard step that bypasses the CLI.
    """
    server, _port = _start(home)
    try:
        status, _hdr, body_bytes = _get(server, f"/{server.token}/next")
        assert status == 200
        body = body_bytes.decode("utf-8")
        # The recommended path is the existing CLI command.
        assert "krellbot service install" in body
        assert "never leaves the box" not in body
        assert 'action="activate"' in body
        assert "krellbot.dev/api/license" in body
        assert 'action="install-scheduler"' not in body
        assert 'action="scheduler/install"' not in body
        assert 'action="install_scheduler"' not in body
        # And there is no button labeled "install scheduler".
        assert "Install scheduler" not in body
        assert "Install Scheduler" not in body
    finally:
        _stop(server)


# ---- 6. CSRF / Origin / Host gates apply to every new POST ---------------


def test_activate_csrf_failure_is_403(home, monkeypatch) -> None:
    """The CSRF gate must reject an activate POST without a valid form csrf."""
    from krellbot import cli as kb_cli

    monkeypatch.setattr(kb_cli, "check_license", lambda key: {"status": "paid", "message": "ok"})
    monkeypatch.setattr(kb_cli, "download_catalog", lambda key: True)

    server, _port = _start(home)
    try:
        cookies, _csrf = _login(server, server.bound_port)
        body = "csrf=WRONG&activation_key=ABC"
        status, _headers, _body = _post(
            server,
            f"/{server.token}/activate",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert status == 403, status
    finally:
        _stop(server)


def test_paper_arm_origin_failure_is_403(home) -> None:
    """An Origin outside the loopback allow-list is refused with 403."""
    server, _port = _start(home)
    try:
        cookies, csrf = _login(server, server.bound_port)
        body = f"csrf={csrf}&pack_id=trend-follow&venue=kraken&paper_balance=1000"
        status, _headers, _body = _post(
            server,
            f"/{server.token}/paper-arm",
            body,
            cookies=cookies,
            origin="http://evil.example.com",
        )
        assert status == 403, status
    finally:
        _stop(server)

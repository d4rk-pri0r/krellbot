"""Tests for the dashboard UI server.

Each test starts a server on a thread (port=0, reads the bound port back)
and tears it down in `finally`. No sleep-to-poll: the server is synchronous
in-process and responds immediately.

The server binds to 127.0.0.1 only. A 32-byte hex token gates access. POSTs
are CSRF-protected via the `krellbot_csrf` cookie + form field + Origin
header.
"""

from __future__ import annotations

import http.client
import re
import socket
from decimal import Decimal
from pathlib import Path

from krellbot import config as kb_config
from krellbot import paths as kb_paths
from krellbot.ui.server import DashboardServer

# ---- helpers --------------------------------------------------------------


def _parse_set_cookies(resp: http.client.HTTPResponse) -> dict[str, str]:
    """Pull every Set-Cookie header off a response and return a name->value map."""
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
    """GET /<token>/ to set cookies. Return (Cookie header, csrf value)."""
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.request("GET", f"/{server.token}/")
        resp = conn.getresponse()
        resp.read()
        cookies = _parse_set_cookies(resp)
        session = cookies.get("krellbot_session", "")
        csrf = cookies.get("krellbot_csrf", "")
        assert session, f"krellbot_session cookie not set; headers={resp.getheaders()}"
        assert csrf, f"krellbot_csrf cookie not set; headers={resp.getheaders()}"
        header = f"krellbot_session={session}; krellbot_csrf={csrf}"
        return header, csrf
    finally:
        conn.close()


def _post_form(
    server: DashboardServer,
    port: int,
    path: str,
    body: str,
    *,
    cookies: str,
    origin: str | None = None,
) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Cookie": cookies,
        }
        if origin is not None:
            headers["Origin"] = origin
        conn.request("POST", path, body=body, headers=headers)
        return conn.getresponse()
    finally:
        # Caller reads the response. Don't close here — that would tear down
        # the response body. The conn is short-lived and the OS will reap it.
        pass


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


def test_loopback_start_never_needs_reverse_dns(tmp_path: Path, monkeypatch) -> None:
    """Starting the local UI must not wait on hostname resolution."""

    def unexpected_lookup(_host: str) -> str:
        raise AssertionError("reverse DNS must not run on UI bind")

    monkeypatch.setattr(socket, "getfqdn", unexpected_lookup)
    server = DashboardServer(home=tmp_path, port=0)
    try:
        server.start()
        assert server.bound_host == "127.0.0.1"
        assert server.bound_port > 0
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port, timeout=2)
        try:
            conn.request("GET", f"/{server.token}/")
            resp = conn.getresponse()
            resp.read()
            assert resp.status == 200
        finally:
            conn.close()
    finally:
        if server.bound_port:
            server.stop()


def _seed_two_paper_packs(home: Path) -> None:
    kb_paths.ensure_layout()
    cfg = kb_config.Config()
    cfg.armed.append(
        kb_config.ArmedPack(
            pack_path="",
            pack_sha256="",
            pack_id="a",
            pack_version="1",
            venue="kraken",
            pair="SUIUSD",
            cap=Decimal(10),
            stop=Decimal(5),
            mode="paper",
            starting_cash=Decimal(1000),
            requires_license=False,
            armed_at_ts=0,
        )
    )
    cfg.armed.append(
        kb_config.ArmedPack(
            pack_path="",
            pack_sha256="",
            pack_id="b",
            pack_version="1",
            venue="kraken",
            pair="BTCUSD",
            cap=Decimal(10),
            stop=Decimal(50000),
            mode="paper",
            starting_cash=Decimal(1000),
            requires_license=False,
            armed_at_ts=0,
        )
    )
    kb_config.save_config(home, cfg)


# ---- tests ----------------------------------------------------------------


def test_binds_loopback_only(home):
    """The server socket must be bound to 127.0.0.1, not 0.0.0.0."""
    server, port = _start(home)
    try:
        assert server.bound_host == "127.0.0.1", server.bound_host
        # Also confirm the listening socket is on loopback by looking up its peer.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(("127.0.0.1", port))
            peer = sock.getpeername()
            assert peer[0] == "127.0.0.1", peer
        finally:
            sock.close()
    finally:
        _stop(server)


def test_rejects_foreign_host_header(home):
    """A request with a Host header that isn't 127.0.0.1:<port> or localhost:<port>
    must be rejected with 403."""
    server, port = _start(home)
    try:
        token = server.token
        # Hand-craft a request with a foreign Host. http.client doesn't let us
        # override Host without bypassing its sanity check, so we speak HTTP/1.1
        # by hand against a raw socket.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(("127.0.0.1", port))
            request = (f"GET /{token}/ HTTP/1.1\r\nHost: evil.example.com\r\nConnection: close\r\n\r\n").encode("ascii")
            sock.sendall(request)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        finally:
            sock.close()
        head = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        assert " 403 " in head, head
        # And no cookie set.
        assert b"Set-Cookie" not in data
    finally:
        _stop(server)


def test_post_without_csrf_rejected(home):
    """A POST without a CSRF token (no cookie + no form field) is 403."""
    server, port = _start(home)
    try:
        token = server.token
        # Hit POST without ever setting cookies.
        conn = http.client.HTTPConnection("127.0.0.1", port)
        try:
            conn.request("POST", f"/{token}/stop_all", body="")
            resp = conn.getresponse()
            assert resp.status == 403, f"expected 403, got {resp.status}"
            resp.read()
        finally:
            conn.close()
    finally:
        _stop(server)


def test_no_external_urls_in_static():
    """Every file under src/krellbot/ui/static/ must be free of http://, https://,
    and protocol-relative URLs. This test guards the static asset contract."""
    static = Path(__file__).resolve().parents[1] / "src" / "krellbot" / "ui" / "static"
    assert static.is_dir(), f"missing static dir: {static}"
    needles = ("http://", "https://")
    failures: list[str] = []
    for path in sorted(static.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in needles:
            if needle in text:
                failures.append(f"{path}: contains {needle!r}")
        # Protocol-relative URL: a // that lives inside a URL attribute.
        for match in re.finditer(r'(["\'])\s*//[^/"\'][^"\']*\1', text):
            failures.append(f"{path}: protocol-relative URL {match.group(0)!r}")
    assert not failures, "\n".join(failures)


def test_stop_all_disarms_everything(home):
    """POST stop_all removes every armed pack from config.json."""
    server, port = _start(home)
    try:
        _seed_two_paper_packs(home)
        cookies, csrf = _login(server, port)
        body = f"csrf={csrf}"
        resp = _post_form(
            server,
            port,
            f"/{server.token}/stop_all",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{port}",
        )
        assert resp.status == 200, f"expected 200, got {resp.status}"
        resp.read()
        # Config has no armed packs.
        cfg = kb_config.load_config(home)
        assert cfg.armed == [], cfg.armed
    finally:
        _stop(server)


def test_live_arm_from_page_is_refused(home):
    """POST arm with mode=live returns 403 and changes no state."""
    server, port = _start(home)
    try:
        cookies, csrf = _login(server, port)
        body = f"csrf={csrf}&mode=live&pack_path=anywhere&venue=kraken&paper_balance=1000"
        resp = _post_form(
            server,
            port,
            f"/{server.token}/arm",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{port}",
        )
        assert resp.status == 403, f"expected 403, got {resp.status}"
        resp.read()
        cfg = kb_config.load_config(home)
        assert cfg.armed == [], cfg.armed
    finally:
        _stop(server)


def test_adopt_pending_refused_while_long(home):
    """POST adopt refuses when the pack still owns quantity."""
    server, port = _start(home)
    try:
        kb_paths.ensure_layout()
        cfg = kb_config.Config()
        cfg.armed.append(
            kb_config.ArmedPack(
                pack_path="",
                pack_sha256="",
                pack_id="a",
                pack_version="1",
                venue="kraken",
                pair="SUIUSD",
                cap=Decimal(10),
                stop=Decimal(5),
                mode="paper",
                starting_cash=Decimal(1000),
                requires_license=False,
                armed_at_ts=0,
                owned_qty=Decimal(5),
                pending_version="2",
            )
        )
        kb_config.save_config(home, cfg)

        cookies, csrf = _login(server, port)
        body = f"csrf={csrf}&pack_id=a"
        resp = _post_form(
            server,
            port,
            f"/{server.token}/adopt",
            body,
            cookies=cookies,
            origin=f"http://127.0.0.1:{port}",
        )
        assert resp.status == 403, f"expected 403, got {resp.status}"
        resp.read()
        # Pending version is still pending; pack_version unchanged.
        cfg = kb_config.load_config(home)
        assert len(cfg.armed) == 1
        armed = cfg.armed[0]
        assert armed.pending_version == "2"
        assert armed.pack_version == "1"
    finally:
        _stop(server)


def test_root_does_not_disclose_token(home):
    """GET / has no path token. It must be 403 and must not reveal the gate."""
    server, port = _start(home)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        try:
            conn.request("GET", "/")
            resp = conn.getresponse()
            body = resp.read()
            header_blob = "\n".join(f"{k}: {v}" for k, v in resp.getheaders())
            assert resp.status == 403, resp.status
            assert server.token not in body.decode("utf-8", errors="replace")
            assert server.token not in header_blob
            assert "location" not in header_blob.lower()
        finally:
            conn.close()
    finally:
        _stop(server)


def test_page_embeds_csrf_for_forms(home):
    """The browser cannot read the HttpOnly cookie, so the form field must carry it."""
    from krellbot.ui.first_run import mark_visited_dashboard

    # Mark visited so the dashboard shell renders at the index. The
    # welcome/security/next shells only carry the wizard nav and a
    # single form (the enter-dashboard POST on Next) — they have
    # their own CSRF embedding tests.
    mark_visited_dashboard(home)
    server, port = _start(home)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        try:
            conn.request("GET", f"/{server.token}/")
            resp = conn.getresponse()
            body = resp.read()
            cookies = _parse_set_cookies(resp)
            csrf = cookies["krellbot_csrf"]
            assert f'name="csrf" value="{csrf}"'.encode() in body
        finally:
            conn.close()
    finally:
        _stop(server)


def test_view_json_cannot_break_out_of_script(home):
    """A journal string must not close the inline script tag."""
    import json

    kb_paths.ensure_layout()
    journal_dir = Path(home) / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    payload = "</script><script>alert(1)</script>"
    (journal_dir / "2099-01.jsonl").write_text(
        json.dumps({"detail": payload}) + "\n",
        encoding="utf-8",
    )
    # The wizard root renders the welcome shell (no visit preference yet).
    # Set the preference so /<token>/ renders the dashboard, which is the
    # view that embeds journal records.
    from krellbot.ui.first_run import mark_visited_dashboard

    mark_visited_dashboard(home)
    server, port = _start(home)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port)
        try:
            conn.request("GET", f"/{server.token}/")
            resp = conn.getresponse()
            body = resp.read()
            assert resp.status == 200
            assert b"</script><script>" not in body
            assert b"\\u003c/script\\u003e" in body
        finally:
            conn.close()
    finally:
        _stop(server)


def test_stop_all_exits_owned_qty_only(home):
    """Stop-all sells the pack's qty, not every coin in the paper balance."""
    import json

    kb_paths.ensure_layout()
    cfg = kb_config.Config()
    cfg.armed.append(
        kb_config.ArmedPack(
            pack_path="",
            pack_sha256="",
            pack_id="a",
            pack_version="1",
            venue="kraken",
            pair="SUIUSD",
            cap=Decimal(10),
            stop=Decimal(2),
            mode="paper",
            starting_cash=Decimal(1000),
            requires_license=False,
            armed_at_ts=0,
            owned_qty=Decimal(2),
        )
    )
    kb_config.save_config(home, cfg)
    run_dir = Path(home) / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "paper-kraken.json").write_text(
        json.dumps(
            {
                "venue": "kraken",
                "balances": {"SUI": "10", "USD": "100", "BTC": "1"},
                "open_orders": [{"pair": "SUIUSD", "stop_price": "2", "qty": "10", "side": "sell"}],
                "recent_fills": [{"pair": "SUIUSD", "price": "3", "side": "buy", "qty": "10"}],
            }
        ),
        encoding="utf-8",
    )
    server, port = _start(home)
    try:
        cookies, csrf = _login(server, port)
        resp = _post_form(
            server,
            port,
            f"/{server.token}/stop_all",
            f"csrf={csrf}",
            cookies=cookies,
            origin=f"http://127.0.0.1:{port}",
        )
        assert resp.status == 200, resp.status
        resp.read()
        state = json.loads((run_dir / "paper-kraken.json").read_text(encoding="utf-8"))
        balances = state["balances"]
        assert Decimal(str(balances["SUI"])) == Decimal(8)
        assert Decimal(str(balances["BTC"])) == Decimal(1)
        usd = Decimal(str(balances["USD"]))
        assert Decimal(105) < usd < Decimal(107), usd
        assert all(o.get("pair") != "SUIUSD" for o in state["open_orders"])
    finally:
        _stop(server)

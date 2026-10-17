"""NS06a — versioned loopback API.

Tests-first. The API package (`krellbot.api`) does not exist before this
NS lands; the import lines below must fail with ``ModuleNotFoundError`` in
the RED phase.

The FastAPI app is bound to ``127.0.0.1`` only. Tests speak to it through
a tiny stdlib ASGI client (no httpx — that dependency is not on the
allow-list). The client builds the ASGI scope, runs ``asyncio.run`` on the
app's coroutine, and returns ``(status, headers_list, body_bytes, set_cookies)``.

Test layout:

  * Loopback-only Host: a foreign Host header is 403.
  * Bootstrap endpoint: redeems a one-time token, sets a
    HttpOnly / SameSite=Strict / Path=/ session cookie, returns a CSRF
    token. Reuse, wrong token, or non-loopback Origin is 403.
  * Commands endpoint: requires session cookie, exact loopback Origin,
    and a matching ``X-Krellbot-CSRF`` header. Paper commands delegate to
    ``PaperService``; a ``mode: live`` payload or a command name starting
    with ``live.`` returns 403 and leaves config bytes untouched.
  * Capabilities endpoint: paper and research are reported available,
    live orders are not.
  * OpenAPI: ``/api/v1/commands`` and ``/api/v1/session/bootstrap`` paths
    appear in the generated schema.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

# ---- ASGI test client ----------------------------------------------------


def _ascii_headers(headers: list[tuple[str, str]]) -> list[tuple[bytes, bytes]]:
    """Encode the raw ASGI header list as (bytes, bytes) tuples.

    Each header name is lowercased on the wire, so we follow the same
    convention the ASGI spec recommends. ASGI does not require lowercasing
    but Starlette/FastAPI normalizes ``request.headers`` accordingly.
    """

    return [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers]


def asgi_call(
    app,
    *,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    """Issue one ASGI request to ``app`` and return the captured response.

    Returns ``(status, headers_list, body_bytes, set_cookies)``. The
    headers list contains every header except Set-Cookie, which is split
    out so callers can inspect cookies individually.
    """
    body = body if body is not None else b""
    headers = list(headers or [])
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    captured: dict[str, object] = {"status": 500, "headers": [], "body": bytearray()}

    async def send(message: dict[str, object]) -> None:
        mtype = message["type"]
        if mtype == "http.response.start":
            captured["status"] = int(message["status"])
            captured["headers"] = list(message.get("headers", []))
        elif mtype == "http.response.body":
            captured["body"] = captured["body"] + message.get("body", b"")

    raw_path = path.encode("latin-1")
    if b"?" in raw_path:
        path_only, _, query = raw_path.partition(b"?")
        query_string = query
        raw_path_out = path_only
        path_out = path_only.decode("latin-1")
    else:
        path_out = path
        raw_path_out = raw_path
        query_string = b""

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path_out,
        "raw_path": raw_path_out,
        "query_string": query_string,
        "server": ("127.0.0.1", 0),
        "client": ("127.0.0.1", 12345),
        "headers": _ascii_headers(headers),
        "root_path": "",
    }

    asyncio.run(app(scope, receive, send))

    flat: list[tuple[str, str]] = []
    set_cookies: list[str] = []
    for name_b, value_b in captured["headers"]:
        name = name_b.decode("latin-1")
        value = value_b.decode("latin-1")
        if name.lower() == "set-cookie":
            set_cookies.append(value)
        else:
            flat.append((name, value))
    return int(captured["status"]), flat, bytes(captured["body"]), set_cookies


# ---- helpers --------------------------------------------------------------


TEST_PORT = 8080


def _default_host_header(port: int = TEST_PORT) -> list[tuple[str, str]]:
    """Default Host header. ``Host: 127.0.0.1:<port>`` is loopback-allowed."""

    return [("Host", f"127.0.0.1:{port}")]


def _default_origin_header(port: int = TEST_PORT) -> list[tuple[str, str]]:
    """Default Origin header. Must match the loopback origin set."""

    return [("Origin", f"http://127.0.0.1:{port}")]


def _build_app(home: Path, *, bootstrap_token: str = "boot-test-token"):
    """Build a fresh API app with the given home + bootstrap token."""

    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


def _bootstrap_token(home: Path) -> str:
    """Distinct bootstrap token per test for isolation."""

    return f"boot-{home.name}-{id(home)}"


def _post_json(
    app,
    path: str,
    payload: dict,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    body = json.dumps(payload).encode("utf-8")
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="POST", path=path, body=body, headers=base)


def _do_bootstrap(app, *, token: str) -> tuple[dict, str | None]:
    """Redeem a bootstrap token. Returns (body_dict, csrf_token)."""

    status, _hdrs, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, body, cookies)
    decoded = json.loads(body)
    csrf_token = decoded.get("csrf_token")
    assert csrf_token, decoded
    session_cookie = next((c for c in cookies if c.startswith("krellbot_session=")), None)
    assert session_cookie, cookies
    return decoded, csrf_token


def _write_dsl_pack(home: Path, *, pack_id: str = "trend-follow") -> Path:
    """Write a runnable DSL pack under <home>/packs/."""

    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "krellbot ns06a tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _config_bytes(home: Path) -> bytes:
    config_path = home / "config.json"
    if not config_path.exists():
        return b""
    return config_path.read_bytes()


# ---- 1. bind host is 127.0.0.1; non-loopback Host is 403 ------------------


def test_non_loopback_host_is_403(home: Path) -> None:
    """A request with a non-loopback Host header is 403 before any route runs."""

    app = _build_app(home)
    headers = [("Host", "evil.example.com")]
    status, _hdrs, _body, _cookies = asgi_call(app, method="GET", path="/api/v1/capabilities", headers=headers)
    assert status == 403, status


def test_localhost_host_header_is_accepted(home: Path) -> None:
    """The literal ``localhost:<port>`` Host is allowed alongside 127.0.0.1."""

    app = _build_app(home)
    status, _hdrs, _body, _cookies = asgi_call(
        app,
        method="GET",
        path="/api/v1/capabilities",
        headers=[("Host", f"localhost:{TEST_PORT}")],
    )
    assert status == 200, status


# ---- 2. bootstrap: token in, session cookie + csrf token out -------------


def test_bootstrap_redeems_token_and_sets_session_cookie(home: Path) -> None:
    """POST /api/v1/session/bootstrap with the right token returns 200,
    sets an HttpOnly / SameSite=Strict / Path=/ session cookie, and returns
    a CSRF token in the body."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    status, _hdrs, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, body, cookies)
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1"
    csrf_token = decoded["csrf_token"]
    assert csrf_token and len(csrf_token) >= 16
    session_cookie = next((c for c in cookies if c.startswith("krellbot_session=")), None)
    assert session_cookie, cookies
    sc = session_cookie.lower()
    assert "httponly" in sc
    assert "samesite=strict" in sc
    assert "path=/" in sc
    # The raw token must not be in the response body.
    assert token not in body.decode("utf-8")


def test_bootstrap_reuse_is_403(home: Path) -> None:
    """The bootstrap token is one-time. A second redemption is 403."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    first = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert first[0] == 200, first
    second = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert second[0] == 403, second


def test_bootstrap_wrong_token_is_403(home: Path) -> None:
    """A bootstrap with the wrong token is 403 and does not create a session."""

    app = _build_app(home, bootstrap_token="real-token")
    status, _hdrs, _body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": "not-the-real-one"},
        headers=_default_origin_header(),
    )
    assert status == 403, status
    assert not any(c.startswith("krellbot_session=") for c in cookies)


def test_bootstrap_rejects_non_loopback_origin(home: Path) -> None:
    """Bootstrap refuses an Origin that isn't in the loopback origin set."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", "http://evil.example.com")],
    )
    assert status == 403, status


def test_bootstrap_rejects_missing_origin(home: Path) -> None:
    """Bootstrap requires an Origin header."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[],
    )
    assert status == 403, status


# ---- 3. commands endpoint gates ------------------------------------------


def _full_auth_headers(csrf_token: str, port: int = TEST_PORT) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{port}"),
        ("X-Krellbot-CSRF", csrf_token),
    ]


def test_commands_requires_session_cookie(home: Path) -> None:
    """POST /api/v1/commands without a session cookie is 403."""

    app = _build_app(home)
    headers = [("Origin", f"http://127.0.0.1:{TEST_PORT}"), ("X-Krellbot-CSRF", "anything")]
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/commands",
        {"command": "paper.arm", "payload": {}},
        headers=headers,
    )
    assert status == 403, status


def test_commands_requires_exact_origin(home: Path) -> None:
    """POST /api/v1/commands with a non-loopback Origin is 403 even when
    a session cookie is present."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    status, _hdrs, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, body)
    csrf_token = json.loads(body)["csrf_token"]
    session_value = _session_from_cookies(cookies)
    headers = [
        ("Origin", "http://evil.example.com"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/commands",
        {"command": "paper.arm", "payload": {}},
        headers=headers,
    )
    assert status == 403, status


def test_commands_requires_csrf_header(home: Path) -> None:
    """POST /api/v1/commands with the right session + Origin but the wrong
    CSRF is 403."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _status, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert _status == 200
    session = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = session.split(";", 1)[0].split("=", 1)[1]
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", "wrong-csrf"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/commands",
        {"command": "paper.arm", "payload": {}},
        headers=headers,
    )
    assert status == 403, status


# ---- 4. commands endpoint delegates paper commands -----------------------


def _session_from_cookies(cookies: list[str]) -> str:
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    return cookie.split(";", 1)[0].split("=", 1)[1]


def test_commands_paper_arm_delegates_to_paper_service(home: Path) -> None:
    """A POST with full auth + paper.arm writes the same on-disk record
    the paper service writes."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _status, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert _status == 200
    decoded = json.loads(_b)
    csrf_token = decoded["csrf_token"]
    session_value = _session_from_cookies(cookies)

    pack_path = _write_dsl_pack(home)
    payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "correlation_id": "api-arm-1",
        "expected_revision": None,
        "payload": {
            "pack_path": str(pack_path),
            "venue": "kraken",
            "paper_balance": "1000",
        },
    }
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _hdrs, body, _cookies = _post_json(app, "/api/v1/commands", payload, headers=headers)
    assert status == 200, (status, body)
    result = json.loads(body)
    assert result["schema_version"] == "1"
    assert result["ok"] is True
    assert result["code"] == "armed"
    assert result["effect"] == "changed"
    # The on-disk config must now exist.
    assert (home / "config.json").exists()
    on_disk = json.loads((home / "config.json").read_text())
    assert on_disk["armed"], on_disk


def test_commands_paper_disarm_delegates(home: Path) -> None:
    """`paper.disarm` round-trips through PaperService.disarm."""

    _run_paper_arm(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _status, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert _status == 200, (_status, _b)
    decoded = json.loads(_b)
    csrf_token = decoded["csrf_token"]
    session_value = _session_from_cookies(cookies)

    payload = {
        "schema_version": "1",
        "command": "paper.disarm",
        "correlation_id": "api-disarm-1",
        "payload": {"venue": "kraken", "pair": "SUIUSD"},
    }
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _hdrs, body, _cookies = _post_json(app, "/api/v1/commands", payload, headers=headers)
    assert status == 200, (status, body)
    result = json.loads(body)
    assert result["code"] == "disarmed"


def test_commands_paper_pause_resume_and_raise_stop_delegate(home: Path) -> None:
    """pause / resume / raise-stop each round-trip through PaperService."""

    _run_paper_arm(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _status, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    decoded = json.loads(_b)
    csrf_token = decoded["csrf_token"]
    session_value = _session_from_cookies(cookies)
    base_headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={session_value}"),
    ]

    pause = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "paper.pause_entries",
            "payload": {"venue": "kraken", "pair": "SUIUSD"},
        },
        headers=base_headers,
    )
    assert pause[0] == 200, pause
    assert json.loads(pause[2])["code"] == "entries_paused"

    resume = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "paper.resume_entries",
            "payload": {"venue": "kraken", "pair": "SUIUSD"},
        },
        headers=base_headers,
    )
    assert resume[0] == 200, resume
    assert json.loads(resume[2])["code"] == "entries_resumed"

    raise_stop = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "paper.raise_stop",
            "payload": {"venue": "kraken", "pair": "SUIUSD", "new_stop": "10"},
        },
        headers=base_headers,
    )
    assert raise_stop[0] == 200, raise_stop
    assert json.loads(raise_stop[2])["code"] == "stop_raised"


def _run_paper_arm(home: Path) -> None:
    """Arm a pack via the paper service so disarm/pause/raise-stop tests
    have a record to act on."""

    from krellbot.application.paper import PaperService

    pack_path = _write_dsl_pack(home)
    service = PaperService(home=home)
    result = service.arm(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), correlation_id="seed")
    assert result.ok, result.message


def _bootstrap_and_get_csrf(app, token: str) -> str:
    s, _h, _b, _c = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert s == 200
    return json.loads(_b)["csrf_token"]


# ---- 5. live commands are 403 and leave config untouched -----------------


def test_commands_live_mode_in_arm_payload_returns_403_and_leaves_config(home: Path) -> None:
    """A paper.arm request with a ``mode: live`` payload is 403 and the
    config file is unchanged."""

    _write_dsl_pack(home)
    before = _config_bytes(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _status, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    decoded = json.loads(_b)
    csrf_token = decoded["csrf_token"]
    session_value = _session_from_cookies(cookies)
    pack_path = _write_dsl_pack(home)

    payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "payload": {
            "pack_path": str(pack_path),
            "venue": "kraken",
            "mode": "live",
            "paper_balance": "1000",
        },
    }
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _hdrs, body, _cookies = _post_json(app, "/api/v1/commands", payload, headers=headers)
    assert status == 403, (status, body)
    # Config bytes must be byte-identical to before.
    assert _config_bytes(home) == before


def test_commands_live_command_name_returns_403_and_leaves_config(home: Path) -> None:
    """A command whose name starts with ``live.`` is 403 without mutation."""

    before = _config_bytes(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _status, _h, _b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    decoded = json.loads(_b)
    csrf_token = decoded["csrf_token"]
    session_value = _session_from_cookies(cookies)

    payload = {
        "schema_version": "1",
        "command": "live.arm",
        "payload": {"venue": "kraken"},
    }
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _hdrs, body, _cookies = _post_json(app, "/api/v1/commands", payload, headers=headers)
    assert status == 403, (status, body)
    assert _config_bytes(home) == before


# ---- 6. capabilities endpoint --------------------------------------------


def test_capabilities_reports_paper_research_available_live_unavailable(home: Path) -> None:
    """``GET /api/v1/capabilities`` reports paper commands and research as
    available, live orders as unavailable."""

    app = _build_app(home)
    status, _hdrs, body, _cookies = asgi_call(
        app, method="GET", path="/api/v1/capabilities", headers=_default_host_header()
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1"
    paper = decoded.get("paper_commands")
    assert isinstance(paper, list)
    for cmd in ("paper.arm", "paper.disarm", "paper.pause_entries", "paper.resume_entries", "paper.raise_stop"):
        assert cmd in paper, cmd
    assert decoded.get("research") is True
    assert decoded.get("live_orders") is False


# ---- 7. OpenAPI schema includes the v1 paths ------------------------------


def test_openapi_schema_includes_session_and_commands_paths(home: Path) -> None:
    """The generated OpenAPI document lists the session and command routes."""

    app = _build_app(home)
    status, _hdrs, body, _cookies = asgi_call(app, method="GET", path="/openapi.json", headers=_default_host_header())
    assert status == 200, (status, body)
    schema = json.loads(body)
    paths = schema.get("paths") or {}
    assert "/api/v1/session/bootstrap" in paths, sorted(paths.keys())
    assert "/api/v1/commands" in paths, sorted(paths.keys())
    assert "/api/v1/capabilities" in paths, sorted(paths.keys())


# ---- 8. existing wizard/dashboard server remains available ----------------


def test_existing_dashboard_server_still_works(home: Path) -> None:
    """`krellbot.ui.server.DashboardServer` continues to bind, expose the
    dashboard, and host the wizard/dashboard routes the M1 contract
    explicitly preserves."""

    from krellbot.ui.server import DashboardServer

    server = DashboardServer(home=home, port=0)
    try:
        server.start()
        assert server.bound_host == "127.0.0.1"
        import http.client

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

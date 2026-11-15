"""M1.10 — web-owned live authorization API.

Covers J8.2–J8.5 from ``docs/journeys/j8-live-authorization.md``:

* grant for one exact venue/pair with expiry behind typed ``LIVE``
* expiry clears authorization for live send
* revoke clears authorization
* wrong-pair refusal leaves the fake transport uncalled

J8.1 (paper-only disabled panel) is covered by the browser journey.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import MagicMock

TEST_PORT = 8080
VENUE = "kraken"
PAIR = "BTC/USD"
OTHER_PAIR = "ETH/USD"


def _now() -> int:
    return int(time.time())


def _ascii_headers(headers: list[tuple[str, str]]) -> list[tuple[bytes, bytes]]:
    return [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers]


def asgi_call(
    app,
    *,
    method: str,
    path: str,
    body: bytes | None = None,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
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
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": b"",
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


def _origin() -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{TEST_PORT}")]


def _build_app(home: Path, *, bootstrap_token: str = "boot-live-auth"):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


def _post_json(app, path: str, payload: dict, headers: list[tuple[str, str]] | None = None):
    body = json.dumps(payload).encode("utf-8")
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="POST", path=path, body=body, headers=base)


def _delete(app, path: str, headers: list[tuple[str, str]] | None = None):
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="DELETE", path=path, headers=base)


def _get(app, path: str, headers: list[tuple[str, str]] | None = None):
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=path, headers=base)


def _bootstrap(app, token: str = "boot-live-auth") -> list[tuple[str, str]]:
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_origin(),
    )
    assert status == 200, body
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


class FakeTransport:
    """Spy transport; never talks to a live venue."""

    def __init__(self) -> None:
        self.send = MagicMock()
        self.balances = MagicMock(return_value={"USD": 1000.0})
        self.calls: list[object] = []

    def was_sent(self) -> bool:
        return self.send.called


def _install_transport(app, transport: FakeTransport) -> None:
    app.state.krellbot.live_transport = transport


def test_paper_only_get_shows_disabled_policy(home: Path) -> None:
    """GET reports paper-only so the Operations panel can stay visible/disabled."""
    app = _build_app(home)
    session = _bootstrap(app)
    status, _headers, body, _cookies = _get(
        app,
        "/api/v1/operations/live-authorization",
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["release_policy"] == "paper_only"
    assert payload["release_policy_code"] == "live_disabled_paper_only_release"
    assert "paper-only" in (payload["release_policy_message"] or "").lower()
    assert payload["confirmation_required"] == "LIVE"
    assert payload["authorization"]["active"] is False


def test_paper_only_grant_refuses_without_writing(home: Path) -> None:
    from krellbot.application import live_gate

    app = _build_app(home)
    session = _bootstrap(app)
    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/operations/live-authorization",
        {
            "venue": VENUE,
            "pair": PAIR,
            "expires_at": _now() + 3600,
            "confirmation": "LIVE",
        },
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["code"] == "live_disabled_paper_only_release"
    assert not live_gate.auth_path(home).exists()


def test_grant_creates_authorization_for_exact_venue_pair(home: Path, live_capable_release, monkeypatch) -> None:
    """J8.2 — grant behind typed LIVE creates one exact venue/pair authorization."""
    from krellbot.application import live_gate

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")

    app = _build_app(home)
    session = _bootstrap(app)
    now = _now()
    expires_at = now + 3600
    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/operations/live-authorization",
        {
            "venue": VENUE,
            "pair": PAIR,
            "expires_at": expires_at,
            "confirmation": "LIVE",
        },
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["code"] == "live_authorized"
    assert payload["authorization"]["active"] is True
    assert payload["authorization"]["expires_at"] == expires_at
    assert payload["authorization"]["grants"] == [{"venue": VENUE, "pair": PAIR}]

    grants = live_gate.read_authorization(home, now=now)
    assert grants == [(VENUE, PAIR)]
    gate = live_gate.check_live_send(
        home,
        venue=VENUE,
        pair=PAIR,
        env={"KRELLBOT_ENABLE_LIVE": "1"},
        now=now,
    )
    assert gate.ok is True
    assert gate.code == "ok"


def test_expired_authorization_refuses_live_send(home: Path, live_capable_release, monkeypatch) -> None:
    """J8.3 — after expiry the grant no longer authorizes a live send."""
    from krellbot.application import live_gate

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    app = _build_app(home)
    session = _bootstrap(app)
    now = _now()
    expires_at = now + 30
    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/operations/live-authorization",
        {
            "venue": VENUE,
            "pair": PAIR,
            "expires_at": expires_at,
            "confirmation": "LIVE",
        },
        headers=session,
    )
    assert status == 200, body
    assert json.loads(body.decode("utf-8"))["ok"] is True

    still_ok = live_gate.check_live_send(
        home,
        venue=VENUE,
        pair=PAIR,
        env={"KRELLBOT_ENABLE_LIVE": "1"},
        now=now + 5,
    )
    assert still_ok.ok is True

    expired = live_gate.check_live_send(
        home,
        venue=VENUE,
        pair=PAIR,
        env={"KRELLBOT_ENABLE_LIVE": "1"},
        now=expires_at + 1,
    )
    assert expired.ok is False
    assert expired.code == live_gate.CODE_LIVE_NOT_AUTHORIZED
    assert live_gate.read_authorization(home, now=expires_at + 1) == []


def test_revoke_clears_authorization(home: Path, live_capable_release, monkeypatch) -> None:
    """J8.4 — revoke removes the authorization so no venue/pair remains authorized."""
    from krellbot.application import live_gate

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    app = _build_app(home)
    session = _bootstrap(app)
    now = _now()
    grant_status, _h, grant_body, _c = _post_json(
        app,
        "/api/v1/operations/live-authorization",
        {
            "venue": VENUE,
            "pair": PAIR,
            "expires_at": now + 3600,
            "confirmation": "LIVE",
        },
        headers=session,
    )
    assert grant_status == 200, grant_body
    assert json.loads(grant_body.decode("utf-8"))["ok"] is True

    rev_status, _h, rev_body, _c = _delete(
        app,
        "/api/v1/operations/live-authorization",
        headers=session,
    )
    assert rev_status == 200, rev_body
    payload = json.loads(rev_body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["code"] == "live_authorization_revoked"
    assert payload["authorization"]["active"] is False
    assert live_gate.read_authorization(home, now=now) == []
    assert not live_gate.auth_path(home).exists()


def test_wrong_pair_refuses_without_calling_fake_transport(home: Path, live_capable_release, monkeypatch) -> None:
    """J8.5 — a different pair is refused and the fake transport is never called."""
    from krellbot.application import live_gate

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    app = _build_app(home)
    transport = FakeTransport()
    _install_transport(app, transport)
    session = _bootstrap(app)
    now = _now()

    grant_status, _h, grant_body, _c = _post_json(
        app,
        "/api/v1/operations/live-authorization",
        {
            "venue": VENUE,
            "pair": PAIR,
            "expires_at": now + 3600,
            "confirmation": "LIVE",
        },
        headers=session,
    )
    assert grant_status == 200, grant_body
    assert json.loads(grant_body.decode("utf-8"))["ok"] is True

    wrong = live_gate.check_live_send(
        home,
        venue=VENUE,
        pair=OTHER_PAIR,
        env={"KRELLBOT_ENABLE_LIVE": "1"},
        now=now,
    )
    assert wrong.ok is False
    assert wrong.code == live_gate.CODE_LIVE_NOT_AUTHORIZED
    # Wrong-pair refusal happens in the gate before any venue I/O, so the
    # installed fake transport must remain untouched.
    assert transport.was_sent() is False
    assert transport.send.call_count == 0
    assert any(name == "X-Krellbot-CSRF" for name, _value in session)


def test_grant_requires_typed_live_confirmation(home: Path, live_capable_release, monkeypatch) -> None:
    from krellbot.application import live_gate

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    app = _build_app(home)
    session = _bootstrap(app)
    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/operations/live-authorization",
        {
            "venue": VENUE,
            "pair": PAIR,
            "expires_at": _now() + 3600,
            "confirmation": "live",
        },
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["code"] == "confirmation_required"
    assert not live_gate.auth_path(home).exists()

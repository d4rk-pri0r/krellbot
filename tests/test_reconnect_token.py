"""Reconnect token: short-lived local re-pair for a second session.

Pins M8.1 behaviour:

* An authenticated session can ``POST /api/v1/session/reconnect/issue``
  (session cookie + CSRF + loopback Origin) and receive a short-lived
  token plus a QR payload URL.
* A second browser redeems via ``POST /api/v1/session/reconnect/redeem``
  with loopback Origin only (no prior session) and receives a new
  session cookie + CSRF — without restarting the process or reviving
  the one-time bootstrap token.
* Fake clock: an expired offer is refused; Host / Origin / CSRF / session
  gates stay intact on issue and redeem.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot.api.app import CSRF_HEADER, SESSION_COOKIE
from krellbot.api.security import RECONNECT_TOKEN_TTL_SECONDS
from tests.test_ns06_api import asgi_call

TEST_PORT = 8080


def _build_app(home: Path, *, bootstrap_token: str = "boot-reconnect"):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


def _origin() -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{TEST_PORT}")]


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


def _bootstrap(app, token: str = "boot-reconnect") -> list[tuple[str, str]]:
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_origin(),
    )
    assert status == 200, body
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        (CSRF_HEADER, csrf),
        ("Cookie", f"{SESSION_COOKIE}={session_value}"),
    ]


def _set_clock(app, now: int) -> None:
    app.state.krellbot.clock = lambda: now


def test_reconnect_issue_requires_session_csrf_and_loopback_origin(home: Path) -> None:
    app = _build_app(home)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=[])
    assert status == 403, body
    assert json.loads(body)["detail"] == "origin not loopback"

    no_csrf = [h for h in session if h[0] != CSRF_HEADER]
    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=no_csrf)
    assert status == 403, body
    assert json.loads(body)["detail"] == "csrf required"

    no_cookie = [h for h in session if h[0] != "Cookie"]
    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=no_cookie)
    assert status == 403, body
    assert json.loads(body)["detail"] == "session required"


def test_reconnect_issue_rejects_non_loopback_host(home: Path) -> None:
    app = _build_app(home)
    session = _bootstrap(app)
    body = b"{}"
    status, _h, resp, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/session/reconnect/issue",
        body=body,
        headers=[
            ("Host", "evil.example"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            *session,
        ],
    )
    assert status == 403, resp
    assert json.loads(resp)["detail"] == "loopback only"


def test_authenticated_session_issues_token_and_qr_payload(home: Path) -> None:
    app = _build_app(home)
    session = _bootstrap(app)
    _set_clock(app, 1_700_000_000)

    status, headers, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=session)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["schema_version"] == "1"
    assert isinstance(payload["token"], str) and len(payload["token"]) >= 16
    assert payload["expires_at"] == 1_700_000_000 + RECONNECT_TOKEN_TTL_SECONDS
    assert payload["expires_in"] == RECONNECT_TOKEN_TTL_SECONDS
    assert payload["redeem_path"] == f"/?reconnect={payload['token']}"
    assert payload["qr_payload"] == f"http://127.0.0.1:{TEST_PORT}/?reconnect={payload['token']}"
    header_map = {n.lower(): v for n, v in headers}
    assert header_map.get("cache-control") == "no-store"


def test_second_session_redeems_reconnect_token_with_fake_clock(home: Path) -> None:
    app = _build_app(home)
    primary = _bootstrap(app)
    _set_clock(app, 1_700_000_000)

    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=primary)
    assert status == 200, body
    token = json.loads(body)["token"]
    primary_sessions = set(app.state.krellbot.sessions)

    # Still valid just before expiry.
    _set_clock(app, 1_700_000_000 + RECONNECT_TOKEN_TTL_SECONDS - 1)
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/reconnect/redeem",
        {"token": token},
        headers=_origin(),
    )
    assert status == 200, body
    second = json.loads(body)
    assert isinstance(second["csrf_token"], str) and second["csrf_token"]
    cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    second_session = cookie.split(";", 1)[0].split("=", 1)[1]
    assert second_session not in primary_sessions
    assert second_session in app.state.krellbot.sessions
    assert app.state.krellbot.sessions[second_session] == second["csrf_token"]
    # Primary session is untouched; offer is spent.
    assert primary_sessions <= set(app.state.krellbot.sessions)
    assert app.state.krellbot.reconnect_offer is None

    # Second redeem of the same token fails.
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/session/reconnect/redeem",
        {"token": token},
        headers=_origin(),
    )
    assert status == 403, body
    assert json.loads(body)["detail"] == "wrong token"


def test_reconnect_redeem_refuses_expired_token_with_fake_clock(home: Path) -> None:
    app = _build_app(home)
    primary = _bootstrap(app)
    _set_clock(app, 1000)

    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=primary)
    token = json.loads(body)["token"]

    _set_clock(app, 1000 + RECONNECT_TOKEN_TTL_SECONDS)
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/session/reconnect/redeem",
        {"token": token},
        headers=_origin(),
    )
    assert status == 403, body
    assert json.loads(body)["detail"] == "token expired"
    assert app.state.krellbot.reconnect_offer is None


def test_reconnect_redeem_requires_loopback_origin_and_host(home: Path) -> None:
    app = _build_app(home)
    primary = _bootstrap(app)
    _set_clock(app, 50)
    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=primary)
    token = json.loads(body)["token"]

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/session/reconnect/redeem",
        {"token": token},
        headers=[("Origin", "http://evil.example")],
    )
    assert status == 403, body
    assert json.loads(body)["detail"] == "origin not loopback"
    # Offer still outstanding after a refused Origin.
    assert app.state.krellbot.reconnect_offer is not None

    raw = json.dumps({"token": token}).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/session/reconnect/redeem",
        body=raw,
        headers=[
            ("Host", "evil.example"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(raw))),
        ],
    )
    assert status == 403, body
    assert json.loads(body)["detail"] == "loopback only"


def test_reconnect_does_not_revive_spent_bootstrap_token(home: Path) -> None:
    app = _build_app(home, bootstrap_token="once-only")
    primary = _bootstrap(app, token="once-only")
    assert app.state.krellbot.bootstrap_used is True

    _set_clock(app, 10)
    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=primary)
    assert status == 200, body
    reconnect_token = json.loads(body)["token"]

    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/reconnect/redeem",
        {"token": reconnect_token},
        headers=_origin(),
    )
    assert status == 200, body
    assert any(c.startswith(f"{SESSION_COOKIE}=") for c in cookies)

    # Bootstrap remains spent.
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": "once-only"},
        headers=_origin(),
    )
    assert status == 403, body
    assert json.loads(body)["detail"] == "token already redeemed"


def test_second_session_can_use_csrf_after_reconnect_redeem(home: Path) -> None:
    """Redeemed session passes the same state-change gate as bootstrap."""

    app = _build_app(home)
    primary = _bootstrap(app)
    _set_clock(app, 200)
    token = json.loads(_post_json(app, "/api/v1/session/reconnect/issue", {}, headers=primary)[2])["token"]

    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/reconnect/redeem",
        {"token": token},
        headers=_origin(),
    )
    assert status == 200, body
    csrf = json.loads(body)["csrf_token"]
    cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    second_headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        (CSRF_HEADER, csrf),
        ("Cookie", f"{SESSION_COOKIE}={session_value}"),
    ]

    # Issue another reconnect token from the *second* session.
    status, _h, body, _c = _post_json(app, "/api/v1/session/reconnect/issue", {}, headers=second_headers)
    assert status == 200, body
    assert isinstance(json.loads(body)["token"], str)

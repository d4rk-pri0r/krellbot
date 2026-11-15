"""Keys onboarding API (Kraken): probe-store, status, deletion, balances.

Pins M3.1 loopback routes:

* ``POST /api/v1/keys/kraken`` probe-then-store via ``keys_onboarding``
* ``GET /api/v1/keys/kraken`` connection status + balances
* ``DELETE /api/v1/keys/kraken`` removal

Trade-only enforcement is preserved. Session/CSRF/origin/host checks are
unchanged. Tests use FakeKeyring + FakeKrakenTransport only — no real
credentials, no live venue calls, and no ``secrets.py`` / ``keys/`` path.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import keyring as _keyring
from fakes.fake_kraken import FakeKrakenTransport

from krellbot.api.app import CSRF_HEADER, SESSION_COOKIE

TEST_PORT = 8080
VENUE = "kraken"

# Fake-shaped Kraken secret (base64). Disposable test material only.
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="
KRAKEN_TEST_KEY = "fake-kraken-api-key-trade-only-001"
LEAKY_KEY = "FAKEKEY-API-DO-NOT-LOG-ME-XYZ"
LEAKY_SECRET = "FAKESECRET-API-DO-NOT-LOG-ME-XYZ"


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


def _build_app(home: Path, *, bootstrap_token: str = "boot-keys"):
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


def _bootstrap(app, token: str = "boot-keys") -> list[tuple[str, str]]:
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


def _trade_only_transport(*, balances: dict[str, str] | None = None) -> FakeKrakenTransport:
    bal = balances if balances is not None else {"ZUSD": "100.50", "XXBT": "0.01"}
    return FakeKrakenTransport(
        responses=[
            {"error": [], "result": bal},
            {"error": [], "result": {"trades": {}}},
        ],
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
            ]
        },
    )


def _withdraw_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        api_key_info={"permissions": ["query-funds", "withdraw-funds"]},
    )


def _enable_keys(app, transport: FakeKrakenTransport) -> None:
    app.state.krellbot.keys_transport = transport
    app.state.krellbot.keys_allow_fake_backend = True


def _assert_no_leak(body: bytes, *secrets: str) -> None:
    text = body.decode("utf-8", errors="replace")
    lowered = text.lower()
    for secret in secrets:
        assert secret not in text
        assert secret.lower() not in lowered


def test_keys_get_absent_when_no_key_stored(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    status, headers, body, _cookies = _get(app, f"/api/v1/keys/{VENUE}", headers=session)
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["schema_version"] == "1"
    assert payload["venue"] == VENUE
    assert payload["present"] is False
    assert payload["corrupt"] is False
    assert payload["balances"] is None
    assert payload["balances_available"] is False
    assert payload["message"] == "no key stored"
    assert dict(headers).get("cache-control") == "no-store"


def test_keys_post_stores_trade_only_and_get_returns_balances(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    transport = _trade_only_transport()
    _enable_keys(app, transport)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": KRAKEN_TEST_KEY, "secret": KRAKEN_TEST_SECRET_B64},
        headers=session,
    )
    assert status == 200, body
    stored = json.loads(body.decode("utf-8"))
    assert stored["ok"] is True
    assert stored["status"] == "stored"
    assert stored["effect"] == "changed"
    assert stored["message"] == "stored in native OS keychain"
    _assert_no_leak(body, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)

    # Pair is in the fake keyring; never assert by printing secrets.
    assert _keyring.get_password(f"krellbot:{VENUE}", "key") == KRAKEN_TEST_KEY
    assert _keyring.get_password(f"krellbot:{VENUE}", "secret") == KRAKEN_TEST_SECRET_B64

    status, _h, body, _c = _get(app, f"/api/v1/keys/{VENUE}", headers=session)
    assert status == 200, body
    snap = json.loads(body.decode("utf-8"))
    assert snap["present"] is True
    assert snap["corrupt"] is False
    assert snap["balances_available"] is True
    assert snap["balances"] == [
        {"asset": "ZUSD", "free": "100.5"},
        {"asset": "XXBT", "free": "0.01"},
    ]
    _assert_no_leak(body, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)


def test_keys_post_refuses_withdraw_capable_without_storing(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _withdraw_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": LEAKY_KEY, "secret": KRAKEN_TEST_SECRET_B64},
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["status"] == "refused_withdraw"
    assert payload["effect"] == "refused"
    assert _keyring.get_password(f"krellbot:{VENUE}", "key") is None
    assert _keyring.get_password(f"krellbot:{VENUE}", "secret") is None
    _assert_no_leak(body, LEAKY_KEY, KRAKEN_TEST_SECRET_B64)


def test_keys_delete_removes_stored_pair(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": KRAKEN_TEST_KEY, "secret": KRAKEN_TEST_SECRET_B64},
        headers=session,
    )
    assert status == 200, body
    assert json.loads(body.decode("utf-8"))["ok"] is True

    # Fresh transport for a post-delete status read (Balance queue consumed).
    _enable_keys(app, _trade_only_transport())

    status, _h, body, _c = _delete(app, f"/api/v1/keys/{VENUE}", headers=session)
    assert status == 200, body
    removed = json.loads(body.decode("utf-8"))
    assert removed["ok"] is True
    assert removed["status"] == "removed"
    assert removed["effect"] == "changed"
    assert _keyring.get_password(f"krellbot:{VENUE}", "key") is None
    assert _keyring.get_password(f"krellbot:{VENUE}", "secret") is None

    status, _h, body, _c = _get(app, f"/api/v1/keys/{VENUE}", headers=session)
    assert status == 200, body
    snap = json.loads(body.decode("utf-8"))
    assert snap["present"] is False
    assert snap["message"] == "no key stored"


def test_keys_post_requires_csrf_and_session(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    # Missing CSRF header.
    no_csrf = [h for h in session if h[0] != CSRF_HEADER]
    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": KRAKEN_TEST_KEY, "secret": KRAKEN_TEST_SECRET_B64},
        headers=no_csrf,
    )
    assert status == 403, body
    assert json.loads(body.decode("utf-8"))["detail"] == "csrf required"

    # Missing session cookie.
    no_cookie = [h for h in session if h[0] != "Cookie"]
    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": KRAKEN_TEST_KEY, "secret": KRAKEN_TEST_SECRET_B64},
        headers=no_cookie,
    )
    assert status == 403, body
    assert json.loads(body.decode("utf-8"))["detail"] == "session required"


def test_keys_post_rejects_non_loopback_origin(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)
    bad = [(n, "http://evil.example" if n == "Origin" else v) for n, v in session]

    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": KRAKEN_TEST_KEY, "secret": KRAKEN_TEST_SECRET_B64},
        headers=bad,
    )
    assert status == 403, body
    assert json.loads(body.decode("utf-8"))["detail"] == "origin not loopback"
    assert _keyring.get_password(f"krellbot:{VENUE}", "key") is None


def test_keys_get_requires_session(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())

    status, _h, body, _c = _get(
        app,
        f"/api/v1/keys/{VENUE}",
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, body
    assert json.loads(body.decode("utf-8"))["detail"] == "session required"


def test_keys_delete_requires_csrf(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)
    no_csrf = [h for h in session if h[0] != CSRF_HEADER]

    status, _h, body, _c = _delete(app, f"/api/v1/keys/{VENUE}", headers=no_csrf)
    assert status == 403, body
    assert json.loads(body.decode("utf-8"))["detail"] == "csrf required"


def test_keys_rejects_non_loopback_host(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path=f"/api/v1/keys/{VENUE}",
        headers=[("Host", "evil.example")] + session,
    )
    assert status == 403, body
    assert json.loads(body.decode("utf-8"))["detail"] == "loopback only"


def test_keys_unknown_venue_is_not_found(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _get(app, "/api/v1/keys/binance", headers=session)
    assert status == 404, body
    assert json.loads(body.decode("utf-8"))["detail"] == "not found"


def test_keys_post_does_not_echo_leaky_credentials_on_invalid_body(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": LEAKY_KEY, "secret": 123},
        headers=session,
    )
    assert status == 400, body
    _assert_no_leak(body, LEAKY_KEY)

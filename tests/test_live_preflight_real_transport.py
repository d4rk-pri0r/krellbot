"""Deploy preflight uses a real venue transport seam (M10.2).

Pins:

* Production wiring builds ``VenueBackedPreflightTransport`` (or a blocked
  stand-in when no key is stored) — never the legacy zero-USD
  ``SandboxTransport``.
* With a stored trade-only key and injectable ``FakeKrakenTransport``,
  ``live.preflight`` checks permissions (GetApiKeyInfo) and balances
  (Balance / snapshot), returns those in the body, and never places
  (no AddOrder).
* Bad permissions and unreachable balance reads refuse with typed codes
  without calling ``send`` / AddOrder.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fakes.fake_kraken import FakeKrakenTransport

from krellbot.api.app import _live_transport
from krellbot.application.live_preflight import (
    CODE_KEY_WITHDRAW_CAPABLE,
    CODE_OK,
    CODE_PREFLIGHT_BLOCKED,
    CODE_VENUE_UNREACHABLE,
    SandboxTransport,
    VenueBackedPreflightTransport,
    build_venue_preflight_transport,
    evaluate,
)

TEST_PORT = 8080
VENUE = "kraken"
KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="

_TRADE_ONLY_PERMS = [
    "query-funds",
    "query-open-trades",
    "modify-trades",
    "close-trades",
]


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


def _build_app(home: Path, *, bootstrap_token: str = "boot-preflight-real"):
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


def _bootstrap(app, token: str = "boot-preflight-real") -> list[tuple[str, str]]:
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
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


def _trade_only_transport(*, balances: dict[str, str] | None = None) -> FakeKrakenTransport:
    bal = balances if balances is not None else {"ZUSD": "100.50", "XXBT": "0.01"}
    return FakeKrakenTransport(
        responses=[
            {"error": [], "result": bal},
            {"error": [], "result": {"trades": {}}},
        ],
        api_key_info={"permissions": list(_TRADE_ONLY_PERMS)},
    )


def _enable_keys(app, transport: FakeKrakenTransport) -> None:
    app.state.krellbot.keys_transport = transport
    app.state.krellbot.keys_allow_fake_backend = True


def _store_kraken_key(fresh_keyring) -> None:
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)


def _preflight_payload(
    *,
    account_id: str = VENUE,
    revision_id: str = "rev-preflight-1",
    mode: str = "sandbox",
    venue: str = VENUE,
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "command": "live.preflight",
        "correlation_id": "preflight-real-1",
        "payload": {
            "account_id": account_id,
            "revision_id": revision_id,
            "mode": mode,
            "venue": venue,
        },
    }


def _endpoints(transport: FakeKrakenTransport) -> list[str]:
    return [call.url.rsplit("/", 1)[-1] for call in transport.calls]


def test_production_factory_is_not_sandbox_zero_usd(fresh_keyring) -> None:
    """Default factory never returns SandboxTransport with a zero USD stub."""
    del fresh_keyring
    transport = build_venue_preflight_transport(venue=VENUE, http_transport=FakeKrakenTransport())
    assert not isinstance(transport, SandboxTransport)
    assert transport.account == VENUE


def test_app_live_transport_defaults_to_venue_backed(home: Path, fresh_keyring) -> None:
    """App factory builds a venue-backed (or blocked) transport, not SandboxTransport."""
    _store_kraken_key(fresh_keyring)
    app = _build_app(home)
    http = _trade_only_transport()
    _enable_keys(app, http)
    resolved = _live_transport(app.state.krellbot, venue=VENUE)
    assert not isinstance(resolved, SandboxTransport)
    assert isinstance(resolved, VenueBackedPreflightTransport)
    assert resolved.account == VENUE


def test_helper_trade_only_balance_check_never_sends(fresh_keyring) -> None:
    """Venue-backed helper reads permissions + balances and never calls send."""
    _store_kraken_key(fresh_keyring)
    http = _trade_only_transport()
    transport = build_venue_preflight_transport(venue=VENUE, http_transport=http)
    result = evaluate(
        account_id=VENUE,
        revision_id="rev-1",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is True, result
    assert result.code == CODE_OK
    assert result.permissions == {"can_trade": True, "can_withdraw": False}
    assert result.balances is not None
    assert "ZUSD" in result.balances
    assert "XXBT" in result.balances
    endpoints = _endpoints(http)
    assert "GetApiKeyInfo" in endpoints
    assert "Balance" in endpoints
    assert "AddOrder" not in endpoints


def test_app_preflight_trade_only_returns_balances_and_permissions(home: Path, fresh_keyring) -> None:
    """POST live.preflight through the app hits FakeKraken and returns status."""
    _store_kraken_key(fresh_keyring)
    http = _trade_only_transport()
    app = _build_app(home)
    _enable_keys(app, http)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is True, decoded
    assert decoded["code"] == CODE_OK
    assert decoded["account_id"] == VENUE
    assert decoded["permissions"] == {"can_trade": True, "can_withdraw": False}
    assert decoded["balances"]["ZUSD"] == "100.50"
    assert decoded["balances"]["XXBT"] == "0.01"
    endpoints = _endpoints(http)
    assert "GetApiKeyInfo" in endpoints
    assert "Balance" in endpoints
    assert not any("AddOrder" in call.url for call in http.calls)


def test_app_preflight_blocks_withdraw_capable_key(home: Path, fresh_keyring) -> None:
    """A key with withdraw rights refuses as key_withdraw_capable without placing."""
    _store_kraken_key(fresh_keyring)
    http = FakeKrakenTransport(
        responses=[
            {"error": [], "result": {"ZUSD": "50"}},
            {"error": [], "result": {"trades": {}}},
        ],
        api_key_info={
            "permissions": [
                *_TRADE_ONLY_PERMS,
                "withdraw-funds",
            ]
        },
    )
    app = _build_app(home)
    _enable_keys(app, http)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_KEY_WITHDRAW_CAPABLE
    assert "AddOrder" not in _endpoints(http)
    assert "Balance" not in _endpoints(http)


def test_app_preflight_venue_unreachable_on_balance_failure(home: Path, fresh_keyring) -> None:
    """Balance permission denial surfaces as venue_unreachable after trade-only check."""
    _store_kraken_key(fresh_keyring)
    http = FakeKrakenTransport(
        responses=[],
        permission_error_on={"Balance"},
        api_key_info={"permissions": list(_TRADE_ONLY_PERMS)},
    )
    app = _build_app(home)
    _enable_keys(app, http)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_VENUE_UNREACHABLE
    assert "GetApiKeyInfo" in _endpoints(http)
    assert not any("AddOrder" in call.url for call in http.calls)


def test_app_preflight_missing_key_is_blocked(home: Path, fresh_keyring) -> None:
    """No stored key refuses as preflight_blocked without venue I/O."""
    del fresh_keyring
    http = _trade_only_transport()
    app = _build_app(home)
    _enable_keys(app, http)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_PREFLIGHT_BLOCKED
    assert http.calls == []

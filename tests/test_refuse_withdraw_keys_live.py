"""Refuse withdraw-capable and unknown-permission keys (M20.2).

Pins SECURITY.md posture with fake transports only:

* Web ``live.arm`` returns typed 403 codes for withdraw-capable and
  unrecognized-permission keys; config is unchanged and no AddOrder.
* Keys onboarding POST refuses the same keys without storing.
* Live preflight refuses withdraw-capable keys with a typed code.
* Exchange / keys status copy never claims a live "connected" state.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import keyring as _keyring
from fakes.fake_kraken import FakeKrakenTransport
from fakes.live_grant import write_grant

from krellbot.api import app as api_app
from krellbot.application.live_preflight import CODE_KEY_WITHDRAW_CAPABLE
from krellbot.release_policy import PAPER_ONLY_RELEASE

TEST_PORT = 8080
VENUE = "kraken"
PAIR = "SUIUSD"
KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="
LEAKY_KEY = "LEAKY-WITHDRAW-KEY-MATERIAL"
LEAKY_SECRET = KRAKEN_TEST_SECRET_B64

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


def _build_app(home: Path, *, bootstrap_token: str = "boot-refuse-withdraw"):
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


def _get(app, path: str, headers: list[tuple[str, str]] | None = None):
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=path, headers=base)


def _bootstrap(app, token: str = "boot-refuse-withdraw") -> list[tuple[str, str]]:
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


def _write_pack(home: Path, *, pack_id: str = "refuse-withdraw-arm", pair: str = PAIR) -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Refuse withdraw keys live",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": VENUE, "pair": pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _trade_only_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        responses=[
            {"error": [], "result": {"ZUSD": "100.50", "XXBT": "0.01"}},
            {"error": [], "result": {"trades": {}}},
        ],
        api_key_info={"permissions": list(_TRADE_ONLY_PERMS)},
    )


def _withdraw_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        api_key_info={"permissions": ["query-funds", "withdraw-funds"]},
    )


def _unknown_permission_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        api_key_info={
            "permissions": [
                *_TRADE_ONLY_PERMS,
                "transfer-funds",  # unrecognized → fail-closed
            ]
        },
    )


def _enable_keys(app, transport: FakeKrakenTransport) -> None:
    app.state.krellbot.keys_transport = transport
    app.state.krellbot.keys_allow_fake_backend = True


def _config_bytes(home: Path) -> bytes | None:
    path = home / "config.json"
    if not path.exists():
        return None
    return path.read_bytes()


def _live_arm_payload(pack_path: Path, *, confirmation: str = "LIVE") -> dict:
    return {
        "schema_version": "1",
        "command": "live.arm",
        "correlation_id": "refuse-withdraw-keys-1",
        "payload": {
            "pack_path": str(pack_path),
            "venue": VENUE,
            "mode": "live",
            "confirmation": confirmation,
        },
    }


def _preflight_payload() -> dict:
    return {
        "schema_version": "1",
        "command": "live.preflight",
        "correlation_id": "refuse-withdraw-preflight-1",
        "payload": {
            "account_id": VENUE,
            "revision_id": "rev-refuse-withdraw",
            "mode": "sandbox",
        },
    }


def _assert_no_leak(body: bytes, *secrets: str) -> None:
    text = body.decode("utf-8", errors="replace")
    lowered = text.lower()
    for secret in secrets:
        assert secret not in text
        assert secret.lower() not in lowered


def _assert_no_connected_claim(body: bytes) -> None:
    text = body.decode("utf-8", errors="replace").lower()
    assert "connected" not in text


def test_paper_only_release_still_true() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_web_live_arm_refuses_withdraw_capable_key_typed(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    del live_capable_release
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    pack_path = _write_pack(home)
    before = _config_bytes(home)
    transport = _withdraw_transport()
    app = _build_app(home)
    _enable_keys(app, transport)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path),
        headers=session,
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert decoded["effect"] == "refused"
    assert decoded["code"] == api_app.CODE_LIVE_ARM_KEY_WITHDRAW_CAPABLE
    assert "withdraw" in decoded["message"].lower()
    assert _config_bytes(home) == before
    assert not any("AddOrder" in c.url for c in transport.calls)
    assert any("GetApiKeyInfo" in c.url for c in transport.calls)
    _assert_no_connected_claim(body)
    _assert_no_leak(body, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)


def test_web_live_arm_refuses_unknown_permission_typed(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    del live_capable_release
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    pack_path = _write_pack(home)
    before = _config_bytes(home)
    transport = _unknown_permission_transport()
    app = _build_app(home)
    _enable_keys(app, transport)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path),
        headers=session,
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert decoded["effect"] == "refused"
    assert decoded["code"] == api_app.CODE_LIVE_ARM_KEY_UNKNOWN_PERMISSION
    assert decoded["code"] != api_app.CODE_LIVE_ARM_KEY_WITHDRAW_CAPABLE
    assert "unrecognized" in decoded["message"].lower() or "unknown" in decoded["message"].lower()
    assert "transfer-funds" not in decoded["message"]
    assert _config_bytes(home) == before
    assert not any("AddOrder" in c.url for c in transport.calls)
    _assert_no_connected_claim(body)
    _assert_no_leak(body, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)


def test_web_live_arm_trade_only_still_arms(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    del live_capable_release
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    pack_path = _write_pack(home)
    transport = _trade_only_transport()
    app = _build_app(home)
    _enable_keys(app, transport)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path),
        headers=session,
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is True
    assert decoded["code"] == "armed"
    assert decoded["effect"] == "changed"
    assert not any("AddOrder" in c.url for c in transport.calls)
    _assert_no_connected_claim(body)


def test_keys_post_refuses_withdraw_without_store(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _withdraw_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": LEAKY_KEY, "secret": LEAKY_SECRET},
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["status"] == "refused_withdraw"
    assert payload["effect"] == "refused"
    assert "withdraw" in payload["message"].lower()
    assert _keyring.get_password(f"krellbot:{VENUE}", "key") is None
    assert _keyring.get_password(f"krellbot:{VENUE}", "secret") is None
    _assert_no_connected_claim(body)
    _assert_no_leak(body, LEAKY_KEY, LEAKY_SECRET)


def test_keys_post_refuses_unknown_permission_without_store(home: Path, fresh_keyring) -> None:
    del fresh_keyring
    app = _build_app(home)
    _enable_keys(app, _unknown_permission_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        f"/api/v1/keys/{VENUE}",
        {"key": LEAKY_KEY, "secret": LEAKY_SECRET},
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["ok"] is False
    assert payload["status"] == "refused_unknown_permission"
    assert payload["effect"] == "refused"
    assert "transfer-funds" not in payload["message"]
    assert _keyring.get_password(f"krellbot:{VENUE}", "key") is None
    assert _keyring.get_password(f"krellbot:{VENUE}", "secret") is None
    _assert_no_connected_claim(body)
    _assert_no_leak(body, LEAKY_KEY, LEAKY_SECRET)


def test_live_preflight_blocks_withdraw_capable(home: Path, fresh_keyring) -> None:
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)
    transport = FakeKrakenTransport(
        responses=[
            {"error": [], "result": {"ZUSD": "50"}},
            {"error": [], "result": {"trades": {}}},
        ],
        api_key_info={"permissions": [*_TRADE_ONLY_PERMS, "withdraw-funds"]},
    )
    app = _build_app(home)
    _enable_keys(app, transport)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _preflight_payload(),
        headers=session,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert decoded["code"] == CODE_KEY_WITHDRAW_CAPABLE
    assert "withdraw" in decoded["message"].lower()
    assert not any("AddOrder" in c.url for c in transport.calls)
    _assert_no_connected_claim(body)


def test_keys_status_present_message_is_not_connected(home: Path, fresh_keyring) -> None:
    """Stored-key status reports presence, never a live 'connected' claim."""
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)
    app = _build_app(home)
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _get(app, f"/api/v1/keys/{VENUE}", headers=session)
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["present"] is True
    assert "connected" not in payload["message"].lower()
    assert payload["message"] == "key present"
    _assert_no_connected_claim(body)
    _assert_no_leak(body, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)

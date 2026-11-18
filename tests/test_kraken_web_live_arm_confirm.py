"""Kraken web live arm + confirm (M20.1).

Pins the Deploy/Operations workstation path:

* While ``PAPER_ONLY_RELEASE`` is True, ``live.arm`` returns an honest 403
  with ``live_disabled_paper_only_release`` and never places via fake transport.
* Typed ``LIVE`` confirmation on the arm payload is validated; a wrong
  confirm refuses before pack/key work (when the paper-only fence is lifted).
* Non-Kraken venues are refused (M20 is Kraken-only).
* With grant + env + trade-only key + typed LIVE, arm succeeds without stdin
  and without ``AddOrder``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fakes.fake_kraken import FakeKrakenTransport
from fakes.live_grant import write_grant

from krellbot.application import live_gate
from krellbot.release_policy import CODE_PAPER_ONLY_RELEASE, paper_only_message

TEST_PORT = 8080
VENUE = "kraken"
PAIR = "SUIUSD"
KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


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


def _build_app(home: Path, *, bootstrap_token: str = "boot-kraken-live-arm"):
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


def _bootstrap(app, token: str = "boot-kraken-live-arm") -> list[tuple[str, str]]:
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


def _write_pack(home: Path, *, pack_id: str = "kraken-live-arm", pair: str = PAIR) -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Kraken live arm confirm",
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
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
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


def _live_arm_payload(
    pack_path: Path,
    *,
    venue: str = VENUE,
    confirmation: str | None = "LIVE",
) -> dict:
    payload: dict[str, object] = {
        "pack_path": str(pack_path),
        "venue": venue,
        "mode": "live",
    }
    if confirmation is not None:
        payload["confirmation"] = confirmation
    return {
        "schema_version": "1",
        "command": "live.arm",
        "correlation_id": "kraken-live-arm-confirm-1",
        "payload": payload,
    }


def test_kraken_web_live_arm_paper_only_honest_403(home: Path, fresh_keyring) -> None:
    """Default release: live.arm is 403 with the paper-only code, no mutation."""
    del fresh_keyring
    before = _config_bytes(home)
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
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert decoded["code"] == CODE_PAPER_ONLY_RELEASE
    assert decoded["effect"] == "refused"
    assert decoded["message"] == paper_only_message()
    assert _config_bytes(home) == before
    assert not any("AddOrder" in c.url for c in transport.calls)


def test_kraken_web_live_arm_wrong_confirmation_refuses(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    del live_capable_release
    del fresh_keyring
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    pack_path = _write_pack(home)
    before = _config_bytes(home)
    transport = _trade_only_transport()
    app = _build_app(home)
    _enable_keys(app, transport)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path, confirmation="live"),
        headers=session,
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert decoded["code"] == live_gate.CODE_CONFIRMATION_REQUIRED
    assert _config_bytes(home) == before
    assert not any("AddOrder" in c.url for c in transport.calls)


def test_kraken_web_live_arm_refuses_non_kraken_venue(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    del live_capable_release
    del fresh_keyring
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home)
    before = _config_bytes(home)
    app = _build_app(home)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path, venue="coinbase", confirmation="LIVE"),
        headers=session,
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == live_gate.CODE_LIVE_ARM_VENUE_UNSUPPORTED
    assert "kraken" in decoded["message"].lower()
    assert _config_bytes(home) == before


def test_kraken_web_live_arm_confirm_succeeds_without_stdin(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    """Grant + env + trade-only key + typed LIVE arms without stdin or AddOrder."""
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

    prompts: list[str] = []

    def must_not_prompt() -> str:
        prompts.append("called")
        raise AssertionError("web live.arm must not prompt Type LIVE on stdin")

    monkeypatch.setattr("builtins.input", must_not_prompt)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path, confirmation="LIVE"),
        headers=session,
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is True
    assert decoded["code"] == "armed"
    assert decoded["effect"] == "changed"
    assert decoded["venue"] == VENUE
    assert decoded["pair"] == PAIR
    assert prompts == []

    on_disk = json.loads((home / "config.json").read_text(encoding="utf-8"))
    assert on_disk["live_first_armed"] is True
    assert len(on_disk["armed"]) == 1
    assert on_disk["armed"][0]["mode"] == "live"
    assert on_disk["armed"][0]["venue"] == VENUE
    assert on_disk["armed"][0]["pair"] == PAIR
    assert not any("AddOrder" in c.url for c in transport.calls)


def test_validate_web_live_arm_confirmation_helpers() -> None:
    assert live_gate.validate_web_live_arm_confirmation(None) is None
    assert live_gate.validate_web_live_arm_confirmation("LIVE") is None
    bad = live_gate.validate_web_live_arm_confirmation("live")
    assert bad is not None
    assert bad.code == live_gate.CODE_CONFIRMATION_REQUIRED

    ok_venue = live_gate.check_web_live_arm_venue("kraken")
    assert ok_venue is None
    refused = live_gate.check_web_live_arm_venue("binance")
    assert refused is not None
    assert refused.code == live_gate.CODE_LIVE_ARM_VENUE_UNSUPPORTED


def test_web_live_arm_preflight_venue_constant() -> None:
    from krellbot.application import live_preflight

    assert live_preflight.WEB_LIVE_ARM_PREFLIGHT_VENUE == "kraken"
    assert "kraken" in live_gate.WEB_LIVE_ARM_VENUES

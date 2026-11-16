"""Web ``live.arm`` behind the live gate (M10.1).

Pins:

* While ``PAPER_ONLY_RELEASE`` is True, ``POST /api/v1/commands``
  ``live.arm`` returns an honest 403 with ``live_disabled_paper_only_release``
  and leaves config untouched; fake transport is never asked to place.
* When the paper-only fence is lifted in tests, arming requires env + grant
  + kill-switch clear, uses the injectable fake key transport, and skips
  stdin ``Type LIVE`` (grant already required typed LIVE).
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


def _build_app(home: Path, *, bootstrap_token: str = "boot-web-live-arm"):
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


def _bootstrap(app, token: str = "boot-web-live-arm") -> list[tuple[str, str]]:
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


def _write_pack(home: Path, *, pack_id: str = "web-live-arm", pair: str = PAIR) -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Web live arm",
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


def _live_arm_payload(pack_path: Path) -> dict:
    return {
        "schema_version": "1",
        "command": "live.arm",
        "correlation_id": "web-live-arm-1",
        "payload": {
            "pack_path": str(pack_path),
            "venue": VENUE,
            "mode": "live",
        },
    }


def test_web_live_arm_paper_only_honest_403_leaves_config(home: Path, fresh_keyring) -> None:
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
    assert decoded["detail"] == paper_only_message()
    assert _config_bytes(home) == before
    assert not any("AddOrder" in c.url for c in transport.calls)


def test_web_live_arm_succeeds_behind_gate_without_stdin(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    """With grant + env + trade-only key, web arm succeeds and skips stdin."""
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
        _live_arm_payload(pack_path),
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
    # Key probe may hit GetApiKeyInfo; arm must never place.
    assert not any("AddOrder" in c.url for c in transport.calls)


def test_web_live_arm_refuses_without_grant(
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
    _enable_keys(app, _trade_only_transport())
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path),
        headers=session,
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == live_gate.CODE_LIVE_NOT_AUTHORIZED
    assert decoded["ok"] is False
    assert _config_bytes(home) == before


def test_web_live_arm_refuses_when_kill_engaged(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    del live_capable_release
    del fresh_keyring
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    live_gate.engage_kill(home, reason="test halt", now=1_700_000_000)
    pack_path = _write_pack(home)
    before = _config_bytes(home)
    app = _build_app(home)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path),
        headers=session,
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == live_gate.CODE_KILL_SWITCH
    assert _config_bytes(home) == before


def test_web_live_arm_refuses_when_env_unset(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    del live_capable_release
    del fresh_keyring
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    write_grant(home, venue=VENUE, pair=PAIR)
    pack_path = _write_pack(home)
    before = _config_bytes(home)
    app = _build_app(home)
    session = _bootstrap(app)

    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        _live_arm_payload(pack_path),
        headers=session,
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded["code"] == live_gate.CODE_LIVE_DISABLED
    assert _config_bytes(home) == before


def test_arm_pack_skip_confirm_bypasses_stdin(
    home: Path,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    """Engine seam: skip_confirm arms without confirm_fn / stdin."""
    from krellbot import secrets
    from krellbot.run import arm_pack
    from krellbot.venues.base import KeyPerms

    del live_capable_release
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    secrets.store("kraken", KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)
    pack_path = _write_pack(home)

    def must_not_call() -> str:
        raise AssertionError("confirm_fn must not run when skip_confirm=True")

    rc = arm_pack(
        pack_path,
        venue=VENUE,
        mode="live",
        home=home,
        skip_confirm=True,
        confirm_fn=must_not_call,
        key_check=lambda _v: KeyPerms(can_trade=True, can_withdraw=False),
    )
    assert rc == 0
    gate = live_gate.check_web_live_arm(
        home,
        venue=VENUE,
        pair=PAIR,
        env={"KRELLBOT_ENABLE_LIVE": "1"},
    )
    assert live_gate.web_arm_skips_stdin_confirmation(gate) is True


def test_check_web_live_arm_matches_check_live_send(home: Path) -> None:
    """Named web-arm entry point shares the send gate fence."""
    result = live_gate.check_web_live_arm(home, venue=VENUE, pair=PAIR)
    assert result.code == CODE_PAPER_ONLY_RELEASE
    assert live_gate.web_arm_skips_stdin_confirmation(result) is False

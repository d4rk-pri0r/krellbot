"""User policy file enforcement — MCP and workstation honor operator policy.

Pins M22.2: operator-owned ``user-policy.json`` under ``$KRELLBOT_HOME``
(allow paper-arm / deny key export by default; written policy can deny
live); MCP and the workstation refuse denied actions with typed codes;
policy writes are audited in the journal. Hard MCP live/key tool refuses
stay unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.api.app import CSRF_HEADER, SESSION_COOKIE, create_app
from krellbot.application import user_policy
from krellbot.application.paper import CODE_USER_POLICY_DENIED, PaperService
from krellbot.journal import read_records_lenient
from krellbot.mcp import CODE_POLICY_DENIED, McpTools
from krellbot.release_policy import PAPER_ONLY_RELEASE


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

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("latin-1"),
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


def _bootstrap(app, *, port: int, token: str) -> list[tuple[str, str]]:
    status, _h, body, cookies = asgi_call(
        app,
        method="POST",
        path="/api/v1/session/bootstrap",
        body=json.dumps({"token": token}).encode(),
        headers=[
            ("Host", f"127.0.0.1:{port}"),
            ("Origin", f"http://127.0.0.1:{port}"),
            ("Content-Type", "application/json"),
        ],
    )
    assert status == 200, body
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    cookie = next(c for c in cookies if c.startswith(f"{SESSION_COOKIE}="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Host", f"127.0.0.1:{port}"),
        ("Origin", f"http://127.0.0.1:{port}"),
        (CSRF_HEADER, csrf),
        ("Cookie", f"{SESSION_COOKIE}={session_value}"),
        ("Content-Type", "application/json"),
    ]


def _write_dsl_pack(
    home: Path,
    *,
    pack_id: str = "trend-follow",
    pair: str = "SUIUSD",
    venue: str = "kraken",
) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Trend follow",
        "author": "krellbot policy tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": venue, "pair": pair}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


@pytest.fixture
def home(tmp_path: Path) -> Path:
    os.environ["KRELLBOT_HOME"] = str(tmp_path)
    return tmp_path


def test_paper_only_release_stays_true():
    assert PAPER_ONLY_RELEASE is True


def test_default_policy_allows_paper_denies_key_export(home: Path):
    policy = user_policy.load_policy(home)
    assert policy.allow_paper_arm is True
    assert policy.allow_live is True  # release/MCP still block live
    assert policy.allow_key_export is False
    assert not user_policy.policy_path(home).exists()

    assert user_policy.check(home, user_policy.ACTION_PAPER_ARM).ok is True
    assert user_policy.check(home, user_policy.ACTION_LIVE).ok is True
    keys = user_policy.check(home, user_policy.ACTION_KEY_EXPORT)
    assert keys.ok is False
    assert keys.code == user_policy.CODE_POLICY_DENIED


def test_malformed_policy_file_fails_closed(home: Path):
    user_policy.policy_path(home).write_text("{not-json", encoding="utf-8")
    decision = user_policy.check(home, user_policy.ACTION_PAPER_ARM)
    assert decision.ok is False
    assert decision.code == user_policy.CODE_POLICY_INVALID
    assert user_policy.load_policy(home).allow_paper_arm is False
    assert user_policy.load_policy(home).allow_live is False
    assert user_policy.load_policy(home).allow_key_export is False


def test_policy_change_is_audited_in_journal(home: Path):
    before = user_policy.load_policy(home)
    result = user_policy.save_policy(
        home,
        user_policy.UserPolicy(
            schema_version=user_policy.SCHEMA_VERSION,
            allow_paper_arm=False,
            allow_live=False,
            allow_key_export=False,
        ),
        clock=lambda: 1_700_000_000,
    )
    assert result.ok is True
    assert result.code == user_policy.CODE_POLICY_UPDATED
    assert user_policy.policy_path(home).is_file()

    records = read_records_lenient(home)
    audits = [r for r in records if r.get("kind") == "user_policy"]
    assert len(audits) == 1
    detail = audits[0]["detail"]
    assert detail["event"] == "changed"
    assert detail["before"] == before.to_dict()
    assert detail["after"]["allow_paper_arm"] is False

    # Identical rewrite does not append a second audit row.
    again = user_policy.save_policy(home, result.policy, clock=lambda: 1_700_000_001)
    assert again.ok is True
    assert again.code == user_policy.CODE_OK
    assert len([r for r in read_records_lenient(home) if r.get("kind") == "user_policy"]) == 1


def test_mcp_paper_arm_honors_deny_paper_arm(home: Path):
    pack = _write_dsl_pack(home)
    user_policy.save_policy(
        home,
        {
            "schema_version": "1",
            "allow_paper_arm": False,
            "allow_live": False,
            "allow_key_export": False,
        },
    )
    mcp = McpTools(home)
    result = mcp.call(
        "paper_arm",
        pack_path=pack,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
    )
    assert result["ok"] is False
    assert result["effect"] == "refused"
    assert result["code"] == CODE_POLICY_DENIED
    assert result["action"] == user_policy.ACTION_PAPER_ARM
    assert result["message"] == user_policy.MESSAGE_DENY_PAPER_ARM
    assert not (home / "config.json").exists()


def test_mcp_policy_check_honors_live_and_key_export(home: Path):
    user_policy.save_policy(
        home,
        {
            "schema_version": "1",
            "allow_paper_arm": True,
            "allow_live": False,
            "allow_key_export": False,
        },
    )
    mcp = McpTools(home)
    live = mcp.policy_check(user_policy.ACTION_LIVE)
    assert live["ok"] is False
    assert live["code"] == CODE_POLICY_DENIED
    assert live["action"] == user_policy.ACTION_LIVE

    keys = mcp.policy_check(user_policy.ACTION_KEY_EXPORT)
    assert keys["ok"] is False
    assert keys["code"] == CODE_POLICY_DENIED
    assert keys["action"] == user_policy.ACTION_KEY_EXPORT

    snapshot = mcp.call("read")
    assert snapshot["ok"] is True
    assert snapshot["policy"]["allow_paper_arm"] is True
    assert snapshot["policy"]["allow_live"] is False
    assert snapshot["policy"]["allow_key_export"] is False


def test_paper_service_honors_deny_paper_arm(home: Path):
    pack = _write_dsl_pack(home)
    user_policy.save_policy(
        home,
        {
            "schema_version": "1",
            "allow_paper_arm": False,
            "allow_live": False,
            "allow_key_export": False,
        },
    )
    result = PaperService(home).arm(
        pack,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="policy-deny",
    )
    assert result.ok is False
    assert result.effect == "refused"
    assert result.code == CODE_USER_POLICY_DENIED
    assert result.message == user_policy.MESSAGE_DENY_PAPER_ARM
    assert result.revision_before == result.revision_after
    assert not (home / "config.json").exists()


def test_workstation_live_arm_honors_deny_live(home: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("krellbot.release_policy.PAPER_ONLY_RELEASE", False)
    user_policy.save_policy(
        home,
        {
            "schema_version": "1",
            "allow_paper_arm": True,
            "allow_live": False,
            "allow_key_export": False,
        },
    )

    port = 8765
    app = create_app(home=home, port=port, bootstrap_token="boot-policy")
    session = _bootstrap(app, port=port, token="boot-policy")

    payload = {
        "schema_version": "1",
        "command": "live.arm",
        "payload": {"venue": "kraken", "pack_path": "trend-follow.json"},
    }
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/commands",
        body=json.dumps(payload).encode(),
        headers=session,
    )
    assert status == 403, body
    refused = json.loads(body)
    assert refused["ok"] is False
    assert refused["code"] == user_policy.CODE_POLICY_DENIED
    assert refused["action"] == user_policy.ACTION_LIVE
    assert refused["message"] == user_policy.MESSAGE_DENY_LIVE


def test_workstation_key_export_honors_deny(home: Path):
    port = 8766
    app = create_app(home=home, port=port, bootstrap_token="boot-keys-policy")
    app.state.krellbot.keys_allow_fake_backend = True
    session = _bootstrap(app, port=port, token="boot-keys-policy")

    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/keys/kraken/export",
        body=b"{}",
        headers=session,
    )
    assert status == 403, body
    refused = json.loads(body)
    assert refused["ok"] is False
    assert refused["code"] == user_policy.CODE_POLICY_DENIED
    assert refused["action"] == user_policy.ACTION_KEY_EXPORT
    assert refused["message"] == user_policy.MESSAGE_DENY_KEY_EXPORT

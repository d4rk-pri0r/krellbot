"""M3-GUI — live-operations, promotion, kill switch, and alerts API surface.

Tests-first. ``src/krellbot/application/alerts.py`` and
``src/krellbot/application/operations.py`` do not exist before this
leaf lands; ``GET /api/v1/operations``, the new ``live.promote`` /
``operations.kill`` / ``operations.release_kill`` / ``alerts.ack``
commands, and the kill-aware ``live.preflight`` carve-out all live in
``src/krellbot/api/app.py``.

The contract documented in the brief (M3-GUI/brief.md):

  * ``GET /api/v1/operations`` returns ``{schema_version, live,
    deployments, alerts}`` without ever leaking ``cap``, ``stop``,
    ``starting_cash``, ``owned_qty``, ``pack_path``, ``pack_sha256``,
    or any balance.
  * ``live.promote`` ALWAYS refuses. Promotion is owner-deferred in
    this build; it never touches the live transport or the journal.
  * ``operations.kill`` / ``operations.release_kill`` never disarm or
    sell; the kill switch is the only byte-changing output of the kill
    commands. ``reason: ""`` is ``bad_input``.
  * ``alerts.ack`` is 200 with the alert body on success and 404
    ``alert_not_found`` on an unknown id.
  * ``live.preflight`` short-circuits with ``kill_switch_engaged``
    when the kill switch is engaged, before any transport ``send`` or
    ``balances`` call.
  * The other ``live.*`` commands stay 403. The session and CSRF gates
    are unchanged.

Helpers are copied from ``tests/test_ns27_live_preflight.py`` — the
same ASGI mini-client, the same bootstrap-then-command idiom. The
companion test for ``tests/test_m3_gui_alerts.py`` exercises
``alerts.collect`` and ``alerts.acknowledge`` directly with the
home as a tmp_path.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# ---- ASGI test client (mirrors test_ns27_live_preflight) ------------------


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


TEST_PORT = 8080


def _default_origin_header() -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{TEST_PORT}")]


def _build_app(home: Path, *, bootstrap_token: str = "boot-m3gui-ops"):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


def _bootstrap_token(home: Path) -> str:
    return f"boot-m3gui-ops-{home.name}-{id(home)}"


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


def _get_json(
    app,
    path: str,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=path, headers=base)


def _bootstrap(app, token: str) -> tuple[str, str]:
    s, _h, b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert s == 200, (s, b, cookies)
    decoded = json.loads(b)
    csrf = decoded["csrf_token"]
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return csrf, session_value


def _auth_headers(csrf: str, session: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]


# ---- fake live transport (same shape as test_ns27) -------------------------


class FakeTransport:
    """Spy with a configurable account id; never talks to a live venue."""

    def __init__(self, account: str, balances: dict[str, Any] | None = None) -> None:
        self.account = account
        self.send = MagicMock()
        self._balances = balances if balances is not None else {"USD": 1234.56}
        self.balances = MagicMock(return_value=dict(self._balances))

    def was_sent(self) -> bool:
        return self.send.called


def _install_transport(app, transport: FakeTransport) -> None:
    state = app.state.krellbot
    state.live_transport = transport


# ---- pack + config helpers ------------------------------------------------


def _write_pack(home: Path, *, pack_id: str = "trend-follow") -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    pack_path = packs / f"{pack_id}.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": pack_id,
                "version": "1.0.0",
                "label": "Trend follow",
                "author": "m3gui tests",
                "timeframe": "1h",
                "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
                "entry": ["close", ">", "sma20"],
                "exit": ["close", "<", "sma20"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
                "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
            }
        ),
        encoding="utf-8",
    )
    return pack_path


def _config_bytes(home: Path) -> bytes:
    p = home / "config.json"
    if not p.exists():
        return b""
    return p.read_bytes()


def _seed_paper_record(home: Path, *, mode: str = "paper", pair: str = "SUIUSD", pack_id: str = "trend-follow") -> None:
    """Append an armed record via krellbot.config (bypassing paper.service)."""
    from krellbot import config as kb_config

    config = kb_config.load_config(home)
    config.armed.append(
        kb_config.ArmedPack(
            pack_path=str(home / "packs" / f"{pack_id}.json"),
            pack_sha256="0" * 64,
            pack_id=pack_id,
            pack_version="1.0.0",
            venue="kraken",
            pair=pair,
            cap=Decimal(25),
            stop=Decimal(0),
            mode=mode,
            starting_cash=Decimal(1000) if mode == "paper" else None,
            requires_license=False,
            armed_at_ts=0,
        )
    )
    kb_config.save_config(home, config)


def _write_operator_grant(
    home: Path, *, venue: str = "kraken", pair: str = "SUIUSD", expires_at: int = 9_999_999_999
) -> None:
    """Hand-write a live-authorization record for tests."""
    path = home / "live-authorization.json"
    payload = {
        "schema_version": "1",
        "granted_by": "operator",
        "expires_at": expires_at,
        "grants": [{"venue": venue, "pair": pair}],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. GET /api/v1/operations shape — closed, never leaks sensitive keys
# ---------------------------------------------------------------------------


def test_operations_requires_session(home: Path) -> None:
    """``GET /api/v1/operations`` without a session is 403."""

    app = _build_app(home, bootstrap_token=_bootstrap_token(home))
    status, _h, _b, _c = _get_json(app, "/api/v1/operations")
    assert status == 403, status


def test_operations_disabled_when_no_live_env(home: Path, monkeypatch) -> None:
    """With ``KRELLBOT_ENABLE_LIVE`` unset and a paper deployment,
    the body reports live_enabled=False, an empty authorized list,
    promotion_available=False, and the deployment's stored mode."""

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    _write_pack(home)
    _seed_paper_record(home, mode="paper")

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)

    status, _h, body, _c = _get_json(app, "/api/v1/operations", headers=_auth_headers(csrf, session))
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1"
    assert decoded["live"]["live_enabled"] is False, decoded["live"]
    assert decoded["live"]["authorized"] == [], decoded["live"]
    assert decoded["live"]["promotion_available"] is False, decoded["live"]
    # One paper deployment; mode is "paper" verbatim, never rewritten.
    assert len(decoded["deployments"]) == 1, decoded["deployments"]
    dep = decoded["deployments"][0]
    assert dep["venue"] == "kraken", dep
    assert dep["pair"] == "SUIUSD", dep
    assert dep["mode"] == "paper", dep
    assert dep["promotion"]["available"] is False, dep["promotion"]
    assert dep["promotion"]["code"] == "live_disabled", dep["promotion"]

    raw = body.decode("utf-8")
    forbidden = ("cap", "stop", "starting_cash", "owned_qty", "pack_path", "pack_sha256")
    for needle in forbidden:
        assert needle not in raw, (needle, raw[:400])


def test_operations_preserves_live_mode_for_seeded_live_row(home: Path, monkeypatch) -> None:
    """A seeded live row keeps its stored ``mode == "live"`` and is
    not rewritten into ``paper`` by the operations surface."""

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    _write_pack(home, pack_id="live-pack")
    _seed_paper_record(home, mode="live", pack_id="live-pack")

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)
    status, _h, body, _c = _get_json(app, "/api/v1/operations", headers=_auth_headers(csrf, session))
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert len(decoded["deployments"]) == 1
    dep = decoded["deployments"][0]
    assert dep["mode"] == "live", dep
    # live_enabled is False (env unset), promotion.code must be live_disabled
    assert dep["promotion"]["code"] == "live_disabled", dep["promotion"]
    assert decoded["live"]["live_enabled"] is False


# ---------------------------------------------------------------------------
# 2. live.promote always refuses; spy transport is never called.
# ---------------------------------------------------------------------------


def _promote_payload(env_state: str | None) -> dict:
    """Build a live.promote body. Returns the wire shape, not the env."""
    return {
        "schema_version": "1",
        "command": "live.promote",
        "payload": {"venue": "kraken", "pair": "SUIUSD", "revision_id": "rev-promote"},
    }


def _post_command(app, csrf, session_value, body):
    return _post_json(app, "/api/v1/commands", body, headers=_auth_headers(csrf, session_value))


def test_promote_refuses_when_live_disabled(home: Path, monkeypatch) -> None:
    """Env unset -> live_disabled; spy transport never called; config untouched."""
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    transport = FakeTransport(account="acct-1")
    _install_transport(app, transport)
    csrf, session = _bootstrap(app, token)
    cfg_before = _config_bytes(home)

    s, _h, body, _c = _post_command(app, csrf, session, _promote_payload(None))
    assert s == 200, (s, body)
    decoded = json.loads(body)
    assert decoded["code"] == "live_disabled", decoded
    assert decoded["ok"] is False, decoded
    assert decoded["effect"] == "refused", decoded
    assert decoded["venue"] == "kraken"
    assert decoded["pair"] == "SUIUSD"
    transport.send.assert_not_called()
    assert _config_bytes(home) == cfg_before


def test_promote_refuses_when_no_grant(home: Path, monkeypatch) -> None:
    """Env "1" with no operator grant -> live_not_authorized."""
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    transport = FakeTransport(account="acct-1")
    _install_transport(app, transport)
    csrf, session = _bootstrap(app, token)
    cfg_before = _config_bytes(home)

    s, _h, body, _c = _post_command(app, csrf, session, _promote_payload("1"))
    assert s == 200, (s, body)
    decoded = json.loads(body)
    assert decoded["code"] == "live_not_authorized", decoded
    assert decoded["ok"] is False, decoded
    transport.send.assert_not_called()
    assert _config_bytes(home) == cfg_before


def test_promote_refuses_owner_deferred_with_grant(home: Path, monkeypatch) -> None:
    """Env "1" with a hand-written grant -> live_promotion_owner_deferred."""
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    _write_operator_grant(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    transport = FakeTransport(account="acct-1")
    _install_transport(app, transport)
    csrf, session = _bootstrap(app, token)
    cfg_before = _config_bytes(home)

    s, _h, body, _c = _post_command(app, csrf, session, _promote_payload("1"))
    assert s == 200, (s, body)
    decoded = json.loads(body)
    assert decoded["code"] == "live_promotion_owner_deferred", decoded
    assert decoded["ok"] is False, decoded
    transport.send.assert_not_called()
    assert _config_bytes(home) == cfg_before


def test_promote_refuses_when_kill_engaged(home: Path, monkeypatch) -> None:
    """With kill engaged, promote returns kill_switch_engaged."""
    from krellbot.application import live_gate

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    _write_operator_grant(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    transport = FakeTransport(account="acct-1")
    _install_transport(app, transport)
    # Engage the kill switch before bootstrap so the file is on disk.
    live_gate.engage_kill(home, reason="ops-test", now=1_700_000_000)
    cfg_before = _config_bytes(home)
    csrf, session = _bootstrap(app, token)

    s, _h, body, _c = _post_command(app, csrf, session, _promote_payload("1"))
    assert s == 200, (s, body)
    decoded = json.loads(body)
    assert decoded["code"] == "kill_switch_engaged", decoded
    assert decoded["ok"] is False, decoded
    transport.send.assert_not_called()
    assert _config_bytes(home) == cfg_before


def test_promote_rejects_non_str_body_field(home: Path, monkeypatch) -> None:
    """A non-str field in the promote payload is 400 invalid body."""
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)
    payload = {
        "schema_version": "1",
        "command": "live.promote",
        "payload": {"venue": "kraken", "pair": 123, "revision_id": "rev"},
    }
    s, _h, body, _c = _post_command(app, csrf, session, payload)
    assert s == 400, (s, body)
    decoded = json.loads(body)
    assert decoded.get("detail") == "invalid body", decoded


# ---------------------------------------------------------------------------
# 3. live.preflight with the kill engaged short-circuits; other modes are unaffected.
# ---------------------------------------------------------------------------


def test_live_preflight_with_kill_engaged_short_circuits(home: Path, monkeypatch) -> None:
    """When the kill switch is engaged, ``live.preflight`` returns
    kill_switch_engaged and never touches the transport."""

    from krellbot.application import live_gate

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    transport = FakeTransport(account="acct-1")
    _install_transport(app, transport)
    live_gate.engage_kill(home, reason="preflight-kill", now=1_700_000_000)
    csrf, session = _bootstrap(app, token)

    body = {
        "schema_version": "1",
        "command": "live.preflight",
        "payload": {
            "account_id": "acct-1",
            "revision_id": "rev-abc",
            "mode": "sandbox",
        },
    }
    s, _h, payload_resp, _h2 = _post_command(app, csrf, session, body)
    assert s == 200, (s, payload_resp)
    decoded = json.loads(payload_resp)
    assert decoded["code"] == "kill_switch_engaged", decoded
    assert decoded["ok"] is False, decoded
    assert decoded["effect"] == "refused", decoded
    transport.send.assert_not_called()
    transport.balances.assert_not_called()


def test_live_preflight_live_mode_does_not_call_send(home: Path, monkeypatch) -> None:
    """For mode=live with env "1" + a grant, the preflight path must
    still refuse before any transport.send (mode != sandbox)."""

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    _write_operator_grant(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    transport = FakeTransport(account="acct-1")
    _install_transport(app, transport)
    csrf, session = _bootstrap(app, token)

    body = {
        "schema_version": "1",
        "command": "live.preflight",
        "payload": {
            "account_id": "acct-1",
            "revision_id": "rev-abc",
            "mode": "live",
        },
    }
    s, _h, payload_resp, _h2 = _post_command(app, csrf, session, body)
    assert s == 200, (s, payload_resp)
    decoded = json.loads(payload_resp)
    assert decoded["code"] != "ok", decoded  # some refusal code
    transport.send.assert_not_called()


# ---------------------------------------------------------------------------
# 4. operations.kill writes the kill file; release removes it; CSRF enforced.
# ---------------------------------------------------------------------------


def test_operations_kill_writes_file_and_release_removes_it(home: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)
    cfg_before = _config_bytes(home)

    body = {
        "schema_version": "1",
        "command": "operations.kill",
        "payload": {"reason": "ops-spec-test"},
    }
    s, _h, payload, _c = _post_command(app, csrf, session, body)
    assert s == 200, (s, payload)
    decoded = json.loads(payload)
    assert decoded["code"] == "kill_switch_engaged", decoded
    assert decoded["ok"] is True, decoded
    assert decoded["effect"] == "changed", decoded
    assert decoded["kill_switch"]["engaged"] is True, decoded
    assert decoded["kill_switch"]["reason"] == "ops-spec-test", decoded

    kill_file = home / "run" / "kill-switch.json"
    assert kill_file.exists(), kill_file
    assert _config_bytes(home) == cfg_before, "config must not change on kill"

    # Now release.
    body = {"schema_version": "1", "command": "operations.release_kill", "payload": {}}
    s, _h, payload, _c = _post_command(app, csrf, session, body)
    assert s == 200, (s, payload)
    decoded = json.loads(payload)
    assert decoded["code"] == "kill_switch_released", decoded
    assert decoded["ok"] is True, decoded
    assert not kill_file.exists(), kill_file


def test_operations_kill_empty_reason_is_bad_input(home: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)

    body = {
        "schema_version": "1",
        "command": "operations.kill",
        "payload": {"reason": ""},
    }
    s, _h, payload, _c = _post_command(app, csrf, session, body)
    assert s == 200, (s, payload)
    decoded = json.loads(payload)
    assert decoded["code"] == "bad_input", decoded
    assert decoded["ok"] is False, decoded
    assert not (home / "run" / "kill-switch.json").exists()


def test_operations_kill_requires_csrf(home: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _csrf, session = _bootstrap(app, token)
    body = {
        "schema_version": "1",
        "command": "operations.kill",
        "payload": {"reason": "x"},
    }
    # Wrong CSRF.
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", "wrong-csrf"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    s, _h, _b, _c = _post_json(app, "/api/v1/commands", body, headers=headers)
    assert s == 403, (s, _b)


def test_release_kill_requires_csrf(home: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _csrf, session = _bootstrap(app, token)
    body = {"schema_version": "1", "command": "operations.release_kill", "payload": {}}
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", "wrong-csrf"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    s, _h, _b, _c = _post_json(app, "/api/v1/commands", body, headers=headers)
    assert s == 403, (s, _b)


# ---------------------------------------------------------------------------
# 5. alerts.ack: 404 for unknown id, 200 on success. Other live.* stay 403.
# ---------------------------------------------------------------------------


def test_alerts_ack_unknown_returns_404(home: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)
    body = {
        "schema_version": "1",
        "command": "alerts.ack",
        "payload": {"alert_id": "deadbeefdeadbeef"},
    }
    s, _h, payload, _c = _post_command(app, csrf, session, body)
    assert s == 404, (s, payload)
    decoded = json.loads(payload)
    assert decoded["code"] == "alert_not_found", decoded
    assert decoded["ok"] is False, decoded


def test_alerts_ack_known_returns_alert_body(home: Path, monkeypatch) -> None:
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    # Seed a kill_switch_engaged alert by engaging the kill switch.
    from krellbot.application import live_gate

    live_gate.engage_kill(home, reason="ack-test", now=1_700_000_000)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)

    # Read /api/v1/operations to grab the kill_switch alert id.
    s, _h, body, _c = _get_json(app, "/api/v1/operations", headers=_auth_headers(csrf, session))
    decoded = json.loads(body)
    alerts = decoded.get("alerts", [])
    assert any(a["kind"] == "kill_switch" for a in alerts), decoded
    alert_id = next(a["id"] for a in alerts if a["kind"] == "kill_switch")

    payload = {
        "schema_version": "1",
        "command": "alerts.ack",
        "payload": {"alert_id": alert_id},
    }
    s, _h, body, _c = _post_command(app, csrf, session, payload)
    assert s == 200, (s, body)
    decoded = json.loads(body)
    assert decoded["code"] == "acknowledged", decoded
    assert decoded["ok"] is True, decoded
    assert decoded["alert"]["acknowledged"] is True, decoded


def test_live_arm_and_live_order_are_still_403(home: Path, monkeypatch) -> None:
    """No new live command is let through; only preflight and the
    new typed commands are accepted."""
    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)

    for cmd in ("live.arm", "live.order"):
        body = {"schema_version": "1", "command": cmd, "payload": {"venue": "kraken"}}
        s, _h, payload, _c = _post_command(app, csrf, session, body)
        assert s == 403, (cmd, s, payload)
        decoded = json.loads(payload)
        assert decoded.get("detail") == "live orders are disabled", decoded

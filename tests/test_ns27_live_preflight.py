"""NS27 — live preflight: a sandbox-only dry-run that never sends an order.

Tests-first. ``krellbot.application.live_preflight`` does not exist
before this NS lands, and the API command branch does not yet route
``live.preflight`` through it; the import lines below must fail with
``ModuleNotFoundError`` in the RED phase.

The helper takes a fake transport (anything with an ``account`` field
and a ``send`` method) and refuses before any ``send`` when the
caller-provided ``account_id`` does not match the transport's account,
when ``mode`` is not ``"sandbox"``, or when ``revision_id`` is missing.
The wrong-mode refusal is a typed ``stored_mode_not_sandbox`` only when
the stored deployment mode is live; an omitted mode never overrides a
stored live deployment into sandbox. A matching sandbox account and
revision returns ``ok=True`` without calling ``send``; the fake transport
may expose balances and is never a live venue client.

The integration half posts ``live.preflight`` through the live API and
asserts the helper ran (the response body has a preflight code) and the
spy transport's ``send`` was never called. A companion test posts
``live.arm`` and asserts the 403 prefix-gate still fires — only
``live.preflight`` is let through, every other ``live.*`` command stays
disabled.

Test layout:

  * SpyTransport — fake with a configurable ``account`` and a ``send``
    spy. ``balances()`` returns a tiny fixed map.
  * Unit tests — exercise every refusal branch and the success branch
    through the helper directly.
  * Integration tests — bootstrap a session, post through
    ``/api/v1/commands`` with body key ``payload`` (the existing parser
    shape), assert the helper ran and the spy was untouched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from krellbot.application.live_preflight import (
    CODE_ACCOUNT_MISMATCH,
    CODE_MODE_NOT_SANDBOX,
    CODE_OK,
    CODE_REVISION_ID_MISSING,
    CODE_STORED_MODE_NOT_SANDBOX,
    evaluate,
)

# ---- ASGI test client (mirrors test_ns06_api) -----------------------------


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


def _build_app(home: Path, *, bootstrap_token: str = "boot-preflight"):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


def _bootstrap_token(home: Path) -> str:
    return f"boot-preflight-{home.name}-{id(home)}"


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


# ---- fake transport -------------------------------------------------------


class FakeTransport:
    """Spy with a configurable account id; never talks to a live venue."""

    def __init__(self, account: str, balances: dict[str, Any] | None = None) -> None:
        self.account = account
        self.send = MagicMock()
        self._balances = balances if balances is not None else {"USD": 1234.56}
        self.balances = MagicMock(return_value=dict(self._balances))

    def was_sent(self) -> bool:
        return self.send.called


# ---- unit tests of the helper -------------------------------------------


def test_helper_ok_does_not_send() -> None:
    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-1",
        revision_id="rev-abc",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is True, result
    assert result.code == CODE_OK, result
    assert result.effect == "unchanged"
    assert result.account_id == "acct-1"
    assert result.revision_id == "rev-abc"
    assert transport.send.assert_not_called() is None
    assert transport.balances.called, "balances should be read on success"


def test_helper_refuses_account_mismatch_before_send() -> None:
    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-2",
        revision_id="rev-abc",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is False, result
    assert result.code == CODE_ACCOUNT_MISMATCH, result
    assert result.effect == "refused"
    assert result.account_id == "acct-2"
    assert result.revision_id == "rev-abc"
    transport.send.assert_not_called()
    assert not transport.balances.called


def test_helper_refuses_missing_revision_id_before_send() -> None:
    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-1",
        revision_id=None,
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is False, result
    assert result.code == CODE_REVISION_ID_MISSING, result
    assert result.effect == "refused"
    transport.send.assert_not_called()


def test_helper_refuses_empty_revision_id_before_send() -> None:
    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-1",
        revision_id="",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is False, result
    assert result.code == CODE_REVISION_ID_MISSING, result
    transport.send.assert_not_called()


def test_helper_refuses_mode_not_sandbox_before_send() -> None:
    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-1",
        revision_id="rev-abc",
        mode="live",
        transport=transport,
    )
    assert result.ok is False, result
    assert result.code == CODE_MODE_NOT_SANDBOX, result
    assert result.effect == "refused"
    transport.send.assert_not_called()


def test_helper_refuses_wrong_mode_when_stored_is_live() -> None:
    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-1",
        revision_id="rev-abc",
        mode="live",
        transport=transport,
        stored_mode="live",
    )
    assert result.ok is False, result
    assert result.code == CODE_STORED_MODE_NOT_SANDBOX, result
    assert result.effect == "refused"
    assert result.stored_mode == "live"
    transport.send.assert_not_called()


def test_helper_refuses_omitted_mode_when_stored_is_live() -> None:
    """A stored live deployment is preserved against an omitted mode.

    The caller cannot override a stored live deployment into sandbox by
    simply omitting ``mode``; the helper refuses with the typed stored
    code before any send.
    """

    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-1",
        revision_id="rev-abc",
        mode=None,
        transport=transport,
        stored_mode="live",
    )
    assert result.ok is False, result
    assert result.code == CODE_STORED_MODE_NOT_SANDBOX, result
    assert result.effect == "refused"
    transport.send.assert_not_called()


def test_helper_accepts_sandbox_when_stored_is_paper() -> None:
    """A stored paper deployment does not block sandbox preflight."""

    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-1",
        revision_id="rev-abc",
        mode="sandbox",
        transport=transport,
        stored_mode="paper",
    )
    assert result.ok is True, result
    assert result.code == CODE_OK, result
    transport.send.assert_not_called()


def test_helper_refusal_order_revision_id_before_account() -> None:
    """A missing revision_id fails first even when the account also mismatches."""

    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-2",
        revision_id=None,
        mode="sandbox",
        transport=transport,
    )
    assert result.code == CODE_REVISION_ID_MISSING, result
    transport.send.assert_not_called()


def test_helper_refusal_order_account_before_mode() -> None:
    """An account mismatch fails before the mode check."""

    transport = FakeTransport(account="acct-1")
    result = evaluate(
        account_id="acct-2",
        revision_id="rev-abc",
        mode="live",
        transport=transport,
    )
    assert result.code == CODE_ACCOUNT_MISMATCH, result
    transport.send.assert_not_called()


# ---- integration: post through the API ----------------------------------


def _install_transport(app, transport: FakeTransport) -> None:
    """Drop a spy onto the app's ``live_transport`` slot.

    The app lazily builds its preflight transport from
    ``_AppState.live_transport``; tests pre-set it so the spy is the
    one the helper receives.
    """

    state = app.state.krellbot
    state.live_transport = transport


def test_app_live_preflight_delegates_to_helper(home: Path) -> None:
    """POST ``live.preflight`` through the app and assert the helper ran."""

    transport = FakeTransport(account="acct-1")
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _install_transport(app, transport)

    csrf, session = _bootstrap(app, token)
    payload = {
        "schema_version": "1",
        "command": "live.preflight",
        "correlation_id": "preflight-1",
        "payload": {
            "account_id": "acct-1",
            "revision_id": "rev-abc",
            "mode": "sandbox",
        },
    }
    status, _hdrs, body, _cookies = _post_json(
        app, "/api/v1/commands", payload, headers=_auth_headers(csrf, session)
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is True, decoded
    assert decoded["code"] == CODE_OK, decoded
    assert decoded["account_id"] == "acct-1"
    assert decoded["revision_id"] == "rev-abc"
    assert transport.balances.called, "the helper should call balances on success"
    transport.send.assert_not_called()


def test_app_live_preflight_refuses_account_mismatch_through_helper(home: Path) -> None:
    """An account mismatch surfaces as a typed refusal through the app."""

    transport = FakeTransport(account="acct-1")
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _install_transport(app, transport)

    csrf, session = _bootstrap(app, token)
    payload = {
        "schema_version": "1",
        "command": "live.preflight",
        "correlation_id": "preflight-mismatch",
        "payload": {
            "account_id": "acct-2",
            "revision_id": "rev-abc",
            "mode": "sandbox",
        },
    }
    status, _hdrs, body, _cookies = _post_json(
        app, "/api/v1/commands", payload, headers=_auth_headers(csrf, session)
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_ACCOUNT_MISMATCH, decoded
    transport.send.assert_not_called()


def test_app_live_preflight_refuses_wrong_mode_when_stored_is_live(home: Path) -> None:
    """Stored live + wrong mode surfaces as ``stored_mode_not_sandbox``."""

    transport = FakeTransport(account="acct-1")
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    _install_transport(app, transport)

    # Plant a live deployment in the config so the app reads it.
    from krellbot import config as kb_config

    config = kb_config.load_config(home)
    config.armed.append(
        kb_config.ArmedPack(
            pack_path="/tmp/dummy",
            pack_sha256="0" * 64,
            pack_id="dummy",
            pack_version="1.0.0",
            venue="kraken",
            pair="SUIUSD",
            cap=__import__("decimal").Decimal("25"),
            stop=__import__("decimal").Decimal("0"),
            mode="live",
            starting_cash=None,
            requires_license=False,
            armed_at_ts=0,
        )
    )
    kb_config.save_config(home, config)

    csrf, session = _bootstrap(app, token)
    payload = {
        "schema_version": "1",
        "command": "live.preflight",
        "correlation_id": "preflight-stored-live",
        "payload": {
            "account_id": "acct-1",
            "revision_id": "rev-abc",
            "mode": "live",
        },
    }
    status, _hdrs, body, _cookies = _post_json(
        app, "/api/v1/commands", payload, headers=_auth_headers(csrf, session)
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is False, decoded
    assert decoded["code"] == CODE_STORED_MODE_NOT_SANDBOX, decoded
    transport.send.assert_not_called()


def test_app_live_arm_is_403(home: Path) -> None:
    """``live.arm`` is still 403 with the standard "live orders are disabled"."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)
    payload = {
        "schema_version": "1",
        "command": "live.arm",
        "payload": {"venue": "kraken"},
    }
    status, _hdrs, body, _cookies = _post_json(
        app, "/api/v1/commands", payload, headers=_auth_headers(csrf, session)
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded.get("detail") == "live orders are disabled", decoded


def test_app_paper_arm_with_mode_live_is_403(home: Path) -> None:
    """The ``mode == "live"`` payload refusal still fires after the prefix carve-out."""

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    csrf, session = _bootstrap(app, token)
    payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "payload": {"venue": "kraken", "mode": "live"},
    }
    status, _hdrs, body, _cookies = _post_json(
        app, "/api/v1/commands", payload, headers=_auth_headers(csrf, session)
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert decoded.get("detail") == "live orders are disabled", decoded
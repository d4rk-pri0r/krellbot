"""Live-ready wizard honesty (M20.4).

Pins the first-run / Exchange path contract:

* ``trust_snapshot`` is presentation-only (no credentials).
* ``GET /api/v1/trust`` is session/origin gated and never claims live-ready.
* Paper-only release and live grant are distinct fields.
* Exchange probe stays trade-only; no license ask on the wizard surface.
* Keys never leave the machine via trust/status bodies.

Uses fake transports / fake keyrings and an isolated ``KRELLBOT_HOME``.
Does not flip ``PAPER_ONLY_RELEASE``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from fakes.fake_kraken import FakeKrakenTransport
from fakes.live_grant import write_grant

from krellbot import release_policy
from krellbot.release_policy import PAPER_ONLY_RELEASE, paper_only_message
from krellbot.trust import trust_snapshot

TEST_PORT = 18765

KRAKEN_TEST_KEY = "wizard-honesty-public-key"
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

    async def receive() -> dict[str, object]:
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
        "server": ("127.0.0.1", TEST_PORT),
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


def _build_app(home: Path, *, bootstrap_token: str = "boot-live-wizard"):
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


def _bootstrap(app, token: str = "boot-live-wizard") -> list[tuple[str, str]]:
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


def _enable_keys(app, transport: FakeKrakenTransport) -> None:
    app.state.krellbot.keys_transport = transport
    app.state.krellbot.keys_allow_fake_backend = True


def _assert_no_leak(body: bytes, *secrets: str) -> None:
    text = body.decode("utf-8", errors="replace")
    for secret in secrets:
        assert secret not in text


def _assert_no_connected(body: bytes) -> None:
    lower = body.decode("utf-8", errors="replace").lower()
    assert "connected" not in lower


# ---- trust_snapshot ------------------------------------------------------


def test_paper_only_release_stays_true() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_trust_snapshot_shape_and_rails(tmp_path: Path) -> None:
    os.chmod(tmp_path, 0o700)
    snap = trust_snapshot(tmp_path)
    required = {
        "home",
        "home_mode",
        "home_mode_ok",
        "keychain_backend",
        "keychain_ok",
        "posture_ok",
        "posture_warning",
        "bind",
        "live_arm_ui_allowed",
        "trade_only_required",
    }
    assert required <= set(snap.keys())
    assert snap["home"] == str(tmp_path)
    assert snap["bind"] == "127.0.0.1"
    assert snap["live_arm_ui_allowed"] is False
    assert snap["trade_only_required"] is True
    blob = json.dumps(snap)
    assert KRAKEN_TEST_KEY not in blob
    assert KRAKEN_TEST_SECRET_B64 not in blob
    assert "license" not in blob.lower()


def test_trust_snapshot_fail_closed_on_permissive_home(tmp_path: Path) -> None:
    """POSIX 0o755 homes fail closed; Windows cannot read DACLs so mode is None.

    Either way the aggregate posture must not be green: Windows surfaces a
    DACL review warning, POSIX names the over-permissive mode and 0o700.
    """
    os.chmod(tmp_path, 0o755)
    snap = trust_snapshot(tmp_path)
    assert snap["home_mode_ok"] is False
    assert snap["posture_ok"] is False
    assert isinstance(snap["posture_warning"], str)
    warning = str(snap["posture_warning"])
    if sys.platform == "win32":
        # chmod is not meaningful on Windows; trust_snapshot returns None
        # and fail-closes with an explicit DACL review message.
        assert snap["home_mode"] is None
        assert "windows" in warning.lower() or "dacl" in warning.lower()
    else:
        assert snap["home_mode"] == "0o755"
        assert "0o755" in warning
        assert "0o700" in warning


# ---- GET /api/v1/trust ---------------------------------------------------


def test_trust_api_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, body, _c = _get(
        app,
        "/api/v1/trust",
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, body
    assert b"session required" in body


def test_trust_api_rejects_non_loopback_origin(home: Path) -> None:
    app = _build_app(home)
    session = _bootstrap(app)
    cookie = next(v for k, v in session if k == "Cookie")
    status, _h, body, _c = _get(
        app,
        "/api/v1/trust",
        headers=[("Origin", "http://example.com"), ("Cookie", cookie)],
    )
    assert status == 403, body
    assert b"origin not loopback" in body


def test_trust_api_distinguishes_paper_only_from_grant(home: Path) -> None:
    assert release_policy.PAPER_ONLY_RELEASE is True
    write_grant(home, venue="kraken", pair="XXBTZUSD")
    os.chmod(home, 0o700)
    app = _build_app(home)
    session = _bootstrap(app)
    status, _h, body, _c = _get(app, "/api/v1/trust", headers=session)
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["paper_only_release"] is True
    assert decoded["release_policy"] == "paper_only"
    assert decoded["release_policy_code"] == release_policy.CODE_PAPER_ONLY_RELEASE
    assert decoded["release_policy_message"] == paper_only_message()
    assert decoded["live_grant_active"] is True
    assert decoded["live_grant"]["active"] is True
    assert decoded["live_grant"]["grants"][0]["venue"] == "kraken"
    assert decoded["live_ready"] is False
    assert decoded["live_arm_ui_allowed"] is False
    assert decoded["trade_only_required"] is True
    assert decoded["license_required_for_exchange"] is False
    assert decoded["keys_leave_machine"] is False
    trust = decoded["trust"]
    assert trust["bind"] == "127.0.0.1"
    assert trust["live_arm_ui_allowed"] is False
    assert trust["trade_only_required"] is True
    _assert_no_leak(body, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)


def test_trust_api_without_grant_still_paper_only(home: Path) -> None:
    os.chmod(home, 0o700)
    app = _build_app(home)
    session = _bootstrap(app)
    status, _h, body, _c = _get(app, "/api/v1/trust", headers=session)
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["paper_only_release"] is True
    assert decoded["live_grant_active"] is False
    assert decoded["live_ready"] is False


# ---- Exchange path honesty -----------------------------------------------


def test_exchange_trade_only_store_and_withdraw_refuse(
    home: Path,
    fresh_keyring,
) -> None:
    del fresh_keyring
    app = _build_app(home)
    session = _bootstrap(app)

    _enable_keys(app, _trade_only_transport())
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/keys/kraken",
        {"key": KRAKEN_TEST_KEY, "secret": KRAKEN_TEST_SECRET_B64},
        headers=session,
    )
    assert status == 200, body
    stored = json.loads(body)
    assert stored["ok"] is True
    assert stored["status"] == "stored"
    _assert_no_connected(body)
    _assert_no_leak(body, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)

    _enable_keys(app, _withdraw_transport())
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/keys/kraken",
        {"key": "other-key", "secret": KRAKEN_TEST_SECRET_B64},
        headers=session,
    )
    assert status == 200, body
    refused = json.loads(body)
    assert refused["ok"] is False
    assert refused["status"] == "refused_withdraw"
    _assert_no_connected(body)
    _assert_no_leak(body, "other-key", KRAKEN_TEST_SECRET_B64)


def test_wizard_frontend_has_no_license_ask_on_live_path() -> None:
    """SPA wizard source must not collect a license on Welcome/Security/Exchange."""
    root = Path(__file__).resolve().parents[1] / "frontend" / "src" / "features" / "onboarding"
    panel = (root / "LiveWizardPanel.tsx").read_text(encoding="utf-8")
    assert "No license token is collected" in panel
    assert "license_required_for_exchange" in (root / "client.ts").read_text(encoding="utf-8")
    assert "licenseToken" not in panel
    assert 'name="license"' not in panel.lower()
    assert "activation/redeem" not in panel

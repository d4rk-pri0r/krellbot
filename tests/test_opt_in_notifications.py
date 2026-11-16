"""Opt-in desktop/email alert notifications (M9.4).

Pins:

* Notifications are off by default; enabling is an explicit settings write.
* Desktop works without external credentials; email needs SMTP host + to.
* SMTP passwords are never stored in ``notifications.json`` (env only).
* ``FakeNotifier`` records deliveries; no real desktop/SMTP is used.
* Unacknowledged alerts notify once per ``(id, last_ts)``; ack stays in-app.
* Telemetry remains a separate opt-in and is untouched by this module.
* Settings GET/PUT are session-gated like the rest of the loopback API.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from krellbot import notifications as kb_notifications
from krellbot import telemetry as kb_telemetry
from krellbot.application import alerts as alerts_app
from krellbot.application import live_gate

TEST_PORT = 8080


# ---- ASGI helpers (same idiom as test_scheduler_api) ------------------------


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


def _origin() -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{TEST_PORT}")]


def _build_app(home: Path, *, bootstrap_token: str = "boot-notifications"):
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


def _put_json(app, path: str, payload: dict, headers: list[tuple[str, str]] | None = None):
    body = json.dumps(payload).encode("utf-8")
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="PUT", path=path, body=body, headers=base)


def _get(app, path: str, headers: list[tuple[str, str]] | None = None):
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=path, headers=base)


def _bootstrap(app, token: str = "boot-notifications") -> list[tuple[str, str]]:
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_origin(),
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


def _alert(
    *,
    alert_id: str = "a1",
    kind: str = "kill_switch",
    severity: str = "critical",
    last_ts: int = 100,
    acknowledged: bool = False,
) -> dict:
    return {
        "id": alert_id,
        "kind": kind,
        "severity": severity,
        "code": None,
        "venue": None,
        "pair": None,
        "count": 1,
        "first_ts": last_ts,
        "last_ts": last_ts,
        "acknowledged": acknowledged,
    }


# ---- Module: defaults and settings -----------------------------------------


def test_notifications_off_by_default(home: Path) -> None:
    settings = kb_notifications.get_settings(home)
    assert settings["desktop_enabled"] is False
    assert settings["email_enabled"] is False
    assert settings["email_configured"] is False
    assert settings["telemetry_separate"] is True
    assert settings["smtp_password_env"] == kb_notifications.SMTP_PASSWORD_ENV
    assert not (home / kb_notifications.CONFIG_FILE).exists()


def test_enable_desktop_without_external_credentials(home: Path) -> None:
    fake = kb_notifications.FakeNotifier()
    updated = kb_notifications.update_settings(home, {"desktop_enabled": True})
    assert updated["desktop_enabled"] is True
    assert updated["email_enabled"] is False

    n = kb_notifications.maybe_notify(home, [_alert()], notifier=fake)
    assert n == 1
    assert fake.sent == [
        {
            "channel": "desktop",
            "title": "Krellbot critical: kill_switch",
            "body": "count=1 ack=in-app",
            "alert_id": "a1",
        }
    ]


def test_email_requires_host_and_to_and_never_stores_password(home: Path) -> None:
    fake = kb_notifications.FakeNotifier()
    kb_notifications.update_settings(
        home,
        {
            "email_enabled": True,
            "email": {"to": "ops@example.com", "smtp_host": "smtp.example.com", "smtp_port": 587},
        },
    )
    settings = kb_notifications.get_settings(home)
    assert settings["email_configured"] is True
    on_disk = json.loads((home / kb_notifications.CONFIG_FILE).read_text(encoding="utf-8"))
    assert "password" not in json.dumps(on_disk)

    try:
        kb_notifications.update_settings(
            home,
            {"email": {"password": "secret"}},
        )
        raise AssertionError("expected ValueError for password in settings")
    except ValueError as exc:
        assert "KRELLBOT_SMTP_PASSWORD" in str(exc)

    n = kb_notifications.maybe_notify(home, [_alert()], notifier=fake)
    assert n == 1
    assert fake.sent[0]["channel"] == "email"


def test_email_enabled_without_config_does_not_notify(home: Path) -> None:
    fake = kb_notifications.FakeNotifier()
    kb_notifications.update_settings(home, {"email_enabled": True})
    n = kb_notifications.maybe_notify(home, [_alert()], notifier=fake)
    assert n == 0
    assert fake.sent == []


def test_acknowledged_alerts_are_not_notified(home: Path) -> None:
    fake = kb_notifications.FakeNotifier()
    kb_notifications.update_settings(home, {"desktop_enabled": True})
    n = kb_notifications.maybe_notify(
        home,
        [_alert(acknowledged=True)],
        notifier=fake,
    )
    assert n == 0
    assert fake.sent == []


def test_dedupe_by_alert_id_and_last_ts(home: Path) -> None:
    fake = kb_notifications.FakeNotifier()
    kb_notifications.update_settings(home, {"desktop_enabled": True})
    first = _alert(last_ts=100)
    assert kb_notifications.maybe_notify(home, [first], notifier=fake) == 1
    assert kb_notifications.maybe_notify(home, [first], notifier=fake) == 0
    assert len(fake.sent) == 1

    later = _alert(last_ts=200)
    assert kb_notifications.maybe_notify(home, [later], notifier=fake) == 1
    assert len(fake.sent) == 2


def test_both_channels_deliver_when_enabled(home: Path) -> None:
    fake = kb_notifications.FakeNotifier()
    kb_notifications.update_settings(
        home,
        {
            "desktop_enabled": True,
            "email_enabled": True,
            "email": {"to": "ops@example.com", "smtp_host": "smtp.example.com"},
        },
    )
    n = kb_notifications.maybe_notify(home, [_alert()], notifier=fake)
    assert n == 2
    channels = [row["channel"] for row in fake.sent]
    assert channels == ["desktop", "email"]


def test_telemetry_remains_separate_and_untouched(home: Path) -> None:
    assert kb_telemetry.is_enabled(home) is False
    kb_notifications.update_settings(home, {"desktop_enabled": True})
    assert kb_telemetry.is_enabled(home) is False
    assert not (home / "telemetry.json").exists()
    settings = kb_notifications.get_settings(home)
    assert settings["telemetry_separate"] is True


def test_kill_switch_alert_notifies_through_collect(home: Path) -> None:
    """End-to-end with real alert collect + FakeNotifier (no desktop/SMTP)."""
    fake = kb_notifications.FakeNotifier()
    live_gate.engage_kill(home, reason="test", now=1_700_000_000)
    collected = alerts_app.collect(home, now=1_700_000_100)
    assert any(a.kind == "kill_switch" and not a.acknowledged for a in collected)

    kb_notifications.update_settings(home, {"desktop_enabled": True})
    n = kb_notifications.maybe_notify(home, collected, notifier=fake)
    assert n >= 1
    assert any(row["channel"] == "desktop" for row in fake.sent)
    assert any("kill_switch" in row["title"] for row in fake.sent)


# ---- API -------------------------------------------------------------------


def test_notifications_api_get_default_and_put_desktop(home: Path) -> None:
    app = _build_app(home)
    auth = _bootstrap(app)

    status, _h, body, _c = _get(app, "/api/v1/notifications", headers=auth)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["desktop_enabled"] is False
    assert payload["email_enabled"] is False
    assert payload["telemetry_separate"] is True

    status, _h, body, _c = _put_json(
        app,
        "/api/v1/notifications",
        {"desktop_enabled": True},
        headers=auth,
    )
    assert status == 200, body
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["desktop_enabled"] is True
    assert payload["code"] == "notifications_updated"


def test_notifications_api_rejects_password_in_body(home: Path) -> None:
    app = _build_app(home)
    auth = _bootstrap(app)
    status, _h, body, _c = _put_json(
        app,
        "/api/v1/notifications",
        {"email": {"password": "nope", "to": "a@b.c", "smtp_host": "smtp.example.com"}},
        headers=auth,
    )
    assert status == 400, body
    payload = json.loads(body)
    assert payload["code"] == "bad_input"
    on_disk = home / kb_notifications.CONFIG_FILE
    if on_disk.exists():
        assert "nope" not in on_disk.read_text(encoding="utf-8")


def test_operations_get_notifies_via_fake_notifier(home: Path) -> None:
    app = _build_app(home)
    fake = kb_notifications.FakeNotifier()
    app.state.krellbot.alert_notifier = fake
    auth = _bootstrap(app)

    kb_notifications.update_settings(home, {"desktop_enabled": True})
    live_gate.engage_kill(home, reason="ops-notify", now=1_700_000_000)

    status, _h, body, _c = _get(app, "/api/v1/operations", headers=auth)
    assert status == 200, body
    ops = json.loads(body)
    assert any(a["kind"] == "kill_switch" for a in ops["alerts"])
    assert any(row["channel"] == "desktop" for row in fake.sent)

    # Second read with same last_ts does not re-notify.
    before = len(fake.sent)
    status, _h, body, _c = _get(app, "/api/v1/operations", headers=auth)
    assert status == 200, body
    assert len(fake.sent) == before


def test_notifications_put_requires_csrf(home: Path) -> None:
    app = _build_app(home)
    auth = _bootstrap(app)
    # Drop CSRF header — state change must fail.
    no_csrf = [h for h in auth if h[0] != "X-Krellbot-CSRF"]
    status, _h, body, _c = _put_json(
        app,
        "/api/v1/notifications",
        {"desktop_enabled": True},
        headers=no_csrf,
    )
    assert status in (403, 401), body

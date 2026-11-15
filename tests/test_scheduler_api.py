"""Scheduler API: install + enable + status behind a fake supervisor (M2.7).

Authenticated loopback routes:

* ``GET  /api/v1/scheduler`` — ``installed`` / ``enabled`` / ``last_error``
* ``POST /api/v1/scheduler/install`` — write unit files via service renderers
* ``POST /api/v1/scheduler/enable`` — platform enable via ``FakeSupervisor``

CSRF/session/origin/host gates match the rest of the state-changing API.
No ``systemctl`` / ``launchctl`` / ``schtasks`` process is spawned.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from krellbot.service.supervise import FakeSupervisor

TEST_PORT = 8080


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


def _build_app(home: Path, *, bootstrap_token: str = "boot-scheduler"):
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


def _bootstrap(app, token: str = "boot-scheduler") -> list[tuple[str, str]]:
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


def _wire_fake(app, home: Path, supervisor: FakeSupervisor | None = None) -> FakeSupervisor:
    """Inject write_root + fake supervisor so tests never touch the real OS home."""
    fake = supervisor if supervisor is not None else FakeSupervisor()
    state = app.state.krellbot
    state.scheduler_supervisor = fake
    state.scheduler_write_root = home
    state.scheduler_executable = "/usr/local/bin/krellbot"
    return fake


def _assert_status_shape(payload: dict) -> None:
    assert set(payload.keys()) == {"schema_version", "installed", "enabled", "last_error"}
    assert payload["schema_version"] == "1"
    assert isinstance(payload["installed"], bool)
    assert isinstance(payload["enabled"], bool)
    assert payload["last_error"] is None or isinstance(payload["last_error"], str)


def _unit_paths(write_root: Path) -> list[Path]:
    if sys.platform == "darwin":
        return [write_root / "Library" / "LaunchAgents" / "dev.krellbot.tick.plist"]
    if sys.platform.startswith("linux"):
        d = write_root / ".config" / "systemd" / "user"
        return [d / "krellbot-tick.timer", d / "krellbot-tick.service"]
    if sys.platform == "win32":
        return [write_root / "Tasks" / "krellbot-tick.xml"]
    raise RuntimeError(f"unsupported test platform: {sys.platform}")


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def test_scheduler_status_uninstalled(home: Path) -> None:
    app = _build_app(home)
    _wire_fake(app, home)
    session = _bootstrap(app)

    status, _headers, body, _cookies = _get(app, "/api/v1/scheduler", headers=session)
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    _assert_status_shape(payload)
    assert payload["installed"] is False
    assert payload["enabled"] is False
    assert payload["last_error"] is None


def test_scheduler_status_requires_session(home: Path) -> None:
    app = _build_app(home)
    _wire_fake(app, home)
    status, _headers, body, _cookies = _get(
        app,
        "/api/v1/scheduler",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}"), *_origin()],
    )
    assert status == 403
    assert json.loads(body.decode("utf-8"))["detail"] == "session required"


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------


def test_scheduler_install_writes_units_and_reports_installed(home: Path) -> None:
    app = _build_app(home)
    fake = _wire_fake(app, home)
    session = _bootstrap(app)

    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/scheduler/install",
        {},
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    _assert_status_shape(payload)
    assert payload["installed"] is True
    assert payload["enabled"] is False
    assert payload["last_error"] is None

    for path in _unit_paths(home):
        assert path.is_file(), f"missing unit: {path}"
    assert (home / "service" / "owners" / "default.owner").is_file()
    assert fake.enable_calls == []


def test_scheduler_install_idempotent_when_already_installed(home: Path) -> None:
    app = _build_app(home)
    _wire_fake(app, home)
    session = _bootstrap(app)

    first = _post_json(app, "/api/v1/scheduler/install", {}, headers=session)
    assert first[0] == 200
    before = {p: p.read_bytes() for p in _unit_paths(home)}

    second_status, _h, body, _c = _post_json(
        app,
        "/api/v1/scheduler/install",
        {},
        headers=session,
    )
    assert second_status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["installed"] is True
    assert payload["last_error"] is None
    for path, raw in before.items():
        assert path.read_bytes() == raw


def test_scheduler_install_requires_csrf(home: Path) -> None:
    app = _build_app(home)
    _wire_fake(app, home)
    session = _bootstrap(app)
    # Drop CSRF header; keep cookie + origin.
    no_csrf = [h for h in session if h[0] != "X-Krellbot-CSRF"]

    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/scheduler/install",
        {},
        headers=no_csrf,
    )
    assert status == 403
    assert json.loads(body.decode("utf-8"))["detail"] == "csrf required"


# ---------------------------------------------------------------------------
# Enable
# ---------------------------------------------------------------------------


def test_scheduler_enable_via_fake_supervisor(home: Path) -> None:
    app = _build_app(home)
    fake = _wire_fake(app, home)
    session = _bootstrap(app)

    install_status, _h, _b, _c = _post_json(
        app,
        "/api/v1/scheduler/install",
        {},
        headers=session,
    )
    assert install_status == 200

    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/scheduler/enable",
        {},
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    _assert_status_shape(payload)
    assert payload["installed"] is True
    assert payload["enabled"] is True
    assert payload["last_error"] is None
    assert fake.enable_calls == [home]


def test_scheduler_enable_without_install_sets_last_error(home: Path) -> None:
    app = _build_app(home)
    fake = _wire_fake(app, home)
    session = _bootstrap(app)

    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/scheduler/enable",
        {},
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    _assert_status_shape(payload)
    assert payload["installed"] is False
    assert payload["enabled"] is False
    assert payload["last_error"] == "not_installed"
    assert fake.enable_calls == []


def test_scheduler_enable_failure_records_last_error(home: Path) -> None:
    app = _build_app(home)
    _wire_fake(app, home, FakeSupervisor(fail_message="boom from fake"))
    session = _bootstrap(app)

    assert _post_json(app, "/api/v1/scheduler/install", {}, headers=session)[0] == 200

    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/scheduler/enable",
        {},
        headers=session,
    )
    assert status == 200, body
    payload = json.loads(body.decode("utf-8"))
    assert payload["installed"] is True
    assert payload["enabled"] is False
    assert payload["last_error"] == "boom from fake"

    # Status GET preserves the durable last_error.
    get_status, _h, get_body, _c = _get(app, "/api/v1/scheduler", headers=session)
    assert get_status == 200
    get_payload = json.loads(get_body.decode("utf-8"))
    assert get_payload["last_error"] == "boom from fake"


def test_scheduler_enable_requires_csrf(home: Path) -> None:
    app = _build_app(home)
    _wire_fake(app, home)
    session = _bootstrap(app)
    no_csrf = [h for h in session if h[0] != "X-Krellbot-CSRF"]

    status, _headers, body, _cookies = _post_json(
        app,
        "/api/v1/scheduler/enable",
        {},
        headers=no_csrf,
    )
    assert status == 403
    assert json.loads(body.decode("utf-8"))["detail"] == "csrf required"


def test_scheduler_happy_path_install_enable_status(home: Path) -> None:
    """End-to-end: install → enable → status with a fake supervisor."""
    app = _build_app(home)
    fake = _wire_fake(app, home)
    session = _bootstrap(app)

    install_status, _h1, install_body, _c1 = _post_json(
        app,
        "/api/v1/scheduler/install",
        {},
        headers=session,
    )
    assert install_status == 200
    install_payload = json.loads(install_body.decode("utf-8"))
    assert install_payload["installed"] is True
    assert install_payload["enabled"] is False

    enable_status, _h2, enable_body, _c2 = _post_json(
        app,
        "/api/v1/scheduler/enable",
        {},
        headers=session,
    )
    assert enable_status == 200
    enable_payload = json.loads(enable_body.decode("utf-8"))
    assert enable_payload["installed"] is True
    assert enable_payload["enabled"] is True
    assert enable_payload["last_error"] is None

    status_code, _h3, status_body, _c3 = _get(app, "/api/v1/scheduler", headers=session)
    assert status_code == 200
    status_payload = json.loads(status_body.decode("utf-8"))
    _assert_status_shape(status_payload)
    assert status_payload == {
        "schema_version": "1",
        "installed": True,
        "enabled": True,
        "last_error": None,
    }
    assert fake.enable_calls == [home]

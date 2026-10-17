"""M3-GUI round 2 — CSRF recovery after a page reload (finding G1).

Tests-first. The contract (review-findings-2.md, finding G1):

  1. After a successful bootstrap redemption, ``GET /`` does NOT
     contain the ``krellbot-bootstrap`` meta tag. Before redemption
     it does. The one-time token must stop being served once it is
     redeemed, so a reload never re-runs a doomed redemption.
  2. ``GET /api/v1/session/csrf`` with the session cookie returns
     200 and the same CSRF the bootstrap returned, with
     ``Cache-Control: no-store``. That CSRF is then accepted by
     ``POST /api/v1/commands`` (``operations.kill`` with a reason
     gives ``ok: true``). The endpoint never mints a session and
     never returns the bootstrap token.
  3. ``GET /api/v1/session/csrf`` without a cookie, and with an
     invented cookie, returns 403 with no ``csrf_token`` key.
  4. A non-loopback ``Origin`` on ``GET /api/v1/session/csrf``
     returns 403.

Helpers mirror ``tests/test_m3_gui_operations_api.py`` (the same ASGI
mini-client and bootstrap idiom), plus the minimal dist tree from
``tests/test_ns10_session.py`` so ``GET /`` has a real index to serve.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

# ---- ASGI test client (mirrors test_m3_gui_operations_api) ------------------


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

SHELL_HTML = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "  <head>\n"
    '    <meta charset="UTF-8" />\n'
    "    <title>Krellbot workstation</title>\n"
    "  </head>\n"
    "  <body>\n"
    '    <div id="root"></div>\n'
    "  </body>\n"
    "</html>\n"
)


def _write_minimal_dist(dist: Path) -> Path:
    dist.mkdir(parents=True, exist_ok=True)
    index_path = dist / "index.html"
    index_path.write_text(SHELL_HTML, encoding="utf-8")
    return index_path


def _loopback_host_header() -> list[tuple[str, str]]:
    return [("Host", f"127.0.0.1:{TEST_PORT}")]


def _default_origin_header() -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{TEST_PORT}")]


def _build_app(home: Path, *, dist_dir: Path, bootstrap_token: str):
    from krellbot.api.app import create_app

    return create_app(
        home=home,
        port=TEST_PORT,
        bootstrap_token=bootstrap_token,
        dist_dir=dist_dir,
    )


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


def _get(
    app,
    path: str,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    base = _loopback_host_header()
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


# ---------------------------------------------------------------------------
# 1. GET / stops serving the bootstrap meta after redemption
# ---------------------------------------------------------------------------


def test_root_meta_tag_gone_after_redemption(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Before redemption ``GET /`` carries the one-time meta tag; after a
    successful bootstrap redemption it does not. A reload must never be
    handed an already-redeemed token."""

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    dist = tmp_path / "dist_recovery"
    _write_minimal_dist(dist)
    token = f"boot-recovery-{home.name}"
    app = _build_app(home, dist_dir=dist, bootstrap_token=token)

    status, _h, body, _c = _get(app, "/")
    assert status == 200, (status, body)
    decoded = body.decode("utf-8")
    assert 'name="krellbot-bootstrap"' in decoded, decoded
    assert f'content="{token}"' in decoded, decoded

    csrf, _session = _bootstrap(app, token)
    assert csrf, "bootstrap must succeed for the post-redemption check"

    status, _h2, body2, _c2 = _get(app, "/")
    assert status == 200, (status, body2)
    decoded2 = body2.decode("utf-8")
    assert "krellbot-bootstrap" not in decoded2, decoded2
    assert token not in decoded2, decoded2


# ---------------------------------------------------------------------------
# 2. GET /api/v1/session/csrf recovers the CSRF for a live session
# ---------------------------------------------------------------------------


def test_csrf_endpoint_returns_session_csrf_and_it_works(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the session cookie, ``GET /api/v1/session/csrf`` returns the
    same CSRF the bootstrap returned (200, ``Cache-Control: no-store``),
    and that CSRF is accepted by a state-changing command
    (``operations.kill`` → ``ok: true``). The response never carries the
    bootstrap token."""

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    dist = tmp_path / "dist_csrf_ok"
    _write_minimal_dist(dist)
    token = f"boot-csrf-ok-{home.name}"
    app = _build_app(home, dist_dir=dist, bootstrap_token=token)

    bootstrap_csrf, session = _bootstrap(app, token)

    status, headers, body, _c = _get(
        app,
        "/api/v1/session/csrf",
        headers=[("Cookie", f"krellbot_session={session}")],
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1", decoded
    assert decoded["csrf_token"] == bootstrap_csrf, decoded
    # The endpoint never returns the bootstrap token.
    assert token not in body.decode("utf-8"), body[:256]
    flat = {name.lower(): value for name, value in headers}
    assert "no-store" in flat.get("cache-control", "").lower(), flat

    # The recovered CSRF must be accepted by a state change.
    kill = {
        "schema_version": "1",
        "command": "operations.kill",
        "payload": {"reason": "recovered-csrf"},
    }
    s, _h3, payload, _c3 = _post_json(
        app,
        "/api/v1/commands",
        kill,
        headers=[
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", decoded["csrf_token"]),
            ("Cookie", f"krellbot_session={session}"),
        ],
    )
    assert s == 200, (s, payload)
    result = json.loads(payload)
    assert result["ok"] is True, result
    assert result["code"] == "kill_switch_engaged", result

    # Clean up so the kill file does not leak into other assertions.
    release = {"schema_version": "1", "command": "operations.release_kill", "payload": {}}
    s, _h4, payload4, _c4 = _post_json(
        app,
        "/api/v1/commands",
        release,
        headers=[
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", decoded["csrf_token"]),
            ("Cookie", f"krellbot_session={session}"),
        ],
    )
    assert s == 200, (s, payload4)


# ---------------------------------------------------------------------------
# 3. GET /api/v1/session/csrf without / with an invented cookie is 403
# ---------------------------------------------------------------------------


def test_csrf_endpoint_requires_a_known_session(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No cookie, or an invented (unknown) session cookie, is 403 with no
    ``csrf_token`` key in the body."""

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    dist = tmp_path / "dist_csrf_deny"
    _write_minimal_dist(dist)
    token = f"boot-csrf-deny-{home.name}"
    app = _build_app(home, dist_dir=dist, bootstrap_token=token)

    status, _h, body, _c = _get(app, "/api/v1/session/csrf")
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert "csrf_token" not in decoded, decoded

    status, _h2, body2, _c2 = _get(
        app,
        "/api/v1/session/csrf",
        headers=[("Cookie", "krellbot_session=invented-session-id")],
    )
    assert status == 403, (status, body2)
    decoded2 = json.loads(body2)
    assert "csrf_token" not in decoded2, decoded2


# ---------------------------------------------------------------------------
# 4. Non-loopback Origin on the csrf endpoint is 403
# ---------------------------------------------------------------------------


def test_csrf_endpoint_rejects_non_loopback_origin(home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A present non-loopback ``Origin`` is refused even with a valid
    session cookie, exactly as ``_gate_get`` does today."""

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    dist = tmp_path / "dist_csrf_origin"
    _write_minimal_dist(dist)
    token = f"boot-csrf-origin-{home.name}"
    app = _build_app(home, dist_dir=dist, bootstrap_token=token)

    _csrf, session = _bootstrap(app, token)

    status, _h, body, _c = _get(
        app,
        "/api/v1/session/csrf",
        headers=[
            ("Origin", "http://evil.example:8080"),
            ("Cookie", f"krellbot_session={session}"),
        ],
    )
    assert status == 403, (status, body)
    decoded = json.loads(body)
    assert "csrf_token" not in decoded, decoded

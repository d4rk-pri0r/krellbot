"""Home export API — ``POST /api/v1/home/export`` (M16.5).

Authenticated loopback export builds a home backup archive via
``storage.home_backup.create`` and returns it as a local download.
Billing/store failure must not block export. CSRF/session/origin/host
gates match other state-changing routes.
"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

from tests.test_ns06_api import (
    TEST_PORT as NS06_PORT,
)
from tests.test_ns06_api import (
    _bootstrap_and_get_csrf,
    _build_app,
    asgi_call,
)

TEST_PORT = NS06_PORT


def _bootstrap(app, token: str) -> tuple[str, str]:
    csrf_token = _bootstrap_and_get_csrf(app, token)
    assert csrf_token, csrf_token
    state = app.state.krellbot
    session_value = next(iter(state.sessions.keys()))
    return session_value, csrf_token


def _headers(session_value: str, csrf_token: str | None = None) -> list[tuple[str, str]]:
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    if csrf_token is not None:
        headers.append(("X-Krellbot-CSRF", csrf_token))
    return headers


def _post_export(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    body = b"{}"
    base = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Content-Type", "application/json"),
        ("Content-Length", str(len(body))),
    ]
    if headers:
        base.extend(headers)
    status, resp_headers, body_out, _cookies = asgi_call(
        app,
        method="POST",
        path="/api/v1/home/export",
        headers=base,
        body=body,
    )
    return status, resp_headers, body_out


def _header(headers: list[tuple[str, str]], name: str) -> str | None:
    for key, value in headers:
        if key.lower() == name.lower():
            return value
    return None


def _seed_home(home: Path) -> None:
    (home / "packs").mkdir(parents=True, exist_ok=True)
    (home / "packs" / "note.txt").write_text("export-me\n", encoding="utf-8")
    (home / "run").mkdir(parents=True, exist_ok=True)
    (home / "run" / "marker.json").write_text('{"ok":true}\n', encoding="utf-8")


# ---- gates ---------------------------------------------------------------


def test_home_export_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, body = _post_export(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, (status, body)


def test_home_export_requires_csrf(home: Path) -> None:
    token = f"boot-export-csrf-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, _csrf = _bootstrap(app, token)
    status, _h, body = _post_export(app, headers=_headers(session_value))
    assert status == 403, (status, body)


def test_home_export_refuses_non_loopback_origin(home: Path) -> None:
    token = f"boot-export-origin-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)
    headers = [
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session_value}"),
        ("X-Krellbot-CSRF", csrf),
    ]
    status, _h, body = _post_export(app, headers=headers)
    assert status == 403, (status, body)


# ---- happy path + store independence ------------------------------------


def test_home_export_returns_gzip_archive_download(home: Path) -> None:
    _seed_home(home)
    token = f"boot-export-ok-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)
    # Freeze the app clock so the Content-Disposition filename is stable.
    app.state.krellbot.clock = lambda: 1_700_000_123

    status, headers, body = _post_export(app, headers=_headers(session_value, csrf))
    assert status == 200, (status, body[:200])
    assert _header(headers, "content-type") == "application/gzip"
    assert _header(headers, "cache-control") == "no-store"
    disposition = _header(headers, "content-disposition") or ""
    assert 'filename="krellbot-home-1700000123.tar.gz"' in disposition, disposition
    assert _header(headers, "x-krellbot-home-export") == "1"

    with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as tf:
        names = set(tf.getnames())
    assert "manifest.json" in names, names
    assert "files/packs/note.txt" in names or any(n.endswith("packs/note.txt") for n in names), names


def test_home_export_ignores_billing_store_failure(home: Path, monkeypatch) -> None:
    """Export must not consult store/billing — a broken store helper is unused."""

    _seed_home(home)
    token = f"boot-export-store-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf = _bootstrap(app, token)
    app.state.krellbot.clock = lambda: 1_700_000_200

    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("store")
        raise RuntimeError("store unavailable")

    # Poison purchase/activation + pack-library store seams. Export must
    # not call them (billing/store failure must not block export).
    import krellbot.application.activation as kb_activation
    import krellbot.application.packs as kb_packs

    monkeypatch.setattr(kb_activation, "claim_device_token", _boom)
    monkeypatch.setattr(kb_packs, "list_packs", _boom)

    status, headers, body = _post_export(app, headers=_headers(session_value, csrf))
    assert status == 200, (status, body[:200])
    assert _header(headers, "content-type") == "application/gzip"
    assert len(body) > 20
    assert calls == [], calls


def test_home_export_path_appears_in_openapi(home: Path) -> None:
    app = _build_app(home)
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path="/openapi.json",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, status
    paths = json.loads(body).get("paths") or {}
    assert "/api/v1/home/export" in paths, sorted(paths.keys())

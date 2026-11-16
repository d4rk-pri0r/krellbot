"""Pack rollback route/client coherence — no dead 404-claiming surface.

Until a prior-revision store exists, ``POST /api/v1/packs/rollback`` is
not mounted. The HTTP packs client must not call that path (M5.4 removed
the dead ``rollback`` method). Install remains orthogonal and never
claims a rollback outcome. Read-only ``rollback_ref`` metadata on list
rows is unchanged.

Fakes only; isolated ``KRELLBOT_HOME``; session/CSRF preserved.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot import license as kb_license
from krellbot.application import pack_library
from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _post_json,
    asgi_call,
)


def _write_catalogue(home: Path) -> None:
    document = {
        "catalogue_version": "1",
        "updated": "2026-11-16T00:00:00Z",
        "packs": [
            {
                "id": "free-dual-ma",
                "label": "Free Dual MA",
                "version": "1.0.0",
                "tier": "free",
                "permissions": [],
            },
        ],
    }
    kb_license.write_catalogue_cache(home, document)


def _session_headers(app) -> list[tuple[str, str]]:
    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    session = next(c for c in cookies if c.startswith("krellbot_session=")).split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
        ("X-Krellbot-CSRF", csrf),
    ]


def test_packs_rollback_route_not_mounted(tmp_path: Path) -> None:
    """POST /api/v1/packs/rollback is absent (404), not a silent success."""
    home = tmp_path / "home"
    home.mkdir()
    app = _build_app(home)
    headers = _session_headers(app)
    body = json.dumps(
        {
            "schema_version": "1",
            "command": "packs.rollback",
            "payload": {"pack_id": "alpha"},
        }
    ).encode("utf-8")
    status, _h, resp, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/packs/rollback",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            *headers,
        ],
        body=body,
    )
    assert status == 404, (status, resp)


def test_packs_install_does_not_claim_rollback(tmp_path: Path) -> None:
    """One-click install returns pack row only — no rollback action fields."""
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)
    app = _build_app(home)
    headers = _session_headers(app)
    body = json.dumps({"pack_id": "free-dual-ma"}).encode("utf-8")
    status, _h, resp, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/packs/install",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body))),
            *headers,
        ],
        body=body,
    )
    assert status == 200, (status, resp)
    payload = json.loads(resp)
    assert payload["ok"] is True
    assert "rollback" not in payload
    assert "rollback_action" not in payload
    pack = payload["pack"]
    assert pack["pack_id"] == "free-dual-ma"
    assert pack["bucket"] == "download_pending"
    # Read-only prior-revision metadata may be null; never a live action.
    assert pack["rollback_ref"] is None


def test_pack_library_has_no_rollback_helper(tmp_path: Path) -> None:
    """Application service exposes no rollback until a prior-revision store."""
    assert not hasattr(pack_library, "rollback_pack")
    assert not hasattr(pack_library, "rollback")
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)
    row = pack_library.install_from_catalogue(home, "free-dual-ma")
    assert row["rollback_ref"] is None

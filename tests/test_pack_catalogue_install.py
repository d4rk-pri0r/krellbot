"""One-click free catalogue install — download_pending marker + library row.

``POST /api/v1/packs/install`` installs a free signed-catalogue entry by
writing a local ``download_pending`` marker (version from the verified
catalogue cache). Paid entries are refused with ``activation_required``.
No network, no real credentials, isolated ``KRELLBOT_HOME``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
            {
                "id": "paid-triple-stack",
                "label": "Triple Stack",
                "version": "2.1.0",
                "tier": "paid",
                "permissions": ["catalog"],
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


def test_install_from_catalogue_writes_download_pending_with_version(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)

    row = pack_library.install_from_catalogue(home, "free-dual-ma")
    assert row["bucket"] == "download_pending"
    assert row["pack_id"] == "free-dual-ma"
    assert row["version"] == "1.0.0"

    marker = home / "packs" / "free-dual-ma.download_pending.json"
    assert marker.is_file()
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["version"] == "1.0.0"

    listed = pack_library.list_installed(home)
    assert any(
        r["pack_id"] == "free-dual-ma" and r["bucket"] == "download_pending" and r["version"] == "1.0.0" for r in listed
    )


def test_install_from_catalogue_refuses_paid_without_activation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)
    with pytest.raises(pack_library.InstallRefused) as caught:
        pack_library.install_from_catalogue(home, "paid-triple-stack")
    assert caught.value.code == "activation_required"
    assert not (home / "packs" / "paid-triple-stack.download_pending.json").exists()


def test_packs_install_route_free_ok_and_paid_forbidden(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    _write_catalogue(home)
    app = _build_app(home)

    headers = _session_headers(app)
    body_bytes = json.dumps({"pack_id": "free-dual-ma"}).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/packs/install",
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )
    assert status == 200, body
    payload = json.loads(body)
    assert payload["ok"] is True
    assert payload["pack"]["bucket"] == "download_pending"
    assert payload["pack"]["version"] == "1.0.0"

    body_bytes = json.dumps({"pack_id": "paid-triple-stack"}).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/packs/install",
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )
    assert status == 403, body
    refused = json.loads(body)
    assert refused["ok"] is False
    assert refused["code"] == "activation_required"

"""GET /api/v1/packs/modes lists shipped built-in trading-mode packs."""

from __future__ import annotations

import json
from pathlib import Path

from krellbot.packs import mode_packs
from tests.test_ns06_api import TEST_PORT, _build_app, _post_json, asgi_call

MODES_PATH = "/api/v1/packs/modes"


def _session_headers(app) -> list[tuple[str, str]]:
    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, (status, body)
    session = next(c for c in cookies if c.startswith("krellbot_session=")).split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]


def _get_modes(app, *, headers: list[tuple[str, str]] | None = None):
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=MODES_PATH, headers=base)


def test_packs_modes_lists_shipped_builtin_modes(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    status, _h, body, _c = _get_modes(app, headers=_session_headers(app))
    assert status == 200, (status, body)
    doc = json.loads(body)
    assert doc["schema_version"] == "1"
    assert isinstance(doc["modes"], list)
    ids = [row["id"] for row in doc["modes"]]
    for kind in mode_packs.available_mode_kinds():
        pack = mode_packs.load_mode_pack(kind)
        assert pack["id"] in ids
    for row in doc["modes"]:
        assert set(row.keys()) == {"id", "label", "description", "pack"}
        assert row["pack"]["id"] == row["id"]
        assert isinstance(row["pack"].get("mode"), dict)
        assert "no profit or return claim" in row["description"].lower()


def test_packs_modes_requires_session(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    status, _h, body, _c = _get_modes(app)
    assert status in {401, 403}, (status, body)

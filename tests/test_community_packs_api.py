"""Community packs list/install loopback API — fake transport only.

``GET /api/v1/community/packs`` lists installed community JSON under
``<home>/packs/community/``. ``GET /api/v1/community/index`` browses the
upstream index through an injectable bytes transport.
``POST /api/v1/community/install`` installs by id from that index and
refuses foreign URLs before any destination write.

CSRF/session/origin/host gates match the existing packs routes. Tests
use an isolated ``KRELLBOT_HOME`` via ``tmp_path`` and never open a
real network socket.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot import community as kb_community
from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _post_json,
    asgi_call,
)

PACK_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json"
FOREIGN_URL = "https://evil.example/packs/trend-follow.json"


class _FakeBytesTransport:
    """In-memory community Transport: no socket, no urllib."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self.mapping = mapping
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self.mapping:
            return self.mapping[url]
        raise AssertionError(f"unexpected url: {url}")


def _pack_bytes(pack_id: str = "trend-follow") -> bytes:
    return json.dumps(
        {
            "schema_version": 1,
            "id": pack_id,
            "version": "1.0.0",
            "label": "Trend follow",
            "author": "community-example",
            "origin": "Community pack. Unverified. No guarantee.",
            "timeframe": "1h",
            "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
            "entry": ["close", ">", "sma20"],
            "exit": ["close", "<", "sma20"],
            "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
            "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
        }
    ).encode("utf-8")


def _index_bytes(*, url: str = PACK_URL, pack_id: str = "trend-follow") -> bytes:
    return json.dumps(
        {
            "packs": [
                {
                    "id": pack_id,
                    "author": "community-example",
                    "label": "Trend follow",
                    "url": url,
                }
            ]
        }
    ).encode("utf-8")


def _session_headers(app, *, csrf: bool = False) -> list[tuple[str, str]]:
    token = app.state.krellbot.bootstrap_token
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    session = next(c for c in cookies if c.startswith("krellbot_session=")).split(";", 1)[0].split("=", 1)[1]
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    if csrf:
        headers.append(("X-Krellbot-CSRF", decoded["csrf_token"]))
    return headers


def _get(
    app,
    path: str,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, bytes]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, _h, body, _c = asgi_call(app, method="GET", path=path, headers=base)
    return status, body


def _post_install(app, pack_id: str, *, headers: list[tuple[str, str]]) -> tuple[int, bytes]:
    body_bytes = json.dumps({"pack_id": pack_id}).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/community/install",
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )
    return status, body


def test_community_packs_list_empty_and_installed(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    app = _build_app(home)
    headers = _session_headers(app)

    status, body = _get(app, "/api/v1/community/packs", headers=headers)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["schema_version"] == "1"
    assert payload["packs"] == []

    dest = home / "packs" / "community"
    dest.mkdir(parents=True)
    (dest / "trend-follow.json").write_bytes(_pack_bytes())

    status, body = _get(app, "/api/v1/community/packs", headers=headers)
    assert status == 200, body
    payload = json.loads(body)
    assert payload["packs"] == [
        {
            "id": "trend-follow",
            "version": "1.0.0",
            "label": "Trend follow",
            "author": "community-example",
            "origin": "Community pack. Unverified. No guarantee.",
        }
    ]


def test_community_packs_list_requires_session(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    app = _build_app(home)
    status, body = _get(app, "/api/v1/community/packs")
    assert status in {401, 403}, body


def test_community_index_and_install_with_fake_transport(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    app = _build_app(home)
    transport = _FakeBytesTransport(
        {
            kb_community.INDEX_URL: _index_bytes(),
            PACK_URL: _pack_bytes(),
        }
    )
    app.state.krellbot.community_transport = transport

    headers = _session_headers(app, csrf=True)

    status, body = _get(app, "/api/v1/community/index", headers=headers)
    assert status == 200, body
    index = json.loads(body)
    assert index["index_url"] == kb_community.INDEX_URL
    assert index["packs"] == [
        {
            "id": "trend-follow",
            "url": PACK_URL,
            "author": "community-example",
            "label": "Trend follow",
        }
    ]
    assert transport.calls == [kb_community.INDEX_URL]

    status, body = _post_install(app, "trend-follow", headers=headers)
    assert status == 200, body
    installed = json.loads(body)
    assert installed["ok"] is True
    assert installed["pack"]["id"] == "trend-follow"
    assert installed["pack"]["author"] == "community-example"
    assert installed["path"] == "packs/community/trend-follow.json"
    assert (home / "packs" / "community" / "trend-follow.json").is_file()
    assert transport.calls == [kb_community.INDEX_URL, kb_community.INDEX_URL, PACK_URL]

    status, body = _get(app, "/api/v1/community/packs", headers=headers)
    assert status == 200, body
    listed = json.loads(body)
    assert any(row["id"] == "trend-follow" for row in listed["packs"])


def test_community_install_refuses_foreign_url(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    app = _build_app(home)
    transport = _FakeBytesTransport({kb_community.INDEX_URL: _index_bytes(url=FOREIGN_URL)})
    app.state.krellbot.community_transport = transport

    headers = _session_headers(app, csrf=True)
    status, body = _post_install(app, "trend-follow", headers=headers)
    assert status == 403, body
    refused = json.loads(body)
    assert refused["ok"] is False
    assert refused["code"] == "foreign_url"
    assert not (home / "packs" / "community").exists() or not any((home / "packs" / "community").glob("*.json"))
    assert transport.calls == [kb_community.INDEX_URL]


def test_community_install_requires_csrf(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    app = _build_app(home)
    transport = _FakeBytesTransport(
        {
            kb_community.INDEX_URL: _index_bytes(),
            PACK_URL: _pack_bytes(),
        }
    )
    app.state.krellbot.community_transport = transport
    headers = _session_headers(app, csrf=False)
    status, body = _post_install(app, "trend-follow", headers=headers)
    assert status in {401, 403}, body
    assert transport.calls == []

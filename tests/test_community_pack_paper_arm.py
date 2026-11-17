"""Community pack open → draft → validate → paper.arm (M17.6).

Installed community packs under ``<home>/packs/community/`` open via
``GET /api/v1/community/packs/{id}``, become Strategies drafts, refuse
``paper.arm`` until validated, then arm on an allowed market. Fake
transport only; ``PAPER_ONLY_RELEASE`` stays True. No risk-path modules.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot import community as kb_community
from krellbot import release_policy
from tests.test_ns06_api import (
    TEST_PORT,
    _build_app,
    _post_json,
    asgi_call,
)

PACK_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json"


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


def _pack_dict(pack_id: str = "trend-follow") -> dict:
    return {
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


def _pack_bytes(pack_id: str = "trend-follow") -> bytes:
    return json.dumps(_pack_dict(pack_id)).encode("utf-8")


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


def _bootstrap(app) -> tuple[str, str]:
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
    return decoded["csrf_token"], session


def _auth(csrf: str, session: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]


def _get(app, path: str, *, headers: list[tuple[str, str]]) -> tuple[int, bytes]:
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path=path,
        headers=[("Host", f"127.0.0.1:{TEST_PORT}"), *headers],
    )
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


def _post_draft(app, pack: dict, *, headers: list[tuple[str, str]]) -> tuple[int, bytes]:
    body_bytes = json.dumps({"pack": pack}).encode("utf-8")
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path="/api/v1/strategies/drafts",
        body=body_bytes,
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", str(len(body_bytes))),
            *headers,
        ],
    )
    return status, body


def _validate(app, revision_id: str, *, headers: list[tuple[str, str]]) -> tuple[int, bytes]:
    status, _h, body, _c = asgi_call(
        app,
        method="POST",
        path=f"/api/v1/strategies/drafts/{revision_id}/validate",
        body=b"{}",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Content-Type", "application/json"),
            ("Content-Length", "2"),
            *headers,
        ],
    )
    return status, body


def _paper_arm(
    app,
    *,
    headers: list[tuple[str, str]],
    revision_id: str | None = None,
    pack_path: str | None = None,
) -> tuple[int, bytes]:
    payload: dict = {
        "venue": "kraken",
        "mode": "paper",
        "paper_balance": "1000",
    }
    if revision_id is not None:
        payload["revision_id"] = revision_id
    if pack_path is not None:
        payload["pack_path"] = pack_path
    arm = {
        "schema_version": "1",
        "command": "paper.arm",
        "correlation_id": "m17-6-community-arm",
        "expected_revision": None,
        "payload": payload,
    }
    status, _h, body, _c = _post_json(app, "/api/v1/commands", arm, headers=headers)
    return status, body


def _install_community(app, home: Path) -> tuple[str, str, list[tuple[str, str]]]:
    transport = _FakeBytesTransport(
        {
            kb_community.INDEX_URL: _index_bytes(),
            PACK_URL: _pack_bytes(),
        }
    )
    app.state.krellbot.community_transport = transport
    csrf, session = _bootstrap(app)
    headers = _auth(csrf, session)
    status, body = _post_install(app, "trend-follow", headers=headers)
    assert status == 200, body
    assert (home / "packs" / "community" / "trend-follow.json").is_file()
    return csrf, session, headers


def test_community_pack_open_validate_paper_arm_path(home: Path) -> None:
    """Install → open → draft → refuse unvalidated → validate → arm → deployed."""

    assert release_policy.PAPER_ONLY_RELEASE is True
    assert release_policy.paper_only_release_active() is True

    app = _build_app(home)
    _csrf, _session, headers = _install_community(app, home)

    # Open installed community pack (source honesty: community).
    status, body = _get(app, "/api/v1/community/packs/trend-follow", headers=headers)
    assert status == 200, body
    opened = json.loads(body)
    assert opened["source"] == "community"
    assert opened["path"] == "packs/community/trend-follow.json"
    pack = opened["pack"]
    assert pack["id"] == "trend-follow"
    assert pack["author"] == "community-example"
    assert pack["origin"]

    # Create Strategies draft from the opened pack.
    status, body = _post_draft(app, pack, headers=headers)
    assert status == 200, body
    draft = json.loads(body)
    revision_id = draft["revision_id"]
    assert draft["state"] == "draft"
    assert draft["strategy_id"] == "trend-follow"

    # Unvalidated draft refuses paper.arm (same rule as owned packs).
    status, body = _paper_arm(app, headers=headers, revision_id=revision_id)
    assert status == 403, body
    refused = json.loads(body)
    assert refused["ok"] is False
    assert refused["code"] == "draft_not_runnable"
    assert refused["effect"] == "refused"
    assert not (home / "config.json").exists()

    # Validate then arm.
    status, body = _validate(app, revision_id, headers=headers)
    assert status == 200, body
    assert json.loads(body)["state"] == "validated"

    status, body = _paper_arm(app, headers=headers, revision_id=revision_id)
    assert status == 200, body
    armed = json.loads(body)
    assert armed["ok"] is True
    assert armed["code"] == "armed"
    assert (home / "config.json").is_file()

    # PAPER_ONLY still pinned — live stays refused by policy.
    assert release_policy.PAPER_ONLY_RELEASE is True


def test_community_pack_path_arm_resolves_under_packs_community(home: Path) -> None:
    """paper.arm pack_path basename resolves into packs/community/ safely."""

    app = _build_app(home)
    _csrf, _session, headers = _install_community(app, home)

    # Direct pack_path arm (legacy address) after writing a runnable pack
    # under packs/community — still basename-confined, never client dirs.
    status, body = _paper_arm(
        app,
        headers=headers,
        pack_path="packs/community/trend-follow.json",
    )
    assert status == 200, body
    assert json.loads(body)["code"] == "armed"


def test_community_pack_open_missing_is_404(home: Path) -> None:
    app = _build_app(home)
    csrf, session = _bootstrap(app)
    headers = _auth(csrf, session)
    status, body = _get(app, "/api/v1/community/packs/missing-pack", headers=headers)
    assert status == 404, body
    decoded = json.loads(body)
    assert decoded["code"] == "pack_not_found"


def test_community_pack_open_bad_id_is_400(home: Path) -> None:
    app = _build_app(home)
    csrf, session = _bootstrap(app)
    headers = _auth(csrf, session)
    # ``..`` is a single path segment to the router but refused by basename rules.
    status, body = _get(app, "/api/v1/community/packs/..", headers=headers)
    assert status == 400, body


def test_read_installed_confines_basename(home: Path) -> None:
    community = home / "packs" / "community"
    community.mkdir(parents=True)
    (community / "trend-follow.json").write_text(json.dumps(_pack_dict()), encoding="utf-8")
    pack = kb_community.read_installed(home, "trend-follow")
    assert pack["id"] == "trend-follow"
    path = kb_community.installed_path(home, "trend-follow")
    assert path == community / "trend-follow.json"
    try:
        kb_community.read_installed(home, "../trend-follow")
        raise AssertionError("expected InstallPayloadError")
    except kb_community.InstallPayloadError:
        pass

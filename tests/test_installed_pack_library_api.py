"""Installed pack library — the loopback API contract.

The route is ``GET /api/v1/packs``; the dashboard Strategies tab's pack
library reads it through ``createPacksHttpClient().listInstalled()``.
The contract:

  1. The route exists in the OpenAPI document.
  2. It is a read endpoint gated by ``_gate_get`` exactly like
     ``GET /api/v1/paper/status``: a session cookie is required, a
     non-loopback Origin is 403, a non-loopback Host is 403, and no CSRF
     header is needed.
  3. The body is the closed row list produced by
     ``krellbot.application.packs.list_packs`` — each row carries
     exactly ``bucket``, ``pack_id``, ``version``, ``permissions``,
     ``rollback_ref``. The route performs no mutation and offers no
     install/catalog/entitlement surface.
  4. A home with no packs returns ``[]`` (a truthful empty list, not an
     error and not a fabricated catalog).

Every test uses an isolated ``KRELLBOT_HOME`` via ``tmp_path``; no real
``~/.krellbot`` is read and no network transport is touched.
"""

from __future__ import annotations

import hashlib
import json
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

CLOSED_ROW_KEYS = {"bucket", "pack_id", "version", "permissions", "rollback_ref"}


# ---- helpers --------------------------------------------------------------


def _get_packs(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    """Issue ``GET /api/v1/packs`` against ``app``."""

    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path="/api/v1/packs", headers=base)


def _session_headers(app, token: str) -> list[tuple[str, str]]:
    """Bootstrap a session on ``app`` and return the gate-passing headers."""

    _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    session_value = next(iter(state.sessions.keys()))
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _write_pack(home: Path, pack_id: str, version: str = "1.0.0") -> str:
    """Write a runnable DSL pack under ``<home>/packs/``; return revision id."""

    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": version,
        "label": f"Pack {pack_id}",
        "author": "installed pack library api tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    (packs / f"{pack_id}.json").write_text(json.dumps(body), encoding="utf-8")
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_deployed(
    home: Path,
    pack_id: str,
    *,
    version: str,
    revision_id: str,
    prior_revision_id: str | None = None,
) -> None:
    """Write a deployed-state record so the row carries ``rollback_ref``."""

    packs = home / "packs"
    payload: dict = {
        "schema_version": "1",
        "pack_id": pack_id,
        "version": version,
        "revision_id": revision_id,
        "deployed_at": 1700000000,
        "permissions": ["trade"],
    }
    if prior_revision_id is not None:
        payload["prior_revision_id"] = prior_revision_id
    (packs / f"{pack_id}.deployed.json").write_text(json.dumps(payload), encoding="utf-8")


# ---- 1. the route exists --------------------------------------------------


def test_packs_route_exists(tmp_path: Path) -> None:
    """The route is registered on the versioned API surface."""

    app = _build_app(tmp_path)
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path="/openapi.json",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, status
    decoded = json.loads(body)
    paths = decoded.get("paths") or {}
    assert "/api/v1/packs" in paths, sorted(paths.keys())


# ---- 2. session gate parity -----------------------------------------------


def test_packs_without_session_cookie_is_403(tmp_path: Path) -> None:
    """No session cookie → 403, the same gate as every other read route."""

    app = _build_app(tmp_path)
    status, _h, _b, _c = _get_packs(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, status


def test_packs_refuses_unauthenticated_with_non_loopback_origin(tmp_path: Path) -> None:
    """A non-loopback Origin is 403 even when a session cookie is presented."""

    token = f"boot-packs-evil-origin-{tmp_path.name}"
    app = _build_app(tmp_path, bootstrap_token=token)
    headers = _session_headers(app, token)
    headers[0] = ("Origin", "http://evil.example.com")
    status, _h, body, _c = _get_packs(app, headers=headers)
    assert status == 403, (status, body)


def test_packs_refuses_unauthenticated_with_non_loopback_host(tmp_path: Path) -> None:
    """A non-loopback Host is 403; the gate checks Host, not just Origin."""

    token = f"boot-packs-evil-host-{tmp_path.name}"
    app = _build_app(tmp_path, bootstrap_token=token)
    headers = _session_headers(app, token)
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path="/api/v1/packs",
        headers=[
            ("Host", "evil.example.com"),
            *headers,
        ],
    )
    assert status == 403, (status, body)


def test_packs_does_not_require_csrf_header(tmp_path: Path) -> None:
    """A read endpoint: a wrong ``X-Krellbot-CSRF`` header still passes."""

    token = f"boot-packs-no-csrf-{tmp_path.name}"
    app = _build_app(tmp_path, bootstrap_token=token)
    headers = [
        *_session_headers(app, token),
        ("X-Krellbot-CSRF", "not-the-real-csrf"),
    ]
    status, _h, body, _c = _get_packs(app, headers=headers)
    assert status == 200, (status, body)
    assert json.loads(body) == []


# ---- 3. closed rows from list_packs ---------------------------------------


def test_packs_returns_closed_rows_from_list_packs(tmp_path: Path) -> None:
    """The body equals ``list_packs(home)`` row for row, closed keys only."""

    deployed_revision = _write_pack(tmp_path, "alpha", version="2.0.0")
    _write_deployed(
        tmp_path,
        "alpha",
        version="2.0.0",
        revision_id=deployed_revision,
        prior_revision_id="0" * 64,
    )
    _write_pack(tmp_path, "bravo", version="1.1.0")

    from krellbot.application.packs import list_packs

    expected = list_packs(tmp_path)
    assert [row["pack_id"] for row in expected] == ["alpha", "bravo"], expected

    token = f"boot-packs-rows-{tmp_path.name}"
    app = _build_app(tmp_path, bootstrap_token=token)
    status, _h, body, _c = _get_packs(app, headers=_session_headers(app, token))
    assert status == 200, (status, body)
    rows = json.loads(body)
    assert rows == expected, (rows, expected)

    by_id = {row["pack_id"]: row for row in rows}
    assert set(by_id) == {"alpha", "bravo"}, by_id
    for pack_id, row in by_id.items():
        assert set(row.keys()) == CLOSED_ROW_KEYS, (pack_id, row)

    assert by_id["alpha"]["bucket"] == "deployed", by_id["alpha"]
    assert by_id["alpha"]["version"] == "2.0.0", by_id["alpha"]
    assert by_id["alpha"]["permissions"] == ["trade"], by_id["alpha"]
    assert by_id["alpha"]["rollback_ref"] == {
        "pack_id": "alpha",
        "prior_revision_id": "0" * 64,
    }, by_id["alpha"]

    assert by_id["bravo"]["bucket"] == "installed", by_id["bravo"]
    assert by_id["bravo"]["version"] == "1.1.0", by_id["bravo"]
    assert by_id["bravo"]["permissions"] == [], by_id["bravo"]
    assert by_id["bravo"]["rollback_ref"] is None, by_id["bravo"]


def test_packs_body_never_leaks_paths_or_tokens(tmp_path: Path) -> None:
    """No filesystem path, license key, or bootstrap token crosses the wire."""

    _write_pack(tmp_path, "alpha")
    token = f"boot-packs-no-leak-{tmp_path.name}"
    app = _build_app(tmp_path, bootstrap_token=token)
    status, _h, body, _c = _get_packs(app, headers=_session_headers(app, token))
    assert status == 200, (status, body)
    raw = body.decode("utf-8")
    assert str(tmp_path) not in raw, raw
    assert token not in raw, raw
    for needle in ("pack_path", "pack_sha256", "license", "key"):
        assert needle not in raw, (needle, raw)


# ---- 4. truthful empty list ------------------------------------------------


def test_packs_returns_empty_list_when_home_has_no_packs(tmp_path: Path) -> None:
    """A home with no pack state returns ``[]`` — not 404, not an error."""

    token = f"boot-packs-empty-{tmp_path.name}"
    app = _build_app(tmp_path, bootstrap_token=token)
    status, _h, body, _c = _get_packs(app, headers=_session_headers(app, token))
    assert status == 200, (status, body)
    assert body == b"[]", body
    assert json.loads(body) == []

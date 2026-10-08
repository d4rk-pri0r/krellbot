"""OPERATIONS-DEPLOYMENT-HISTORY — read-only deployment history API.

``GET /api/v1/operations/deployments`` and
``GET /api/v1/operations/deployments/{deployment_id}`` expose the
user's most recent historical deployment records, derived from the
append-only journal under ``<home>/journal`` by
``krellbot.application.operations.list_deployment_records`` /
``get_deployment_record``.

Contract under test:

  * Both routes are gated by the same session gate as
    ``GET /api/v1/operations``: no session cookie means 403, and a
    loopback Origin + Host with a valid session passes.
  * The list returns closed rows — ``deployment_id``, ``venue``,
    ``pair``, ``created_at_ms``, ``state``, a small ``config`` subset,
    a small ``schedule`` subset, and a ``last_execution_summary``
    excerpt — and never ``cap``, ``stop``, ``starting_cash``,
    ``owned_qty``, ``pack_path``, ``pack_sha256``, or key material.
  * The list is newest-first and capped at the 50 most recent rows.
  * No journal directory means an empty list, not an error.
  * Journal lines missing required fields (or not parseable, or not
    ``kind=deployment``) are skipped, not fatal.
  * The detail route is 404 ``deployment_not_found`` on an unknown id
    and the closed row for a known id.
  * Both routes answer with ``Cache-Control: no-store``.

Helpers mirror ``tests/test_m3_gui_operations_api.py`` — the same
ASGI mini-client and the same bootstrap-then-read idiom, with an
isolated ``KRELLBOT_HOME`` per test via the ``home`` fixture.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

TEST_PORT = 8080


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


# ---- helpers ----------------------------------------------------------------


def _origin() -> list[tuple[str, str]]:
    return [("Origin", f"http://127.0.0.1:{TEST_PORT}")]


def _build_app(home: Path):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token="boot-ops-history")


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


def _session(app) -> list[tuple[str, str]]:
    s, _h, b, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": "boot-ops-history"},
        headers=_origin(),
    )
    assert s == 200, (s, b)
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _deployment_line(
    *,
    deployment_id: str,
    ts: int,
    venue: str = "kraken",
    pair: str = "SUIUSD",
    state: str = "paper",
) -> str:
    return json.dumps(
        {
            "ts": ts,
            "kind": "deployment",
            "venue": venue,
            "pack": "trend-follow",
            "bar_ts": 0,
            "detail": {
                "deployment_id": deployment_id,
                "venue": venue,
                "pair": pair,
                "state": state,
                "config": {
                    "pack_id": "trend-follow",
                    "pack_version": "1.0.0",
                    "mode": "paper",
                    "entries_paused": False,
                    # Sensitive keys must exist in the journal record and
                    # still never reach the response body.
                    "cap": 25,
                    "stop": "1.23",
                    "starting_cash": "1000",
                    "pack_path": "/secret/pack.json",
                    "pack_sha256": "a" * 64,
                },
                "schedule": {"timeframe": "1h", "interval": 3600, "next_run_at_ms": None},
                "last_execution_summary": "one tick, no entries",
            },
        }
    )


def _write_journal(home: Path, filename: str, lines: list[str]) -> None:
    journal = home / "journal"
    journal.mkdir(parents=True, exist_ok=True)
    (journal / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _header(headers: list[tuple[str, str]], name: str) -> str | None:
    for key, value in headers:
        if key.lower() == name.lower():
            return value
    return None


# ---- application helper (direct, isolated home) -----------------------------


def test_list_deployment_records_reads_journal_and_caps_at_50(home: Path) -> None:
    from krellbot.application.operations import DEPLOYMENT_HISTORY_LIMIT, list_deployment_records

    lines = [
        _deployment_line(deployment_id=f"dep-{i}", ts=1_700_000_000 + i) for i in range(60)
    ]
    _write_journal(home, "2026-09.jsonl", lines)

    rows = list_deployment_records(home)
    assert len(rows) == DEPLOYMENT_HISTORY_LIMIT == 50, len(rows)
    # Newest first.
    assert rows[0]["deployment_id"] == "dep-59"
    assert rows[-1]["deployment_id"] == "dep-10"
    row = rows[0]
    assert row["venue"] == "kraken"
    assert row["pair"] == "SUIUSD"
    assert row["created_at_ms"] == (1_700_000_000 + 59) * 1000
    assert row["state"] == "paper"
    # Closed config/schedule subsets: the sensitive keys never appear.
    assert row["config"] == {
        "pack_id": "trend-follow",
        "pack_version": "1.0.0",
        "mode": "paper",
        "entries_paused": False,
    }
    assert row["schedule"] == {"timeframe": "1h", "interval": 3600}
    assert row["last_execution_summary"] == "one tick, no entries"
    raw = json.dumps(rows)
    for forbidden in ("cap", "stop", "starting_cash", "owned_qty", "pack_path", "pack_sha256"):
        assert forbidden not in raw, forbidden


def test_list_deployment_records_empty_without_journal(home: Path) -> None:
    from krellbot.application.operations import list_deployment_records

    assert list_deployment_records(home) == []
    # A journal directory with no deployment records is also empty.
    _write_journal(home, "2026-09.jsonl", [_deployment_line(deployment_id="d", ts=10).replace('"deployment"', '"tick"')])
    assert list_deployment_records(home) == []


def test_list_deployment_records_skips_incomplete_lines(home: Path) -> None:
    from krellbot.application.operations import list_deployment_records

    good = _deployment_line(deployment_id="dep-good", ts=1_700_000_100)
    missing_state = json.dumps(
        {
            "ts": 1_700_000_050,
            "kind": "deployment",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": 0,
            "detail": {"deployment_id": "dep-nostate", "venue": "kraken", "pair": "SUIUSD"},
        }
    )
    missing_id = json.dumps(
        {
            "ts": 1_700_000_040,
            "kind": "deployment",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": 0,
            "detail": {"venue": "kraken", "pair": "SUIUSD", "state": "paper"},
        }
    )
    other_kind = json.dumps(
        {
            "ts": 1_700_000_030,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": 0,
            "detail": {"deployment_id": "dep-tick", "venue": "kraken", "pair": "SUIUSD", "state": "paper"},
        }
    )
    not_json = "{ this line is not json"
    no_detail = json.dumps({"ts": 1_700_000_020, "kind": "deployment", "venue": "kraken", "pack": "-", "bar_ts": 0})
    zero_ts = json.dumps(
        {
            "ts": 0,
            "kind": "deployment",
            "venue": "kraken",
            "pack": "-",
            "bar_ts": 0,
            "detail": {"deployment_id": "dep-zero", "venue": "kraken", "pair": "SUIUSD", "state": "paper"},
        }
    )
    _write_journal(
        home,
        "deployments-2026-09.jsonl",
        [good, missing_state, missing_id, other_kind, not_json, no_detail, zero_ts],
    )

    rows = list_deployment_records(home)
    assert [r["deployment_id"] for r in rows] == ["dep-good"], rows


def test_get_deployment_record_newest_match(home: Path) -> None:
    from krellbot.application.operations import get_deployment_record

    _write_journal(
        home,
        "2026-09.jsonl",
        [
            _deployment_line(deployment_id="dep-a", ts=1_700_000_010, state="paper"),
            _deployment_line(deployment_id="dep-a", ts=1_700_000_020, state="paused"),
            _deployment_line(deployment_id="dep-b", ts=1_700_000_030),
        ],
    )

    row = get_deployment_record(home, "dep-a")
    assert row is not None
    assert row["state"] == "paused"
    assert row["created_at_ms"] == 1_700_000_020_000
    assert get_deployment_record(home, "nope") is None


# ---- routes: session gate ---------------------------------------------------


def test_list_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, _b, _c = _get(app, "/api/v1/operations/deployments")
    assert status == 403, status


def test_detail_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, _b, _c = _get(app, "/api/v1/operations/deployments/dep-1")
    assert status == 403, status


def test_list_refuses_non_loopback_origin(home: Path) -> None:
    app = _build_app(home)
    headers = _session(app)
    # A present non-loopback Origin is refused even with a valid session.
    hijacked = [("Origin", "http://evil.example:8080"), *headers]
    status, _h, _b, _c = _get(app, "/api/v1/operations/deployments", headers=hijacked)
    assert status == 403, status


def test_detail_refuses_non_loopback_origin(home: Path) -> None:
    app = _build_app(home)
    headers = _session(app)
    hijacked = [("Origin", "http://evil.example:8080"), *headers]
    status, _h, _b, _c = _get(app, "/api/v1/operations/deployments/dep-1", headers=hijacked)
    assert status == 403, status


# ---- routes: bodies ---------------------------------------------------------


def test_list_returns_closed_rows_from_journal(home: Path) -> None:
    _write_journal(
        home,
        "2026-09.jsonl",
        [
            _deployment_line(deployment_id="dep-2", ts=1_700_000_020, venue="coinbase", pair="BTC-USD"),
            _deployment_line(deployment_id="dep-1", ts=1_700_000_010),
        ],
    )
    app = _build_app(home)
    status, headers, body, _c = _get(app, "/api/v1/operations/deployments", headers=_session(app))
    assert status == 200, (status, body)
    assert _header(headers, "Cache-Control") == "no-store"
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1"
    assert [r["deployment_id"] for r in decoded["deployments"]] == ["dep-2", "dep-1"]
    raw = body.decode("utf-8")
    for forbidden in ("cap", "stop", "starting_cash", "owned_qty", "pack_path", "pack_sha256"):
        assert forbidden not in raw, forbidden


def test_list_returns_empty_rows_when_no_journal(home: Path) -> None:
    app = _build_app(home)
    status, _h, body, _c = _get(app, "/api/v1/operations/deployments", headers=_session(app))
    assert status == 200, (status, body)
    assert json.loads(body) == {"schema_version": "1", "deployments": []}


def test_list_caps_total_entries_at_50(home: Path) -> None:
    _write_journal(
        home,
        "2026-09.jsonl",
        [_deployment_line(deployment_id=f"dep-{i}", ts=1_700_000_000 + i) for i in range(80)],
    )
    app = _build_app(home)
    status, _h, body, _c = _get(app, "/api/v1/operations/deployments", headers=_session(app))
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert len(decoded["deployments"]) == 50
    assert decoded["deployments"][0]["deployment_id"] == "dep-79"
    assert decoded["deployments"][-1]["deployment_id"] == "dep-30"


def test_detail_returns_404_for_unknown_id(home: Path) -> None:
    _write_journal(home, "2026-09.jsonl", [_deployment_line(deployment_id="dep-1", ts=1_700_000_010)])
    app = _build_app(home)
    status, headers, body, _c = _get(
        app, "/api/v1/operations/deployments/missing", headers=_session(app)
    )
    assert status == 404, (status, body)
    assert _header(headers, "Cache-Control") == "no-store"
    decoded = json.loads(body)
    assert decoded["code"] == "deployment_not_found"


def test_detail_returns_closed_row_for_known_id(home: Path) -> None:
    _write_journal(home, "2026-09.jsonl", [_deployment_line(deployment_id="dep-1", ts=1_700_000_010)])
    app = _build_app(home)
    status, headers, body, _c = _get(
        app, "/api/v1/operations/deployments/dep-1", headers=_session(app)
    )
    assert status == 200, (status, body)
    assert _header(headers, "Cache-Control") == "no-store"
    decoded = json.loads(body)
    assert decoded["deployment_id"] == "dep-1"
    assert decoded["venue"] == "kraken"
    assert decoded["pair"] == "SUIUSD"
    assert decoded["created_at_ms"] == 1_700_000_010_000
    assert decoded["state"] == "paper"
    assert decoded["config"]["pack_id"] == "trend-follow"
    assert decoded["schedule"]["timeframe"] == "1h"
    assert decoded["last_execution_summary"] == "one tick, no entries"
    raw = body.decode("utf-8")
    for forbidden in ("cap", "stop", "starting_cash", "owned_qty", "pack_path", "pack_sha256"):
        assert forbidden not in raw, forbidden

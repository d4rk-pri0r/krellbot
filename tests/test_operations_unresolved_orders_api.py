"""M1.9 — read-only unresolved orders API.

``GET /api/v1/operations/unresolved-orders`` lists every order awaiting
reconcile with ``client_order_id``, ``age_seconds``, and
``last_lookup_result``. Same session gate as ``GET /api/v1/operations``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

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


def _build_app(home: Path):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token="boot-ops-unresolved")


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
        {"token": "boot-ops-unresolved"},
        headers=_origin(),
    )
    assert s == 200, (s, b)
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _header(headers: list[tuple[str, str]], name: str) -> str | None:
    for key, value in headers:
        if key.lower() == name.lower():
            return value
    return None


def _seed_unresolved(home: Path, *, now: int) -> None:
    from krellbot.storage.database import OperationalStore

    store = OperationalStore(home / "ops.sqlite")
    store.connect()
    with store.transaction() as conn:
        for coid, age, lookup_kind in (
            ("coid-old", 200, "reconcile_absent"),
            ("coid-new", 30, None),
        ):
            ts = now - age
            outbox = json.dumps(
                {"coid": coid, "body": "{}", "sent": False, "ts": ts},
                sort_keys=True,
                separators=(",", ":"),
            )
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
                (outbox,),
            )
            audit = json.dumps({"coid": coid, "ts": ts}, sort_keys=True, separators=(",", ":"))
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('needs_reconcile', ?)",
                (audit,),
            )
            if lookup_kind is not None:
                lookup = json.dumps({"coid": coid}, sort_keys=True, separators=(",", ":"))
                conn.execute(
                    "INSERT INTO ledger (kind, payload) VALUES (?, ?)",
                    (lookup_kind, lookup),
                )


def test_list_unresolved_orders_empty_without_ops_db(home: Path) -> None:
    from krellbot.application.operations import list_unresolved_orders

    assert list_unresolved_orders(home, now=1_700_000_000) == []


def test_list_unresolved_orders_projects_coid_age_and_lookup(home: Path) -> None:
    from krellbot.application.operations import list_unresolved_orders

    now = 1_700_000_500
    _seed_unresolved(home, now=now)
    rows = list_unresolved_orders(home, now=now)
    assert [r["client_order_id"] for r in rows] == ["coid-old", "coid-new"]
    assert rows[0]["age_seconds"] == 200
    assert rows[0]["last_lookup_result"] == "absent"
    assert rows[1]["age_seconds"] == 30
    assert rows[1]["last_lookup_result"] == "none"


def test_unresolved_orders_route_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _headers, body, _cookies = _get(
        app,
        "/api/v1/operations/unresolved-orders",
        headers=_origin(),
    )
    assert status == 403, body


def test_unresolved_orders_route_returns_closed_rows(home: Path) -> None:
    now = 1_700_000_500
    _seed_unresolved(home, now=now)
    app = _build_app(home)
    session = _session(app)
    status, headers, body, _cookies = _get(
        app,
        "/api/v1/operations/unresolved-orders",
        headers=session,
    )
    assert status == 200, body
    assert _header(headers, "Cache-Control") == "no-store"
    payload = json.loads(body.decode("utf-8"))
    assert payload["schema_version"] == "1"
    assert isinstance(payload["orders"], list)
    assert len(payload["orders"]) == 2
    first = payload["orders"][0]
    assert set(first) == {"client_order_id", "age_seconds", "last_lookup_result"}
    assert first["client_order_id"] == "coid-old"
    assert first["last_lookup_result"] == "absent"
    blob = body.decode("utf-8")
    for forbidden in ("starting_cash", "pack_path", "pack_sha256", "owned_qty", "cap", "stop"):
        assert forbidden not in blob, forbidden

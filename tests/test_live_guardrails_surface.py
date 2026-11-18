"""Live guardrails surface (M20.3).

Pins Deploy/Operations preflight rails before arm:

* paper-only rail when ``PAPER_ONLY_RELEASE`` is set
* kill switch
* grant expiry
* stop required / max account pct (when pack provided)
* ``live.guardrails`` journals refusals with closed reason codes
* GET ``/api/v1/operations/live-guardrails`` is read-only (no journal)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from krellbot.application import live_gate, live_guardrails
from krellbot.release_policy import CODE_PAPER_ONLY_RELEASE, PAPER_ONLY_RELEASE

TEST_PORT = 8080
VENUE = "kraken"
PAIR = "SUIUSD"


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
    query = b""
    if "?" in path:
        path_only, qs = path.split("?", 1)
        raw_path = path_only.encode("latin-1")
        query = qs.encode("latin-1")
        path = path_only
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": query,
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


def _build_app(home: Path, *, bootstrap_token: str = "boot-live-guardrails"):
    from krellbot.api.app import create_app

    return create_app(home=home, port=TEST_PORT, bootstrap_token=bootstrap_token)


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


def _bootstrap(app, token: str = "boot-live-guardrails") -> list[tuple[str, str]]:
    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, body
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    cookie = next(c for c in cookies if c.startswith("krellbot_session="))
    session_value = cookie.split(";", 1)[0].split("=", 1)[1]
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _read_journal(home: Path) -> list[dict]:
    journal_dir = home / "journal"
    if not journal_dir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(journal_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def test_paper_only_release_stays_true() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_snapshot_shows_active_rails_paper_only(home: Path) -> None:
    snap = live_guardrails.snapshot(home, venue=VENUE, now=1_700_000_000)
    body = snap.to_dict()
    rail_ids = [r["id"] for r in body["rails"]]
    assert rail_ids == [
        "paper_only_rail",
        "kill_switch",
        "grant_expiry",
        "stop_required",
        "max_account_pct",
    ]
    assert body["ok"] is False
    assert CODE_PAPER_ONLY_RELEASE in body["blocking_codes"]
    paper = next(r for r in body["rails"] if r["id"] == "paper_only_rail")
    assert paper["blocking"] is True
    assert paper["code"] == CODE_PAPER_ONLY_RELEASE
    grant = next(r for r in body["rails"] if r["id"] == "grant_expiry")
    assert grant["blocking"] is True
    assert grant["code"] == live_guardrails.CODE_LIVE_NOT_AUTHORIZED


def test_snapshot_kill_switch_and_grant_expiry(home: Path, live_capable_release) -> None:
    del live_capable_release
    now = 1_700_000_000
    live_gate.engage_kill(home, reason="surface-test", now=now)
    snap = live_guardrails.snapshot(home, venue=VENUE, now=now)
    kill = next(r for r in snap.rails if r.id == "kill_switch")
    assert kill.blocking is True
    assert kill.code == live_guardrails.CODE_KILL_SWITCH

    # Expired grant file → grant_expired rail.
    auth_path = live_gate.auth_path(home)
    auth_path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "granted_by": "operator",
                "expires_at": now - 10,
                "grants": [{"venue": VENUE, "pair": PAIR}],
            }
        ),
        encoding="utf-8",
    )
    snap2 = live_guardrails.snapshot(home, venue=VENUE, now=now)
    grant = next(r for r in snap2.rails if r.id == "grant_expiry")
    assert grant.blocking is True
    assert grant.code == live_guardrails.CODE_GRANT_EXPIRED
    assert grant.detail["expires_at"] == now - 10


def test_pack_stop_and_max_account_pct_rails(home: Path, live_capable_release) -> None:
    del live_capable_release
    now = 1_700_000_100
    # Clear kill; grant active.
    live_gate.release_kill(home)
    live_gate.auth_path(home).write_text(
        json.dumps(
            {
                "schema_version": "1",
                "granted_by": "operator",
                "expires_at": now + 3600,
                "grants": [{"venue": VENUE, "pair": PAIR}],
            }
        ),
        encoding="utf-8",
    )
    bad_pack = {
        "id": "no-stop",
        "markets": [{"venue": VENUE, "pair": PAIR}],
        "risk": {"max_account_pct": 0, "stop": {"type": "pct", "pct": 0}},
    }
    snap = live_guardrails.snapshot(home, venue=VENUE, pack_data=bad_pack, now=now)
    assert live_guardrails.CODE_STOP_REQUIRED in snap.blocking_codes
    assert live_guardrails.CODE_MAX_ACCOUNT_PCT in snap.blocking_codes
    assert snap.pair == PAIR


def test_evaluate_journals_refusals(home: Path) -> None:
    body = live_guardrails.evaluate(home, venue=VENUE, journal=True, now=1_700_000_200)
    assert body["ok"] is False
    assert CODE_PAPER_ONLY_RELEASE in body["journaled_codes"]
    records = _read_journal(home)
    assert records, "expected journaled refusal"
    codes = {
        r["detail"]["code"]
        for r in records
        if r.get("detail", {}).get("reason") == "live_refused"
        and r.get("detail", {}).get("source") == "live_guardrails"
    }
    assert CODE_PAPER_ONLY_RELEASE in codes


def test_get_live_guardrails_read_only_no_journal(home: Path) -> None:
    app = _build_app(home)
    headers = _bootstrap(app)
    status, _h, body, _c = _get(
        app,
        "/api/v1/operations/live-guardrails?venue=kraken",
        headers=headers,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["schema_version"] == "1"
    assert CODE_PAPER_ONLY_RELEASE in decoded["blocking_codes"]
    rail_ids = [r["id"] for r in decoded["rails"]]
    assert "paper_only_rail" in rail_ids
    assert "kill_switch" in rail_ids
    assert "grant_expiry" in rail_ids
    assert "stop_required" in rail_ids
    assert "max_account_pct" in rail_ids
    assert _read_journal(home) == []


def test_live_guardrails_command_journals(home: Path) -> None:
    app = _build_app(home)
    headers = _bootstrap(app)
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "live.guardrails",
            "payload": {"venue": VENUE, "journal": True},
        },
        headers=headers,
    )
    assert status == 200, body
    decoded = json.loads(body)
    assert decoded["ok"] is False
    assert CODE_PAPER_ONLY_RELEASE in decoded["journaled_codes"]
    records = _read_journal(home)
    assert any(
        r.get("detail", {}).get("code") == CODE_PAPER_ONLY_RELEASE
        and r.get("detail", {}).get("reason") == "live_refused"
        for r in records
    )


def test_live_arm_paper_only_journals_refusal(home: Path) -> None:
    app = _build_app(home)
    headers = _bootstrap(app)
    status, _h, body, _c = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "live.arm",
            "payload": {
                "venue": VENUE,
                "revision_id": "missing",
                "mode": "live",
                "confirmation": "LIVE",
            },
        },
        headers=headers,
    )
    assert status == 403, body
    decoded = json.loads(body)
    assert decoded["code"] == CODE_PAPER_ONLY_RELEASE
    records = _read_journal(home)
    assert any(
        r.get("detail", {}).get("code") == CODE_PAPER_ONLY_RELEASE
        and r.get("detail", {}).get("reason") == "live_refused"
        for r in records
    )

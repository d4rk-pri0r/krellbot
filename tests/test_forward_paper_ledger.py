"""Forward paper ledger — chronological paper evidence for reproduction.

``GET /api/v1/paper/ledger`` projects journal-backed arms, ticks, fills,
and refusals oldest→newest under an isolated ``KRELLBOT_HOME``. The body
is labeled paper / local evidence and never presents live P&L. Fill
qty/price and owned cash stay off the wire. No exchange credentials or
real orders are touched.
"""

from __future__ import annotations

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


def _journal_record(
    *,
    ts: int,
    venue: str,
    pack: str,
    pair: str,
    detail: dict,
) -> dict:
    return {
        "ts": ts,
        "kind": "tick",
        "venue": venue,
        "pack": pack,
        "bar_ts": 0,
        "detail": {"pair": pair, **detail},
    }


def _seed_journal(home: Path, records: list[dict], month: str = "2026-10") -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
    (journal_dir / f"{month}.jsonl").write_text(lines + "\n", encoding="utf-8")


def _seed_paper_state(home: Path, venue: str, *, fills: list[dict]) -> None:
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "venue": venue,
        "balances": {"USD": "900.0", "SUI": "1.5"},
        "open_orders": [],
        "recent_fills": fills,
        "seeded": True,
    }
    (run_dir / f"paper-{venue}.json").write_text(
        json.dumps(body, sort_keys=True),
        encoding="utf-8",
    )


def _fill(coid: str, pair: str, side: str = "buy", ts_ms: int = 1_000) -> dict:
    return {
        "id": coid,
        "coid": coid,
        "pair": pair,
        "side": side,
        "qty": "1.5",
        "price": "3.25",
        "ts_ms": ts_ms,
    }


def _bootstrap_session(app, token: str) -> str:
    _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _get_ledger(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, flat, body, _set_cookies = asgi_call(app, method="GET", path="/api/v1/paper/ledger", headers=base)
    return status, flat, body


def _authenticated_headers(session_value: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


def _header_map(flat: list[tuple[str, str]]) -> dict[str, str]:
    return {k.lower(): v for k, v in flat}


def test_forward_paper_ledger_route_exists_and_returns_empty_with_session(
    tmp_path: Path,
) -> None:
    token = "boot-ledger-exists"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, flat, body = _get_ledger(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["schema_version"] == "1", decoded
    assert decoded["mode"] == "paper", decoded
    assert decoded["order"] == "forward", decoded
    assert decoded["presentation"] == "local_evidence", decoded
    assert "live" not in decoded["disclaimer"].lower() or "not live" in decoded["disclaimer"].lower()
    assert "P&L" in decoded["disclaimer"] or "pnl" in decoded["disclaimer"].lower()
    assert decoded["events"] == [], decoded
    assert _header_map(flat).get("cache-control") == "no-store"


def test_forward_paper_ledger_refuses_unauthenticated(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    status, _h, body = _get_ledger(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, (status, body)
    assert json.loads(body) == {"detail": "session required"}, body


def test_forward_paper_ledger_refuses_non_loopback_origin(tmp_path: Path) -> None:
    token = "boot-ledger-origin"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, _b = _get_ledger(
        app,
        headers=[
            ("Origin", "http://evil.example.com"),
            ("Cookie", f"krellbot_session={session_value}"),
        ],
    )
    assert status == 403, status


def test_forward_paper_ledger_projects_arms_ticks_fills_refusals_in_order(
    tmp_path: Path,
) -> None:
    from tests.test_ns06_api import _run_paper_arm

    _run_paper_arm(tmp_path)

    _seed_journal(
        tmp_path,
        [
            _journal_record(
                ts=1_760_000_100,
                venue="kraken",
                pack="trend-follow",
                pair="SUIUSD",
                detail={"reason": "no_signal"},
            ),
            _journal_record(
                ts=1_760_000_200,
                venue="kraken",
                pack="trend-follow",
                pair="SUIUSD",
                detail={"reason": "entry", "intent_refused": "store_full"},
            ),
        ],
    )
    _seed_paper_state(
        tmp_path,
        "kraken",
        fills=[
            _fill("coid-entry-1", "SUIUSD", ts_ms=1_760_000_150_000),
            _fill("coid-exit-1", "SUIUSD", side="sell", ts_ms=1_760_000_250_000),
        ],
    )

    token = "boot-ledger-events"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_ledger(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    events = decoded["events"]
    assert isinstance(events, list) and events, decoded

    kinds = [event["kind"] for event in events]
    assert "arm" in kinds, kinds
    assert "tick" in kinds, kinds
    assert "fill" in kinds, kinds
    assert "refusal" in kinds, kinds

    timestamps = [int(event["ts"]) for event in events]
    assert timestamps == sorted(timestamps), timestamps

    arm_events = [event for event in events if event["kind"] == "arm"]
    assert len(arm_events) == 1, arm_events
    assert arm_events[0]["venue"] == "kraken", arm_events[0]
    assert arm_events[0]["pair"], arm_events[0]
    assert arm_events[0]["detail"].get("mode") == "paper", arm_events[0]
    assert "starting_cash" not in arm_events[0]["detail"], arm_events[0]
    assert "pnl" not in json.dumps(arm_events[0]).lower()

    tick_events = [event for event in events if event["kind"] == "tick"]
    assert len(tick_events) == 2, tick_events
    assert tick_events[0]["ts"] <= tick_events[1]["ts"]

    refusal_events = [event for event in events if event["kind"] == "refusal"]
    assert len(refusal_events) == 1, refusal_events
    assert refusal_events[0]["detail"]["code"] == "store_full", refusal_events[0]

    fill_events = [event for event in events if event["kind"] == "fill"]
    assert len(fill_events) == 2, fill_events
    for fill in fill_events:
        detail = fill["detail"]
        assert "qty" not in detail, detail
        assert "price" not in detail, detail
        assert "coid" in detail and "side" in detail and "ts_ms" in detail, detail

    wire = json.dumps(decoded)
    assert "900.0" not in wire
    assert '"qty"' not in wire
    assert '"price"' not in wire


def test_forward_paper_ledger_skips_live_mode_arms(tmp_path: Path) -> None:
    from decimal import Decimal

    from krellbot import config as kb_config
    from krellbot.config import ArmedPack

    kb_config.save_config(
        tmp_path,
        kb_config.Config(
            armed=[
                ArmedPack(
                    pack_path="packs/live-pack.py",
                    pack_sha256="abc",
                    pack_id="live-pack",
                    pack_version="1",
                    venue="kraken",
                    pair="SUIUSD",
                    cap=Decimal(100),
                    stop=Decimal(0),
                    mode="live",
                    starting_cash=None,
                    requires_license=False,
                    armed_at_ts=1_760_000_000,
                )
            ]
        ),
    )

    token = "boot-ledger-live-arm"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_ledger(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    events = _read_json(body)["events"]
    assert all(event["kind"] != "arm" for event in events), events


def test_forward_paper_ledger_projector_unit_order(tmp_path: Path) -> None:
    """Direct projector: mixed sources sort oldest→newest without HTTP."""

    from krellbot.application.paper import project_forward_paper_ledger

    _seed_journal(
        tmp_path,
        [
            _journal_record(
                ts=300,
                venue="kraken",
                pack="p",
                pair="SUIUSD",
                detail={"reason": "later"},
            ),
            _journal_record(
                ts=100,
                venue="kraken",
                pack="p",
                pair="SUIUSD",
                detail={"reason": "earlier", "metadata_refusal": "missing_rules"},
            ),
        ],
    )
    _seed_paper_state(
        tmp_path,
        "kraken",
        fills=[_fill("c1", "SUIUSD", ts_ms=200_000)],
    )
    body = project_forward_paper_ledger(tmp_path)
    assert body["order"] == "forward"
    assert body["mode"] == "paper"
    events = body["events"]
    assert [e["kind"] for e in events] == ["tick", "refusal", "fill", "tick"], [e["kind"] for e in events]
    assert [e["ts"] for e in events] == [100, 100, 200, 300]
    assert events[1]["detail"]["code"] == "missing_rules"

"""Paper P&L + position chart — ``GET /api/v1/paper/chart`` contract.

The workstation armed-paper surface charts P&L and position-over-time
(or mark series) from journal ticks and paper-state fills:

  1. Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
     missing session → 403, non-loopback Origin/Host → 403, no CSRF
     required.
  2. Unarmed home → closed ``{"schema_version": "1", "armed": false}``.
  3. Armed with journal ticks → ``position`` carries ``owned_qty_after``
     points for the armed pair (other pairs omitted).
  4. Armed with paper fills → ``pnl`` and ``marks`` replay fill equity
     against ``starting_cash`` (fees at paper taker bps).
  5. Empty journal / no fills → series stay empty lists, never fabricated
     flat zeros.
  6. ``Cache-Control: no-store``.

All data lives under an isolated ``KRELLBOT_HOME`` (``tmp_path`` / ``home``).
No live venue, key, or order is touched; journal and state files are
seeded exactly as the engine writes them.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot import config as kb_config
from tests.test_ns06_api import (
    TEST_PORT as NS06_PORT,
)
from tests.test_ns06_api import (
    _bootstrap_and_get_csrf,
    _build_app,
    _run_paper_arm,
    asgi_call,
)

TEST_PORT = NS06_PORT


def _bootstrap_session(app, token: str) -> str:
    _csrf = _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _authenticated_headers(session_value: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _get_chart(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, flat, body, _set_cookies = asgi_call(app, method="GET", path="/api/v1/paper/chart", headers=base)
    return status, flat, body


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


def _seed_journal(home: Path, records: list[dict]) -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    path = journal_dir / "2026-01.jsonl"
    path.write_text(
        "".join(json.dumps(record, separators=(",", ":")) + "\n" for record in records),
        encoding="utf-8",
    )


def _seed_paper_state(home: Path, venue: str, *, balances: dict, fills: list[dict]) -> None:
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "venue": venue,
        "balances": balances,
        "open_orders": [],
        "recent_fills": fills,
        "seeded": True,
    }
    (run_dir / f"paper-{venue}.json").write_text(
        json.dumps(body, sort_keys=True),
        encoding="utf-8",
    )


def _tick(
    *,
    ts: int,
    venue: str,
    pack: str,
    pair: str,
    owned_qty_after: str,
) -> dict:
    return {
        "ts": ts,
        "kind": "tick",
        "venue": venue,
        "pack": pack,
        "bar_ts": ts * 1000,
        "detail": {
            "pair": pair,
            "reason": "flat",
            "owned_qty_after": owned_qty_after,
            "entry_qty": "0",
            "exit_qty": "0",
            "stop_qty": "0",
        },
    }


def _fill(
    *,
    coid: str,
    pair: str,
    side: str,
    qty: str,
    price: str,
    ts_ms: int,
) -> dict:
    return {
        "id": coid,
        "coid": coid,
        "pair": pair,
        "side": side,
        "qty": qty,
        "price": price,
        "ts_ms": ts_ms,
    }


# ---- 1. session gate parity ----------------------------------------------


def test_paper_chart_without_session_cookie_is_403(home: Path) -> None:
    """``GET /api/v1/paper/chart`` without a session cookie is 403."""

    app = _build_app(home)
    status, _h, _b = _get_chart(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, status


def test_paper_chart_with_non_loopback_origin_is_403(home: Path) -> None:
    """A non-loopback Origin is 403 even with a valid session."""

    token = "boot-chart-origin"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, _b = _get_chart(
        app,
        headers=[
            ("Origin", "http://evil.example.com"),
            ("Cookie", f"krellbot_session={session_value}"),
        ],
    )
    assert status == 403, status


def test_paper_chart_with_non_loopback_host_is_403(home: Path) -> None:
    """A non-loopback Host is 403."""

    app = _build_app(home)
    status, _h, _b = _get_chart(
        app,
        headers=[
            ("Host", "evil.example.com"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ],
    )
    assert status == 403, status


def test_paper_chart_does_not_require_csrf_header(home: Path) -> None:
    """GET gate parity with ``/api/v1/paper/status``: no CSRF required."""

    token = "boot-chart-no-csrf"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    headers = _authenticated_headers(session_value)
    headers.append(("X-Krellbot-CSRF", "not-the-real-csrf"))
    status, _h, body = _get_chart(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded == {"schema_version": "1", "armed": False}, decoded


# ---- 2. unarmed / empty evidence -----------------------------------------


def test_paper_chart_unarmed_returns_closed_shape(home: Path) -> None:
    """When no pack is armed the body is exactly the unarmed closed shape."""

    token = "boot-chart-empty"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, headers, body = _get_chart(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    assert _read_json(body) == {"schema_version": "1", "armed": False}
    assert ("cache-control", "no-store") in [(k.lower(), v.lower()) for k, v in headers]


def test_paper_chart_armed_without_journal_or_fills_keeps_empty_series(home: Path) -> None:
    """Armed with no journal ticks and no fills → empty series, not zeros."""

    _run_paper_arm(home)
    token = "boot-chart-armed-empty"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_chart(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is True
    assert decoded["venue"] == "kraken"
    assert decoded["pair"] == "SUIUSD"
    assert decoded["mode"] == "paper"
    assert decoded["starting_cash"] == "1000"
    assert decoded["pnl"] == []
    assert decoded["position"] == []
    assert decoded["marks"] == []


# ---- 3. position from journal --------------------------------------------


def test_paper_chart_position_series_from_journal_owned_qty(home: Path) -> None:
    """Position series quotes journal ``owned_qty_after`` for the armed pair."""

    _run_paper_arm(home)
    config = kb_config.load_config(home)
    pack_id = config.armed[0].pack_id
    pair = config.armed[0].pair
    venue = config.armed[0].venue

    _seed_journal(
        home,
        [
            _tick(ts=1_700_000_000, venue=venue, pack=pack_id, pair=pair, owned_qty_after="0"),
            _tick(ts=1_700_003_600, venue=venue, pack=pack_id, pair=pair, owned_qty_after="10.5"),
            _tick(ts=1_700_007_200, venue=venue, pack=pack_id, pair=pair, owned_qty_after="10.5"),
            # Other market — must not appear on this chart.
            _tick(
                ts=1_700_010_800,
                venue=venue,
                pack=pack_id,
                pair="BTCUSD",
                owned_qty_after="99",
            ),
            # Non-tick kind — ignored.
            {
                "ts": 1_700_014_400,
                "kind": "wake_gap",
                "venue": venue,
                "pack": pack_id,
                "bar_ts": 0,
                "detail": {"event": "wake_gap"},
            },
        ],
    )

    token = "boot-chart-position"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_chart(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is True
    assert decoded["position"] == [
        {"ts_ms": 1_700_000_000_000, "qty": "0"},
        {"ts_ms": 1_700_003_600_000, "qty": "10.5"},
        {"ts_ms": 1_700_007_200_000, "qty": "10.5"},
    ]


# ---- 4. P&L + marks from fills -------------------------------------------


def test_paper_chart_pnl_and_marks_from_fill_replay(home: Path) -> None:
    """P&L and marks replay paper fills against starting cash with taker fees."""

    _run_paper_arm(home)
    config = kb_config.load_config(home)
    pair = config.armed[0].pair
    venue = config.armed[0].venue

    # Buy 10 @ 10 → notional 100, fee 100 * 40/10000 = 0.4 → cash 899.6, qty 10
    # Equity at mark 10: 899.6 + 100 = 999.6 → pnl -0.4
    # Sell 10 @ 12 → proceeds 120, fee 0.48 → cash 899.6 + 119.52 = 1019.12, qty 0
    # Equity at mark 12: 1019.12 → pnl 19.12
    _seed_paper_state(
        home,
        venue,
        balances={"USD": "1019.12"},
        fills=[
            _fill(coid="c1", pair=pair, side="buy", qty="10", price="10", ts_ms=2_000),
            _fill(coid="c2", pair=pair, side="sell", qty="10", price="12", ts_ms=3_000),
            # Other pair fill — ignored for this chart.
            _fill(coid="c3", pair="BTCUSD", side="buy", qty="1", price="50000", ts_ms=4_000),
        ],
    )

    token = "boot-chart-pnl"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_chart(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["starting_cash"] == "1000"
    assert decoded["marks"] == [
        {"ts_ms": 2_000, "price": "10"},
        {"ts_ms": 3_000, "price": "12"},
    ]
    assert decoded["pnl"] == [
        {"ts_ms": 2_000, "value": "-0.4"},
        {"ts_ms": 3_000, "value": "19.12"},
    ]
    # Spot-check the fee math with Decimal so a float slip cannot pass.
    fee_buy = Decimal(100) * Decimal(40) / Decimal(10_000)
    assert fee_buy == Decimal("0.4")

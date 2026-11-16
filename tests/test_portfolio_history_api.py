"""Portfolio history API — ``GET /api/v1/portfolio/history`` contract.

Cross-deployment portfolio history from journal ticks and paper fills:

  1. Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
     missing session → 403, non-loopback Origin/Host → 403, no CSRF
     required.
  2. Empty home → ``equity`` and ``deployments`` are empty lists.
  3. One armed market with fills → deployment card carries pair-scoped
     ``pnl`` / ``last_pnl`` and ``equity`` replays venue fills against
     ``starting_cash``.
  4. Two armed markets → both deployments appear; combined equity sums
     venue wallets (or a single venue with multi-pair fills).
  5. Journal-only closed run without armed ``starting_cash`` → deployment
     listed, ``pnl`` stays empty (never fabricated).
  6. ``Cache-Control: no-store``.

All data lives under an isolated ``KRELLBOT_HOME`` (``tmp_path`` / ``home``).
No live venue, key, order, or telemetry call is touched.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot import config as kb_config
from krellbot.application.paper import PaperService
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


def _get_portfolio(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, flat, body, _set_cookies = asgi_call(
        app,
        method="GET",
        path="/api/v1/portfolio/history",
        headers=base,
    )
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
    owned_qty_after: str = "0",
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


def _write_pack(home: Path, *, pack_id: str, venue: str, pair: str) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": pack_id,
        "author": "portfolio history tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": venue, "pair": pair}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm(home: Path, pack_path: Path, *, venue: str, pair: str, balance: str = "1000") -> None:
    result = PaperService(home=home).arm(
        pack_path,
        venue=venue,
        mode="paper",
        paper_balance=Decimal(balance),
        correlation_id=f"seed-portfolio-{pair}",
    )
    assert result.ok, result.message


# ---- 1. session gate ------------------------------------------------------


def test_portfolio_history_without_session_cookie_is_403(home: Path) -> None:
    """``GET /api/v1/portfolio/history`` without a session cookie is 403."""

    app = _build_app(home)
    status, _h, _b = _get_portfolio(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, status


def test_portfolio_history_with_non_loopback_origin_is_403(home: Path) -> None:
    """A non-loopback Origin is 403 even with a valid session."""

    token = "boot-portfolio-origin"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, _b = _get_portfolio(
        app,
        headers=[
            ("Origin", "http://evil.example.com"),
            ("Cookie", f"krellbot_session={session_value}"),
        ],
    )
    assert status == 403, status


def test_portfolio_history_with_non_loopback_host_is_403(home: Path) -> None:
    """A non-loopback Host is 403."""

    app = _build_app(home)
    status, _h, _b = _get_portfolio(
        app,
        headers=[
            ("Host", "evil.example.com"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ],
    )
    assert status == 403, status


def test_portfolio_history_does_not_require_csrf_header(home: Path) -> None:
    """GET gate parity with paper reads: no CSRF required."""

    token = "boot-portfolio-no-csrf"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    headers = _authenticated_headers(session_value)
    headers.append(("X-Krellbot-CSRF", "not-the-real-csrf"))
    status, headers_out, body = _get_portfolio(app, headers=headers)
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded == {"schema_version": "1", "equity": [], "deployments": []}
    assert ("cache-control", "no-store") in [(k.lower(), v.lower()) for k, v in headers_out]


# ---- 2. empty / single / multi -------------------------------------------


def test_portfolio_history_empty_home_returns_empty_series(home: Path) -> None:
    """No journal and no armed packs → empty equity and deployments."""

    token = "boot-portfolio-empty"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_portfolio(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    assert _read_json(body) == {
        "schema_version": "1",
        "equity": [],
        "deployments": [],
    }


def test_portfolio_history_armed_with_fills_reports_equity_and_pnl(home: Path) -> None:
    """Armed market with fills → deployment pnl + absolute equity series."""

    _run_paper_arm(home)
    config = kb_config.load_config(home)
    pack_id = config.armed[0].pack_id
    pair = config.armed[0].pair
    venue = config.armed[0].venue

    _seed_journal(
        home,
        [
            _tick(ts=1_700_000_000, venue=venue, pack=pack_id, pair=pair),
            _tick(ts=1_700_003_600, venue=venue, pack=pack_id, pair=pair, owned_qty_after="10"),
        ],
    )
    # Buy 10 @ 10 → fee 0.4 → equity 999.6; sell 10 @ 12 → equity 1019.12
    _seed_paper_state(
        home,
        venue,
        balances={"USD": "1019.12"},
        fills=[
            _fill(coid="c1", pair=pair, side="buy", qty="10", price="10", ts_ms=2_000),
            _fill(coid="c2", pair=pair, side="sell", qty="10", price="12", ts_ms=3_000),
        ],
    )

    token = "boot-portfolio-fills"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_portfolio(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)

    assert decoded["schema_version"] == "1"
    assert decoded["equity"] == [
        {"ts_ms": 2_000, "value": "999.6"},
        {"ts_ms": 3_000, "value": "1019.12"},
    ]
    assert len(decoded["deployments"]) == 1
    dep = decoded["deployments"][0]
    assert dep["venue"] == venue
    assert dep["pair"] == pair
    assert dep["pack_id"] == pack_id
    assert dep["status"] == "active"
    assert dep["starting_cash"] == "1000"
    assert dep["fills_total"] == 2
    assert dep["pnl"] == [
        {"ts_ms": 2_000, "value": "-0.4"},
        {"ts_ms": 3_000, "value": "19.12"},
    ]
    assert dep["last_pnl"] == "19.12"
    fee_buy = Decimal(100) * Decimal(40) / Decimal(10_000)
    assert fee_buy == Decimal("0.4")


def test_portfolio_history_lists_every_armed_deployment(home: Path) -> None:
    """Two armed markets appear as two deployment cards (cross-deployment)."""

    first = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    _arm(home, first, venue="kraken", pair="SUIUSD", balance="1000")
    second = _write_pack(home, pack_id="mean-revert", venue="coinbase", pair="BTC-USD")
    _arm(home, second, venue="coinbase", pair="BTC-USD", balance="2000")

    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "999.6"},
        fills=[_fill(coid="k1", pair="SUIUSD", side="buy", qty="10", price="10", ts_ms=5_000)],
    )
    _seed_paper_state(
        home,
        "coinbase",
        balances={"USD": "1997.6"},
        fills=[
            _fill(coid="c1", pair="BTC-USD", side="buy", qty="0.01", price="200", ts_ms=6_000),
        ],
    )

    token = "boot-portfolio-multi"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_portfolio(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)

    assert len(decoded["deployments"]) == 2
    by_pair = {row["pair"]: row for row in decoded["deployments"]}
    assert set(by_pair) == {"SUIUSD", "BTC-USD"}
    assert by_pair["SUIUSD"]["status"] == "active"
    assert by_pair["BTC-USD"]["status"] == "active"
    assert by_pair["SUIUSD"]["starting_cash"] == "1000"
    assert by_pair["BTC-USD"]["starting_cash"] == "2000"
    assert by_pair["SUIUSD"]["last_pnl"] == "-0.4"
    # Coinbase taker 120 bps: notional 2, fee 0.024 → equity 1999.976 → pnl -0.024
    assert by_pair["BTC-USD"]["last_pnl"] == "-0.024"

    # Combined equity merges both venues by timestamp (carry-forward sum).
    assert decoded["equity"] == [
        {"ts_ms": 5_000, "value": "999.6"},
        {"ts_ms": 6_000, "value": "2999.576"},
    ]


def test_portfolio_history_closed_journal_run_omits_fabricated_pnl(home: Path) -> None:
    """A journalled closed run without armed starting_cash lists without pnl."""

    _seed_journal(
        home,
        [
            _tick(ts=1_700_000_000, venue="kraken", pack="retired-pack", pair="SUIUSD"),
            _tick(ts=1_700_003_600, venue="kraken", pack="retired-pack", pair="SUIUSD"),
        ],
    )
    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "1000"},
        fills=[_fill(coid="old", pair="SUIUSD", side="buy", qty="1", price="10", ts_ms=9_000)],
    )

    token = "boot-portfolio-closed"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_portfolio(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)

    assert decoded["equity"] == []
    assert len(decoded["deployments"]) == 1
    dep = decoded["deployments"][0]
    assert dep["pack_id"] == "retired-pack"
    assert dep["status"] == "closed"
    assert dep["starting_cash"] is None
    assert dep["pnl"] == []
    assert dep["last_pnl"] is None
    assert dep["fills_total"] == 1

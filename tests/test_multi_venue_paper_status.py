"""Multi-venue paper status honesty — Binance BTCUSDT beside peer venues.

M14.6: status/fleet/position/history/portfolio APIs do not assume a single
venue. Armed paper on ``binance`` / ``BTCUSDT`` shows cash and position
without inventing fills; just-armed history stays empty while fleet says
``no tick yet`` (Deployments vs history coherent with M2.9 / M9.1).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.application.paper import _PAPER_TAKER_BPS, PaperService
from krellbot.data.instruments import PAPER_WAVE_BINANCE_BTC_USDT
from tests.test_ns06_api import (
    TEST_PORT as NS06_PORT,
)
from tests.test_ns06_api import (
    _bootstrap_and_get_csrf,
    _build_app,
    asgi_call,
)

TEST_PORT = NS06_PORT
PAPER_WAVE_KRAKEN = "SUIUSD"


def _write_pack(home: Path, *, pack_id: str, venue: str, pair: str) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": pack_id,
        "author": "krellbot multi-venue paper status tests",
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


def _arm(home: Path, pack_path: Path, *, venue: str, paper_balance: Decimal) -> None:
    result = PaperService(home=home).arm(
        pack_path,
        venue=venue,
        mode="paper",
        paper_balance=paper_balance,
        correlation_id=f"seed-multi-venue-{venue}",
    )
    assert result.ok, (result.code, result.message)


def _bootstrap_session(app, token: str) -> str:
    _csrf = _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _authenticated_headers(session_value: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _get(app, path: str, *, headers: list[tuple[str, str]]) -> tuple[int, dict]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}"), *headers]
    status, _flat, body, _cookies = asgi_call(app, method="GET", path=path, headers=base)
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return status, decoded


def _seed_paper_state(home: Path, venue: str, *, balances: dict, fills: list | None = None) -> None:
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "venue": venue,
        "balances": balances,
        "open_orders": [],
        "recent_fills": list(fills or []),
        "seeded": True,
    }
    (run_dir / f"paper-{venue}.json").write_text(json.dumps(body, sort_keys=True), encoding="utf-8")


def test_binance_paper_taker_bps_match_venue() -> None:
    """Chart/portfolio fee replay uses Binance paper taker 10 bps, not Kraken 40."""
    assert _PAPER_TAKER_BPS["binance"] == 10
    assert _PAPER_TAKER_BPS["kraken"] == 40
    assert _PAPER_TAKER_BPS["coinbase"] == 120


def test_binance_just_armed_position_shows_starting_cash_not_zero(home: Path) -> None:
    """Just-armed binance/BTCUSDT with no state file: free cash is the deposit."""
    pack = _write_pack(
        home,
        pack_id="binance-btc-wave",
        venue="binance",
        pair=PAPER_WAVE_BINANCE_BTC_USDT,
    )
    _arm(home, pack, venue="binance", paper_balance=Decimal(2500))
    assert not (home / "run" / "paper-binance.json").exists()

    token = f"boot-bn-just-armed-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    headers = _authenticated_headers(_bootstrap_session(app, token))

    status_code, position = _get(
        app,
        f"/api/v1/paper/position?venue=binance&pair={PAPER_WAVE_BINANCE_BTC_USDT}",
        headers=headers,
    )
    assert status_code == 200, position
    assert position["armed"] is True, position
    assert position["venue"] == "binance", position
    assert position["pair"] == PAPER_WAVE_BINANCE_BTC_USDT, position
    assert position["free_cash"] == "2500", position
    assert position["holdings"] == [], position
    assert position["as_of_run"] is None, position


def test_binance_position_reads_usdt_quote_not_usd(home: Path) -> None:
    """Persisted paper-binance.json cash is the USDT balance, never USD decoy."""
    pack = _write_pack(
        home,
        pack_id="binance-btc-usdt",
        venue="binance",
        pair=PAPER_WAVE_BINANCE_BTC_USDT,
    )
    _arm(home, pack, venue="binance", paper_balance=Decimal(1000))
    _seed_paper_state(
        home,
        "binance",
        balances={"USDT": "900.0", "BTC": "0.01", "USD": "999"},
    )

    token = f"boot-bn-usdt-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    headers = _authenticated_headers(_bootstrap_session(app, token))

    status_code, position = _get(
        app,
        f"/api/v1/paper/position?venue=binance&pair={PAPER_WAVE_BINANCE_BTC_USDT}",
        headers=headers,
    )
    assert status_code == 200, position
    assert position["free_cash"] == "900.0", position
    assert position["holdings"] == [{"symbol": "BTC", "qty": "0.01"}], position


def test_status_and_fleet_list_binance_beside_kraken(home: Path) -> None:
    """Fleet and armed list show binance and kraken as distinct deployments."""
    kraken_pack = _write_pack(home, pack_id="kraken-sui", venue="kraken", pair=PAPER_WAVE_KRAKEN)
    _arm(home, kraken_pack, venue="kraken", paper_balance=Decimal(1000))
    binance_pack = _write_pack(
        home,
        pack_id="binance-btc",
        venue="binance",
        pair=PAPER_WAVE_BINANCE_BTC_USDT,
    )
    _arm(home, binance_pack, venue="binance", paper_balance=Decimal(2000))

    token = f"boot-bn-fleet-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    headers = _authenticated_headers(_bootstrap_session(app, token))

    status_code, status = _get(
        app,
        f"/api/v1/paper/status?venue=binance&pair={PAPER_WAVE_BINANCE_BTC_USDT}",
        headers=headers,
    )
    assert status_code == 200, status
    assert status["armed"] is True, status
    assert status["venue"] == "binance", status
    assert status["pair"] == PAPER_WAVE_BINANCE_BTC_USDT, status
    assert status["armed_count"] == 2, status
    assert "free_cash" not in status, status

    status_code, armed = _get(app, "/api/v1/paper/armed", headers=headers)
    assert status_code == 200, armed
    venues = {(row["venue"], row["pair"]) for row in armed.get("records") or []}
    assert ("binance", PAPER_WAVE_BINANCE_BTC_USDT) in venues, venues
    assert ("kraken", PAPER_WAVE_KRAKEN) in venues, venues

    status_code, fleet = _get(app, "/api/v1/paper/fleet", headers=headers)
    assert status_code == 200, fleet
    assert fleet["armed"] is True, fleet
    assert fleet["armed_count"] == 2, fleet
    fleet_keys = {(row["venue"], row["pair"]) for row in fleet.get("deployments") or []}
    assert ("binance", PAPER_WAVE_BINANCE_BTC_USDT) in fleet_keys, fleet_keys
    assert ("kraken", PAPER_WAVE_KRAKEN) in fleet_keys, fleet_keys
    groups = {(g["venue"], g["pair"]) for g in fleet.get("groups") or []}
    assert ("binance", PAPER_WAVE_BINANCE_BTC_USDT) in groups, groups


def test_binance_just_armed_history_empty_fleet_says_no_tick(home: Path) -> None:
    """Just-armed binance: history empty; fleet last_tick_result is no tick yet."""
    pack = _write_pack(
        home,
        pack_id="binance-history",
        venue="binance",
        pair=PAPER_WAVE_BINANCE_BTC_USDT,
    )
    _arm(home, pack, venue="binance", paper_balance=Decimal(1000))

    token = f"boot-bn-history-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    headers = _authenticated_headers(_bootstrap_session(app, token))

    status_code, history = _get(app, "/api/v1/paper/history", headers=headers)
    assert status_code == 200, history
    assert history.get("runs") == [], history

    status_code, fleet = _get(app, "/api/v1/paper/fleet", headers=headers)
    assert status_code == 200, fleet
    rows = fleet.get("deployments") or []
    assert len(rows) == 1, rows
    assert rows[0]["venue"] == "binance"
    assert rows[0]["pair"] == PAPER_WAVE_BINANCE_BTC_USDT
    assert rows[0]["last_tick_ts_ms"] is None, rows[0]
    assert rows[0]["last_tick_result"] == "no tick yet", rows[0]
    assert "cash" not in rows[0] and "free_cash" not in rows[0], rows[0]


def test_portfolio_lists_binance_armed_without_inventing_fills(home: Path) -> None:
    """Portfolio history lists armed binance with empty pnl until fills exist."""
    pack = _write_pack(
        home,
        pack_id="binance-portfolio",
        venue="binance",
        pair=PAPER_WAVE_BINANCE_BTC_USDT,
    )
    _arm(home, pack, venue="binance", paper_balance=Decimal(1500))

    token = f"boot-bn-portfolio-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    headers = _authenticated_headers(_bootstrap_session(app, token))

    status_code, body = _get(app, "/api/v1/portfolio/history", headers=headers)
    assert status_code == 200, body
    deployments = body.get("deployments") or []
    assert len(deployments) == 1, deployments
    dep = deployments[0]
    assert dep["venue"] == "binance", dep
    assert dep["pair"] == PAPER_WAVE_BINANCE_BTC_USDT, dep
    assert dep["starting_cash"] == "1500", dep
    assert dep["pnl"] == [], dep
    assert dep.get("last_pnl") is None, dep
    assert body.get("equity") == [], body


def test_portfolio_binance_fill_fee_uses_ten_bps(home: Path) -> None:
    """One Binance fill replays at 10 bps (not the Kraken 40 fallback)."""
    pack = _write_pack(
        home,
        pack_id="binance-fee",
        venue="binance",
        pair=PAPER_WAVE_BINANCE_BTC_USDT,
    )
    _arm(home, pack, venue="binance", paper_balance=Decimal(1000))
    # Buy 0.01 @ 100 → notional 1; fee 10 bps = 0.001 → cash 998.999, pnl -0.001
    _seed_paper_state(
        home,
        "binance",
        balances={"USDT": "998.999", "BTC": "0.01"},
        fills=[
            {
                "coid": "bn-1",
                "pair": PAPER_WAVE_BINANCE_BTC_USDT,
                "side": "buy",
                "qty": "0.01",
                "price": "100",
                "ts_ms": 7_000,
            }
        ],
    )

    token = f"boot-bn-fee-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    headers = _authenticated_headers(_bootstrap_session(app, token))

    status_code, body = _get(app, "/api/v1/portfolio/history", headers=headers)
    assert status_code == 200, body
    dep = (body.get("deployments") or [None])[0]
    assert dep is not None, body
    assert dep["last_pnl"] == "-0.001", dep

"""Paper status honesty after arm — free cash, multi-deploy, just-armed.

Pins M2.9 behaviours by name:

  1. ``test_paper_position_just_armed_shows_starting_cash_not_zero`` —
     after arm with a paper balance and before any tick/state file, free
     cash is the configured deposit, never a false ``\"0\"``.
  2. ``test_paper_status_reports_armed_count_for_multi_deploy`` —
     status is not silently limited to ``config.armed[0]``: the body
     always carries ``armed_count``, and ``?venue=&pair=`` selects a
     specific armed record.
  3. ``test_paper_position_persisted_zero_cash_stays_zero`` —
     an explicit persisted quote balance of ``\"0\"`` stays ``\"0\"``
     (starting_cash is not re-applied over a real emptied wallet).

All data lives under an isolated ``KRELLBOT_HOME`` (``tmp_path``). No
live venue, key, or order is touched.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.application.paper import PaperService
from tests.test_ns06_api import (
    TEST_PORT as NS06_PORT,
)
from tests.test_ns06_api import (
    _bootstrap_and_get_csrf,
    _build_app,
    asgi_call,
)

TEST_PORT = NS06_PORT


def _write_pack(home: Path, *, pack_id: str, venue: str, pair: str) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": pack_id,
        "author": "krellbot paper status armed cash tests",
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
        correlation_id="seed-armed-cash",
    )
    assert result.ok, result.message


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


def _seed_paper_state(home: Path, venue: str, *, balances: dict) -> None:
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "venue": venue,
        "balances": balances,
        "open_orders": [],
        "recent_fills": [],
        "seeded": True,
    }
    (run_dir / f"paper-{venue}.json").write_text(
        json.dumps(body, sort_keys=True),
        encoding="utf-8",
    )


def test_paper_position_just_armed_shows_starting_cash_not_zero(home: Path) -> None:
    """Just-armed with paper balance 2500 and no state file: free cash is 2500."""

    pack = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    _arm(home, pack, venue="kraken", paper_balance=Decimal(2500))
    assert not (home / "run" / "paper-kraken.json").exists()

    token = f"boot-armed-cash-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap_session(app, token)
    headers = _authenticated_headers(session)

    status_code, position = _get(app, "/api/v1/paper/position", headers=headers)
    assert status_code == 200, position
    assert position["armed"] is True, position
    assert position["free_cash"] == "2500", position
    assert position["holdings"] == [], position
    assert position["as_of_run"] is None, position
    assert "armed_count" not in position, position


def test_paper_status_reports_armed_count_for_multi_deploy(home: Path) -> None:
    """Two armed packs: status carries armed_count and can select either."""

    first = _write_pack(home, pack_id="sui-pack", venue="kraken", pair="SUIUSD")
    _arm(home, first, venue="kraken", paper_balance=Decimal(1000))
    second = _write_pack(home, pack_id="eth-pack", venue="kraken", pair="ETHUSD")
    _arm(home, second, venue="kraken", paper_balance=Decimal(2000))

    token = f"boot-multi-deploy-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap_session(app, token)
    headers = _authenticated_headers(session)

    status_code, default_status = _get(app, "/api/v1/paper/status", headers=headers)
    assert status_code == 200, default_status
    assert default_status["armed"] is True, default_status
    assert default_status["armed_count"] == 2, default_status
    assert default_status["pair"] == "SUIUSD", default_status

    status_code, eth_status = _get(
        app,
        "/api/v1/paper/status?venue=kraken&pair=ETHUSD",
        headers=headers,
    )
    assert status_code == 200, eth_status
    assert eth_status["armed"] is True, eth_status
    assert eth_status["pair"] == "ETHUSD", eth_status
    assert eth_status["pack_id"] == "eth-pack", eth_status
    assert eth_status["armed_count"] == 2, eth_status

    status_code, eth_position = _get(
        app,
        "/api/v1/paper/position?venue=kraken&pair=ETHUSD",
        headers=headers,
    )
    assert status_code == 200, eth_position
    assert eth_position["armed"] is True, eth_position
    assert eth_position["pair"] == "ETHUSD", eth_position
    assert eth_position["free_cash"] == "2000", eth_position
    assert eth_position["armed_count"] == 2, eth_position

    status_code, missing = _get(
        app,
        "/api/v1/paper/status?venue=kraken&pair=BTCUSD",
        headers=headers,
    )
    assert status_code == 200, missing
    assert missing["armed"] is False, missing
    assert missing["armed_count"] == 2, missing


def test_paper_position_persisted_zero_cash_stays_zero(home: Path) -> None:
    """A real emptied wallet (quote balance \"0\") is not replaced by starting_cash."""

    pack = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    _arm(home, pack, venue="kraken", paper_balance=Decimal(1000))
    _seed_paper_state(home, "kraken", balances={"USD": "0", "SUI": "10"})

    token = f"boot-zero-cash-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session = _bootstrap_session(app, token)
    headers = _authenticated_headers(session)

    status_code, position = _get(app, "/api/v1/paper/position", headers=headers)
    assert status_code == 200, position
    assert position["free_cash"] == "0", position
    assert position["holdings"] == [{"symbol": "SUI", "qty": "10"}], position

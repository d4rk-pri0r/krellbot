"""Paper status/position stay scoped to one armed market (#173 / M0.8).

A shared venue wallet may hold balances for more than one pair. The
owned-position projection for the currently armed market must never
present another market's base holding as that market's position. Status
and position both name the same venue/pair/mode for the first armed
record.

All data lives under an isolated ``KRELLBOT_HOME`` (``tmp_path``). No
live venue, key, or order is touched.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.application.paper import PaperService, base_quote, project_owned_position
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
        "author": "krellbot paper status market scope tests",
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


def _arm(home: Path, pack_path: Path, *, venue: str) -> None:
    result = PaperService(home=home).arm(
        pack_path,
        venue=venue,
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="seed-market-scope",
    )
    assert result.ok, result.message


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


def test_base_quote_splits_kraken_style_pairs() -> None:
    assert base_quote("SUIUSD") == ("SUI", "USD")
    assert base_quote("ETHUSD") == ("ETH", "USD")


def test_project_owned_position_omits_other_market_base_holdings(tmp_path: Path) -> None:
    """A wallet with SUI and ETH only reports ETH when the armed pair is ETHUSD."""

    _seed_paper_state(
        tmp_path,
        "kraken",
        balances={
            "USD": "500.000000000",
            "SUI": "2.5000",
            "ETH": "0.125000000",
        },
    )
    body = project_owned_position(
        tmp_path,
        venue="kraken",
        pair="ETHUSD",
        mode="paper",
        as_of_run=None,
    )
    assert body["venue"] == "kraken"
    assert body["pair"] == "ETHUSD"
    assert body["mode"] == "paper"
    assert body["free_cash"] == "500.000000000"
    assert body["holdings"] == [{"symbol": "ETH", "qty": "0.125000000"}]
    assert "SUI" not in {row["symbol"] for row in body["holdings"]}


def test_project_owned_position_empty_when_armed_market_has_no_base(tmp_path: Path) -> None:
    """Armed on ETHUSD with only a leftover SUI balance is an empty owned position."""

    _seed_paper_state(
        tmp_path,
        "kraken",
        balances={"USD": "748.123400", "SUI": "2.5000"},
    )
    body = project_owned_position(
        tmp_path,
        venue="kraken",
        pair="ETHUSD",
        mode="paper",
        as_of_run="kraken:trend-follow:ETHUSD",
    )
    assert body["pair"] == "ETHUSD"
    assert body["free_cash"] == "748.123400"
    assert body["holdings"] == []
    assert body["as_of_run"] == "kraken:trend-follow:ETHUSD"


def test_paper_position_route_scopes_holdings_to_armed_pair(home: Path) -> None:
    """GET /api/v1/paper/position returns only the armed pair's base holding."""

    pack = _write_pack(home, pack_id="eth-pack", venue="kraken", pair="ETHUSD")
    _arm(home, pack, venue="kraken")
    _seed_paper_state(
        home,
        "kraken",
        balances={
            "USD": "748.123400",
            "SUI": "2.5000",
            "ETH": "1.2500",
        },
    )

    token = f"boot-market-scope-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    headers = _authenticated_headers(session_value)

    status_code, status_body = _get(app, "/api/v1/paper/status", headers=headers)
    assert status_code == 200, status_body
    assert status_body["armed"] is True
    assert status_body["venue"] == "kraken"
    assert status_body["pair"] == "ETHUSD"
    assert status_body["mode"] == "paper"

    pos_code, position = _get(app, "/api/v1/paper/position", headers=headers)
    assert pos_code == 200, position
    assert position["armed"] is True
    assert position["venue"] == status_body["venue"]
    assert position["pair"] == status_body["pair"]
    assert position["mode"] == status_body["mode"]
    assert position["free_cash"] == "748.123400"
    assert position["holdings"] == [{"symbol": "ETH", "qty": "1.2500"}]


def test_paper_position_route_after_rearm_to_other_pair_drops_prior_base(
    home: Path,
) -> None:
    """After disarm + arm onto another pair, status/position name that pair
    and do not keep the previous market's base holding in the projection."""

    first = _write_pack(home, pack_id="sui-pack", venue="kraken", pair="SUIUSD")
    _arm(home, first, venue="kraken")
    _seed_paper_state(
        home,
        "kraken",
        balances={"USD": "748.123400", "SUI": "2.5000"},
    )

    PaperService(home=home).disarm(
        venue="kraken",
        pair="SUIUSD",
        correlation_id="seed-disarm-scope",
    )
    second = _write_pack(home, pack_id="eth-pack", venue="kraken", pair="ETHUSD")
    _arm(home, second, venue="kraken")

    token = f"boot-market-scope-rearm-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    headers = _authenticated_headers(session_value)

    status_code, status_body = _get(app, "/api/v1/paper/status", headers=headers)
    assert status_code == 200, status_body
    assert status_body["pair"] == "ETHUSD"

    pos_code, position = _get(app, "/api/v1/paper/position", headers=headers)
    assert pos_code == 200, position
    assert position["pair"] == "ETHUSD"
    assert position["venue"] == "kraken"
    assert position["mode"] == "paper"
    # Leftover SUI from the prior market is still on disk, but must not
    # appear as ETHUSD's owned position.
    assert position["holdings"] == []
    assert position["free_cash"] == "748.123400"

"""Multi-pair fleet list — groups/filters without ``armed[0]`` collapse.

Extends M9.1 ``GET /api/v1/paper/fleet`` for operator supervision of
concurrent paper arms on different pairs (M16.1).

Contract under test:

  1. Two concurrent paper arms on different pairs both appear as
     distinct deployments and as distinct ``groups`` keyed by
     ``(venue, pair)`` — never collapsed to ``config.armed[0]``.
  2. ``?venue=&pair=`` filters deployments/groups to that market while
     ``armed_count`` still reports the unfiltered armed total.
  3. Partial filters (venue-only or pair-only) narrow without guessing
     a missing axis.
  4. One-pack-per-(venue,pair) is preserved: a second arm on the same
     market is refused as ``already_armed`` and the fleet still shows
     exactly one row for that market.
  5. Session gate + closed shape (no cash/qty/stop/cap/path) unchanged.
"""

from __future__ import annotations

import json
from decimal import Decimal
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


# ---- helpers --------------------------------------------------------------


def _get_fleet(
    app,
    *,
    query: str = "",
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    path = "/api/v1/paper/fleet"
    if query:
        path = f"{path}?{query}"
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path=path, headers=base)


def _bootstrap_session_cookie(app, token: str) -> str:
    csrf_token = _bootstrap_and_get_csrf(app, token)
    assert csrf_token, csrf_token
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _session_headers(session_value: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _write_pack(home: Path, *, pack_id: str, venue: str, pair: str) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": pack_id,
        "author": "krellbot fleet multi-pair tests",
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


def _arm(home: Path, pack_path: Path, *, venue: str, pair: str):
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue=venue,
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="seed-fleet-multi-pair",
    )
    return result


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


def _arm_two_pairs(home: Path) -> None:
    first = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    result = _arm(home, first, venue="kraken", pair="SUIUSD")
    assert result.ok, result.message
    second = _write_pack(home, pack_id="mean-revert", venue="coinbase", pair="BTC-USD")
    result = _arm(home, second, venue="coinbase", pair="BTC-USD")
    assert result.ok, result.message


# ---- multi-pair list + groups --------------------------------------------


def test_fleet_lists_two_pairs_as_separate_groups_not_armed_zero(home: Path) -> None:
    """≥2 concurrent paper arms appear as distinct pair groups."""

    _arm_two_pairs(home)
    token = f"boot-fleet-multi-groups-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is True, decoded
    assert decoded["armed_count"] == 2, decoded
    assert len(decoded["deployments"]) == 2, decoded["deployments"]
    groups = decoded["groups"]
    assert len(groups) == 2, groups
    by_market = {(g["venue"], g["pair"]): g for g in groups}
    assert set(by_market) == {("kraken", "SUIUSD"), ("coinbase", "BTC-USD")}, by_market
    for key, group in by_market.items():
        assert len(group["deployments"]) == 1, group
        row = group["deployments"][0]
        assert (row["venue"], row["pair"]) == key, row
        # Must not silently project only armed[0] — both packs present.
        assert row["pack_id"] in {"trend-follow", "mean-revert"}, row
    pack_ids = {row["pack_id"] for row in decoded["deployments"]}
    assert pack_ids == {"trend-follow", "mean-revert"}, pack_ids


def test_fleet_filters_by_venue_and_pair_keeps_armed_count(home: Path) -> None:
    """Exact venue+pair filter narrows rows; armed_count stays unfiltered."""

    _arm_two_pairs(home)
    token = f"boot-fleet-multi-filter-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(
        app,
        query="venue=coinbase&pair=BTC-USD",
        headers=_session_headers(session_value),
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is True, decoded
    assert decoded["armed_count"] == 2, decoded
    assert decoded["deployments"] == [
        {
            "venue": "coinbase",
            "pair": "BTC-USD",
            "mode": "paper",
            "pack_id": "mean-revert",
            "entries_paused": False,
            "last_tick_ts_ms": None,
            "last_tick_result": "no tick yet",
            "last_refusal_code": None,
            "detail_href": "/?view=workstation&venue=coinbase&pair=BTC-USD",
        }
    ], decoded["deployments"]
    assert decoded["groups"] == [
        {
            "venue": "coinbase",
            "pair": "BTC-USD",
            "deployments": decoded["deployments"],
        }
    ], decoded["groups"]


def test_fleet_filter_miss_reports_disarmed_view_with_armed_count(home: Path) -> None:
    """Unknown market filter → armed false, but armed_count discloses peers."""

    _arm_two_pairs(home)
    token = f"boot-fleet-multi-miss-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(
        app,
        query="venue=kraken&pair=ETHUSD",
        headers=_session_headers(session_value),
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded == {
        "schema_version": "1",
        "armed": False,
        "armed_count": 2,
        "deployments": [],
        "groups": [],
    }, decoded


def test_fleet_filters_by_venue_only(home: Path) -> None:
    """Venue-only filter keeps every armed pair on that venue."""

    first = _write_pack(home, pack_id="sui-pack", venue="kraken", pair="SUIUSD")
    assert _arm(home, first, venue="kraken", pair="SUIUSD").ok
    second = _write_pack(home, pack_id="eth-pack", venue="kraken", pair="ETHUSD")
    assert _arm(home, second, venue="kraken", pair="ETHUSD").ok
    third = _write_pack(home, pack_id="btc-pack", venue="coinbase", pair="BTC-USD")
    assert _arm(home, third, venue="coinbase", pair="BTC-USD").ok

    token = f"boot-fleet-venue-only-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(
        app,
        query="venue=kraken",
        headers=_session_headers(session_value),
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed_count"] == 3, decoded
    pairs = {row["pair"] for row in decoded["deployments"]}
    assert pairs == {"SUIUSD", "ETHUSD"}, pairs
    assert {g["pair"] for g in decoded["groups"]} == pairs


def test_fleet_preserves_one_pack_per_venue_pair(home: Path) -> None:
    """Second arm on the same (venue, pair) is refused; fleet stays one row."""

    from krellbot.application.paper import CODE_ALREADY_ARMED

    first = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    assert _arm(home, first, venue="kraken", pair="SUIUSD").ok
    rival = _write_pack(home, pack_id="rival-pack", venue="kraken", pair="SUIUSD")
    refused = _arm(home, rival, venue="kraken", pair="SUIUSD")
    assert refused.ok is False, refused
    assert refused.code == CODE_ALREADY_ARMED, refused

    token = f"boot-fleet-one-pack-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed_count"] == 1, decoded
    assert len(decoded["deployments"]) == 1, decoded["deployments"]
    assert decoded["deployments"][0]["pack_id"] == "trend-follow", decoded["deployments"]
    assert len(decoded["groups"]) == 1, decoded["groups"]
    assert decoded["groups"][0]["venue"] == "kraken"
    assert decoded["groups"][0]["pair"] == "SUIUSD"
    assert len(decoded["groups"][0]["deployments"]) == 1


def test_fleet_multi_pair_omits_cash_qty_stop_cap_and_path(home: Path) -> None:
    _arm_two_pairs(home)
    token = f"boot-fleet-multi-closed-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    raw = body.decode("utf-8")
    for needle in ("starting_cash", "owned_qty", "stop", "cap", "pack_path"):
        assert needle not in raw, (needle, raw)

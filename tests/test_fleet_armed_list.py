"""Armed fleet list — ``GET /api/v1/paper/fleet``.

The fleet management view joins every armed config record with journal
last-tick time/result and a relative deep link into Workstation detail.

Contract under test:

  1. Same session gate as ``GET /api/v1/paper/status`` (``_gate_get``):
     missing session / non-loopback Origin or Host → 403.
  2. Empty home → ``armed: false``, ``deployments: []``.
  3. Armed rows carry venue/pair/mode/pack_id/entries_paused plus
     ``last_tick_ts_ms``, ``last_tick_result``, ``last_refusal_code``,
     and ``detail_href``.
  4. Armed with no journal ticks → ``last_tick_ts_ms: null``,
     ``last_tick_result: "no tick yet"``.
  5. Journal ticks populate last-tick time/result (and refusal when
     present); closed shape never leaks cash/qty/stop/cap/path.
  6. ``Cache-Control: no-store``; path listed in OpenAPI.
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
    _run_paper_arm,
    asgi_call,
)

TEST_PORT = NS06_PORT


# ---- helpers --------------------------------------------------------------


def _get_fleet(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes, list[str]]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    return asgi_call(app, method="GET", path="/api/v1/paper/fleet", headers=base)


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
        "author": "krellbot fleet armed list tests",
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


def _arm(home: Path, pack_path: Path, *, venue: str, pair: str) -> None:
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue=venue,
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="seed-fleet-armed",
    )
    assert result.ok, result.message


def _journal_record(
    *,
    ts: int,
    venue: str,
    pack: str,
    pair: str,
    detail: dict | None = None,
) -> dict:
    return {
        "ts": ts,
        "kind": "tick",
        "venue": venue,
        "pack": pack,
        "bar_ts": 0,
        "detail": {"pair": pair, **(detail or {})},
    }


def _seed_journal(home: Path, records: list[dict], month: str = "2026-11") -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
    (journal_dir / f"{month}.jsonl").write_text(lines + "\n", encoding="utf-8")


def _read_json(body: bytes) -> dict:
    decoded = json.loads(body)
    assert isinstance(decoded, dict), decoded
    return decoded


# ---- 1. session gate ------------------------------------------------------


def test_fleet_requires_a_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, _b, _c = _get_fleet(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, status


def test_fleet_refuses_non_loopback_origin(home: Path) -> None:
    token = f"boot-fleet-origin-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, _b, _c = _get_fleet(app, headers=headers)
    assert status == 403, status


def test_fleet_refuses_non_loopback_host(home: Path) -> None:
    app = _build_app(home)
    headers = [
        ("Host", "evil.example.com"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
    ]
    status, _h, _b, _c = _get_fleet(app, headers=headers)
    assert status == 403, status


# ---- 2. empty / armed without ticks --------------------------------------


def test_fleet_empty_returns_disarmed_shape(home: Path) -> None:
    token = f"boot-fleet-empty-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    assert _read_json(body) == {
        "schema_version": "1",
        "armed": False,
        "armed_count": 0,
        "deployments": [],
        "groups": [],
    }


def test_fleet_armed_without_ticks_reports_no_tick_yet(home: Path) -> None:
    _run_paper_arm(home)
    token = f"boot-fleet-no-tick-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["armed"] is True, decoded
    assert decoded["deployments"] == [
        {
            "venue": "kraken",
            "pair": "SUIUSD",
            "mode": "paper",
            "pack_id": "trend-follow",
            "entries_paused": False,
            "last_tick_ts_ms": None,
            "last_tick_result": "no tick yet",
            "last_refusal_code": None,
            "detail_href": "/?view=workstation&venue=kraken&pair=SUIUSD",
        }
    ], decoded["deployments"]


# ---- 3. last tick time/result + multi-deploy -----------------------------


def test_fleet_joins_last_tick_time_and_result(home: Path) -> None:
    _run_paper_arm(home)
    _seed_journal(
        home,
        [
            _journal_record(
                ts=1_700_000_000,
                venue="kraken",
                pack="trend-follow",
                pair="SUIUSD",
                detail={"decision": "hold"},
            ),
            _journal_record(
                ts=1_700_000_100,
                venue="kraken",
                pack="trend-follow",
                pair="SUIUSD",
                detail={"code": "insufficient_cash"},
            ),
        ],
    )
    token = f"boot-fleet-tick-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    row = _read_json(body)["deployments"][0]
    assert row["last_tick_ts_ms"] == 1_700_000_100_000, row
    assert row["last_refusal_code"] == "insufficient_cash", row
    assert row["last_tick_result"] == "2 ticks, last refusal insufficient_cash", row
    assert row["detail_href"] == "/?view=workstation&venue=kraken&pair=SUIUSD", row


def test_fleet_lists_every_armed_deployment_not_just_the_first(home: Path) -> None:
    first = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    _arm(home, first, venue="kraken", pair="SUIUSD")
    second = _write_pack(home, pack_id="mean-revert", venue="coinbase", pair="BTC-USD")
    _arm(home, second, venue="coinbase", pair="BTC-USD")
    _seed_journal(
        home,
        [
            _journal_record(
                ts=1_700_000_050,
                venue="coinbase",
                pack="mean-revert",
                pair="BTC-USD",
            ),
        ],
    )

    token = f"boot-fleet-two-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    deployments = _read_json(body)["deployments"]
    assert len(deployments) == 2, deployments
    by_pair = {row["pair"]: row for row in deployments}
    assert by_pair["SUIUSD"]["last_tick_result"] == "no tick yet", by_pair["SUIUSD"]
    assert by_pair["BTC-USD"]["last_tick_ts_ms"] == 1_700_000_050_000, by_pair["BTC-USD"]
    assert by_pair["BTC-USD"]["last_tick_result"] == "1 tick, no refusal", by_pair["BTC-USD"]
    assert by_pair["BTC-USD"]["detail_href"] == ("/?view=workstation&venue=coinbase&pair=BTC-USD"), by_pair["BTC-USD"]


def test_fleet_reflects_entries_paused(home: Path) -> None:
    _run_paper_arm(home)
    from krellbot.application.paper import PaperService

    PaperService(home=home).pause_entries(
        venue="kraken",
        pair="SUIUSD",
        correlation_id="seed-fleet-pause",
    )
    token = f"boot-fleet-paused-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    assert _read_json(body)["deployments"][0]["entries_paused"] is True


# ---- 4. closed shape / hygiene -------------------------------------------


def test_fleet_omits_cash_qty_stop_cap_and_path(home: Path) -> None:
    _run_paper_arm(home)
    token = f"boot-fleet-no-leak-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, _h, body, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    for row in decoded["deployments"]:
        leaked = sorted(field for field in ("starting_cash", "owned_qty", "stop", "cap", "pack_path") if field in row)
        assert leaked == [], (leaked, row)
    raw = body.decode("utf-8")
    for needle in ("starting_cash", "owned_qty", "stop", "cap", "pack_path"):
        assert needle not in raw, (needle, raw)


def test_fleet_is_no_store(home: Path) -> None:
    _run_paper_arm(home)
    token = f"boot-fleet-store-{home.name}"
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    status, headers, _b, _c = _get_fleet(app, headers=_session_headers(session_value))
    assert status == 200, status
    cache_control = [value for (name, value) in headers if name.lower() == "cache-control"]
    assert cache_control == ["no-store"], cache_control


def test_fleet_path_appears_in_openapi(home: Path) -> None:
    app = _build_app(home)
    status, _h, body, _c = asgi_call(
        app,
        method="GET",
        path="/openapi.json",
        headers=[("Host", f"127.0.0.1:{TEST_PORT}")],
    )
    assert status == 200, status
    paths = _read_json(body).get("paths") or {}
    assert "/api/v1/paper/fleet" in paths, sorted(paths.keys())

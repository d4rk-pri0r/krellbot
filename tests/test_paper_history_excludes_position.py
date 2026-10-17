"""Paper history stays position-free after the owned-position route lands.

``GET /api/v1/paper/history`` is the read-only "Last runs" projection and
its closed shape must not grow money-plane fields now that
``GET /api/v1/paper/position`` exists: the two reads stay separate, the
history body keeps no cash, quantity, stop, cap, pack path, balances or
fill qty/price, and the seeded owned-position values must not appear
anywhere in the history wire body even with a fully populated state file.
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


# ---- helpers --------------------------------------------------------------


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


def _seed_journal(home: Path, records: list[dict]) -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
    (journal_dir / "2026-10.jsonl").write_text(lines + "\n", encoding="utf-8")


def _seed_paper_state(home: Path, venue: str) -> None:
    """A fully populated state file: owned cash, a base holding, a fill."""

    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "venue": venue,
        "balances": {"USD": "748.874640020", "SUI": "62.538182660"},
        "open_orders": [],
        "recent_fills": [
            {
                "id": "coid-entry-1",
                "coid": "coid-entry-1",
                "pair": "SUIUSD",
                "side": "buy",
                "qty": "62.538182660",
                "price": "4.0143",
                "ts_ms": 1_000,
            }
        ],
        "seeded": True,
    }
    (run_dir / f"paper-{venue}.json").write_text(
        json.dumps(body, sort_keys=True),
        encoding="utf-8",
    )


def _get_history(app, headers: list[tuple[str, str]]):
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    base.extend(headers)
    status, flat, body, _set_cookies = asgi_call(app, method="GET", path="/api/v1/paper/history", headers=base)
    return status, flat, body


def _authenticated_headers(session_value: str) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


def _seeded_app(tmp_path: Path):
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
        ],
    )
    _seed_paper_state(tmp_path, "kraken")
    token = "boot-history-position-free"
    app = _build_app(tmp_path, bootstrap_token=token)
    _csrf = _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    session_value = next(iter(state.sessions.keys()))
    return app, session_value


# ---- the contract ----------------------------------------------------------


def test_paper_history_body_has_no_position_fields(tmp_path: Path) -> None:
    """No owned-position field appears at any level of the history body."""

    app, session_value = _seeded_app(tmp_path)
    status, _h, body = _get_history(app, _authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = json.loads(body)

    forbidden = {
        "free_cash": "owned cash",
        "holdings": "owned holdings",
        "balances": "balances",
        "owned_qty": "quantity",
        "qty": "fill quantity",
        "price": "fill price",
        "avg_cost": "average cost",
        "starting_cash": "cash",
        "stop": "stop price",
        "cap": "cap percent",
        "pack_path": "pack path",
    }

    leaked = sorted(field for field in forbidden if field in decoded)
    assert leaked == [], (leaked, decoded)
    for run in decoded["runs"]:
        leaked_run = sorted(field for field in forbidden if field in run)
        assert leaked_run == [], (leaked_run, run)
        for fill in run["recent_fills"]:
            leaked_fill = sorted(field for field in forbidden if field in fill)
            assert leaked_fill == [], (leaked_fill, fill)
            # The fill projection stays the coid/side/ts_ms triple.
            assert set(fill.keys()) == {"coid", "side", "ts_ms"}, fill


def test_paper_history_wire_carries_no_owned_position_values(tmp_path: Path) -> None:
    """The seeded owned-position decimal strings appear nowhere in the
    serialised history body — the position values live only on
    ``/api/v1/paper/position``."""

    app, session_value = _seeded_app(tmp_path)
    status, _h, body = _get_history(app, _authenticated_headers(session_value))
    assert status == 200, (status, body)
    text = body.decode("utf-8")
    for secret in ("748.874640020", "62.538182660", "4.0143", "free_cash", "holdings"):
        assert secret not in text, (secret, text)


def test_paper_position_route_does_not_change_history_shape(tmp_path: Path) -> None:
    """With the owned position readable on its own route, the history body
    is still exactly ``{"schema_version": "1", "runs": [...]}``."""

    app, session_value = _seeded_app(tmp_path)
    status, _h, body = _get_history(app, _authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert set(decoded.keys()) == {"schema_version", "runs"}, decoded
    assert decoded["schema_version"] == "1", decoded
    assert len(decoded["runs"]) == 1, decoded

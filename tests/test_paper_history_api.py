"""Paper history — read-only ``GET /api/v1/paper/history`` contract.

The Python half is the contract for the paper panel's "Last runs" table:

  1. The route exists behind the same session gate as
     ``GET /api/v1/paper/status`` (``_gate_get``): a missing session
     cookie is 403, a non-loopback Origin is 403.
  2. With journal records + a paper state file present the body is the
     closed shape ``{"schema_version": "1", "runs": [...]}`` where each
     run carries venue, pair, pack_id, first_ts_ms, last_ts_ms,
     ticks_total, last_refusal_code, mode, status, summary and
     recent_fills (capped at 50). A run whose (venue, pack, pair) the
     config still arms is ``status: "active"`` with the armed record's
     pack_version; otherwise ``status: "closed"``.
  3. With no journal files the body is ``{"schema_version": "1",
     "runs": []}``.
  4. No owned cash, quantity, stop, cap, pack path, pack digest, or fill
     qty/price appears anywhere in the body, and the response is served
     with ``Cache-Control: no-store``.

All data lives under an isolated ``KRELLBOT_HOME`` (``tmp_path``). No
live venue, key, or order is touched; the journal lines and paper state
file are seeded exactly as the engine writes them.
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
    """One tick record in the exact shape ``run.tick`` journals."""

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
    """Seed ``<home>/run/paper-<venue>.json`` as the paper venue writes it."""

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
    _csrf = _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _get_history(
    app,
    *,
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, flat, body, _set_cookies = asgi_call(
        app, method="GET", path="/api/v1/paper/history", headers=base
    )
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


# ---- 1. the route exists and requires a session ---------------------------


def test_paper_history_route_exists_and_returns_200_with_session(tmp_path: Path) -> None:
    """``GET /api/v1/paper/history`` answers 200 with a valid session."""

    token = "boot-history-exists"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["schema_version"] == "1", decoded
    assert decoded["runs"] == [], decoded


def test_paper_history_refuses_unauthenticated(tmp_path: Path) -> None:
    """No session cookie → 403 with ``{"detail": "session required"}``."""

    app = _build_app(tmp_path)
    status, _h, body = _get_history(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, (status, body)
    assert json.loads(body) == {"detail": "session required"}, body


def test_paper_history_refuses_invented_session_cookie(tmp_path: Path) -> None:
    """A cookie that is not a key in the session map is 403 too."""

    app = _build_app(tmp_path)
    status, _h, _b = _get_history(
        app,
        headers=_authenticated_headers("not-a-real-session"),
    )
    assert status == 403, status


def test_paper_history_refuses_non_loopback_origin(tmp_path: Path) -> None:
    """A present non-loopback Origin is refused even with a session."""

    token = "boot-history-origin"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, _b = _get_history(
        app,
        headers=[
            ("Origin", "http://evil.example.com"),
            ("Cookie", f"krellbot_session={session_value}"),
        ],
    )
    assert status == 403, status


def test_paper_history_does_not_require_csrf_header(tmp_path: Path) -> None:
    """GET gate parity with ``/api/v1/paper/status``: no CSRF required."""

    token = "boot-history-no-csrf"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    headers = _authenticated_headers(session_value)
    headers.append(("X-Krellbot-CSRF", "not-the-real-csrf"))
    status, _h, body = _get_history(app, headers=headers)
    assert status == 200, (status, body)
    assert _read_json(body)["runs"] == []


# ---- 2. closed runs body --------------------------------------------------


def test_paper_history_returns_closed_runs_body(tmp_path: Path) -> None:
    """Journal ticks + paper fills project to the closed run shape."""

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
                detail={"reason": "no_signal", "intent_refused": "store_full"},
            ),
        ],
    )
    _seed_paper_state(
        tmp_path,
        "kraken",
        fills=[_fill("coid-entry-1", "SUIUSD"), _fill("coid-exit-1", "SUIUSD", side="sell", ts_ms=2_000)],
    )

    token = "boot-history-runs"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)

    assert decoded["schema_version"] == "1", decoded
    runs = decoded["runs"]
    assert isinstance(runs, list) and len(runs) == 1, decoded
    run = runs[0]
    assert run["venue"] == "kraken", run
    assert run["pair"] == "SUIUSD", run
    assert run["pack_id"] == "trend-follow", run
    assert "pack_version" not in run, run
    assert run["first_ts_ms"] == 1_760_000_100 * 1000, run
    assert run["last_ts_ms"] == 1_760_000_200 * 1000, run
    assert run["ticks_total"] == 2, run
    assert run["last_refusal_code"] == "store_full", run
    assert run["mode"] == "paper", run
    assert run["status"] == "closed", run
    assert run["summary"] == "2 ticks, 2 fills, last refusal store_full, closed", run
    assert run["recent_fills"] == [
        {"coid": "coid-entry-1", "side": "buy", "ts_ms": 1_000},
        {"coid": "coid-exit-1", "side": "sell", "ts_ms": 2_000},
    ], run


def test_paper_history_marks_armed_run_active_with_pack_version(tmp_path: Path) -> None:
    """A run the config still arms is ``active`` with its pack_version."""

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
        ],
    )
    _seed_paper_state(tmp_path, "kraken", fills=[])

    token = "boot-history-active"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    runs = _read_json(body)["runs"]
    assert len(runs) == 1, runs
    run = runs[0]
    assert run["status"] == "active", run
    assert run["mode"] == "paper", run
    assert isinstance(run["pack_version"], str) and run["pack_version"], run
    assert run["summary"].endswith("active"), run


def test_paper_history_ignores_non_tick_records_and_pairless_ticks(tmp_path: Path) -> None:
    """Only tick records with a pair in the detail count as runs."""

    _seed_journal(
        tmp_path,
        [
            {"ts": 1, "kind": "supervision", "venue": "kraken", "pack": "x", "bar_ts": 0, "detail": {}},
            _journal_record(ts=1_760_000_100, venue="kraken", pack="trend-follow", pair="SUIUSD", detail={}),
        ],
    )
    token = "boot-history-kind"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    runs = _read_json(body)["runs"]
    assert len(runs) == 1 and runs[0]["ticks_total"] == 1, runs


def test_paper_history_sorts_most_recent_first_and_caps_runs_at_20(tmp_path: Path) -> None:
    """Runs sort by ``last_ts_ms`` descending and cap at 20 entries."""

    records = [
        _journal_record(
            ts=1_760_000_000 + index,
            venue="kraken",
            pack=f"pack-{index:02d}",
            pair=f"P{index:02d}USD",
            detail={"reason": "no_signal"},
        )
        for index in range(25)
    ]
    _seed_journal(tmp_path, records)
    token = "boot-history-cap"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    runs = _read_json(body)["runs"]
    assert len(runs) == 20, len(runs)
    last_ts_values = [run["last_ts_ms"] for run in runs]
    assert last_ts_values == sorted(last_ts_values, reverse=True), last_ts_values
    assert runs[0]["pack_id"] == "pack-24", runs[0]


def test_paper_history_caps_recent_fills_at_50(tmp_path: Path) -> None:
    """``recent_fills`` keeps at most the last 50 fills of the run."""

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
    _seed_paper_state(
        tmp_path,
        "kraken",
        fills=[
            _fill(f"coid-{index}", "SUIUSD", ts_ms=index) for index in range(60)
        ],
    )
    token = "boot-history-fills-cap"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    runs = _read_json(body)["runs"]
    fills = runs[0]["recent_fills"]
    assert len(fills) == 50, len(fills)
    assert fills[0]["coid"] == "coid-10", fills[0]
    assert fills[-1]["coid"] == "coid-59", fills[-1]


# ---- 3. empty state -------------------------------------------------------


def test_paper_history_returns_empty_runs_when_no_journal_files(tmp_path: Path) -> None:
    """No journal directory at all → ``runs: []``, still 200."""

    token = "boot-history-empty"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded == {"schema_version": "1", "runs": []}, decoded


def test_paper_history_skips_malformed_journal_lines(tmp_path: Path) -> None:
    """A torn journal line never breaks the read-only view."""

    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    good = _journal_record(
        ts=1_760_000_100,
        venue="kraken",
        pack="trend-follow",
        pair="SUIUSD",
        detail={"reason": "no_signal"},
    )
    (journal_dir / "2026-10.jsonl").write_text(
        json.dumps(good, separators=(",", ":")) + "\n{torn line\n",
        encoding="utf-8",
    )
    token = "boot-history-torn"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    runs = _read_json(body)["runs"]
    assert len(runs) == 1 and runs[0]["ticks_total"] == 1, runs


# ---- 4. no-leak + caching -------------------------------------------------


def test_paper_history_omits_cash_qty_stop_cap_and_path(tmp_path: Path) -> None:
    """The single no-leak assertion surface for the history body."""

    _seed_journal(
        tmp_path,
        [
            _journal_record(
                ts=1_760_000_100,
                venue="kraken",
                pack="trend-follow",
                pair="SUIUSD",
                detail={
                    "reason": "no_signal",
                    "owned_qty_after": "1.5",
                    "intent_refused": "store_full",
                },
            ),
        ],
    )
    _seed_paper_state(
        tmp_path,
        "kraken",
        fills=[_fill("coid-entry-1", "SUIUSD")],
    )
    token = "boot-history-no-leak"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_history(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)

    forbidden_fields = {
        "starting_cash": "cash",
        "owned_qty": "quantity",
        "owned_qty_after": "quantity",
        "stop": "stop price",
        "cap": "cap percent",
        "pack_path": "pack path",
        "pack_sha256": "pack digest",
        "balances": "balances",
        "qty": "fill quantity",
        "price": "fill price",
    }
    leaked = sorted(field for field in forbidden_fields if field in decoded)
    assert leaked == [], (leaked, decoded)
    for run in decoded["runs"]:
        leaked_run = sorted(field for field in forbidden_fields if field in run)
        assert leaked_run == [], (leaked_run, run)
        for fill in run["recent_fills"]:
            leaked_fill = sorted(field for field in forbidden_fields if field in fill)
            assert leaked_fill == [], (leaked_fill, fill)
            assert set(fill.keys()) == {"coid", "side", "ts_ms"}, fill

    # The seeded money-plane strings must not appear anywhere in the wire body.
    text = body.decode("utf-8")
    for secret in ("900.0", "1.5", "3.25", "/packs/"):
        assert secret not in text, (secret, text)


def test_paper_history_served_no_store(tmp_path: Path) -> None:
    """The projection is fresh evidence, never a cacheable response."""

    token = "boot-history-no-store"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    _status, headers, _body = _get_history(app, headers=_authenticated_headers(session_value))
    cache_control = [value for name, value in headers if name.lower() == "cache-control"]
    assert cache_control == ["no-store"], cache_control

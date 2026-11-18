"""Live journal browse — paper/live filter + readable rows (M20.5).

Pins the Operations journal contract beyond M9.3:

  1. ``?mode=paper|live`` filters classify-then-tail (and classify-then-since).
  2. Live refuse / fill-like ticks are projected with readable ``summary``.
  3. Export secret fields stay absent even when planted on live rows.
  4. Invalid ``mode`` is 400 with ``code: unsupported_mode``.

Seeded JSONL under an isolated ``KRELLBOT_HOME`` only — no live venue,
keys, or risk-path imports.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

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
    kind: str = "tick",
    venue: str = "kraken",
    pack: str = "sma_cross",
    detail: dict | str | None = None,
) -> dict:
    return {
        "ts": ts,
        "kind": kind,
        "venue": venue,
        "pack": pack,
        "bar_ts": ts,
        "detail": detail if detail is not None else {"pair": "SUIUSD", "reason": "no_signal"},
    }


def _seed_journal(home: Path, records: list[dict], month: str = "2026-10") -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(json.dumps(record, separators=(",", ":")) for record in records)
    (journal_dir / f"{month}.jsonl").write_text(lines + "\n", encoding="utf-8")


def _bootstrap_session(app, token: str) -> str:
    _bootstrap_and_get_csrf(app, token)
    state = app.state.krellbot
    return next(iter(state.sessions.keys()))


def _get_journal(
    app,
    *,
    query: str = "",
    headers: list[tuple[str, str]] | None = None,
) -> tuple[int, list[tuple[str, str]], bytes]:
    path = "/api/v1/journal" + (f"?{query}" if query else "")
    base = [("Host", f"127.0.0.1:{TEST_PORT}")]
    if headers:
        base.extend(headers)
    status, flat, body, _set_cookies = asgi_call(app, method="GET", path=path, headers=base)
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


def _seed_mixed(home: Path) -> None:
    """Paper tick, live fill, live refuse (with planted secrets), supervision."""

    _seed_journal(
        home,
        [
            _journal_record(
                ts=1_700_000_000,
                detail={"pair": "SUIUSD", "mode": "paper", "reason": "no_signal"},
            ),
            _journal_record(
                ts=1_700_000_100,
                detail={
                    "pair": "SUIUSD",
                    "mode": "live",
                    "reason": "entry",
                    "entry_qty": "1",
                    "exit_qty": "0",
                    "stop_qty": "0",
                    "owned_qty_after": "1",
                },
            ),
            _journal_record(
                ts=1_700_000_200,
                detail={
                    "pair": "SUIUSD",
                    "reason": "live_refused",
                    "code": "paper_only_release",
                    "key": "should-not-leak",
                    "secret": "also-secret",
                    "license": "lic",
                    "balance": "999",
                },
            ),
            _journal_record(
                ts=1_700_000_300,
                kind="supervision",
                pack="-",
                detail={"event": "wake_gap", "gap_s": 9000},
            ),
        ],
    )


def test_mode_live_returns_only_live_rows_with_readable_summary(tmp_path: Path) -> None:
    token = "boot-live-journal-mode-live"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    _seed_mixed(tmp_path)

    status, _h, body = _get_journal(
        app,
        query="mode=live&tail=10",
        headers=_authenticated_headers(session_value),
    )
    assert status == 200, (status, body)
    records = _read_json(body)["records"]
    assert [r["ts"] for r in records] == [1_700_000_100, 1_700_000_200]
    assert all(r["mode"] == "live" for r in records)

    fill, refuse = records
    assert "bought 1" in fill["summary"]
    assert "live" in fill["summary"]
    assert refuse["summary"].startswith("live refused: paper_only_release")
    assert "SUIUSD" in refuse["summary"]

    detail = refuse["detail"]
    assert "key" not in detail
    assert "secret" not in detail
    assert "license" not in detail
    assert "balance" not in detail
    assert detail["reason"] == "live_refused"


def test_mode_paper_excludes_live_classified_rows(tmp_path: Path) -> None:
    token = "boot-live-journal-mode-paper"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    _seed_mixed(tmp_path)

    status, _h, body = _get_journal(
        app,
        query="mode=paper&tail=10",
        headers=_authenticated_headers(session_value),
    )
    assert status == 200, (status, body)
    records = _read_json(body)["records"]
    assert [r["ts"] for r in records] == [1_700_000_000, 1_700_000_300]
    assert all(r["mode"] == "paper" for r in records)
    assert "no_signal" in records[0]["summary"]


def test_default_browse_includes_all_modes_with_projections(tmp_path: Path) -> None:
    token = "boot-live-journal-all"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    _seed_mixed(tmp_path)

    status, _h, body = _get_journal(
        app,
        query="tail=10",
        headers=_authenticated_headers(session_value),
    )
    assert status == 200, (status, body)
    records = _read_json(body)["records"]
    assert len(records) == 4
    modes = {r["ts"]: r["mode"] for r in records}
    assert modes[1_700_000_000] == "paper"
    assert modes[1_700_000_100] == "live"
    assert modes[1_700_000_200] == "live"
    assert modes[1_700_000_300] == "paper"
    assert all(isinstance(r.get("summary"), str) and r["summary"] for r in records)


def test_mode_filter_then_tail_selects_last_n_live(tmp_path: Path) -> None:
    """Last-N + live means last N live rows, not last N overall then drop."""

    token = "boot-live-journal-filter-then-tail"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    records = []
    for i in range(8):
        mode = "live" if i % 2 == 1 else "paper"
        records.append(
            _journal_record(
                ts=1_700_000_000 + i,
                detail={"pair": "SUIUSD", "mode": mode, "reason": "no_signal", "n": i},
            )
        )
    _seed_journal(tmp_path, records)

    status, _h, body = _get_journal(
        app,
        query="mode=live&tail=2",
        headers=_authenticated_headers(session_value),
    )
    assert status == 200, (status, body)
    got = _read_json(body)["records"]
    assert [r["ts"] for r in got] == [1_700_000_005, 1_700_000_007]
    assert all(r["mode"] == "live" for r in got)


def test_mode_filter_then_since_window(tmp_path: Path) -> None:
    token = "boot-live-journal-since-mode"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    now = 1_700_000_000
    _seed_journal(
        tmp_path,
        [
            _journal_record(
                ts=now - 48 * 3600,
                detail={"pair": "SUIUSD", "mode": "live", "reason": "entry", "entry_qty": "1"},
            ),
            _journal_record(
                ts=now - 2 * 3600,
                detail={"pair": "SUIUSD", "mode": "paper", "reason": "no_signal"},
            ),
            _journal_record(
                ts=now - 3600,
                detail={
                    "pair": "SUIUSD",
                    "reason": "live_refused",
                    "code": "paper_only_release",
                },
            ),
        ],
    )

    with patch("krellbot.journal.time.time", return_value=float(now)):
        status, _h, body = _get_journal(
            app,
            query="since=24h&mode=live",
            headers=_authenticated_headers(session_value),
        )
    assert status == 200, (status, body)
    got = _read_json(body)["records"]
    assert [r["ts"] for r in got] == [now - 3600]
    assert got[0]["mode"] == "live"
    assert got[0]["summary"].startswith("live refused:")


def test_unsupported_mode_is_400(tmp_path: Path) -> None:
    token = "boot-live-journal-bad-mode"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_journal(
        app,
        query="mode=futures",
        headers=_authenticated_headers(session_value),
    )
    assert status == 400, (status, body)
    decoded = _read_json(body)
    assert decoded["code"] == "unsupported_mode", decoded

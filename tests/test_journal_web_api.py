"""Journal browse — read-only ``GET /api/v1/journal`` contract (M9.3).

The Python half is the contract for the Operations journal panel:

  1. The route exists behind the same session gate as
     ``GET /api/v1/paper/status`` (``_gate_get``): a missing session
     cookie is 403, a non-loopback Origin is 403. CSRF is not required.
  2. Default selection is the last 5 records (CLI ``--tail`` default).
     ``?tail=N`` (N ≥ 1) and ``?since=24h|14d`` match CLI selection;
     when both are present, ``since`` wins. Invalid params are 400 with
     typed ``code``.
  3. With no journal files the body is
     ``{"schema_version": "1", "records": []}``.
  4. Export secret fields (``key``, ``secret``, ``license``, ``balance``)
     are absent at any depth, and the response is served with
     ``Cache-Control: no-store``.

All data lives under an isolated ``KRELLBOT_HOME`` (``tmp_path``). No
live venue, key, or order is touched.
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
    detail: dict | None = None,
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


def _header_map(flat: list[tuple[str, str]]) -> dict[str, str]:
    return {k.lower(): v for k, v in flat}


# ---- gate -----------------------------------------------------------------


def test_journal_route_exists_and_returns_200_with_session(tmp_path: Path) -> None:
    token = "boot-journal-exists"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, flat, body = _get_journal(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert decoded["schema_version"] == "1", decoded
    assert decoded["records"] == [], decoded
    assert _header_map(flat).get("cache-control") == "no-store"


def test_journal_refuses_unauthenticated(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    status, _h, body = _get_journal(
        app,
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}")],
    )
    assert status == 403, (status, body)
    assert json.loads(body) == {"detail": "session required"}, body


def test_journal_refuses_invented_session_cookie(tmp_path: Path) -> None:
    app = _build_app(tmp_path)
    status, _h, _b = _get_journal(
        app,
        headers=_authenticated_headers("not-a-real-session"),
    )
    assert status == 403, status


def test_journal_refuses_non_loopback_origin(tmp_path: Path) -> None:
    token = "boot-journal-origin"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, _b = _get_journal(
        app,
        headers=[
            ("Origin", "http://evil.example.com"),
            ("Cookie", f"krellbot_session={session_value}"),
        ],
    )
    assert status == 403, status


def test_journal_does_not_require_csrf_header(tmp_path: Path) -> None:
    token = "boot-journal-no-csrf"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    headers = _authenticated_headers(session_value)
    headers.append(("X-Krellbot-CSRF", "not-the-real-csrf"))
    status, _h, body = _get_journal(app, headers=headers)
    assert status == 200, (status, body)
    assert _read_json(body)["records"] == []


# ---- selection parity with CLI --------------------------------------------


def test_journal_default_tail_is_five(tmp_path: Path) -> None:
    token = "boot-journal-default-tail"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    records = [_journal_record(ts=1_700_000_000 + i, detail={"pair": "SUIUSD", "n": i}) for i in range(8)]
    _seed_journal(tmp_path, records)

    status, _h, body = _get_journal(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert len(decoded["records"]) == 5
    assert [r["ts"] for r in decoded["records"]] == [1_700_000_003 + i for i in range(5)]


def test_journal_tail_n_returns_last_n(tmp_path: Path) -> None:
    token = "boot-journal-tail-n"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    records = [_journal_record(ts=1_700_000_000 + i) for i in range(6)]
    _seed_journal(tmp_path, records)

    status, _h, body = _get_journal(
        app,
        query="tail=2",
        headers=_authenticated_headers(session_value),
    )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert [r["ts"] for r in decoded["records"]] == [1_700_000_004, 1_700_000_005]


def test_journal_since_24h_filters_window(tmp_path: Path) -> None:
    token = "boot-journal-since-24h"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    now = 1_700_000_000
    _seed_journal(
        tmp_path,
        [
            _journal_record(ts=now - 48 * 3600),
            _journal_record(ts=now - 3 * 3600),
            _journal_record(ts=now),
        ],
    )

    with patch("krellbot.journal.time.time", return_value=float(now)):
        status, _h, body = _get_journal(
            app,
            query="since=24h",
            headers=_authenticated_headers(session_value),
        )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert [r["ts"] for r in decoded["records"]] == [now - 3 * 3600, now]


def test_journal_since_14d_filters_window(tmp_path: Path) -> None:
    token = "boot-journal-since-14d"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    now = 1_700_000_000
    _seed_journal(
        tmp_path,
        [
            _journal_record(ts=now - 15 * 24 * 3600),
            _journal_record(ts=now - 13 * 24 * 3600),
            _journal_record(ts=now),
        ],
    )

    with patch("krellbot.journal.time.time", return_value=float(now)):
        status, _h, body = _get_journal(
            app,
            query="since=14d",
            headers=_authenticated_headers(session_value),
        )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert [r["ts"] for r in decoded["records"]] == [now - 13 * 24 * 3600, now]


def test_journal_since_wins_over_tail(tmp_path: Path) -> None:
    """CLI parity: when both flags appear, the since-window selects."""

    token = "boot-journal-since-wins"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    now = 1_700_000_000
    _seed_journal(
        tmp_path,
        [
            _journal_record(ts=now - 2 * 3600),
            _journal_record(ts=now - 3600),
            _journal_record(ts=now),
        ],
    )

    with patch("krellbot.journal.time.time", return_value=float(now)):
        status, _h, body = _get_journal(
            app,
            query="tail=1&since=24h",
            headers=_authenticated_headers(session_value),
        )
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert len(decoded["records"]) == 3


def test_journal_invalid_tail_is_400(tmp_path: Path) -> None:
    token = "boot-journal-bad-tail"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    for query in ("tail=0", "tail=-1", "tail=abc"):
        status, _h, body = _get_journal(
            app,
            query=query,
            headers=_authenticated_headers(session_value),
        )
        assert status == 400, (query, status, body)
        decoded = _read_json(body)
        assert decoded["code"] == "invalid_tail", decoded


def test_journal_unsupported_since_is_400(tmp_path: Path) -> None:
    token = "boot-journal-bad-since"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    status, _h, body = _get_journal(
        app,
        query="since=7d",
        headers=_authenticated_headers(session_value),
    )
    assert status == 400, (status, body)
    decoded = _read_json(body)
    assert decoded["code"] == "unsupported_since", decoded


# ---- redaction / closed shape ---------------------------------------------


def test_journal_drops_export_secret_fields(tmp_path: Path) -> None:
    token = "boot-journal-secrets"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    _seed_journal(
        tmp_path,
        [
            _journal_record(
                ts=1_700_000_000,
                detail={
                    "pair": "SUIUSD",
                    "key": "should-not-leak",
                    "secret": "also-secret",
                    "license": "lic",
                    "balance": "999",
                    "nested": {"key": "nested-key", "ok": True},
                },
            )
        ],
    )

    status, _h, body = _get_journal(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert len(decoded["records"]) == 1
    detail = decoded["records"][0]["detail"]
    assert "key" not in detail
    assert "secret" not in detail
    assert "license" not in detail
    assert "balance" not in detail
    assert detail["nested"] == {"ok": True}
    assert detail["pair"] == "SUIUSD"


def test_journal_skips_malformed_lines(tmp_path: Path) -> None:
    token = "boot-journal-malformed"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    good = _journal_record(ts=1_700_000_000)
    (journal_dir / "2026-10.jsonl").write_text(
        "not-json\n" + json.dumps(good) + "\n{bad\n",
        encoding="utf-8",
    )

    status, _h, body = _get_journal(app, headers=_authenticated_headers(session_value))
    assert status == 200, (status, body)
    decoded = _read_json(body)
    assert len(decoded["records"]) == 1
    assert decoded["records"][0]["ts"] == 1_700_000_000


def test_journal_includes_non_tick_kinds(tmp_path: Path) -> None:
    """Raw journal browse is not tick-only (unlike alerts / paper history)."""

    token = "boot-journal-kinds"
    app = _build_app(tmp_path, bootstrap_token=token)
    session_value = _bootstrap_session(app, token)
    _seed_journal(
        tmp_path,
        [
            _journal_record(ts=1, kind="tick"),
            _journal_record(
                ts=2,
                kind="supervision",
                pack="-",
                detail={"event": "wake_gap", "gap_s": 9000},
            ),
            _journal_record(ts=3, kind="rate_limit", pack="", detail="rate limit"),
        ],
    )

    status, _h, body = _get_journal(
        app,
        query="tail=10",
        headers=_authenticated_headers(session_value),
    )
    assert status == 200, (status, body)
    kinds = [r["kind"] for r in _read_json(body)["records"]]
    assert kinds == ["tick", "supervision", "rate_limit"]

"""Task E support: `cmd_journal` accepts `--since` and `--json`.

`--since 24h` and `--since 14d` are the only accepted windows. `--json`
prints one JSON object per line of records whose `ts` is inside the
window, exits 0, and drops `key`, `secret`, `license`, and `balance`
fields. Unknown windows exit 2.
"""

from __future__ import annotations

import json

import pytest

from krellbot import journal


def _write_record(ts: int, **detail) -> None:
    journal.append(
        {
            "ts": ts,
            "kind": "tick",
            "venue": "kraken",
            "pack": "p",
            "bar_ts": ts,
            "detail": detail,
        }
    )


def _lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture(autouse=True)
def _isolate_secrets():
    from krellbot import sanitize

    sanitize.register_secret("FAKESECRET")
    yield


def test_journal_since_24h_returns_only_recent_records(home, capsys):
    now = 1_700_000_000
    recent = now - 3 * 3600  # 3 hours ago
    old = now - 48 * 3600  # 48 hours ago

    _write_record(now, pair="SUIUSD", entry_qty="5")
    _write_record(recent, pair="SUIUSD", entry_qty="1")
    _write_record(old, pair="SUIUSD", entry_qty="99")

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--since", "24h"], now=now)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    timestamps = sorted(r["ts"] for r in records)
    assert timestamps == sorted([now, recent])


def test_journal_since_14d_returns_two_weeks_of_records(home, capsys):
    now = 1_700_000_000
    within = now - 13 * 24 * 3600  # 13 days ago
    outside = now - 15 * 24 * 3600  # 15 days ago

    _write_record(now, pair="SUIUSD", entry_qty="1")
    _write_record(within, pair="SUIUSD", entry_qty="2")
    _write_record(outside, pair="SUIUSD", entry_qty="3")

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--since", "14d"], now=now)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    timestamps = sorted(r["ts"] for r in records)
    assert timestamps == sorted([now, within])


def test_journal_since_unknown_window_exits_2(home, capsys):
    _write_record(1_700_000_000, pair="SUIUSD", entry_qty="1")

    from krellbot.cli import cmd_journal

    rc = cmd_journal(["--since", "7d"], now=1_700_000_000)
    captured = capsys.readouterr()

    assert rc == 2
    assert "7d" in captured.err or "7d" in captured.out


def test_journal_json_drops_secret_key_fields(home, capsys):
    from krellbot.cli import cmd_journal

    _write_record(
        1_700_000_000,
        pair="SUIUSD",
        key="FAKESECRET",
        secret="FAKESECRET",
        license="FAKESECRET",
        balance="FAKESECRET",
        note="ok",
    )

    rc = cmd_journal(["--json"], now=1_700_000_000)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert records, "at least one record expected"
    detail = records[-1]["detail"]
    assert "key" not in detail
    assert "secret" not in detail
    assert "license" not in detail
    assert "balance" not in detail
    assert detail.get("note") == "ok"


def test_journal_json_filters_window_with_since(home, capsys):
    from krellbot.cli import cmd_journal

    now = 1_700_000_000
    _write_record(now, pair="SUIUSD", entry_qty="5")
    _write_record(now - 30 * 24 * 3600, pair="SUIUSD", entry_qty="99")

    rc = cmd_journal(["--since", "14d", "--json"], now=now)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert [r["ts"] for r in records] == [now]


def test_journal_tail_still_works_alongside_since(home, capsys):
    from krellbot.cli import cmd_journal

    now = 1_700_000_000
    _write_record(now, pair="SUIUSD", entry_qty="1")
    _write_record(now - 1, pair="SUIUSD", entry_qty="2")
    _write_record(now - 2, pair="SUIUSD", entry_qty="3")

    rc = cmd_journal(["--tail", "2"], now=now)
    out = capsys.readouterr().out

    assert rc == 0
    records = _lines(out)
    assert len(records) == 2

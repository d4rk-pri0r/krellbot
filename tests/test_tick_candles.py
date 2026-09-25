"""Task A: cmd_tick builds a candle reader that calls the public fetch.

When `--offline-candles` is absent, the reader loads the armed pack JSON,
reads `timeframe`, and calls the injected fetch. The test injects a fake
fetch so the real HTTP functions are never called. When `--offline-candles`
is set, the public fetch is bypassed.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


def _write_pack(home: Path, *, tf: str = "1h", pair: str = "SUIUSD") -> Path:
    body = {
        "schema_version": 1,
        "id": "tick-candles",
        "version": "1.0.0",
        "label": "Tick candles",
        "author": "krellbot tests",
        "timeframe": tf,
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": pair}],
    }
    target = home / "tick-candles.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path, *, pair: str = "SUIUSD") -> None:
    from krellbot.config import ArmedPack, Config, save_config

    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id="tick-candles",
                    pack_version="1.0.0",
                    venue="kraken",
                    pair=pair,
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode="paper",
                    starting_cash=Decimal(1000),
                    requires_license=False,
                    armed_at_ts=1,
                )
            ]
        ),
    )


class _RecordingFetch:
    """Records every (venue, pair, tf, transport) the reader passes through."""

    def __init__(self, candles):
        self.candles = candles
        self.calls: list[tuple[str, str, str, object]] = []

    def __call__(self, venue, pair, tf, transport):
        self.calls.append((venue, pair, tf, transport))
        return list(self.candles)


class _SilentTransport:
    """A Kraken-shaped transport that records every call.

    The tick path must never touch a private order URL during a paper tick
    that goes through the fetch reader.
    """

    def __init__(self):
        self.gets: list[str] = []
        self.posts: list[str] = []

    def get(self, url, headers=None):
        self.gets.append(url)
        return {"error": [], "result": {}}

    def post(self, url, form, headers):
        self.posts.append(url)
        return {"error": [], "result": {}}


def test_paper_tick_calls_kraken_fetch_with_pair_and_timeframe(home, fresh_keyring):
    """No `--offline-candles`: the reader fetches via the injected function
    using the armed pack's pair and timeframe. No private order POST lands
    on the transport.
    """
    from krellbot.cli import cmd_tick

    pack_path = _write_pack(home, tf="1h", pair="SUIUSD")
    _arm_paper(home, pack_path, pair="SUIUSD")

    fetch = _RecordingFetch(candles=[])
    transport = _SilentTransport()

    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=transport)

    assert rc == 0
    assert len(fetch.calls) == 1, f"expected one fetch call, got {fetch.calls!r}"
    venue_arg, pair_arg, tf_arg, transport_arg = fetch.calls[0]
    assert venue_arg == "kraken"
    assert pair_arg == "SUIUSD"
    assert tf_arg == "1h"
    assert transport_arg is transport
    private_posts = [u for u in transport.posts if "/0/private/" in u]
    assert not private_posts, f"no private order POST expected, got {private_posts!r}"


def test_offline_candles_does_not_call_public_fetch(home, fresh_keyring):
    """`--offline-candles` set: the public fetch must not be called.

    The offline reader parses the CSV; the fetch function is never invoked.
    """
    from krellbot.cli import cmd_tick

    pack_path = _write_pack(home, tf="1h", pair="SUIUSD")
    _arm_paper(home, pack_path, pair="SUIUSD")

    csv_path = home / "candles.csv"
    csv_path.write_text("ts_ms,open,high,low,close,volume\n0,10,11,9,10,100\n", encoding="utf-8")

    fetch = _RecordingFetch(candles=[])
    transport = _SilentTransport()

    rc = cmd_tick(
        ["--venue", "kraken", "--offline-candles", str(csv_path)],
        fetch=fetch,
        transport=transport,
    )

    assert rc == 0
    assert fetch.calls == [], "fetch must not be called when offline-candles is set"


def test_paper_tick_uses_pack_timeframe_not_some_default(home, fresh_keyring):
    """A pack whose timeframe is `4h` must drive the fetch with `4h`."""

    from krellbot.cli import cmd_tick

    pack_path = _write_pack(home, tf="4h", pair="BTCUSD")
    _arm_paper(home, pack_path, pair="BTCUSD")

    fetch = _RecordingFetch(candles=[])
    transport = _SilentTransport()

    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=transport)

    assert rc == 0
    assert fetch.calls, "fetch must be called once"
    assert fetch.calls[0][1] == "BTCUSD"
    assert fetch.calls[0][2] == "4h"


def test_fetch_error_prints_exception_type_name_and_exits_1(home, fresh_keyring, capsys):
    """A fetch exception is reported by type name only (not the message)
    and the tick exits 1 without inventing a candle.
    """
    from krellbot.cli import cmd_tick

    pack_path = _write_pack(home, tf="1h", pair="SUIUSD")
    _arm_paper(home, pack_path, pair="SUIUSD")

    def boom(venue, pair, tf, transport):
        raise ConnectionError("connection refused: api.example.com")

    transport = _SilentTransport()

    rc = cmd_tick(["--venue", "kraken"], fetch=boom, transport=transport)

    assert rc == 1
    captured = capsys.readouterr()
    assert "ConnectionError" in captured.out
    assert "connection refused" not in captured.out
    assert "***" not in captured.out
    # The error was journaled.
    journal_dir = home / "journal"
    if journal_dir.exists():
        files = sorted(journal_dir.glob("*.jsonl"))
        assert files
        text = files[-1].read_text(encoding="utf-8")
        assert "fetch_error" in text
        assert "ConnectionError" in text


def test_tick_summary_lines_cover_each_outcome():
    from krellbot.cli import _tick_summary_line

    def rec(**detail):
        return {"kind": "tick", "venue": "kraken", "pack": "p", "detail": {"pair": "SUIUSD", **detail}}

    assert _tick_summary_line(rec(reason="entry", entry_qty="2.5"), "paper") == (
        "kraken SUIUSD p (paper): bought 2.5, protective stop resting"
    )
    assert _tick_summary_line(rec(reason="exit", exit_qty="2.5"), "live") == "kraken SUIUSD p (live): sold 2.5"
    assert _tick_summary_line(rec(reason="entry", entry_qty="0", owned_qty_after="2.5"), "paper").endswith(
        "holding 2.5, stop resting"
    )
    assert _tick_summary_line(rec(reason="flat", stop_qty="2.5"), "paper").endswith("stop filled, sold 2.5")
    assert _tick_summary_line(rec(reason="warmup"), "paper").endswith("warming up indicators, no trade")
    assert _tick_summary_line(rec(reason="flat"), "paper").endswith("no signal, staying flat")
    assert _tick_summary_line(rec(reason="no_candles"), "paper").endswith("no closed candle yet, nothing to do")
    assert _tick_summary_line({"kind": "arm"}, "paper") is None


def test_paper_tick_prints_what_it_did(home, fresh_keyring, capsys):
    from krellbot.cli import cmd_tick
    from krellbot.pack.model import Candle

    pack_path = _write_pack(home, tf="1h", pair="SUIUSD")
    _arm_paper(home, pack_path, pair="SUIUSD")
    hour = 3_600_000
    closes = [10, 9, 12]
    candles = [
        Candle(i * hour, Decimal(c), Decimal(c) + 1, Decimal(c) - 1, Decimal(c), Decimal(100))
        for i, c in enumerate(closes)
    ]
    rc = cmd_tick(["--venue", "kraken"], fetch=_RecordingFetch(candles), transport=_SilentTransport())
    out = capsys.readouterr().out
    assert rc == 0
    assert "kraken SUIUSD tick-candles (paper): bought " in out
    assert "protective stop resting" in out

"""`krellbot backtest` without --data: cache first, one public fetch, then cache.

The public fetch is monkeypatched; the suite never touches the network.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import cli
from krellbot.data import cache_path
from krellbot.pack.model import Candle

DAY_MS = 86_400_000

PACK = {
    "schema_version": 1,
    "id": "bt-cache-fixture",
    "version": "1.0.0",
    "label": "fixture",
    "author": "tests",
    "origin": "fixture",
    "timeframe": "1d",
    "indicators": {"sma5": {"fn": "sma", "src": "close", "len": 5}},
    "entry": ["close", ">", "sma5"],
    "exit": ["close", "<", "sma5"],
    "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
    "markets": [{"venue": "kraken", "pair": "XBTUSD"}],
}


def _candles(n: int = 60) -> list[Candle]:
    out = []
    t0 = 1_700_000_000_000 - (1_700_000_000_000 % DAY_MS)
    for i in range(n):
        px = Decimal(100 + (i % 10) * 3 + i)
        out.append(Candle(t0 + i * DAY_MS, px, px + 2, px - 2, px + 1, Decimal(10)))
    return out


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "kb"
    monkeypatch.setenv("KRELLBOT_HOME", str(home))
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps(PACK), encoding="utf-8")
    calls: list[tuple[str, str, str]] = []

    def fake_fetch(venue, pair, tf, transport):
        calls.append((venue, pair, tf))
        return _candles()

    monkeypatch.setattr(cli, "_default_fetch", fake_fetch)
    monkeypatch.setattr(cli, "_default_transport", lambda: None)
    return home, pack, calls


def test_backtest_without_data_fetches_once_then_uses_cache(env, capsys):
    home, pack, calls = env
    assert cli.cmd_backtest([str(pack), "--venue", "kraken"]) == 0
    out1 = capsys.readouterr()
    assert calls == [("kraken", "XBTUSD", "1d")]
    assert "fetched 60 1d candles from kraken public data (cached)" in out1.err
    assert "total_return_pct" in out1.out
    assert cache_path(home, "kraken", "XBTUSD", "1d").exists()

    assert cli.cmd_backtest([str(pack), "--venue", "kraken"]) == 0
    out2 = capsys.readouterr()
    assert calls == [("kraken", "XBTUSD", "1d")]  # no second fetch
    assert "fetched" not in out2.err
    assert out2.out == out1.out  # same cached bytes, same receipt


def test_backtest_without_data_reports_fetch_failure_by_type_only(env, capsys, monkeypatch):
    _, pack, _ = env

    def boom(venue, pair, tf, transport):
        raise ConnectionError("secret-ish detail that must not print")

    monkeypatch.setattr(cli, "_default_fetch", boom)
    assert cli.cmd_backtest([str(pack), "--venue", "kraken"]) == 1
    err = capsys.readouterr().err
    assert "ConnectionError" in err and "--data" in err
    assert "secret-ish" not in err

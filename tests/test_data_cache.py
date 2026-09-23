"""Backtest: cache.py - CSV + JSON manifest on disk."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.data.cache import (
    cache_path,
    manifest_path,
    read_cache,
    sha256_bytes,
    write_cache,
)
from krellbot.pack.model import Candle


def _candle(ts_ms: int, close: str = "10") -> Candle:
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal(1),
    )


def test_cache_write_then_read(tmp_path: Path):
    """write_cache creates a CSV + JSON manifest with a stable sha256."""
    candles = [_candle(0), _candle(3_600_000, "11"), _candle(7_200_000, "12")]
    csv_path, digest = write_cache(tmp_path, "kraken", "SUIUSD", "1h", candles)
    assert csv_path.exists()
    assert manifest_path(tmp_path, "kraken", "SUIUSD", "1h").exists()
    body = csv_path.read_bytes()
    assert sha256_bytes(body) == digest
    out = read_cache(tmp_path, "kraken", "SUIUSD", "1h")
    assert out is not None
    loaded, sha = out
    assert len(loaded) == 3
    assert sha == digest


def test_cache_path_is_stable(tmp_path: Path):
    """cache_path is a pure function of (home, venue, pair, tf)."""
    p = cache_path(tmp_path, "kraken", "SUIUSD", "1h")
    assert p == tmp_path / "cache" / "kraken__SUIUSD__1h.csv"


def test_cache_read_returns_none_when_missing(tmp_path: Path):
    out = read_cache(tmp_path, "kraken", "SUIUSD", "1h")
    assert out is None


def test_cache_manifest_json(tmp_path: Path):
    """Manifest is JSON with sha256, rows, venue, pair, tf."""
    candles = [_candle(0), _candle(3_600_000)]
    write_cache(tmp_path, "coinbase", "BTCUSD", "4h", candles)
    man = json.loads(manifest_path(tmp_path, "coinbase", "BTCUSD", "4h").read_text(encoding="utf-8"))
    assert man["venue"] == "coinbase"
    assert man["pair"] == "BTCUSD"
    assert man["tf"] == "4h"
    assert man["rows"] == 2
    assert len(man["sha256"]) == 64

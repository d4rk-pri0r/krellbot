"""Data: kraken_public.py - OHLC parser + OHLCVT zip import."""

from __future__ import annotations

import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.data.kraken_public import (
    OHLC_TF_MINUTES,
    import_kraken_ohlcvt_zip,
    parse_kraken_ohlc,
)


def _kraken_payload(rows: list[list], pair_key: str = "XSUIZUSD") -> dict:
    return {"result": {"last": 0, pair_key: rows}}


def _row(ts_s: int, o="10", h="11", l="9", c="10", v="100") -> list:
    return [ts_s, o, h, l, c, "10", v, "5"]


def test_kraken_ohlc_ignores_altname_key():
    """The pair key may be XSUIZUSD while the altname is SUIUSD.

    The parser picks the only array-valued key, so the requested altname
    is irrelevant to parsing.
    """
    payload = _kraken_payload(
        [_row(1_700_000_000), _row(1_700_003_600, c="11")],
        pair_key="XSUIZUSD",
    )
    candles = parse_kraken_ohlc(payload, pair="SUIUSD")
    assert len(candles) == 2
    assert candles[0].ts_ms == 1_700_000_000 * 1000
    assert candles[1].ts_ms == 1_700_003_600 * 1000
    assert candles[1].close == Decimal(11)


def test_kraken_ohlc_ignores_vwap_and_count():
    """vwap and count are not in the Candle; their values are ignored."""
    payload = _kraken_payload([_row(1_700_000_000, c="12")])
    candles = parse_kraken_ohlc(payload, pair="SUIUSD")
    assert candles[0].close == Decimal(12)
    assert candles[0].volume == Decimal(100)


def test_kraken_ohlc_drops_forming_bar_when_now_ms_given():
    """When now_ms is passed, drop the bar whose ts_ms + tf_ms > now_ms."""
    payload = _kraken_payload(
        [
            _row(1_700_000_000),
            _row(1_700_003_600, c="11"),
        ],
    )
    # Bar at ts=1_700_003_600 sec -> ms=1_700_003_600_000, closes at +3_600_000.
    # now_ms = 1_700_007_199_999 -> drop the forming bar.
    candles = parse_kraken_ohlc(payload, pair="SUIUSD", now_ms=1_700_007_199_999, tf="1h")
    assert len(candles) == 1
    # now_ms = 1_700_007_200_000 -> keep the bar (closes exactly at now_ms).
    candles = parse_kraken_ohlc(payload, pair="SUIUSD", now_ms=1_700_007_200_000, tf="1h")
    assert len(candles) == 2


def test_kraken_ohlc_rejects_wrong_row_width():
    """A row with != 8 fields raises."""
    payload = _kraken_payload([_row(1_700_000_000), [1, 2, 3]])
    with pytest.raises(ValueError):
        parse_kraken_ohlc(payload, pair="SUIUSD")


def test_kraken_ohlcvt_zip_streams_and_filters(tmp_path: Path):
    """Stream a zip without loading members fully. Pair + interval filter."""
    suiusd = "time,open,high,low,close,volume,count\n1700000000,1,2,1,1,10,1\n1700003600,1,2,1,2,10,1\n"
    btcusd = "time,open,high,low,close,volume,count\n1700000000,100,101,99,100,1,1\n"
    zip_path = tmp_path / "kraken.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("SUIUSD_60.zip", suiusd)
        zf.writestr("BTCUSD_60.zip", btcusd)
    candles = import_kraken_ohlcvt_zip(zip_path, pair="SUIUSD", tf="1h")
    assert len(candles) == 2
    assert candles[0].close == Decimal(1)
    assert candles[1].close == Decimal(2)


def test_kraken_ohlcvt_zip_skips_header_row(tmp_path: Path):
    """A non-numeric first field is the header row; it is skipped."""
    body = "time,open,high,low,close,volume,count\n1700000000,1,2,1,1,10,1\n"
    zip_path = tmp_path / "kraken.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("SUIUSD_60.csv", body)
    candles = import_kraken_ohlcvt_zip(zip_path, pair="SUIUSD", tf="1h")
    assert len(candles) == 1
    assert candles[0].ts_ms == 1_700_000_000 * 1000


def test_ohlc_tf_minutes_table():
    """Timeframe -> minutes table used to filter zip members."""
    assert OHLC_TF_MINUTES == {"1h": 60, "4h": 240, "1d": 1440}

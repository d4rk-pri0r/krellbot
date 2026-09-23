"""Data: gaps.py - refuse a series missing more than 1% of bars."""

from __future__ import annotations

from decimal import Decimal

import pytest

from krellbot.data.gaps import GapError, check_gaps
from krellbot.pack.model import Candle


def _candle(ts_ms: int) -> Candle:
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(1),
        high=Decimal(1),
        low=Decimal(1),
        close=Decimal(1),
        volume=Decimal(1),
    )


def test_gap_over_1pct_refused():
    """A 10-bar 1h series missing 2 of 11 expected bars fails.

    expected = (last - first) / tf_ms + 1 = (10 * 3_600_000) / 3_600_000 + 1 = 11.
    actual = 9. missing = 2. (2 / 11) > 0.01 -> refuse.
    """
    candles = [_candle(i * 3_600_000) for i in range(10) if i != 4 and i != 7]
    # bars 0..9 inclusive would be 10; we dropped 4 and 7 -> 8 candles? Let me recount.
    # We want missing 2 out of 11. expected=11, actual=9.
    # Need 11 expected. first=0, last=10*3_600_000. (10*3_600_000) / 3_600_000 + 1 = 11. actual=9. missing=2.
    # We dropped i in {4, 7}, leaving 0,1,2,3,5,6,8,9 = 8 candles. Need 9.
    # Let me redo: 11 expected, 9 actual, drop 2.
    candles = []
    for i in range(11):
        if i not in (4, 7):
            candles.append(_candle(i * 3_600_000))
    assert len(candles) == 9
    with pytest.raises(GapError) as ei:
        check_gaps(candles, "1h", pair="SUIUSD")
    msg = str(ei.value)
    assert "SUIUSD" in msg
    assert "missing" in msg


def test_gap_under_1pct_allowed():
    """A series missing <=1% does not raise."""
    # 100 expected bars, 99 actual -> 1% missing, allowed.
    candles = [_candle(i * 3_600_000) for i in range(99)]
    check_gaps(candles, "1h", pair="SUIUSD")  # must not raise


def test_gap_allow_gaps_suppresses_error():
    """allow_gaps=True lets through any missing rate."""
    candles = [_candle(i * 3_600_000) for i in range(11) if i not in (4, 7)]
    check_gaps(candles, "1h", pair="SUIUSD", allow_gaps=True)


def test_gap_no_missing_does_not_raise():
    """A perfectly contiguous series passes."""
    candles = [_candle(i * 3_600_000) for i in range(5)]
    check_gaps(candles, "1h")

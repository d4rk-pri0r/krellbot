"""Data: candles.py - parse_timestamp unit detection and drop_forming."""

from __future__ import annotations

from decimal import Decimal

import pytest

from krellbot.data.candles import TF_MS, drop_forming, parse_timestamp
from krellbot.pack.model import Candle


def _c(ts_ms: int, close: str = "10") -> Candle:
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=Decimal(1),
    )


def test_timestamp_units_s_ms_us():
    """Pick the unit by magnitude: s for <1e11, ms for <1e14, us otherwise.

    1_700_000_000 seconds is a 2023-2024-era unix timestamp; the parser
    treats anything below 1e11 as seconds. A string of digits is also
    accepted. Anything that is not a digit string raises.
    """
    # seconds: < 1e11
    assert parse_timestamp(1_700_000_000) == 1_700_000_000 * 1000
    # milliseconds: 1e11 <= n < 1e14
    assert parse_timestamp(1_700_000_000_000) == 1_700_000_000_000
    # microseconds: >= 1e14
    assert parse_timestamp(1_700_000_000_000_000) == 1_700_000_000_000_000 // 1000
    # string of digits is allowed
    assert parse_timestamp("1700000000") == 1_700_000_000 * 1000
    assert parse_timestamp("1700000000000") == 1_700_000_000_000


def test_timestamp_rejects_non_digit_string():
    """Strings that are not pure digits raise. Same for non-int/non-str."""
    with pytest.raises(ValueError):
        parse_timestamp("1700000000.0")
    with pytest.raises(ValueError):
        parse_timestamp("not-a-number")
    with pytest.raises(TypeError):
        parse_timestamp(1.5)  # float is not int or str
    with pytest.raises(ValueError):
        parse_timestamp("")


def test_forming_bar_dropped():
    """drop_forming trims a bar whose ts_ms + tf_ms > now_ms.

    A bar that closed exactly at now_ms stays. The forming bar (ts_ms +
    tf_ms > now_ms) is removed.
    """
    # 1h timeframe = 3_600_000 ms. Bar at ts=0 closes at ts=3_600_000.
    candles = [
        _c(0),
        _c(3_600_000),
        _c(7_200_000),  # closes at 10_800_000
        _c(10_800_000),  # closes at 14_400_000
    ]
    # now_ms = 10_800_000: keep bars whose ts + 3_600_000 <= 10_800_000
    # = bars at ts 0, 3_600_000, 7_200_000 (ts + tf = 10_800_000, exactly equal -> keep)
    out = drop_forming(candles, "1h", 10_800_000)
    assert [c.ts_ms for c in out] == [0, 3_600_000, 7_200_000]

    # now_ms = 10_799_999: the bar at ts=7_200_000 has ts+tf = 10_800_000 > 10_799_999 -> drop.
    out2 = drop_forming(candles, "1h", 10_799_999)
    assert [c.ts_ms for c in out2] == [0, 3_600_000]

    # now_ms very large: keep everything
    out3 = drop_forming(candles, "1h", 1_000_000_000)
    assert [c.ts_ms for c in out3] == [0, 3_600_000, 7_200_000, 10_800_000]


def test_tf_ms_constants():
    """Timeframe table: 1h, 4h, 1d."""
    assert TF_MS["1h"] == 3_600_000
    assert TF_MS["4h"] == 14_400_000
    assert TF_MS["1d"] == 86_400_000

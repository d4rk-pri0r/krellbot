"""Candle parsing: timestamp units, forming-bar drop, in-memory shapes.

All timestamp arithmetic is in milliseconds. `parse_timestamp` accepts an
int or a numeric string and picks the unit by magnitude; anything that does
not fit the rule raises. `drop_forming` trims the half-finished bar at the
right edge, given a now_ms in milliseconds.

This module has no sibling imports to avoid circular deps; parsers live in
kraken_public / coinbase_public.
"""

from __future__ import annotations

__all__ = [
    "TF_MS",
    "drop_forming",
    "parse_timestamp",
]


TF_MS: dict[str, int] = {
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


def parse_timestamp(n: int | str) -> int:
    """Return milliseconds.

    Unit is picked by magnitude:
      * n < 10**11  -> seconds
      * n < 10**14  -> milliseconds
      * else        -> microseconds
    Strings of digits are accepted; everything else raises.
    """
    if isinstance(n, bool):
        raise TypeError(f"parse_timestamp: expected int or digit-string, got {type(n).__name__}")
    if isinstance(n, int):
        value = n
    elif isinstance(n, str):
        if not n or not n.isdigit():
            raise ValueError(f"parse_timestamp: not a digit string: {n!r}")
        value = int(n)
    else:
        raise TypeError(f"parse_timestamp: expected int or digit string, got {type(n).__name__}")
    if value < 10**11:
        return value * 1000
    if value < 10**14:
        return value
    return value // 1000


def drop_forming(candles: list, tf: str, now_ms: int) -> list:
    """Return candles whose `ts_ms + tf_ms <= now_ms`.

    A bar whose `ts_ms + tf_ms` equals `now_ms` exactly stays (it just closed).
    Anything beyond `now_ms` is half-formed and is dropped.
    """
    tf_ms = TF_MS[tf]
    return [c for c in candles if c.ts_ms + tf_ms <= now_ms]

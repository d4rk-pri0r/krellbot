"""Event-time order validation and gap detection for candle series.

expected = (last_ts - first_ts) / tf_ms + 1. If (expected - actual) / expected
> 0.01, the error names the pair and the missing count, unless the caller
passed `allow_gaps=True`.
Adjacent decreasing timestamps always refuse, including with `allow_gaps=True`.
Equal timestamps retain the existing duplicate behavior.
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import pairwise

from krellbot.pack.model import Candle

from .candles import TF_MS


class GapError(ValueError):
    """Raised for decreasing timestamps or more than 1% missing bars."""


def check_gaps(
    candles: list[Candle],
    tf: str,
    now_ms: int | None = None,
    *,
    pair: str = "",
    allow_gaps: bool = False,
) -> None:
    """Raise `GapError` for decreasing timestamps or more than 1% missing bars.

    `now_ms` is optional; when given, the expected count treats the most
    recent bar as the one whose `ts_ms + tf_ms` <= now_ms. When not given,
    the expected count is derived from the series's own first and last
    bar. The error names the pair and the missing count.
    """
    if not candles:
        return
    tf_ms = TF_MS[tf]
    for index, (previous, current) in enumerate(pairwise(candles), start=1):
        if previous.ts_ms > current.ts_ms:
            raise GapError(
                f"event-time order refusal: pair={pair!r} tf={tf} index={index} "
                f"previous_ts={previous.ts_ms} ts={current.ts_ms}"
            )
    first = candles[0].ts_ms
    last = candles[-1].ts_ms
    expected = (last - first) // tf_ms + 1
    actual = len(candles)
    if expected <= 0:
        return
    missing = expected - actual
    if missing <= 0:
        return
    if missing / expected <= 0.01:
        return
    if allow_gaps:
        return
    raise GapError(f"gap refusal: pair={pair!r} tf={tf} missing={missing} expected={expected} actual={actual}")


def dedupe(candles: Iterable[Candle]) -> list[Candle]:
    """Return candles sorted by ts_ms with duplicates removed (last wins)."""
    out: dict[int, Candle] = {}
    for c in candles:
        out[c.ts_ms] = c
    return [out[k] for k in sorted(out)]

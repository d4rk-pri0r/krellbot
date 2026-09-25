"""Coinbase public candles parser + paginated transport.

Tests inject a transport. The HTTP layer (`urllib.request`) is never called
from tests.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from decimal import Decimal
from typing import Protocol

from krellbot.pack.model import Candle

COINBASE_URL = "https://api.coinbase.com/api/v3/brokerage/market/products/{product_id}/candles"
COINBASE_GRANULARITY: dict[str, str] = {"1h": "ONE_HOUR", "4h": "FOUR_HOUR", "1d": "ONE_DAY"}
PAGE_LIMIT = 350
MAX_REQUESTS = 100


class Transport(Protocol):
    """Anything with a `get(url, params)` that returns a parsed JSON dict.

    params is a dict of string->str. Implementations build the URL however
    they want. Tests pass a fake that records the requests it sees.
    """

    def get(self, url: str, params: dict[str, str]) -> dict:  # pragma: no cover - protocol
        ...


class HttpTransport:
    """The real transport. Uses urllib; tests must not call this."""

    def get(self, url: str, params: dict[str, str]) -> dict:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        full = f"{url}?{qs}" if qs else url
        req = urllib.request.Request(full, headers={"user-agent": "krellbot/0.1"})
        from krellbot.tls import urlopen

        with urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))


class TransportError(RuntimeError):
    """Raised when the transport returns a non-2xx or a malformed body."""


def fetch_coinbase_candles(
    product_id: str,
    tf: str,
    transport: Transport,
    start_unix_s: int | None = None,
    end_unix_s: int | None = None,
) -> list[Candle]:
    """Pull all Coinbase candles in 350-bar pages for `product_id` and `tf`.

    Pagination rule: walk forward in 350-bar windows of `tf`, asking for
    `start` = last bar's `start + tf_seconds`, until a window returns zero
    rows. Hard cap at 100 requests; raise if exceeded. Sort ascending and
    dedupe on `start`.
    """
    if tf not in COINBASE_GRANULARITY:
        raise ValueError(f"coinbase: unsupported timeframe {tf!r}")
    granularity = COINBASE_GRANULARITY[tf]
    url = COINBASE_URL.format(product_id=product_id)
    tf_seconds = {"1h": 3600, "4h": 14_400, "1d": 86_400}[tf]

    seen: set[int] = set()
    out: list[Candle] = []
    cursor = start_unix_s
    requests = 0
    while True:
        requests += 1
        if requests > MAX_REQUESTS:
            raise TransportError(f"coinbase: pagination exceeded {MAX_REQUESTS} requests for {product_id}")
        params: dict[str, str] = {"granularity": granularity, "limit": str(PAGE_LIMIT)}
        if cursor is not None:
            params["start"] = str(cursor)
        if end_unix_s is not None:
            params["end"] = str(end_unix_s)
        body = transport.get(url, params)
        rows = body.get("candles") or []
        if not rows:
            break
        added = 0
        for row in rows:
            candle = _row_to_candle(row)
            if candle is None:
                continue
            if candle.ts_ms in seen:
                continue
            seen.add(candle.ts_ms)
            out.append(candle)
            added += 1
        if added == 0:
            break
        # Move the cursor to the last bar we received + one tf.
        last = max(candle.ts_ms for candle in out[-added:])
        cursor = last // 1000 + tf_seconds
    out.sort(key=lambda c: c.ts_ms)
    return out


def parse_coinbase_candles(body: dict) -> list[Candle]:
    """Parse a single Coinbase `/candles` body. Sorted, deduped on `start`."""
    rows = body.get("candles") or []
    seen: set[int] = set()
    out: list[Candle] = []
    for row in rows:
        candle = _row_to_candle(row)
        if candle is None or candle.ts_ms in seen:
            continue
        seen.add(candle.ts_ms)
        out.append(candle)
    out.sort(key=lambda c: c.ts_ms)
    return out


def _row_to_candle(row: dict) -> Candle | None:
    """Parse one Coinbase candle row. Required keys: start, low, high, open, close, volume.

    All values are strings. `start` is unix seconds.
    """
    if not isinstance(row, dict):
        return None
    try:
        start = int(row["start"])
        ts_ms = start * 1000
        return Candle(
            ts_ms=ts_ms,
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
            volume=Decimal(str(row["volume"])),
        )
    except (KeyError, ValueError, TypeError):
        return None

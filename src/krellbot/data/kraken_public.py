"""Kraken public OHLC: JSON parser + OHLCVT zip import.

The HTTP function `fetch_kraken_ohlc` is a thin wrapper tests never call.
Tests pass a pre-fetched JSON object to `parse_kraken_ohlc` directly, and a
fake zip path to `import_kraken_ohlcvt_zip`.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.request
import zipfile
from decimal import Decimal
from pathlib import Path

from krellbot.pack.model import Candle

from .candles import drop_forming, parse_timestamp

OHLC_URL = "https://api.kraken.com/0/public/OHLC"
OHLC_TF_MINUTES: dict[str, int] = {"1h": 60, "4h": 240, "1d": 1440}
OHLC_CAP = 720


def fetch_kraken_ohlc(pair: str, tf: str) -> list[Candle]:
    """Fetch one window of Kraken OHLC. Returns up to 720 closed candles.

    Network is only used here; tests must call `parse_kraken_ohlc` directly.
    The 'last' integer in the response is ignored; the most recent array in
    the pair key is the forming bar and is dropped after fetching.
    """
    if tf not in OHLC_TF_MINUTES:
        raise ValueError(f"kraken: unsupported timeframe {tf!r}")
    interval = OHLC_TF_MINUTES[tf]
    url = f"{OHLC_URL}?pair={pair}&interval={interval}"
    req = urllib.request.Request(url, headers={"user-agent": "krellbot/0.1"})
    from krellbot.tls import urlopen

    with urlopen(req, timeout=20) as resp:
        body = resp.read()
    payload = json.loads(body.decode("utf-8"))
    candles = parse_kraken_ohlc(payload, pair=pair, tf=tf)
    return candles[-OHLC_CAP:]


def parse_kraken_ohlc(payload: dict, pair: str, now_ms: int | None = None, tf: str = "1h") -> list[Candle]:
    """Turn a Kraken `/public/OHLC` response into a sorted list of Candle.

    The pair key in `payload["result"]` may not equal the requested altname
    (e.g. `SUIUSD` arrives as `XSUIZUSD`). The only array-valued key in
    `payload["result"]` is the candles for the pair; use it. When `now_ms`
    is given, drop any bar whose `ts_ms + tf_ms` exceeds it (the forming
    bar). Without `now_ms`, return everything sorted.
    """
    result = payload.get("result")
    if not isinstance(result, dict):
        raise TypeError("kraken: response.result is not an object")
    pair_key = _find_pair_key(result, pair)
    rows = result[pair_key]
    if not isinstance(rows, list):
        raise TypeError("kraken: pair key is not an array")
    candles: list[Candle] = []
    for row in rows:
        if not (isinstance(row, list) and len(row) == 8):
            raise ValueError(
                f"kraken: row must have 8 fields, got {len(row) if isinstance(row, list) else type(row).__name__}"
            )
        ts_str, open_s, high_s, low_s, close_s, _vwap, vol_s, _count = row
        candles.append(
            Candle(
                ts_ms=parse_timestamp(ts_str),
                open=Decimal(str(open_s)),
                high=Decimal(str(high_s)),
                low=Decimal(str(low_s)),
                close=Decimal(str(close_s)),
                volume=Decimal(str(vol_s)),
            )
        )
    candles.sort(key=lambda c: c.ts_ms)
    if now_ms is not None:
        candles = drop_forming(candles, tf, now_ms)
    return candles


def _find_pair_key(result: dict, requested_pair: str) -> str:
    """Find the single array-valued key inside `result`.

    Kraken uses an internal name like `XSUIZUSD` for the altname `SUIUSD`.
    The only array-valued key in the response belongs to the pair we asked
    for. Do not match by name.
    """
    array_keys = [k for k, v in result.items() if isinstance(v, list) and k != "last"]
    if len(array_keys) != 1:
        raise ValueError(
            f"kraken: expected exactly one pair key, got {len(array_keys)} ({array_keys!r}); "
            f"requested={requested_pair!r}"
        )
    return array_keys[0]


def import_kraken_ohlcvt_zip(path: str | Path, pair: str, tf: str) -> list[Candle]:
    """Stream a Kraken OHLCVT zip, parse matching members, return sorted candles.

    A member is used only when its complete basename stem (case-insensitive)
    is exactly `pair + '_' + interval minutes`, with a `.csv` suffix
    (case-insensitive). The `.zip` suffix stays accepted for the legacy
    fixture that stores a CSV payload under a zip name; nested zip payloads
    are never unpacked. Directory entries are skipped, and the parent
    directory cannot supply a missing pair or interval token: matching looks
    at the basename only, never the full archive path. No alias, prefix or
    substring matching - `SUIUSDT_60.csv` is not `SUIUSD_60.csv` and
    `SUIUSD_160.csv` is not a 60-minute member.

    CSV rows are read lazily through the ZipExtFile handle - never loaded
    fully into memory before filtering. The first field of every row must be
    numeric; otherwise the row is skipped (handles a header row without
    crashing).
    """
    if tf not in OHLC_TF_MINUTES:
        raise ValueError(f"kraken zip: unsupported timeframe {tf!r}")
    minutes = str(OHLC_TF_MINUTES[tf])
    candles: list[Candle] = []
    with zipfile.ZipFile(str(path), "r") as zf:
        for name in zf.namelist():
            if not _member_matches(name, pair, minutes):
                continue
            with zf.open(name, "r") as fh:
                wrapper = io.TextIOWrapper(fh, encoding="utf-8", newline="")
                reader = csv.reader(wrapper)
                for row in reader:
                    if not row:
                        continue
                    first = row[0].strip()
                    if not _is_numeric(first):
                        continue
                    if len(row) != 7:
                        continue
                    time_s, open_s, high_s, low_s, close_s, vol_s, _count = row
                    candles.append(
                        Candle(
                            ts_ms=parse_timestamp(time_s.strip()),
                            open=Decimal(open_s.strip()),
                            high=Decimal(high_s.strip()),
                            low=Decimal(low_s.strip()),
                            close=Decimal(close_s.strip()),
                            volume=Decimal(vol_s.strip()),
                        )
                    )
    candles.sort(key=lambda c: c.ts_ms)
    return candles


# `.csv` is the documented member name; `.zip` is kept only for the legacy
# fixture that stores a CSV payload under a zip name.
_MEMBER_SUFFIXES = (".csv", ".zip")


def _member_matches(name: str, pair: str, minutes: str) -> bool:
    """True when member `name` is the `pair`/`minutes` OHLCVT CSV by basename.

    Only the basename (after the last `/`) is considered, so a directory
    component never satisfies the identity. The stem must equal
    `pair + '_' + minutes` exactly, case-insensitively; the requested pair and
    interval tokens must be complete, so near-collisions such as `SUIUSDT`,
    `160` for `60`, or a stem holding only one of the two tokens never match.
    """
    if name.endswith("/"):
        return False
    basename = name.rsplit("/", 1)[-1].lower()
    for suffix in _MEMBER_SUFFIXES:
        if basename.endswith(suffix):
            stem = basename[: -len(suffix)]
            return stem == f"{pair.lower()}_{minutes}"
    return False


def _is_numeric(s: str) -> bool:
    if not s:
        return False
    if s[0] in "+-":
        s = s[1:]
    return s.isdigit()

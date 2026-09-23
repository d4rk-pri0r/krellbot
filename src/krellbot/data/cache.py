"""CSV candle cache + JSON manifest.

One CSV per `(venue, pair, tf)` lives under `<KRELLBOT_HOME>/cache/`. The
manifest is a sibling `.manifest.json` with `{sha256, rows, venue, pair, tf}`.
The `sha256` is the hex digest of the CSV bytes, not of any in-memory form.
"""

from __future__ import annotations

import hashlib
import io
import json
from decimal import Decimal
from pathlib import Path

from krellbot import paths as kb_paths
from krellbot.pack.model import Candle

CSV_HEADER = "ts_ms,open,high,low,close,volume"


def sha256_bytes(data: bytes) -> str:
    """Hex sha256 of `data`."""
    return hashlib.sha256(data).hexdigest()


def cache_path(home: Path, venue: str, pair: str, tf: str) -> Path:
    """Return `<home>/cache/<venue>__<pair>__<tf>.csv`."""
    safe_pair = pair.replace("/", "_")
    return Path(home) / "cache" / f"{venue}__{safe_pair}__{tf}.csv"


def manifest_path(home: Path, venue: str, pair: str, tf: str) -> Path:
    """Return the manifest sibling of `cache_path(home, venue, pair, tf)`."""
    return cache_path(home, venue, pair, tf).with_suffix(".manifest.json")


def write_cache(
    home: Path,
    venue: str,
    pair: str,
    tf: str,
    candles: list[Candle],
) -> tuple[Path, str]:
    """Write CSV + manifest. Returns (csv_path, sha256).

    The CSV is written with utf-8 + \\n newlines, no BOM. The sha256 is taken
    over the bytes that hit disk, not the bytes the caller had in memory.
    """
    csv_path = cache_path(home, venue, pair, tf)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    body = _render_csv(candles)
    kb_paths.atomic_write(csv_path, body, mode=0o600)
    digest = sha256_bytes(body)
    manifest = {
        "sha256": digest,
        "rows": len(candles),
        "venue": venue,
        "pair": pair,
        "tf": tf,
    }
    kb_paths.atomic_write(
        manifest_path(home, venue, pair, tf),
        json.dumps(manifest, sort_keys=True).encode("utf-8"),
        mode=0o600,
    )
    return csv_path, digest


def read_cache(
    home: Path,
    venue: str,
    pair: str,
    tf: str,
) -> tuple[list[Candle], str] | None:
    """Return `(candles, sha256)` if the cache exists, else `None`.

    The sha256 is read from the manifest so the backtest can record the
    exact bytes the cache currently holds.
    """
    csv_path = cache_path(home, venue, pair, tf)
    man_path = manifest_path(home, venue, pair, tf)
    if not csv_path.exists() or not man_path.exists():
        return None
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    body = csv_path.read_bytes()
    return _parse_csv(body), manifest["sha256"]


def _render_csv(candles: list[Candle]) -> bytes:
    """Render candles to CSV bytes. Newline-terminated, no trailing newline gymnastics."""
    out = io.StringIO()
    out.write(CSV_HEADER + "\n")
    for c in candles:
        out.write(f"{c.ts_ms},{c.open},{c.high},{c.low},{c.close},{c.volume}\n")
    return out.getvalue().encode("utf-8")


def _parse_csv(body: bytes) -> list[Candle]:
    """Parse CSV bytes (with or without header) into candles. Skips bad rows."""
    text = body.decode("utf-8")
    out: list[Candle] = []
    seen_header = False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if not seen_header and line.startswith("ts_ms,"):
            seen_header = True
            continue
        parts = line.split(",")
        if len(parts) != 6:
            continue
        try:
            out.append(
                Candle(
                    ts_ms=int(parts[0]),
                    open=Decimal(parts[1]),
                    high=Decimal(parts[2]),
                    low=Decimal(parts[3]),
                    close=Decimal(parts[4]),
                    volume=Decimal(parts[5]),
                )
            )
        except (ValueError, IndexError):
            continue
    return out

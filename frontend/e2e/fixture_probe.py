#!/usr/bin/env python3
"""NS20 fixture probe: proves the edit dataset produces a different
backtest result at ``sma2.len = 2`` vs ``sma2.len = 20``.

Run with ``uv run python frontend/e2e/fixture_probe.py``. When invoked
without arguments, the probe writes ``frontend/e2e/fixtures/edit.csv``
exactly as the Playwright global-setup will. When invoked with a path
argument, the probe reads the existing CSV and runs both backtests.

The probe is stdlib-only for the dataset writer (``csv`` + ``math``).
``ResearchService`` is imported from the installed package, so a test
runner using the same venv can exercise it without network or fixtures.

Output (one line per run):

    edit.csv rows=400 from=0 to=...
    sma2.len=2 equity=<...> trade_count=<...>
    sma2.len=20 equity=<...> trade_count=<...>
    DIFFERENT=YES equity_changed=<bool> trade_changed=<bool>

The script exits 0 only when the two results differ in either equity
or trade count. If they do not differ the script exits 1 and prints
the failing line so the harness operator can rebuild the fixture.
"""

from __future__ import annotations

import csv
import math
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

# We deliberately do NOT touch sys.path here: the probe runs under the
# repo venv (``uv run``) so the installed ``krellbot`` package is
# already importable. If this file is moved or invoked differently the
# import below will raise ImportError and the operator gets a clear
# message — the brief never asks this script to be portable.


def write_edit_csv(path: Path, *, rows: int = 400, base_ts_ms: int = 1_700_000_000_000,
                   tf_ms: int = 3_600_000) -> Path:
    """Write a deterministic zig-zag CSV with the NS20 candle schema.

    ``ts_ms,open,high,low,close,volume``. Close alternates with a slow
    sine so that an SMA(2) and an SMA(20) take opposite positions on
    the bar — enough to flip the entry/exit crossovers on a
    ``close crosses_above/below sma2`` rule. Volume is a small positive
    integer so the dataset does not look degenerate.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_needed = max(2, rows)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for index in range(rows_needed):
            ts_ms = base_ts_ms + index * tf_ms
            # Zig-zag close around 100 with a slow sine drift. SMA(2)
            # tracks close closely, SMA(20) lags by ~10 bars. The sin
            # amplitude (12) and the alternating noise keep the two
            # crossovers out of phase long enough to change trade count.
            drift = 12.0 * math.sin(index / 18.0)
            close = 100.0 + drift + ((-1.0) ** index) * 1.5
            open_ = close - 0.5
            high = max(open_, close) + 0.25
            low = min(open_, close) - 0.25
            writer.writerow([
                ts_ms,
                f"{open_:.4f}",
                f"{high:.4f}",
                f"{low:.4f}",
                f"{close:.4f}",
                1,
            ])
    return path


def _pack(sma_len: int) -> dict:
    return {
        "schema_version": 1,
        "id": "ns20-e2e",
        "version": "1.0.0",
        "label": "NS20 fixture probe",
        "author": "ns20-e2e",
        "timeframe": "1h",
        "indicators": {
            "sma2": {"fn": "sma", "src": "close", "len": int(sma_len)},
        },
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {
            "max_account_pct": 100,
            "stop": {"type": "pct", "pct": 50},
        },
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


def run_backtest(csv_path: Path, sma_len: int) -> tuple[float, int]:
    """Run the canonical ResearchService over ``csv_path`` once.

    Returns ``(equity, trade_count)`` as floats/ints. Imports
    ``ResearchService`` lazily so the dataset-only path still works
    without the krellbot package installed. ``from_ms=0`` and
    ``to_ms`` left as ``None`` so the engine takes every bar; an
    explicit ``to_ms=0`` would filter out every candle (the engine
    uses ``<=`` on ``to_ms``).
    """
    from krellbot.application.research import ResearchRequest, ResearchService

    pack_path = Path(tempfile.mkstemp(prefix="ns20-probe-", suffix=".json")[1])
    home = Path(tempfile.mkdtemp(prefix="ns20-probe-home-"))
    try:
        import json as _json

        pack_path.write_text(_json.dumps(_pack(sma_len)), encoding="utf-8")
        service = ResearchService(home=home)
        request = ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            dataset_csv=csv_path,
            starting_cash=Decimal(10000),
            fee_bps=10,
            from_ms=0,
            to_ms=None,
        )
        result = service.run(request)
    finally:
        try:
            pack_path.unlink()
        except OSError:
            pass
    if not result.ok or not result.legacy_receipt:
        raise SystemExit(f"backtest failed: {result.refusal}")
    metrics = result.legacy_receipt.get("metrics", {})
    equity = float(metrics.get("total_return_pct", 0.0))
    trade_count = int(metrics.get("trade_count", 0))
    return equity, trade_count


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        csv_path = Path(argv[1])
        if not csv_path.exists():
            print(f"ERROR: csv not found at {csv_path}", file=sys.stderr)
            return 2
    else:
        csv_path = Path(__file__).parent / "fixtures" / "edit.csv"
        write_edit_csv(csv_path)

    rows = sum(1 for _ in csv_path.open("r", encoding="utf-8")) - 1
    first_ts = int(csv_path.open("r", encoding="utf-8").readlines()[1].split(",")[0])
    last_line = csv_path.open("r", encoding="utf-8").readlines()[-1]
    last_ts = int(last_line.split(",")[0])
    print(f"edit.csv rows={rows} from={first_ts} to={last_ts} path={csv_path}")

    eq2, tc2 = run_backtest(csv_path, sma_len=2)
    eq20, tc20 = run_backtest(csv_path, sma_len=20)
    print(f"sma2.len=2 equity={eq2} trade_count={tc2}")
    print(f"sma2.len=20 equity={eq20} trade_count={tc20}")
    equity_changed = eq2 != eq20
    trade_changed = tc2 != tc20
    different = "YES" if (equity_changed or trade_changed) else "NO"
    print(
        f"DIFFERENT={different} equity_changed={equity_changed} trade_changed={trade_changed}"
    )
    return 0 if different == "YES" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
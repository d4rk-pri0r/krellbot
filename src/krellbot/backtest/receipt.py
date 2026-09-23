"""Receipt: the locked JSON shape the CLI emits.

Keys exactly: engine_version, pack_sha256, data_manifest_sha256, venue,
pair, tf, from, to, fee_bps, slippage_bps, slippage_mult, metrics,
equity_curve.

The equity_curve is downsampled from the per-bar total-return series to at
most 64 points; the last point is always the final bar's return.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from decimal import Decimal
from typing import Any

from krellbot import __version__ as ENGINE_VERSION

from .engine import BarRecord
from .metrics import buy_and_hold_curve, compute_metrics


def pack_sha256(pack: dict) -> str:
    """sha256 of the canonical pack JSON: sort_keys=True, no whitespace."""
    body = json.dumps(pack, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def downsample(curve: list[float], max_points: int = 64) -> list[float]:
    """Downsample `curve` to `max_points` numbers; last point is preserved."""
    n = len(curve)
    if n <= max_points:
        return list(curve)
    if max_points < 2:
        return [curve[-1]]
    last_idx = n - 1
    indices: list[int] = []
    for i in range(max_points):
        idx = round(i * last_idx / (max_points - 1))
        if not indices or idx > indices[-1]:
            indices.append(idx)
    if indices[-1] != last_idx:
        indices.append(last_idx)
    return [curve[i] for i in indices[:max_points]]


def build_receipt(
    pack: dict,
    records: list[BarRecord],
    trade_count: int,
    data_manifest_sha256: str,
    venue: str,
    pair: str,
    tf: str,
    fee_bps: int,
    slippage_bps: int,
    slippage_mult: float,
    starting_cash: Decimal = Decimal(10000),
) -> dict[str, Any]:
    """Build the locked JSON receipt shape."""
    curve = [(r.ts_ms, r.equity) for r in records]
    bars_in_market = sum(1 for r in records if r.qty_after > 0)
    bar_count = len(records)
    metrics = compute_metrics(curve, trade_count, bars_in_market, bar_count, starting_cash)
    bh_curve = buy_and_hold_curve(records, starting_cash, fee_bps, slippage_bps, slippage_mult)
    bh_trade_count = 0
    bh_bars_in_market = len(records) - 1 if len(records) >= 2 else 0  # after entry at bar 1
    bh_metrics = compute_metrics(bh_curve, bh_trade_count, bh_bars_in_market, bar_count, starting_cash)
    per_bar_returns = [(eq / starting_cash - Decimal(1)) * Decimal(100) for _ts, eq in curve]
    equity_curve = [float(v) for v in per_bar_returns]
    equity_curve = downsample(equity_curve, 64)
    if equity_curve and abs(equity_curve[-1] - metrics.total_return_pct) > 0.01:
        equity_curve[-1] = metrics.total_return_pct

    from_s, to_s = _date_range(records)
    receipt = {
        "engine_version": ENGINE_VERSION,
        "pack_sha256": pack_sha256(pack),
        "data_manifest_sha256": data_manifest_sha256,
        "venue": venue,
        "pair": pair,
        "tf": tf,
        "from": from_s,
        "to": to_s,
        "fee_bps": int(fee_bps),
        "slippage_bps": int(slippage_bps),
        "slippage_mult": float(slippage_mult),
        "metrics": {
            "total_return_pct": metrics.total_return_pct,
            "cagr_pct": metrics.cagr_pct,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "return_to_dd": metrics.return_to_dd,
            "per_year": metrics.per_year,
            "trade_count": metrics.trade_count,
            "exposure_pct": metrics.exposure_pct,
            "buy_and_hold": {
                "total_return_pct": bh_metrics.total_return_pct,
                "cagr_pct": bh_metrics.cagr_pct,
                "max_drawdown_pct": bh_metrics.max_drawdown_pct,
                "return_to_dd": bh_metrics.return_to_dd,
                "per_year": bh_metrics.per_year,
                "trade_count": bh_metrics.trade_count,
                "exposure_pct": bh_metrics.exposure_pct,
            },
        },
        "equity_curve": equity_curve,
    }
    return receipt


def _date_range(records: list[BarRecord]) -> tuple[str, str]:
    """Return ('YYYY-MM-DD', 'YYYY-MM-DD') for the first and last bar, in UTC."""
    if not records:
        return ("", "")
    first = _dt.datetime.fromtimestamp(records[0].ts_ms / 1000, tz=_dt.timezone.utc)
    last = _dt.datetime.fromtimestamp(records[-1].ts_ms / 1000, tz=_dt.timezone.utc)
    return (first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"))

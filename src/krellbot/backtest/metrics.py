"""Backtest metrics: total return, CAGR, drawdown, per-year, exposure.

All math is Decimal where it touches money, float only for the year-fraction
inside the CAGR exponent (which has no monetary meaning). The buy-and-hold
metrics are computed by reusing the same building blocks on a synthetic
equity curve, so the per-year / CAGR / drawdown semantics match.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)
TEN_THOUSAND = Decimal(10000)
MS_PER_DAY = 86_400_000
DAYS_PER_YEAR = 365.25

CurvePoint = tuple[int, Decimal]  # (ts_ms, equity)


@dataclass
class Metrics:
    total_return_pct: float
    cagr_pct: float | None
    max_drawdown_pct: float
    return_to_dd: float | None
    per_year: dict[str, float]
    trade_count: int
    exposure_pct: float


def compute_metrics(
    curve: list[CurvePoint],
    trade_count: int,
    bars_in_market: int,
    bar_count: int,
    starting_cash: Decimal = Decimal(10000),
) -> Metrics:
    """Return the locked metric set for one equity curve.

    `curve` is the per-bar (ts_ms, equity) series. `bars_in_market` is the
    number of bars where `qty > 0` (used for exposure). `bar_count` is the
    total bar count.
    """
    if not curve:
        return Metrics(0.0, None, 0.0, None, {}, trade_count, 0.0)
    final_equity = curve[-1][1]
    total_return = float((final_equity / starting_cash - ONE) * HUNDRED)
    cagr = _cagr(curve, starting_cash)
    max_dd = _max_drawdown(curve)
    rdd: float | None
    if max_dd == 0 or cagr is None:
        rdd = None
    else:
        rdd = cagr / max_dd
    per_year = _per_year(curve)
    exposure = (bars_in_market / bar_count * 100.0) if bar_count else 0.0
    return Metrics(
        total_return_pct=total_return,
        cagr_pct=cagr,
        max_drawdown_pct=max_dd,
        return_to_dd=rdd,
        per_year=per_year,
        trade_count=trade_count,
        exposure_pct=exposure,
    )


def buy_and_hold_curve(
    bars: list,
    starting_cash: Decimal,
    fee_bps: int,
    slippage_bps: int,
    slippage_mult: float,
) -> list[CurvePoint]:
    """Compute the buy-and-hold equity curve over `bars`.

    Enter at the open of bar 1 (the first fill opportunity), hold to the
    last close. Apply entry fee and entry slippage; no exit fee. Trade
    count is 0 and exposure is 100% (always long after entry).
    """
    if len(bars) < 2:
        return [(bars[0].ts_ms, starting_cash)] if bars else []
    enter_open = bars[1].open
    slip = (Decimal(slippage_bps) / TEN_THOUSAND) * Decimal(str(slippage_mult))
    fill = enter_open * (ONE + slip)
    fee_mult = ONE + Decimal(fee_bps) / TEN_THOUSAND
    qty = (starting_cash / (fill * fee_mult)).quantize(Decimal("0.00000001"))
    cost = qty * fill
    fee = cost * Decimal(fee_bps) / TEN_THOUSAND
    cash_after = starting_cash - cost - fee
    out: list[CurvePoint] = [(bars[0].ts_ms, starting_cash)]
    for i, b in enumerate(bars):
        if i == 0:
            continue
        equity = cash_after + qty * b.close
        out.append((b.ts_ms, equity))
    return out


def _cagr(curve: list[CurvePoint], starting_cash: Decimal) -> float | None:
    """Annualized return using a 365.25-day year. None when span < 1 day."""
    if len(curve) < 2:
        return None
    first_ts, first_eq = curve[0]
    last_ts, last_eq = curve[-1]
    span_ms = last_ts - first_ts
    if span_ms < MS_PER_DAY:
        return None
    if first_eq <= ZERO or last_eq <= ZERO:
        return None
    years = span_ms / (MS_PER_DAY * DAYS_PER_YEAR)
    if years <= 0:
        return None
    ratio = float(last_eq / first_eq)
    cagr = (ratio ** (1.0 / years) - 1.0) * 100.0
    return cagr


def _max_drawdown(curve: list[CurvePoint]) -> float:
    """Positive magnitude: the deepest peak-to-trough drop, in percent."""
    peak = curve[0][1]
    max_dd = ZERO
    for _ts, eq in curve:
        peak = max(peak, eq)
        if peak <= ZERO:
            continue
        dd = (peak - eq) / peak * HUNDRED
        max_dd = max(max_dd, dd)
    return float(max_dd)


def _per_year(curve: list[CurvePoint]) -> dict[str, float]:
    """Per calendar year, in UTC: (this_year_end_eq / prev_year_end_eq - 1) * 100.

    The first year uses the first bar's equity as the starting point.
    """
    if not curve:
        return {}
    out: dict[str, float] = {}
    year_open_eq: Decimal | None = None
    current_year: int | None = None
    for ts_ms, eq in curve:
        year = _dt.datetime.fromtimestamp(ts_ms / 1000, tz=_dt.timezone.utc).year
        if current_year is None:
            current_year = year
            year_open_eq = curve[0][1]
        if year != current_year:
            assert year_open_eq is not None
            if year_open_eq > ZERO:
                ret = float((eq / year_open_eq - ONE) * HUNDRED)
            else:
                ret = 0.0
            out[str(current_year)] = ret
            current_year = year
            year_open_eq = eq
    if current_year is not None and year_open_eq is not None:
        last_eq = curve[-1][1]
        if year_open_eq > ZERO:
            ret = float((last_eq / year_open_eq - ONE) * HUNDRED)
        else:
            ret = 0.0
        out[str(current_year)] = ret
    return out

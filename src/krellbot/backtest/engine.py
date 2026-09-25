"""Backtest engine: turn a DSL pack and a candle series into a receipt.

Public surface:
    * `Backtester` - runs the bar-by-bar loop with Decimal ledger
    * `run` - convenience wrapper for `Backtester(...).run()`

Locked rules:
    * Signal on the close of bar t -> fill at the open of bar t+1
    * Stop, while long, checked on bar t before the signal fill of that bar
    * Stop, while long, fills on the triggering bar at min(stop, open) * (1 - sell_slip), before any signal fill.
    * Buy fill = open * (1 + buy_slip); sell fill = open * (1 - sell_slip)
    * Fee on every fill, subtracted from cash on buys, deducted from proceeds on sells
    * Equity each bar = cash + qty * close
    * No trade when the desired side equals the current side
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from krellbot.pack.evaluate import run_series
from krellbot.pack.model import Candle

from .ledger import Ledger

ZERO = Decimal(0)
ONE = Decimal(1)
TEN_THOUSAND = Decimal(10000)
QTY_QUANT = Decimal("0.00000001")


@dataclass
class BarRecord:
    """One bar's outcome for the equity curve."""

    t: int
    ts_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    cash_after: Decimal
    qty_after: Decimal
    equity: Decimal
    fill: dict | None = None  # {side, price, qty, fee, is_stop}


@dataclass
class PendingFill:
    """A fill queued at the close of bar t, to execute at open[t+1]."""

    side: str  # "buy" or "sell"
    base_price: Decimal  # open (signal) or min(stop, open) (stop)
    is_stop: bool = False


class Backtester:
    """Run a single backtest. Decimal throughout, no clock, no IO."""

    def __init__(
        self,
        pack: dict,
        candles: list[Candle],
        starting_cash: Decimal = Decimal(10000),
        fee_bps: int = 0,
        slippage_bps: int = 0,
        slippage_mult: float = 1.0,
    ) -> None:
        self.pack = pack
        self.candles = candles
        self.starting_cash = starting_cash
        self.fee_bps = int(fee_bps)
        self.slippage_bps = int(slippage_bps)
        self.slippage_mult = Decimal(str(slippage_mult))
        self.slip = (Decimal(self.slippage_bps) / TEN_THOUSAND) * self.slippage_mult

    def run(self) -> list[BarRecord]:
        """Execute the bar-by-bar loop. Returns one record per bar."""
        ledger = Ledger(cash=self.starting_cash)
        stop_price: Decimal | None = None
        pending: PendingFill | None = None
        trade_count = 0
        round_trip_open_qty: Decimal | None = None
        records: list[BarRecord] = []

        # Precompute every bar's Target once: bit-identical to per-prefix
        # evaluation because every pack indicator is causal (see run_series).
        targets = run_series(self.pack, self.candles)

        for t, candle in enumerate(self.candles):
            fill_record = None
            stop_fired = False
            # A resting long is stopped on this bar, before a signal fill.
            if ledger.qty > ZERO and stop_price is not None and candle.low <= stop_price:
                stop_fired = True
                pending = None
                base = min(stop_price, candle.open)
                fill = self._execute_pending(
                    PendingFill(side="sell", base_price=base, is_stop=True),
                    ledger,
                    candle.open,
                )
                fill_record = {
                    "side": "sell",
                    "price": fill,
                    "qty": ledger.last_fill_qty,
                    "fee": ledger.last_fill_fee,
                    "is_stop": True,
                }
                trade_count += 1
                round_trip_open_qty = None
                stop_price = None
            elif pending is not None:
                fill = self._execute_pending(pending, ledger, candle.open)
                fill_record = {
                    "side": pending.side,
                    "price": fill,
                    "qty": ledger.last_fill_qty,
                    "fee": ledger.last_fill_fee,
                    "is_stop": pending.is_stop,
                }
                if pending.side == "buy" and round_trip_open_qty is None:
                    round_trip_open_qty = ledger.qty
                if pending.side == "sell" and round_trip_open_qty is not None:
                    trade_count += 1
                    round_trip_open_qty = None
                pending = None

            if not stop_fired:
                target = targets[t]
                if target.reason == "entry" and ledger.qty == ZERO and t + 1 < len(self.candles):
                    if target.stop_price is not None:
                        stop_price = target.stop_price
                    pending = PendingFill(side="buy", base_price=self.candles[t + 1].open)
                elif target.reason == "exit" and ledger.qty > ZERO and t + 1 < len(self.candles):
                    pending = PendingFill(side="sell", base_price=self.candles[t + 1].open, is_stop=False)

            equity = ledger.cash + ledger.qty * candle.close
            assert ledger.cash >= ZERO, f"cash negative at t={t}: {ledger.cash}"
            assert equity == ledger.cash + ledger.qty * candle.close
            records.append(
                BarRecord(
                    t=t,
                    ts_ms=candle.ts_ms,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    cash_after=ledger.cash,
                    qty_after=ledger.qty,
                    equity=equity,
                    fill=fill_record,
                )
            )

        self.trade_count = trade_count
        return records

    def _execute_pending(self, pending: PendingFill, ledger: Ledger, candle_open: Decimal) -> Decimal:
        """Apply a pending fill at the bar's open. Updates ledger in place."""
        if pending.side == "buy":
            fill_price = pending.base_price * (ONE + self.slip)
            equity = ledger.cash  # qty == 0 here
            qty = _buy_qty(
                cash=ledger.cash,
                fill_price=fill_price,
                fee_bps=self.fee_bps,
                max_account_pct=int(self.pack["risk"]["max_account_pct"]),
                equity=equity,
            )
            if qty <= ZERO:
                ledger.last_fill_qty = ZERO
                ledger.last_fill_fee = ZERO
                return candle_open
            cost = qty * fill_price
            fee = cost * Decimal(self.fee_bps) / TEN_THOUSAND
            ledger.cash -= cost + fee
            ledger.qty += qty
            ledger.last_fill_qty = qty
            ledger.last_fill_fee = fee
            return fill_price
        # sell
        fill_price = pending.base_price * (ONE - self.slip)
        qty = ledger.qty
        if qty <= ZERO:
            ledger.last_fill_qty = ZERO
            ledger.last_fill_fee = ZERO
            return fill_price
        proceeds = qty * fill_price
        fee = proceeds * Decimal(self.fee_bps) / TEN_THOUSAND
        ledger.cash += proceeds - fee
        ledger.qty = ZERO
        ledger.last_fill_qty = qty
        ledger.last_fill_fee = fee
        return fill_price


def _buy_qty(
    cash: Decimal,
    fill_price: Decimal,
    fee_bps: int,
    max_account_pct: int,
    equity: Decimal,
) -> Decimal:
    """Compute the entry quantity, rounded DOWN to 8 decimals.

    Budget = min(equity * max_account_pct / 100, cash). The qty is sized so
    that the total spend (cost + fee) does not exceed the budget. We round
    DOWN to 8 decimals, so the spend is always <= budget, never above.
    """
    if fill_price <= ZERO or max_account_pct <= 0:
        return ZERO
    budget_pct = equity * Decimal(max_account_pct) / Decimal(100)
    budget = min(budget_pct, cash)
    if budget <= ZERO:
        return ZERO
    fee_mult = ONE + Decimal(fee_bps) / TEN_THOUSAND
    raw = budget / (fill_price * fee_mult)
    qty = raw.quantize(QTY_QUANT, rounding=ROUND_DOWN)
    if qty <= ZERO:
        return ZERO
    cost = qty * fill_price
    fee = cost * Decimal(fee_bps) / TEN_THOUSAND
    # Safety: the brief says cash must stay >= 0. Quantized spend must fit.
    if cost + fee > cash:
        # Reduce to the largest qty whose total cost fits in `cash`.
        max_total = cash
        # cost + fee = cost * (1 + fee_bps/10000) = cost * fee_mult
        max_cost = max_total / fee_mult
        qty = (max_cost / fill_price).quantize(QTY_QUANT, rounding=ROUND_DOWN)
        qty = max(qty, ZERO)
    return qty

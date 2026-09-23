"""Decimal ledger for the backtester.

`cash` and `qty` are the running state. `equity(c)` is the mark-to-market
value at close `c`. The invariants are enforced by the engine after every
fill, not here, so this module is just a typed bag of state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

MAX_QTY_DIGITS = 8


@dataclass
class Ledger:
    cash: Decimal
    qty: Decimal = Decimal(0)
    last_fill_qty: Decimal = Decimal(0)
    last_fill_fee: Decimal = Decimal(0)

    def equity(self, close: Decimal) -> Decimal:
        return self.cash + self.qty * close

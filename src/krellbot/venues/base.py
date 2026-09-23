"""Venue abstractions: shared dataclasses and the `Venue` protocol.

Money and quantity math is `decimal.Decimal` everywhere. The protocol methods
all take Decimal for size/price. Concrete adapters live in `kraken.py` and
`coinbase.py`; both speak through a Transport that tests inject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class PairRules:
    """Trading rules for one pair on a venue."""

    ordermin: Decimal
    costmin: Decimal
    lot_decimals: int
    price_decimals: int


@dataclass(frozen=True)
class Balance:
    """A spot asset balance: free (available) + locked (in open orders)."""

    asset: str
    free: Decimal
    locked: Decimal = Decimal(0)


@dataclass(frozen=True)
class OpenOrder:
    """One resting or live order the venue reports."""

    id: str
    coid: str
    pair: str
    side: str  # "buy" or "sell"
    qty: Decimal
    stop_price: Decimal | None = None


@dataclass(frozen=True)
class Fill:
    """A historical fill reported in the venue's truth snapshot."""

    id: str
    coid: str
    pair: str
    side: str
    qty: Decimal
    price: Decimal
    ts_ms: int


@dataclass(frozen=True)
class Truth:
    """A point-in-time view of account state."""

    balances: list[Balance] = field(default_factory=list)
    open_orders: list[OpenOrder] = field(default_factory=list)
    recent_fills: list[Fill] = field(default_factory=list)


@dataclass(frozen=True)
class OrderRef:
    """What `place_*` returns: where the order went and how much we got."""

    id: str
    coid: str
    pair: str
    side: str
    qty: Decimal
    filled_qty: Decimal
    stop_price: Decimal | None = None


@dataclass(frozen=True)
class KeyPerms:
    """What the venue says the API key can do."""

    can_trade: bool
    can_withdraw: bool


class WithdrawCapableError(RuntimeError):
    """Raised when `check_key` finds the key can withdraw. Engine refuses it."""


class Venue(Protocol):
    """The contract every venue adapter satisfies.

    Adapters are constructed with their credentials and a Transport. They never
    contact a live HTTP endpoint during tests because Transport is faked.
    """

    def rules(self, pair: str) -> PairRules: ...

    def snapshot(self) -> Truth: ...

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef: ...

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef: ...

    def cancel_stops(self, pair: str) -> None: ...

    def raise_stop(self, pair: str, new_stop: Decimal) -> None: ...

    def order_by_coid(self, coid: str) -> OpenOrder | None: ...

    def check_key(self) -> KeyPerms: ...

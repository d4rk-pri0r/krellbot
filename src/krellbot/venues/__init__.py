"""Venue adapters: a base protocol, a Kraken adapter, and a Coinbase adapter.

`Venue` lives in `krellbot.venues.base`. Every adapter accepts Decimal for
size/price, and `qty`/`stop` are quantized to the venue's lot/price decimals
with `ROUND_DOWN` before they leave this process.
"""

from __future__ import annotations

from .base import (
    Balance,
    Fill,
    KeyPerms,
    OpenOrder,
    OrderRef,
    PairRules,
    Truth,
    Venue,
    WithdrawCapableError,
)
from .coinbase import CoinbaseVenue
from .kraken import KrakenVenue

__all__ = [
    "Balance",
    "CoinbaseVenue",
    "Fill",
    "KeyPerms",
    "KrakenVenue",
    "OpenOrder",
    "OrderRef",
    "PairRules",
    "Truth",
    "Venue",
    "WithdrawCapableError",
]

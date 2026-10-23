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


def __getattr__(name: str) -> object:
    """Load remote adapters only when their public re-export is requested."""
    if name == "CoinbaseVenue":
        from .coinbase import CoinbaseVenue

        globals()[name] = CoinbaseVenue
        return CoinbaseVenue
    if name == "KrakenVenue":
        from .kraken import KrakenVenue

        globals()[name] = KrakenVenue
        return KrakenVenue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

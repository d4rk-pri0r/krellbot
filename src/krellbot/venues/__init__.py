"""Venue adapters: base protocol plus Kraken, Coinbase, Binance, Gate, Pionex, and Bybit spot.

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
    "BinanceVenue",
    "BybitVenue",
    "CoinbaseVenue",
    "Fill",
    "GateVenue",
    "KeyPerms",
    "KrakenVenue",
    "OpenOrder",
    "OrderRef",
    "PairRules",
    "PionexVenue",
    "Truth",
    "Venue",
    "WithdrawCapableError",
]


def __dir__() -> list[str]:
    """Keep lazy public adapters discoverable without importing them."""
    return sorted(set(globals()) | set(__all__))


def __getattr__(name: str) -> object:
    """Load remote adapters only when their public re-export is requested."""
    if name == "BinanceVenue":
        from .binance import BinanceVenue

        globals()[name] = BinanceVenue
        return BinanceVenue
    if name == "BybitVenue":
        from .bybit import BybitVenue

        globals()[name] = BybitVenue
        return BybitVenue
    if name == "CoinbaseVenue":
        from .coinbase import CoinbaseVenue

        globals()[name] = CoinbaseVenue
        return CoinbaseVenue
    if name == "GateVenue":
        from .gate import GateVenue

        globals()[name] = GateVenue
        return GateVenue
    if name == "PionexVenue":
        from .pionex import PionexVenue

        globals()[name] = PionexVenue
        return PionexVenue
    if name == "KrakenVenue":
        from .kraken import KrakenVenue

        globals()[name] = KrakenVenue
        return KrakenVenue
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

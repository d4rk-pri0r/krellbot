"""Pure data types for the Pack DSL.

`Candle` is the only input shape. `Target` is the only output shape. Both use
Decimal for monetary precision (indicator math is float64 elsewhere). No IO,
no clock, no mutable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Candle:
    """One OHLCV bar. Decimal throughout so a stop price is exact."""

    ts_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candle:
        """Build a Candle from a {open, high, low, close, volume} dict."""
        return cls(
            ts_ms=int(data.get("ts_ms", 0)),
            open=Decimal(str(data["open"])),
            high=Decimal(str(data["high"])),
            low=Decimal(str(data["low"])),
            close=Decimal(str(data["close"])),
            volume=Decimal(str(data["volume"])),
        )


@dataclass(frozen=True)
class Target:
    """The single decision returned by `evaluate()`."""

    long: bool
    stop_price: Decimal | None
    reason: str  # one of "warmup", "exit", "entry", "flat"

    def __post_init__(self) -> None:
        if self.reason not in {"warmup", "exit", "entry", "flat"}:
            raise ValueError(f"unknown reason: {self.reason!r}")
        if self.reason == "entry":
            if self.stop_price is None:
                raise ValueError("entry reason requires stop_price")
            if not self.long:
                raise ValueError("entry reason requires long=True")
        elif self.reason in {"warmup", "flat", "exit"}:
            if self.stop_price is not None:
                raise ValueError(f"{self.reason} reason requires stop_price=None")
            if self.long:
                raise ValueError(f"{self.reason} reason requires long=False")

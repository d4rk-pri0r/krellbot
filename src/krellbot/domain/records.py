"""NS11a — versioned spot domain records.

The engine's domain layer holds the canonical, transport-agnostic shape
of an instrument (one venue, one pair, asset_class=spot) and a gate
that refuses to submit a stop the venue cannot honor. Nothing here
imports or calls `krellbot.venues`; venue knowledge stays in the
adapter layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

SCHEMA_VERSION = "1"

SPOT = "spot"

STOP_NATIVE = "native"
STOP_EMULATED = "emulated"
STOP_UNSUPPORTED = "unsupported"

_STOP_CAPABILITIES = frozenset({STOP_NATIVE, STOP_EMULATED, STOP_UNSUPPORTED})


class UnsupportedAssetClass(ValueError):
    """Refused: this engine only stores spot instruments."""

    def __init__(self, asset_class: Any) -> None:
        super().__init__(f"domain: unsupported asset_class {asset_class!r}; only {SPOT!r} is stored")
        self.asset_class = asset_class


class UnsupportedStop(RuntimeError):
    """Refused: the venue cannot honor a stop for this pair.

    Raised before any submit-side effect so an unsupported stop never
    reaches the adapter.
    """

    def __init__(self, capability: str) -> None:
        super().__init__(f"domain: stop capability {capability!r} is unsupported; refusing to submit")
        self.capability = capability


def _reject_float(name: str, value: Any) -> None:
    if isinstance(value, float):
        raise TypeError(f"domain: {name} must be decimal.Decimal; got float ({value!r}); do not coerce a float")


@dataclass(frozen=True)
class InstrumentRecord:
    """One spot instrument record on one venue.

    Construction validates `asset_class` first; anything other than
    `"spot"` raises `UnsupportedAssetClass` and the object is never
    assigned (frozen + raise in `__post_init__` ⇒ "stores nothing").

    `quantity` and `price` are `Decimal`. A `float` raises `TypeError`;
    this module never coerces a float.
    """

    venue: str
    pair: str
    asset_class: str
    quantity: Decimal | None = None
    price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.asset_class != SPOT:
            raise UnsupportedAssetClass(self.asset_class)
        _reject_float("quantity", self.quantity)
        _reject_float("price", self.price)

    @property
    def instrument_id(self) -> str:
        """Stable string id for (venue, pair). Same inputs ⇒ same string."""
        return f"{self.venue}:{self.pair}"


def make_instrument(
    venue: str,
    pair: str,
    asset_class: str = SPOT,
    *,
    quantity: Decimal | None = None,
    price: Decimal | None = None,
) -> InstrumentRecord:
    """Build an `InstrumentRecord`.

    A non-spot `asset_class` raises `UnsupportedAssetClass` and returns
    no record.
    """
    return InstrumentRecord(
        venue=venue,
        pair=pair,
        asset_class=asset_class,
        quantity=quantity,
        price=price,
    )


def require_supported_stop(capability: str, submit: Callable[[], Any]) -> Any:
    """Call `submit` only when the venue actually supports a stop.

    `native` and `emulated` ⇒ call `submit` and return its result.
    `unsupported` ⇒ raise `UnsupportedStop` and do NOT call `submit`.
    Any other capability raises `ValueError`.
    """
    if capability not in _STOP_CAPABILITIES:
        raise ValueError(
            f"domain: unknown stop capability {capability!r}; expected one of {sorted(_STOP_CAPABILITIES)}"
        )
    if capability == STOP_UNSUPPORTED:
        raise UnsupportedStop(capability)
    return submit()

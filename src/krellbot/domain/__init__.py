"""Domain layer: versioned spot instruments and stop-capability gating.

The engine's domain layer holds the transport-agnostic shape of an
instrument (one venue, one pair, asset_class=spot) and the stop gate.
It never imports or calls `krellbot.venues`; venue knowledge lives in
the adapter layer.
"""

from __future__ import annotations

from .records import (
    SCHEMA_VERSION,
    SPOT,
    STOP_EMULATED,
    STOP_NATIVE,
    STOP_UNSUPPORTED,
    InstrumentRecord,
    UnsupportedAssetClass,
    UnsupportedStop,
    make_instrument,
    require_supported_stop,
)

__all__ = [
    "SCHEMA_VERSION",
    "SPOT",
    "STOP_EMULATED",
    "STOP_NATIVE",
    "STOP_UNSUPPORTED",
    "InstrumentRecord",
    "UnsupportedAssetClass",
    "UnsupportedStop",
    "make_instrument",
    "require_supported_stop",
]

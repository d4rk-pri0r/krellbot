"""Domain layer: versioned spot instruments and stop-capability gating.

The engine's domain layer holds the transport-agnostic shape of an
instrument (one venue, one pair, asset_class=spot) and the stop gate.
It never imports or calls `krellbot.venues`; venue knowledge lives in
the adapter layer.
"""

from __future__ import annotations

from .capabilities import (
    PAPER,
    stop_capability,
    submit_if_supported,
)
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
from .trace import DecisionTrace, decision_trace

__all__ = [
    "PAPER",
    "SCHEMA_VERSION",
    "SPOT",
    "STOP_EMULATED",
    "STOP_NATIVE",
    "STOP_UNSUPPORTED",
    "DecisionTrace",
    "InstrumentRecord",
    "UnsupportedAssetClass",
    "UnsupportedStop",
    "decision_trace",
    "make_instrument",
    "require_supported_stop",
    "stop_capability",
    "submit_if_supported",
]

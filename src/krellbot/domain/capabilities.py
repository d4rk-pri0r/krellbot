"""NS11b — stop-capability declaration without venue imports.

This leaf declares the per-venue stop capability of the engine and a
single helper that combines the asset-class check with the capability
check before any submit callable runs. It does not import or call
`krellbot.venues`; venue knowledge stays in the adapter layer.

The table is deliberately minimal: `paper` is the only venue with a
declared capability at this leaf, and it is `emulated`, not `native`.
Promoting a live venue to `native` here is forbidden until an adapter
proves the venue actually honors an exchange-side stop.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .records import (
    SPOT,
    STOP_EMULATED,
    STOP_UNSUPPORTED,
    UnsupportedAssetClass,
    UnsupportedStop,
)

PAPER = "paper"

# Per-venue stop capability declared at this leaf. `paper` is emulated;
# every other venue — `kraken`, `coinbase`, and any unknown venue —
# is unsupported. Do not add a live venue here without an adapter
# that proves the venue actually executes an exchange-side stop.
_CAPABILITY_BY_VENUE: dict[str, str] = {
    PAPER: STOP_EMULATED,
}


def stop_capability(venue: str) -> str:
    """Return the engine's declared stop capability for `venue`.

    `paper` returns `emulated`. Every other venue — including `kraken`
    and `coinbase`, and any unknown venue — returns `unsupported`.
    This leaf does not claim a native exchange stop for any venue.
    """
    return _CAPABILITY_BY_VENUE.get(venue, STOP_UNSUPPORTED)


def submit_if_supported(
    venue: str,
    asset_class: str,
    submit: Callable[[], Any],
) -> Any:
    """Call `submit` only when the venue supports a stop.

    Order of checks:

    1. `asset_class` must be `spot`. Anything else raises
       `UnsupportedAssetClass` and `submit` is never called.
    2. The venue's stop capability must be `native` or `emulated`.
       `unsupported` raises `UnsupportedStop` and `submit` is never
       called.
    3. Otherwise, `submit()` is invoked and its result is returned.

    No venue adapter is imported; this leaf consults only the static
    capability table above.
    """
    if asset_class != SPOT:
        raise UnsupportedAssetClass(asset_class)
    capability = stop_capability(venue)
    if capability == STOP_UNSUPPORTED:
        raise UnsupportedStop(capability)
    return submit()

"""Distribution-gate venue product path (M23.4 / P4).

Pins which venues are **qualified for the live product path** behind the
existing live gates and paper-only release rail, versus paper-only breadth
(M14 Binance-class).

This is honesty for Deploy/Ops UI and docs — not a flip of
``PAPER_ONLY_RELEASE``. Live order send still refuses until the owner
changes release policy. CI uses fake transports only.

Do not add a third live-qualified venue here without a milestone that
widens the P4 “two venues” product claim.
"""

from __future__ import annotations

from typing import Final

# First venue (Kraken) + second distribution venue (Coinbase Advanced).
QUALIFIED_LIVE_VENUES: Final[frozenset[str]] = frozenset({"kraken", "coinbase"})

# Paper-capable breadth that must not be advertised as qualified live.
PAPER_ONLY_VENUES: Final[frozenset[str]] = frozenset({"binance", "gate", "pionex", "okx"})

SECOND_DISTRIBUTION_VENUE: Final[str] = "coinbase"
SECOND_DISTRIBUTION_WAVE_PAIR: Final[str] = "BTC-USD"


def is_qualified_live_venue(venue: str) -> bool:
    """Return True when ``venue`` is on the distribution live product path."""
    return venue in QUALIFIED_LIVE_VENUES


def is_paper_only_venue(venue: str) -> bool:
    """Return True when ``venue`` is paper breadth only (not qualified live)."""
    return venue in PAPER_ONLY_VENUES

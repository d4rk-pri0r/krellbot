"""Strategy IR: the typed graph representation of a strategy.

The strategy IR is the typed graph that NS19 introduces alongside the
v1 rule DSL. NS19a contributes the availability check — the predicate
that refuses a node which reads a future bar at a given decision bar.
Other NS19 steps will own the rest of the compiler surface. This
package does not own evaluation, venues, or runtime orchestration; it
holds the IR types and the pure predicates that operate on them.
"""

from __future__ import annotations

from .availability import FutureData, check_availability

__all__ = ["FutureData", "check_availability"]

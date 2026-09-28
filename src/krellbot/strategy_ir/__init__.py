"""Strategy IR: the typed graph representation of a strategy.

The strategy IR is the typed graph that NS19 introduces alongside the
v1 rule DSL. NS19a contributes the availability check — the predicate
that refuses a node which reads a future bar at a given decision bar.
NS19b contributes the execution id — the hash that ignores canvas
state. NS19c contributes the v1 strip — the mapping transform that
drops the editor / layout keys the v1 decision engine must never
see. Other NS19 steps will own the rest of the compiler surface.
This package does not own evaluation, venues, or runtime
orchestration; it holds the IR types and the pure predicates that
operate on them.
"""

from __future__ import annotations

from .availability import FutureData, check_availability
from .identity import execution_id
from .v1 import strip_editor

__all__ = ["FutureData", "check_availability", "execution_id", "strip_editor"]

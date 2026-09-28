"""Strategy IR: the typed graph representation of a strategy.

The strategy IR is the typed graph that NS19 introduces alongside the
v1 rule DSL. NS19a contributes the availability check — the predicate
that refuses a node which reads a future bar at a given decision bar.
NS19b contributes the execution id — the hash that ignores canvas
state. NS19c contributes the v1 strip — the mapping transform that
drops the editor / layout keys the v1 decision engine must never
see. NS19d contributes the compose step — the small routine that
strips the pack, refuses future bars, and then hands the clean pack
to a caller-supplied evaluator. NS19e contributes the v1 clock — the
strict predicate that refuses a graph whose ``schema_version`` is
not the integer ``1`` or whose ``timeframe`` is not exactly ``"1h"``,
``"4h"``, or ``"1d"``. NS19f contributes the canonical serializer —
the UTF-8 JSON document built from the stripped graph with sorted
keys and ``(",", ":")`` separators, which is a fixed point under
``parse ∘ canonical_bytes``. NS19g contributes the size check — the
predicate that refuses a v1 condition tree whose node count exceeds
``max_nodes`` or whose nesting depth exceeds ``max_depth``, walking
stops the moment either bound is exceeded, and ``True`` / ``1.0`` are
not legal bounds. NS19h contributes the checkpoint check — the
predicate that refuses a stateful operator (``ema``, ``atr``, or
``roofing_filter``) whose ``checkpoint`` is not a ``dict``; missing
keys, ``None``, ``0``, ``0.0``, and ``True`` all raise
``MissingCheckpoint``. Other NS19 steps will own the rest of the
compiler surface. This package does not own evaluation, venues, or
runtime orchestration; it holds the IR types and the pure predicates
that operate on them.
"""

from __future__ import annotations

from .availability import FutureData, check_availability
from .bounds import GraphTooLarge, check_bounds
from .canonical import canonical_bytes
from .checkpoint import STATEFUL_FNS, MissingCheckpoint, require_checkpoint
from .identity import execution_id
from .units import InvalidGraph, require_v1_clock
from .v1 import prepare_v1, strip_editor

__all__ = [
    "STATEFUL_FNS",
    "FutureData",
    "GraphTooLarge",
    "InvalidGraph",
    "MissingCheckpoint",
    "canonical_bytes",
    "check_availability",
    "check_bounds",
    "execution_id",
    "prepare_v1",
    "require_checkpoint",
    "require_v1_clock",
    "strip_editor",
]

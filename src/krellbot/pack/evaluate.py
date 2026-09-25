"""Pure pack evaluation: pack + candles → Target.

No IO, no clock. Same input always returns the same Target. Decimal only at
the stop price; indicator math is float64 inside.

Precedence on the last bar:
    1. any used indicator None on the last bar -> warmup (long=False, no stop)
    2. exit true -> exit (long=False, no stop)
    3. entry true -> entry (long=True, stop from last bar)
    4. else -> flat (long=False, no stop)

`crosses_above` / `crosses_below` are False on bar 0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import indicators as ind
from .model import Candle, Target

OPS = {">", "<", ">=", "<=", "crosses_above", "crosses_below"}


def run(pack: dict, candles: list[Candle]) -> Target:
    """Evaluate a DSL pack on the given candles and return the Target."""
    if not candles:
        return Target(long=False, stop_price=None, reason="flat")

    computed, atr_series = _compute_all(pack, candles)
    return _decide(pack, computed, candles, atr_series, len(candles) - 1)


def run_series(pack: dict, candles: list[Candle]) -> list[Target]:
    """Target for every bar index t, identical to run(pack, candles[: t + 1]).

    Every indicator in the pack is causal (the value at index i depends only on
    candles[: i + 1]), so computing each series once over the full candle list
    gives, at every index t, exactly the value that ``ind.compute(candles[: t
    + 1])`` returns at its last index. The precomputed series therefore yields
    bit-identical Targets to the per-prefix ``run`` call.
    """
    if not candles:
        return []
    computed, atr_series = _compute_all(pack, candles)
    return [_decide(pack, computed, candles, atr_series, t) for t in range(len(candles))]


def _compute_all(pack: dict, candles: list[Candle]) -> tuple[dict[str, list[float | None]], list[float | None] | None]:
    """Compute every pack indicator plus the ATR stop series (if any) once."""
    indicators_map: dict[str, dict] = pack.get("indicators", {})
    computed: dict[str, list[float | None]] = {
        name: ind.compute(candles, params) for name, params in indicators_map.items()
    }
    risk = pack.get("risk") or {}
    stop = risk.get("stop") or {}
    atr_series: list[float | None] | None = None
    if stop.get("type") == "atr":
        atr_series = ind.compute(candles, {"fn": "atr", "len": int(stop["len"])})
    return computed, atr_series


def _decide(
    pack: dict,
    computed: dict[str, list[float | None]],
    candles: list[Candle],
    atr_series: list[float | None] | None,
    t: int,
) -> Target:
    """The per-bar decision used by BOTH ``run`` and ``run_series``.

    Both entry paths share this helper so the two cannot drift: the difference
    between ``run`` and ``run_series`` is only which index they evaluate, never
    the rules at that index.
    """
    # Used indicator names come from the condition tree.
    used = _used_indicators(pack.get("entry")) | _used_indicators(pack.get("exit"))
    for name in used:
        series = computed.get(name)
        if series is None or series[t] is None:
            return Target(long=False, stop_price=None, reason="warmup")

    exit_hit = _eval_condition(pack.get("exit"), computed, candles, t)
    if exit_hit:
        return Target(long=False, stop_price=None, reason="exit")
    entry_hit = _eval_condition(pack.get("entry"), computed, candles, t)
    if not entry_hit:
        return Target(long=False, stop_price=None, reason="flat")

    # Entry fired: compute stop.
    risk = pack["risk"]
    stop = risk["stop"]
    last_close = candles[t].close
    if stop["type"] == "pct":
        pct = Decimal(str(stop["pct"]))
        stop_price = last_close * (Decimal(1) - pct / Decimal(100))
    else:  # atr
        mult = Decimal(str(stop["mult"]))
        atr_val = atr_series[t] if atr_series is not None else None
        if atr_val is None:
            return Target(long=False, stop_price=None, reason="warmup")
        stop_price = last_close - Decimal(str(atr_val)) * mult
    return Target(long=True, stop_price=stop_price, reason="entry")


def _used_indicators(condition: Any) -> set[str]:
    """Walk a condition and collect indicator names referenced as operands."""
    used: set[str] = set()
    if isinstance(condition, dict):
        for sub in condition.get("all", []) + condition.get("any", []):
            used |= _used_indicators(sub)
    elif isinstance(condition, list) and len(condition) == 3:
        for operand in (condition[0], condition[2]):
            if isinstance(operand, str) and operand not in ind.PRICE_FIELDS:
                used.add(operand)
    return used


def _eval_condition(
    condition: Any,
    computed: dict[str, list[float | None]],
    candles: list[Candle],
    i: int,
) -> bool:
    if isinstance(condition, dict):
        if "all" in condition:
            return all(_eval_condition(sub, computed, candles, i) for sub in condition["all"])
        if "any" in condition:
            return any(_eval_condition(sub, computed, candles, i) for sub in condition["any"])
        return False
    if isinstance(condition, list):
        if len(condition) != 3:
            return False
        left, op, right = condition
        if op not in OPS:
            return False
        return _eval_leaf(left, op, right, computed, candles, i)
    return False


def _eval_leaf(
    left: Any,
    op: str,
    right: Any,
    computed: dict[str, list[float | None]],
    candles: list[Candle],
    i: int,
) -> bool:
    if op == "crosses_above":
        if i == 0:
            return False
        l0 = _operand(left, computed, candles, i)
        r0 = _operand(right, computed, candles, i)
        l1 = _operand(left, computed, candles, i - 1)
        r1 = _operand(right, computed, candles, i - 1)
        if l0 is None or r0 is None or l1 is None or r1 is None:
            return False
        return l1 <= r1 and l0 > r0
    if op == "crosses_below":
        if i == 0:
            return False
        l0 = _operand(left, computed, candles, i)
        r0 = _operand(right, computed, candles, i)
        l1 = _operand(left, computed, candles, i - 1)
        r1 = _operand(right, computed, candles, i - 1)
        if l0 is None or r0 is None or l1 is None or r1 is None:
            return False
        return l1 >= r1 and l0 < r0

    lv = _operand(left, computed, candles, i)
    rv = _operand(right, computed, candles, i)
    if lv is None or rv is None:
        return False
    if op == ">":
        return lv > rv
    if op == "<":
        return lv < rv
    if op == ">=":
        return lv >= rv
    if op == "<=":
        return lv <= rv
    return False


def _operand(
    token: Any,
    computed: dict[str, list[float | None]],
    candles: list[Candle],
    i: int,
) -> float | None:
    """Resolve an operand token to a float64 value at bar i."""
    if isinstance(token, (int, float)):
        return float(token)
    if isinstance(token, str):
        if token == "open":
            return float(candles[i].open)
        if token == "high":
            return float(candles[i].high)
        if token == "low":
            return float(candles[i].low)
        if token == "close":
            return float(candles[i].close)
        if token == "volume":
            return float(candles[i].volume)
        series = computed.get(token)
        if series is None:
            return None
        return series[i]
    return None

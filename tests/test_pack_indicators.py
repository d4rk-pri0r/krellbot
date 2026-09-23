"""Per-indicator math tests for krellbot.pack.indicators.

Each whitelist fn has a 24-bar fixture with expected values precomputed from the
locked formulas. We compare implementation output to expected with abs tol 1e-9.
test_no_lookahead mutates a later candle and confirms output at i is unchanged.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from krellbot.pack import indicators
from krellbot.pack.model import Candle

FIX = Path(__file__).parent / "fixtures" / "indicators"

WHITELIST = [
    "sma",
    "ema",
    "wma",
    "vwma",
    "stdev",
    "roc",
    "efficiency_ratio",
    "power_mean",
    "hma",
    "atr",
    "highest",
    "lowest",
    "roofing_filter",
]


def _load_candles(name: str) -> tuple[list[Candle], dict]:
    data = json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))
    candles = [Candle.from_dict(c) for c in data["candles"]]
    return candles, data["params"]


def _close(name: str, *args):
    """Approximate equality for floats with abs tol 1e-9, None-safe."""
    if name == "None":
        return args[0] is None and args[1] is None
    a, b = args
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, abs_tol=1e-9, rel_tol=1e-9)


@pytest.mark.parametrize("fn_name", WHITELIST)
def test_indicator_matches_golden(fn_name: str):
    data = json.loads((FIX / f"{fn_name}.json").read_text(encoding="utf-8"))
    candles = [Candle.from_dict(c) for c in data["candles"]]
    params = data["params"]
    expected = data["expected"]
    out = indicators.compute(candles, params)
    assert len(out) == len(candles)
    for i, (a, b) in enumerate(zip(out, expected, strict=False)):
        assert _close("fn_name", a, b), f"{fn_name}[{i}]: got {a!r}, expected {b!r}"


@pytest.mark.parametrize("fn_name", WHITELIST)
def test_no_lookahead(fn_name: str):
    """Mutating candle i+1 must not change output at index i for any fn."""
    candles, params = _load_candles(fn_name)
    original = list(indicators.compute(candles, params))
    for i in range(len(candles) - 1):
        # Mutate candle i+1 (set a clearly different price and volume).
        c = candles[i + 1]
        mutated = Candle(
            ts_ms=c.ts_ms,
            open=_flip(c.open),
            high=_flip(c.high),
            low=_flip(c.low),
            close=_flip(c.close),
            volume=_flip(c.volume) if c.volume != 0 else Candle.from_dict({}).volume + 1,
        )
        new_candles = list(candles)
        new_candles[i + 1] = mutated
        new_out = indicators.compute(new_candles, params)
        for j in range(i + 1):
            assert original[j] == new_out[j], (
                f"{fn_name}: mutation at {i + 1} changed output at {j} ({original[j]!r} -> {new_out[j]!r})"
            )


def _flip(value) -> float:
    """Nudge a value away from itself so we can detect cross-bar leakage."""
    f = float(value)
    return f + 7.123 if f >= 0 else f - 7.123

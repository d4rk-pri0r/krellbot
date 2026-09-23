"""Evaluate tests for krellbot.pack.evaluate.

evaluate() is pure: it takes a pack dict and a list of candles and returns a
Target (long, stop_price, reason). No IO, no clock.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.pack import evaluate
from krellbot.pack.model import Candle, Target

FIX = Path(__file__).parent / "fixtures" / "packs"


def _load_pack(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _make_candles(closes: list[float], vol: float = 100.0) -> list[Candle]:
    out: list[Candle] = []
    for i, c in enumerate(closes):
        out.append(
            Candle(
                ts_ms=i * 60_000,
                open=Decimal(str(c)),
                high=Decimal(str(c + 0.5)),
                low=Decimal(str(c - 0.5)),
                close=Decimal(str(c)),
                volume=Decimal(str(vol)),
            )
        )
    return out


def test_evaluate_stop_pct():
    """Entry + pct stop: stop_price = close * (1 - pct/100), with Decimal precision."""
    pack = _load_pack("valid.json")
    candles = _make_candles([float(i) for i in range(1, 25)])
    target = evaluate.run(pack, candles)
    assert isinstance(target, Target)
    assert target.long is True
    assert target.reason == "entry"
    assert target.stop_price is not None
    expected = Decimal(24) * (Decimal(1) - Decimal(5) / Decimal(100))
    assert target.stop_price == expected


def test_evaluate_warmup_returns_none_stop():
    """If any used indicator is None on the last bar, return warmup."""
    pack = _load_pack("valid.json")
    candles = _make_candles([float(i) for i in range(1, 15)])  # not enough bars for sma(20)
    target = evaluate.run(pack, candles)
    assert target.long is False
    assert target.stop_price is None
    assert target.reason == "warmup"


def test_evaluate_flat_when_no_entry_signal():
    """Entry is false, exit is false -> reason='flat'."""
    pack = _load_pack("flat_only.json")
    candles = _make_candles([1.0] * 24)
    target = evaluate.run(pack, candles)
    assert target.long is False
    assert target.reason == "flat"


def test_evaluate_exit_overrides_entry():
    """Exit signal wins over entry on the same bar."""
    pack = _load_pack("exit_overrides.json")
    candles = _make_candles([float(i) for i in range(1, 25)])
    target = evaluate.run(pack, candles)
    assert target.long is False
    assert target.reason == "exit"
    assert target.stop_price is None


def test_evaluate_atr_stop_uses_atr_indicator():
    """ATR stop: stop_price = close - atr*mult (with Decimal conversion)."""
    pack = _load_pack("valid_atr.json")
    candles = _make_candles([float(i) for i in range(1, 30)])
    target = evaluate.run(pack, candles)
    assert target.long is True
    assert target.reason == "entry"
    assert target.stop_price is not None
    # Stop should be strictly less than close since mult > 0 and atr > 0.
    assert target.stop_price < Decimal(29)
    assert target.stop_price > Decimal(0)


def test_evaluate_crosses_above_includes_equal_previous():
    """A touch (equal, then above) is a cross. The locked rule uses <=, not <."""
    pack = _load_pack("valid.json")
    pack["indicators"] = {"line": {"fn": "sma", "src": "close", "len": 2}}
    pack["entry"] = ["close", "crosses_above", "line"]
    pack["exit"] = ["close", "crosses_below", "line"]
    # Bar 2 close equals the sma of bars 1-2. Bar 3 close is above that sma.
    candles = _make_candles([10.0, 10.0, 12.0])
    target = evaluate.run(pack, candles)
    assert target.reason == "entry"
    assert target.long is True


def test_evaluate_crosses_on_bar_zero_is_false():
    """On the very first bar (i=0), crosses_above and crosses_below are False."""
    pack = _load_pack("cross_first_bar.json")
    # Only 1 candle: i=0, so crosses_* must be false.
    candles = _make_candles([10.0])
    target = evaluate.run(pack, candles)
    assert target.long is False
    assert target.reason in {"warmup", "flat"}

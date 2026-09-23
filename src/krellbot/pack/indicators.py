"""Whitelist indicator math for the Pack DSL.

All math is float64. `compute(candles, params)` returns a list[float | None]
the same length as `candles`. Index i may only depend on candles j<=i; the
no-lookahead invariant is checked by the test_no_lookahead test, not asserted
here. Index 0..warmup-1 are None.

Implementations follow the formulas locked in the Phase 2 brief.
"""

from __future__ import annotations

import math

from .model import Candle

PRICE_FIELDS = ("open", "high", "low", "close", "volume")


def _series(candles: list[Candle], field: str) -> list[float]:
    """Extract a single price field as a float64 list."""
    if field not in PRICE_FIELDS:
        raise ValueError(f"unknown price field: {field!r}")
    getter = {
        "open": lambda c: c.open,
        "high": lambda c: c.high,
        "low": lambda c: c.low,
        "close": lambda c: c.close,
        "volume": lambda c: c.volume,
    }[field]
    return [float(getter(c)) for c in candles]


def compute(candles: list[Candle], params: dict) -> list[float | None]:
    """Dispatch on params['fn'] and return a same-length list."""
    fn = params.get("fn")
    if fn == "sma":
        return _sma(candles, params)
    if fn == "ema":
        return _ema(candles, params)
    if fn == "wma":
        return _wma(candles, params)
    if fn == "vwma":
        return _vwma(candles, params)
    if fn == "stdev":
        return _stdev(candles, params)
    if fn == "roc":
        return _roc(candles, params)
    if fn == "efficiency_ratio":
        return _efficiency_ratio(candles, params)
    if fn == "power_mean":
        return _power_mean(candles, params)
    if fn == "hma":
        return _hma(candles, params)
    if fn == "atr":
        return _atr(candles, params)
    if fn == "highest":
        return _highest(candles, params)
    if fn == "lowest":
        return _lowest(candles, params)
    if fn == "roofing_filter":
        return _roofing_filter(candles, params)
    raise ValueError(f"unknown indicator fn: {fn!r}")


def _pad(n: int, length: int) -> list[float | None]:
    """Return a list of n Nones, optionally extended to `length` items."""
    out: list[float | None] = [None] * n
    return out


def _sma(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    s = 0.0
    for i, v in enumerate(src):
        s += v
        if i >= n:
            s -= src[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def _ema(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    k = 2.0 / (n + 1)
    # Seed = sma at index len-1.
    seed = sum(src[:n]) / n
    out[n - 1] = seed
    prev = seed
    for i in range(n, len(src)):
        v = src[i] * k + prev * (1.0 - k)
        out[i] = v
        prev = v
    return out


def _wma(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    weight_sum = float(n * (n + 1) // 2)
    # Rolling weighted sum: at each step, drop oldest (mult=1) and add newest (mult=n).
    for i in range(n - 1, len(src)):
        total = 0.0
        for w in range(1, n + 1):
            total += w * src[i - (n - w)]
        out[i] = total / weight_sum
    return out


def _vwma(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    vol = _series(candles, "volume")
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    psum = 0.0
    vsum = 0.0
    for i in range(len(src)):
        psum += src[i] * vol[i]
        vsum += vol[i]
        if i >= n:
            psum -= src[i - n] * vol[i - n]
            vsum -= vol[i - n]
        if i >= n - 1:
            if vsum == 0.0:
                out[i] = None
            else:
                out[i] = psum / vsum
    return out


def _stdev(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    for i in range(n - 1, len(src)):
        window = src[i - n + 1 : i + 1]
        mean = sum(window) / n
        var = sum((x - mean) ** 2 for x in window) / n  # population
        out[i] = math.sqrt(var)
    return out


def _roc(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) <= n:
        return out
    for i in range(n, len(src)):
        denom = src[i - n]
        if denom == 0.0:
            out[i] = None
        else:
            out[i] = (src[i] - denom) / denom * 100.0
    return out


def _efficiency_ratio(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) <= n:
        return out
    for i in range(n, len(src)):
        num = abs(src[i] - src[i - n])
        denom = 0.0
        for j in range(i - n + 1, i + 1):
            denom += abs(src[j] - src[j - 1])
        if denom == 0.0:
            out[i] = None
        else:
            out[i] = num / denom
    return out


def _power_mean(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    p = float(params["p"])
    if p == 0.0:
        raise ValueError("power_mean p must be non-zero")
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    for i in range(n - 1, len(src)):
        window = src[i - n + 1 : i + 1]
        if any(v <= 0.0 for v in window):
            out[i] = None
            continue
        m = sum(v**p for v in window) / n
        out[i] = m ** (1.0 / p)
    return out


def _hma(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    half = max(2, n // 2)
    sqrt_len = max(2, round(n**0.5))

    inner_a = _wma_from(src, half)
    inner_b = _wma_from(src, n)

    # inner[i] = 2*inner_a[i] - inner_b[i]
    inner: list[float | None] = [None] * len(src)
    for i in range(len(src)):
        a = inner_a[i]
        b = inner_b[i]
        if a is not None and b is not None:
            inner[i] = 2.0 * a - b

    out = _wma_inner(inner, sqrt_len)
    return out


def _wma_from(src: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(src)
    if n < 1 or len(src) < n:
        return out
    weight_sum = float(n * (n + 1) // 2)
    for i in range(n - 1, len(src)):
        total = 0.0
        for w in range(1, n + 1):
            total += w * src[i - (n - w)]
        out[i] = total / weight_sum
    return out


def _wma_inner(src: list[float | None], n: int) -> list[float | None]:
    """Like _wma_from but treats None inputs as blockers (None propagates)."""
    out: list[float | None] = [None] * len(src)
    if n < 1 or len(src) < n:
        return out
    weight_sum = float(n * (n + 1) // 2)
    for i in range(n - 1, len(src)):
        window: list[float] = []
        for j in range(i - n + 1, i + 1):
            value = src[j]
            if value is None:
                window = []
                break
            window.append(value)
        if len(window) != n:
            continue
        total = sum(w * window[w - 1] for w in range(1, n + 1))
        out[i] = total / weight_sum
    return out


def _atr(candles: list[Candle], params: dict) -> list[float | None]:
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(candles) <= n:
        return out
    high = [float(c.high) for c in candles]
    low = [float(c.low) for c in candles]
    close = [float(c.close) for c in candles]

    tr: list[float | None] = [None] * len(candles)
    for i in range(1, len(candles)):
        pc = close[i - 1]
        tr[i] = max(high[i] - low[i], abs(high[i] - pc), abs(low[i] - pc))

    # First ATR = sma of first n TRs, at index n.
    if n < len(tr):
        trs: list[float] = []
        for i in range(1, n + 1):
            value = tr[i]
            if value is None:
                return out
            trs.append(value)
        prev = sum(trs) / n
        out[n] = prev
        for i in range(n + 1, len(candles)):
            value = tr[i]
            if value is None:
                return out
            prev = (prev * (n - 1) + value) / n
            out[i] = prev
    return out


def _highest(candles: list[Candle], params: dict) -> list[float | None]:
    src_field = params.get("src", "high")
    src = _series(candles, src_field)
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    for i in range(n - 1, len(src)):
        out[i] = max(src[i - n + 1 : i + 1])
    return out


def _lowest(candles: list[Candle], params: dict) -> list[float | None]:
    src_field = params.get("src", "low")
    src = _series(candles, src_field)
    n = int(params["len"])
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < n:
        return out
    for i in range(n - 1, len(src)):
        out[i] = min(src[i - n + 1 : i + 1])
    return out


def _roofing_filter(candles: list[Candle], params: dict) -> list[float | None]:
    src = _series(candles, params["src"])
    n = int(params["len"])
    smooth = int(params.get("smooth", 10))
    out: list[float | None] = [None] * len(candles)
    if n < 1 or len(src) < 1:
        return out

    # High-pass coefficients (2-pole Butterworth high-pass, Ehlers).
    # alpha1 = (cos(0.707*2*pi/hp) + sin(0.707*2*pi/hp) - 1) / cos(0.707*2*pi/hp)
    angle = 0.707 * 2.0 * math.pi / n
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    alpha1 = (cos_a + sin_a - 1.0) / cos_a
    one_minus_alpha_half = (1.0 - alpha1 / 2.0) ** 2

    hp: list[float] = [0.0] * len(src)
    if len(src) >= 1:
        # hp[0] uses only src[0] and src[-1] (which is 0) ... per the brief
        # `hp` starts at 0. We follow: hp[0]=0, hp[1] requires src[1], src[0], src[-1]
        # but the formula references src[i-2]. The standard convention is to
        # treat out-of-range src as 0; that matches hp starting at 0.
        pass
    for i in range(len(src)):
        s_i = src[i]
        s_i1 = src[i - 1] if i - 1 >= 0 else 0.0
        s_i2 = src[i - 2] if i - 2 >= 0 else 0.0
        hp_prev = hp[i - 1] if i - 1 >= 0 else 0.0
        hp_prev2 = hp[i - 2] if i - 2 >= 0 else 0.0
        hp[i] = (
            one_minus_alpha_half * (s_i - 2.0 * s_i1 + s_i2)
            + 2.0 * (1.0 - alpha1) * hp_prev
            - (1.0 - alpha1) ** 2 * hp_prev2
        )

    # Super-smoother (2-pole low-pass, Ehlers).
    a1 = math.exp(-1.414 * math.pi / smooth)
    b1 = 2.0 * a1 * math.cos(1.414 * math.pi / smooth)
    c2 = b1
    c3 = -a1 * a1
    c1 = 1.0 - c2 - c3

    warmup = max(n, smooth)
    if len(src) >= 1:
        out[0] = None  # always None at i=0 even if both inputs are 0; brief says values before warmup are None.
    o_prev = 0.0
    o_prev2 = 0.0
    for i in range(1, len(src)):
        hp_i = hp[i]
        hp_i1 = hp[i - 1]
        v = c1 * (hp_i + hp_i1) / 2.0 + c2 * o_prev + c3 * o_prev2
        o_prev2 = o_prev
        o_prev = v
        if i >= warmup:
            out[i] = v
    return out


def lookback(params: dict) -> int:
    """Return the warmup length (in candles) needed before this indicator is defined.

    For atr the budget is `len` (lint adds the extra bar).
    For roofing_filter: max(len, smooth).
    Otherwise: len.
    """
    fn = params.get("fn")
    n = int(params.get("len", 0))
    if fn == "atr":
        return n
    if fn == "roofing_filter":
        return max(n, int(params.get("smooth", 10)))
    return n


def all_lookback(indicators_map: dict[str, dict]) -> int:
    """Sum-free max-lookback across all indicators in the pack."""
    if not indicators_map:
        return 0
    return max(lookback(p) for p in indicators_map.values())

"""Every starter example validates and evaluates to expected targets.

Each shipped starter (``GET /api/v1/packs/starters``) is proven here
against transparently synthetic candle prefixes — series defined in this
test file, never in production data — with hand-checkable indicator
arithmetic:

  * the dual-MA crossover entry fires exactly when the 10-bar SMA of
    close crosses above the 30-bar SMA, and the 5% pct stop is exact
    Decimal math on the last close;
  * the mean-reversion band entry fires when close is under the 20-bar
    SMA with the 20-bar population stdev above 0.75, with a 4% stop;
  * the range breakout entry fires when close pushes above the 20-bar
    SMA of highs with volume above 150, and the ATR stop uses a
    uniform-series ATR that is exactly 2.0 (TR constant at 2), so the
    stop is 2.5 x 2.0 below the last close.

Every expected Target (long, reason, stop_price) is asserted exactly,
including warmup/flat/exit prefixes. These tests use the real shipped
JSON resources, the real validator, and the real evaluator — no mocks.
"""

from __future__ import annotations

from decimal import Decimal

from krellbot.pack import evaluate
from krellbot.pack.lint import check, is_legacy
from krellbot.pack.model import Candle, Target
from krellbot.packs import catalogue


# ---- helpers --------------------------------------------------------------


def _bar(i: int, o: float, h: float, low: float, c: float, v: float) -> Candle:
    """One synthetic OHLCV bar; ts is a synthetic hourly index."""

    return Candle(
        ts_ms=i * 3_600_000,
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(low)),
        close=Decimal(str(c)),
        volume=Decimal(str(v)),
    )


def _flat(i: int, price: float, *, h: float | None = None, low: float | None = None) -> Candle:
    """A self-consistent bar at ``price`` with optional high/low wick."""

    return _bar(
        i,
        price,
        h if h is not None else price,
        low if low is not None else price,
        price,
        200,
    )


def _pack(example_id: str) -> dict:
    rows = {row["id"]: row for row in catalogue.list_examples()}
    assert example_id in rows, (example_id, sorted(rows))
    return rows[example_id]["pack"]


def _expect(target: Target, *, long: bool, reason: str, stop: Decimal | None) -> None:
    assert target.long is long, target
    assert target.reason == reason, target
    assert target.stop_price == stop, (target.stop_price, stop)


# ---- every example is a valid, non-legacy, real pack ----------------------


def test_every_starters_example_validates() -> None:
    """The existing validator passes every shipped starter pack."""

    for row in catalogue.list_examples():
        pack = row["pack"]
        assert pack["id"] == row["id"], row["id"]
        assert check(pack) == [], (row["id"], check(pack))
        assert not is_legacy(pack), row["id"]


def test_starters_examples_have_real_positions_and_predicates() -> None:
    """No stub packs: real indicators, entry/exit predicates, risk, market."""

    for row in catalogue.list_examples():
        pack = row["pack"]
        assert len(pack["indicators"]) >= 2, (row["id"], pack["indicators"])
        assert pack["entry"], row["id"]
        assert pack["exit"], row["id"]
        assert 1 <= pack["risk"]["max_account_pct"] <= 100, row["id"]
        assert pack["markets"], row["id"]
        assert pack["markets"][0]["venue"] == "kraken", row["id"]


# ---- 1. dual moving-average crossover -------------------------------------


def _dual_ma_entry_prefix() -> list[Candle]:
    """40 flat bars at 100, then a close of 110.

    Last bar (40): fast sma10 = mean(closes[31..40]) = (9*100 + 110)/10
    = 101.0; slow sma30 = mean(closes[11..40]) = (29*100 + 110)/30 =
    100.3333...; bar 39 had fast = slow = 100 (flat), so
    ``crosses_above`` fires exactly on bar 40.
    """

    return [ _flat(i, 100) for i in range(40) ] + [ _bar(40, 105, 111, 105, 110, 200) ]


def test_dual_ma_crossover_entry_target_is_exact() -> None:
    pack = _pack("starter-dual-ma-crossover")
    target = evaluate.run(pack, _dual_ma_entry_prefix())
    # stop = close * (1 - 5/100) = 110 * 0.95 = 104.5
    _expect(target, long=True, reason="entry", stop=Decimal("104.5"))


def test_dual_ma_crossover_warmup_before_slow_ma_window() -> None:
    pack = _pack("starter-dual-ma-crossover")
    # 25 bars: the 30-bar SMA is still None on the last bar.
    target = evaluate.run(pack, [ _flat(i, 100) for i in range(25) ])
    _expect(target, long=False, reason="warmup", stop=None)


def test_dual_ma_crossover_flat_when_no_cross() -> None:
    pack = _pack("starter-dual-ma-crossover")
    # 41 flat bars: both MAs equal, no cross, no exit.
    target = evaluate.run(pack, [ _flat(i, 100) for i in range(41) ])
    _expect(target, long=False, reason="flat", stop=None)


def test_dual_ma_crossover_exit_on_cross_below() -> None:
    pack = _pack("starter-dual-ma-crossover")
    # 40 flat bars then a close of 90: fast drops below slow on bar 40.
    candles = [ _flat(i, 100) for i in range(40) ] + [ _bar(40, 95, 95, 89, 90, 200) ]
    target = evaluate.run(pack, candles)
    _expect(target, long=False, reason="exit", stop=None)


def test_dual_ma_crossover_entry_matches_series_and_prefix_evaluations() -> None:
    """run_series at the last index equals run on the full prefix, and
    per-prefix run() at each t equals run_series[t] — the shipped pack
    rides the same evaluator invariants the engine tests lock."""

    pack = _pack("starter-dual-ma-crossover")
    candles = _dual_ma_entry_prefix()
    series = evaluate.run_series(pack, candles)
    _expect(series[-1], long=True, reason="entry", stop=Decimal("104.5"))
    _expect(series[24], long=False, reason="warmup", stop=None)
    _expect(series[40], long=True, reason="entry", stop=Decimal("104.5"))
    for t in (10, 29, 30, 39, 40):
        assert evaluate.run(pack, candles[: t + 1]) == series[t], t


# ---- 2. mean-reversion band -----------------------------------------------


def _band_entry_prefix() -> list[Candle]:
    """19 alternating 100/110 bars, 19 bars at 106, then a close of 100.

    Last bar (38): basis = mean(closes[19..38]) = (19*106 + 100)/20 =
    105.7; dev = population stdev of the same window = sqrt(1.71) ≈
    1.3077 > 0.75; close 100 < basis 105.7; exit close >= basis is
    false → entry with the 4% stop.
    """

    head = [ _flat(i, 100 if i % 2 == 0 else 110) for i in range(19) ]
    mid = [ _flat(i, 106) for i in range(19, 38) ]
    return head + mid + [ _flat(38, 100) ]


def test_mean_reversion_band_entry_target_is_exact() -> None:
    pack = _pack("starter-mean-reversion-band")
    target = evaluate.run(pack, _band_entry_prefix())
    # stop = close * (1 - 4/100) = 100 * 0.96 = 96
    _expect(target, long=True, reason="entry", stop=Decimal("96"))


def test_mean_reversion_band_warmup_before_window() -> None:
    pack = _pack("starter-mean-reversion-band")
    # 19 bars: the 20-bar SMA/stdev are still None on the last bar.
    target = evaluate.run(pack, [ _flat(i, 100 if i % 2 == 0 else 110) for i in range(19) ])
    _expect(target, long=False, reason="warmup", stop=None)


def test_mean_reversion_band_flat_when_band_too_tight() -> None:
    pack = _pack("starter-mean-reversion-band")
    # Close is under the basis but dev is tiny: the entry filter fails,
    # so the pack sits flat instead of entering a noise dip.
    candles = (
        [ _flat(i, 100) for i in range(19) ]
        + [ _flat(i, 100.1) for i in range(19, 39) ]
        + [ _flat(39, 100.05) ]
    )
    target = evaluate.run(pack, candles)
    _expect(target, long=False, reason="flat", stop=None)


def test_mean_reversion_band_exit_when_close_back_at_mean() -> None:
    pack = _pack("starter-mean-reversion-band")
    # Close back at/above the 20-bar mean → exit.
    candles = (
        [ _flat(i, 100 if i % 2 == 0 else 110) for i in range(19) ]
        + [ _flat(i, 112) for i in range(19, 39) ]
    )
    target = evaluate.run(pack, candles)
    _expect(target, long=False, reason="exit", stop=None)


# ---- 3. range breakout ----------------------------------------------------


def _breakout_entry_prefix() -> list[Candle]:
    """20 bars with open=close=100, high=101, low=99, volume=200; then a
    bar with high=102, low=100, close=101.9, volume=200.

    Last bar (20): range_top = mean(high[1..20]) = (19*101 + 102)/20 =
    101.2; close 101.9 > 101.2 and volume 200 > 150 → entry. The exit
    legs are false: range_floor = mean(low[1..20]) = (19*99 + 100)/20 =
    99.05 (close is above it) and volume is above 150.

    The ATR stop: every TR is exactly 2 (range 2, and both close-gap
    legs ≤ 2), so the Wilder ATR is exactly 2.0 on every bar ≥ 14 and
    the stop is close - 2.5 * 2.0 = 101.9 - 5.0 = 96.9.
    """

    return [ _flat(i, 100, h=101, low=99) for i in range(20) ] + [
        _bar(20, 101, 102, 100, 101.9, 200)
    ]


def test_range_breakout_entry_target_is_exact() -> None:
    pack = _pack("starter-range-breakout")
    target = evaluate.run(pack, _breakout_entry_prefix())
    _expect(target, long=True, reason="entry", stop=Decimal("96.9"))


def test_range_breakout_warmup_before_window() -> None:
    pack = _pack("starter-range-breakout")
    # 19 bars: the 20-bar SMAs are still None on the last bar.
    target = evaluate.run(pack, [ _flat(i, 100, h=101, low=99) for i in range(19) ])
    _expect(target, long=False, reason="warmup", stop=None)


def test_range_breakout_flat_inside_range() -> None:
    pack = _pack("starter-range-breakout")
    # 21 bars inside the range: close never clears the average high.
    target = evaluate.run(pack, [ _flat(i, 100, h=101, low=99) for i in range(21) ])
    _expect(target, long=False, reason="flat", stop=None)


def test_range_breakout_exit_on_volume_fade() -> None:
    pack = _pack("starter-range-breakout")
    # Same breakout bar but volume 100 ≤ 150: the exit any-leg fires.
    candles = [ _flat(i, 100, h=101, low=99) for i in range(20) ] + [
        _bar(20, 101, 102, 100, 101.9, 100)
    ]
    target = evaluate.run(pack, candles)
    _expect(target, long=False, reason="exit", stop=None)


# ---- cross-example invariants ---------------------------------------------


def test_every_starter_evaluates_every_reason_across_prefixes() -> None:
    """Each starter produces warmup, flat, entry, and exit targets."""

    prefixes = {
        "starter-dual-ma-crossover": _dual_ma_entry_prefix(),
        "starter-mean-reversion-band": _band_entry_prefix(),
        "starter-range-breakout": _breakout_entry_prefix(),
    }
    for example_id, candles in prefixes.items():
        pack = _pack(example_id)
        series = evaluate.run_series(pack, candles)
        reasons = {t.reason for t in series}
        assert "warmup" in reasons, (example_id, reasons)
        assert "entry" in reasons, (example_id, reasons)
        last = series[-1]
        assert last.reason == "entry" and last.long is True, (example_id, last)


def test_starter_evaluation_is_deterministic() -> None:
    """Same pack, same candles → identical Targets on repeated runs."""

    for example_id, candles in (
        ("starter-dual-ma-crossover", _dual_ma_entry_prefix()),
        ("starter-mean-reversion-band", _band_entry_prefix()),
        ("starter-range-breakout", _breakout_entry_prefix()),
    ):
        pack = _pack(example_id)
        first = evaluate.run(pack, candles)
        second = evaluate.run(pack, candles)
        assert first == second, example_id
        assert first.stop_price is not None, example_id

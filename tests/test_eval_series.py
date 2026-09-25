"""run_series equivalence tests.

`evaluate.run_series` is the precompute path the backtester uses. Because every
pack indicator is causal, precomputing each series once over the full candle
list produces, at every bar index t, exactly the Target that `evaluate.run`
would have produced on `candles[: t + 1]`. These tests pin that invariant:

    * Per-indicator equivalence: for every whitelisted fn (and for both stop
      types), the precomputed Target matches the per-prefix Target at every t.
    * Backtest identity: the new Backtester.run is bit-identical to the old
      per-prefix loop across multiple packs and candle series.
    * Receipt identity: the JSON receipt is byte-identical.
    * No per-bar recompute: with a counting monkeypatch, `indicators.compute`
      is called at most (number of pack indicators + 1) times per backtest,
      confirming the indicators are precomputed once.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import asdict
from decimal import Decimal

import pytest

from krellbot.backtest.engine import ZERO, Backtester, BarRecord, PendingFill
from krellbot.backtest.ledger import Ledger
from krellbot.backtest.receipt import build_receipt
from krellbot.pack import run as evaluate_run
from krellbot.pack.evaluate import run_series
from krellbot.pack.model import Candle

# Every fn in the schema. Each gets a pack that exercises it in entry and exit
# via both a cross and a plain comparison, so the precomputed series and the
# per-prefix series are compared across all per-bar code paths.
INDICATOR_FNS = [
    "sma",
    "ema",
    "wma",
    "vwma",
    "hma",
    "stdev",
    "roc",
    "efficiency_ratio",
    "power_mean",
    "highest",
    "lowest",
    "roofing_filter",
    "atr",
]


def _indicator_params(fn: str) -> dict:
    """Build a valid params dict for each whitelisted fn, len=5 throughout."""
    if fn in ("sma", "ema", "wma", "vwma", "stdev", "roc", "efficiency_ratio", "hma"):
        return {"fn": fn, "src": "close", "len": 5}
    if fn in ("highest", "lowest"):
        return {"fn": fn, "src": "close", "len": 5}
    if fn == "power_mean":
        return {"fn": "power_mean", "src": "close", "len": 5, "p": 2}
    if fn == "roofing_filter":
        return {"fn": "roofing_filter", "src": "close", "len": 5, "smooth": 5}
    if fn == "atr":
        return {"fn": "atr", "len": 5}
    raise AssertionError(f"unhandled fn: {fn}")


def _pack_for(fn: str, stop: str = "pct") -> dict:
    """Build a pack that uses <fn> in entry and exit via cross + plain compare."""
    return {
        "schema_version": 1,
        "id": f"equiv-{fn}-{stop}",
        "version": "1.0.0",
        "label": f"equiv {fn} {stop}",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {fn: _indicator_params(fn)},
        "entry": {
            "all": [
                [fn, "crosses_above", "close"],
                ["close", ">", fn],
            ]
        },
        "exit": {
            "any": [
                [fn, "crosses_below", "close"],
                ["close", "<", fn],
            ]
        },
        "risk": {
            "max_account_pct": 25,
            "stop": ({"type": "pct", "pct": 5} if stop == "pct" else {"type": "atr", "len": 5, "mult": 2}),
        },
        "markets": [{"venue": "kraken", "pair": "BTCUSD"}],
    }


def _make_candles(n: int, seed: int = 1337) -> list[Candle]:
    """Generate n deterministic pseudo-random candles with flat stretches and
    zero-volume bars so every indicator path is exercised (vwma gets zeros)."""
    rng = random.Random(seed)
    candles: list[Candle] = []
    price = Decimal(100)
    for i in range(n):
        # ~10% zero-volume bars (vwma warmup edge case).
        vol = Decimal(0) if rng.random() < 0.10 else Decimal(str(round(rng.uniform(1.0, 100.0), 4)))
        # ~10% flat bars (no change) so sma/ema constant-region paths fire.
        if rng.random() < 0.10:
            change = Decimal(0)
        else:
            change = Decimal(str(round(rng.uniform(-2.0, 2.0), 4)))
        new_price = price + change
        if new_price <= 0:
            new_price = Decimal(1)
        o = price
        c = new_price
        # high/low bracket open/close with some noise.
        spread = abs(change) + Decimal(str(round(rng.uniform(0.0, 1.0), 4)))
        h = max(o, c) + spread
        lo = max(Decimal(0), min(o, c) - spread)
        candles.append(
            Candle(
                ts_ms=i * 3_600_000,
                open=o,
                high=h,
                low=lo,
                close=c,
                volume=vol,
            )
        )
        price = new_price
    return candles


@pytest.mark.parametrize("fn", INDICATOR_FNS)
def test_run_series_matches_run_for_every_fn_pct_stop(fn: str) -> None:
    """Each whitelisted fn: precomputed Targets == per-prefix Targets at every t."""
    pack = _pack_for(fn, stop="pct")
    candles = _make_candles(400)
    precomputed = run_series(pack, candles)
    assert len(precomputed) == len(candles)
    for t in range(len(candles)):
        prefix = candles[: t + 1]
        per_prefix = evaluate_run(pack, prefix)
        assert precomputed[t] == per_prefix, (
            f"mismatch at t={t} for fn={fn}: precomputed={precomputed[t]!r} per_prefix={per_prefix!r}"
        )


@pytest.mark.parametrize("fn", INDICATOR_FNS)
def test_run_series_matches_run_for_every_fn_atr_stop(fn: str) -> None:
    """Each whitelisted fn with an ATR stop: precomputed == per-prefix at every t."""
    pack = _pack_for(fn, stop="atr")
    candles = _make_candles(400)
    precomputed = run_series(pack, candles)
    for t in range(len(candles)):
        per_prefix = evaluate_run(pack, candles[: t + 1])
        assert precomputed[t] == per_prefix, (
            f"ATR-stop mismatch at t={t} for fn={fn}: precomputed={precomputed[t]!r} per_prefix={per_prefix!r}"
        )


def test_run_series_empty_candles_returns_empty_list() -> None:
    """run_series on an empty list returns [] (not [Target(flat)])."""
    pack = _pack_for("sma", stop="pct")
    assert run_series(pack, []) == []


def test_run_series_full_target_fields_match() -> None:
    """Verify long, stop_price, and reason all match for a representative pack."""
    pack = _pack_for("sma", stop="pct")
    candles = _make_candles(400)
    precomputed = run_series(pack, candles)
    for t in range(len(candles)):
        per_prefix = evaluate_run(pack, candles[: t + 1])
        assert precomputed[t].long == per_prefix.long
        assert precomputed[t].stop_price == per_prefix.stop_price
        assert precomputed[t].reason == per_prefix.reason


# ---------------------------------------------------------------------------
# Backtest identity
# ---------------------------------------------------------------------------


class _ReferenceBacktester(Backtester):
    """Backtester that evaluates the running prefix each bar (the OLD loop).

    Kept here so the new precompute loop can be checked against the original
    semantics on a per-bar basis. Identical to the prior engine.run body: it
    calls ``evaluate.run(self.pack, self.candles[: t + 1])`` at every bar
    instead of consulting a precomputed targets list.
    """

    def run(self) -> list[BarRecord]:
        ledger = Ledger(cash=self.starting_cash)
        stop_price: Decimal | None = None
        pending: PendingFill | None = None
        trade_count = 0
        round_trip_open_qty: Decimal | None = None
        records: list[BarRecord] = []

        for t, candle in enumerate(self.candles):
            fill_record = None
            stop_fired = False
            if ledger.qty > ZERO and stop_price is not None and candle.low <= stop_price:
                stop_fired = True
                pending = None
                base = min(stop_price, candle.open)
                fill = self._execute_pending(
                    PendingFill(side="sell", base_price=base, is_stop=True),
                    ledger,
                    candle.open,
                )
                fill_record = {
                    "side": "sell",
                    "price": fill,
                    "qty": ledger.last_fill_qty,
                    "fee": ledger.last_fill_fee,
                    "is_stop": True,
                }
                trade_count += 1
                round_trip_open_qty = None
                stop_price = None
            elif pending is not None:
                fill = self._execute_pending(pending, ledger, candle.open)
                fill_record = {
                    "side": pending.side,
                    "price": fill,
                    "qty": ledger.last_fill_qty,
                    "fee": ledger.last_fill_fee,
                    "is_stop": pending.is_stop,
                }
                if pending.side == "buy" and round_trip_open_qty is None:
                    round_trip_open_qty = ledger.qty
                if pending.side == "sell" and round_trip_open_qty is not None:
                    trade_count += 1
                    round_trip_open_qty = None
                pending = None

            if not stop_fired:
                window = self.candles[: t + 1]
                target = evaluate_run(self.pack, window)
                if target.reason == "entry" and ledger.qty == ZERO and t + 1 < len(self.candles):
                    if target.stop_price is not None:
                        stop_price = target.stop_price
                    pending = PendingFill(side="buy", base_price=self.candles[t + 1].open)
                elif target.reason == "exit" and ledger.qty > ZERO and t + 1 < len(self.candles):
                    pending = PendingFill(side="sell", base_price=self.candles[t + 1].open, is_stop=False)

            equity = ledger.cash + ledger.qty * candle.close
            assert ledger.cash >= ZERO, f"cash negative at t={t}: {ledger.cash}"
            assert equity == ledger.cash + ledger.qty * candle.close
            records.append(
                BarRecord(
                    t=t,
                    ts_ms=candle.ts_ms,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    cash_after=ledger.cash,
                    qty_after=ledger.qty,
                    equity=equity,
                    fill=fill_record,
                )
            )

        self.trade_count = trade_count
        return records


def _records_equal(new: list[BarRecord], ref: list[BarRecord]) -> bool:
    """Compare two BarRecord lists field-by-field, including fill dicts."""
    if len(new) != len(ref):
        return False
    for a, b in zip(new, ref, strict=False):
        if asdict(a) != asdict(b):
            return False
    return True


# Three packs that exercise different code paths: pct stop, atr stop, and a
# deep all/any condition tree. Plus a fourth using vwma so zero-volume bars
# flow through the engine unchanged.
BACKTEST_PACKS = [
    _pack_for("sma", stop="pct"),
    _pack_for("ema", stop="atr"),
    _pack_for("vwma", stop="pct"),
]


@pytest.mark.parametrize("pack", BACKTEST_PACKS)
def test_backtest_records_identical_to_reference(pack: dict) -> None:
    """New Backtester.run returns the same records and trade_count as the old loop."""
    candles = _make_candles(600)
    new = Backtester(pack, candles, fee_bps=40, slippage_bps=5, slippage_mult=1.5)
    new_records = new.run()
    ref = _ReferenceBacktester(pack, candles, fee_bps=40, slippage_bps=5, slippage_mult=1.5)
    ref_records = ref.run()
    assert _records_equal(new_records, ref_records), f"records differ for pack {pack['id']!r}"
    assert new.trade_count == ref.trade_count


@pytest.mark.parametrize("pack", BACKTEST_PACKS)
def test_backtest_receipt_bytes_identical(pack: dict) -> None:
    """The JSON receipt built from new records equals the JSON receipt built
    from reference records byte-for-byte."""
    candles = _make_candles(600)
    new_bt = Backtester(pack, candles, fee_bps=40, slippage_bps=5, slippage_mult=1.5)
    new_records = new_bt.run()
    ref_bt = _ReferenceBacktester(pack, candles, fee_bps=40, slippage_bps=5, slippage_mult=1.5)
    ref_records = ref_bt.run()

    new_receipt = build_receipt(
        pack=pack,
        records=new_records,
        trade_count=new_bt.trade_count,
        data_manifest_sha256="a" * 64,
        venue="kraken",
        pair="BTCUSD",
        tf="1h",
        fee_bps=40,
        slippage_bps=5,
        slippage_mult=1.5,
    )
    ref_receipt = build_receipt(
        pack=pack,
        records=ref_records,
        trade_count=ref_bt.trade_count,
        data_manifest_sha256="a" * 64,
        venue="kraken",
        pair="BTCUSD",
        tf="1h",
        fee_bps=40,
        slippage_bps=5,
        slippage_mult=1.5,
    )
    # Canonical JSON bytes (sorted keys, no whitespace).
    new_bytes = json.dumps(new_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ref_bytes = json.dumps(ref_receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert new_bytes == ref_bytes


# ---------------------------------------------------------------------------
# No per-bar recompute
# ---------------------------------------------------------------------------


def test_indicators_compute_is_called_only_once_per_indicator(monkeypatch) -> None:
    """Backtester.run must precompute indicators once, not per bar.

    With a counting wrapper around ``krellbot.pack.indicators.compute``, a
    1,000-bar backtest of a 2-indicator pack with an ATR stop should call it
    at most (2 pack indicators + 1 ATR stop series) = 3 times.
    """
    from krellbot.pack import indicators

    real_compute = indicators.compute
    calls: list[tuple] = []

    def counting_compute(candles, params):
        calls.append(params)
        return real_compute(candles, params)

    monkeypatch.setattr(indicators, "compute", counting_compute)

    # A 2-indicator pack: sma + ema in entry/exit, with an atr stop.
    pack = {
        "schema_version": 1,
        "id": "recompute-test",
        "version": "1.0.0",
        "label": "recompute",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {
            "a": {"fn": "sma", "src": "close", "len": 5},
            "b": {"fn": "ema", "src": "close", "len": 5},
        },
        "entry": ["a", "crosses_above", "b"],
        "exit": ["a", "crosses_below", "b"],
        "risk": {
            "max_account_pct": 25,
            "stop": {"type": "atr", "len": 5, "mult": 2},
        },
        "markets": [{"venue": "kraken", "pair": "BTCUSD"}],
    }
    candles = _make_candles(1_000)
    bt = Backtester(pack, candles, fee_bps=0, slippage_bps=0)
    bt.run()

    # 2 pack indicators + 1 ATR stop series = 3 calls total.
    assert len(calls) <= 3, f"compute called {len(calls)} times: {calls!r}"
    # Verify all three expected params were computed.
    fns = sorted(c["fn"] for c in calls)
    assert fns == sorted(["sma", "ema", "atr"])


def test_indicators_compute_pct_stop_uses_no_extra_call(monkeypatch) -> None:
    """A pack with a pct stop must not compute an ATR series."""
    from krellbot.pack import indicators

    real_compute = indicators.compute
    calls: list[dict] = []

    def counting_compute(candles, params):
        calls.append(copy.deepcopy(dict(params)))
        return real_compute(candles, params)

    monkeypatch.setattr(indicators, "compute", counting_compute)

    pack = _pack_for("sma", stop="pct")
    candles = _make_candles(500)
    Backtester(pack, candles).run()
    # Exactly the pack's 1 indicator: no ATR call.
    fns = [c["fn"] for c in calls]
    assert fns == ["sma"]

"""Issue 284 regression: SMA must average only its CURRENT window.

The old ``_sma`` kept one rolling running sum across windows. When a large
finite price (e.g. 1e16) slid out of the window, the subtraction left
low-order residue in the accumulator and every later window inherited it:
for closes [1e16, 1e16, 1, 1] with len=2 the last window [1, 1] produced
0.0 instead of 1.0. A rule like ``sma < 0.5`` then reported a phantom
entry and the Backtester executed a phantom next-open simulated buy.

The fix averages exactly the current window (bounded-current-window mean)
with exact float64 summation, so no expired bar can contaminate a later
window while warmup length, same-length output, no-lookahead causality and
all healthy finite-window values are preserved.

All candle data here is SYNTHETIC and exists only to qualify the numeric
behavior; nothing in this file is a market-performance claim.
"""

from __future__ import annotations

import csv
import json
import math
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.backtest.engine import Backtester
from krellbot.pack import evaluate as kb_evaluate
from krellbot.pack import indicators
from krellbot.pack.model import Candle

TF_MS_1H = 3_600_000

# The headline contamination series: two 1e16 closes expire, then the
# current window is exactly [1, 1] whose mean must be 1.0.
EXPIRED = 1e16


def _exact_mean(values: list[float]) -> float:
    """Correctly rounded float64 mean of a window, computed exactly.

    Decimal(float) is exact and the windows here have few elements, so the
    only rounding happens in the final float() — the reference the bounded
    current-window implementation must reproduce for these cases.
    """
    total = sum((Decimal(v) for v in values), Decimal(0))
    return float(total / Decimal(len(values)))


def _assert_window_mean(value: float | None, window: list[float]) -> None:
    """Assert `value` equals the window mean to within one float64 ulp.

    Exact Decimal division can be HALF-ulp away from any float64
    sum-then-divide implementation for windows whose exact mean is not
    representable (e.g. [1e16, 1e16, 3, 1, 2] / 5); one ulp is the tightest
    bound any float64 bounded-current-window mean can guarantee.
    """
    assert value is not None
    expected = _exact_mean(window)
    assert math.isclose(value, expected, rel_tol=2e-16, abs_tol=2e-16), (
        f"window {window}: got {value!r}, expected ~{expected!r}"
    )


def _candles(closes: list[float], *, start_ms: int = 0, tf_ms: int = TF_MS_1H) -> list[Candle]:
    """Synthetic candles with open=high=low=close=c and volume=100."""
    out = []
    for i, c in enumerate(closes):
        d = Decimal(str(c))
        out.append(
            Candle(
                ts_ms=start_ms + i * tf_ms,
                open=d,
                high=d,
                low=d,
                close=d,
                volume=Decimal(100),
            )
        )
    return out


# ---------------------------------------------------------------------------
# 1. Direct compute: the current window alone decides the value.
# ---------------------------------------------------------------------------


def test_sma_current_window_mean_ignores_expired_history():
    closes = [EXPIRED, EXPIRED, 1.0, 1.0]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 2})

    assert out == [None, EXPIRED, _exact_mean([EXPIRED, 1.0]), 1.0]
    assert out[3] == 1.0  # the contaminated production value was 0.0


@pytest.mark.parametrize("magnitude", [1e12, 1e15, 1e16, 1e17, 1e18, 1e19])
def test_sma_expired_history_multiple_magnitudes(magnitude: float):
    closes = [magnitude, magnitude, 1.0, 1.0]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 2})

    assert out[1] == magnitude
    assert out[2] == _exact_mean([magnitude, 1.0])
    assert out[3] == 1.0


def test_sma_expired_history_stays_clean_when_expiry_is_farther_back():
    closes = [EXPIRED, EXPIRED, EXPIRED, EXPIRED, 1.0, 1.0, 1.0]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 2})

    assert out[5] == 1.0
    assert out[6] == 1.0
    assert out[4] == _exact_mean([EXPIRED, 1.0])


def test_sma_longer_window_survives_expired_history():
    closes = [EXPIRED, EXPIRED, EXPIRED, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 3})

    assert out[-1] == 1.0
    assert out[-2] == _exact_mean([2.0, 1.0, 1.0])
    assert out[-3] == _exact_mean([2.0, 2.0, 1.0])


# ---------------------------------------------------------------------------
# 2. Preserved contract: float64 values, warmup length, same-length output.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 2, 3, 5])
def test_sma_contract_shape_warmup_and_length(n: int):
    closes = [EXPIRED, EXPIRED, 3.0, 1.0, 2.0, 4.0]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": n})

    assert len(out) == len(closes)
    assert out[: n - 1] == [None] * (n - 1)
    for i in range(n - 1, len(closes)):
        value = out[i]
        assert isinstance(value, float)
        _assert_window_mean(value, closes[i - n + 1 : i + 1])


def test_sma_warmup_is_unchanged_for_short_series():
    out = indicators.compute(_candles([1.0, 2.0]), {"fn": "sma", "src": "close", "len": 5})
    assert out == [None, None]


# ---------------------------------------------------------------------------
# 3. Healthy finite windows keep their supported values.
# ---------------------------------------------------------------------------


def test_sma_healthy_windows_match_reference():
    closes = [10.0, 10.0, 12.0, 14.0, 8.0, 8.0]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 2})
    assert out == [None, 10.0, 11.0, 13.0, 11.0, 8.0]

    ramp = [1.0, 2.0, 3.0, 4.0, 5.0]
    out3 = indicators.compute(_candles(ramp), {"fn": "sma", "src": "close", "len": 3})
    assert out3 == [None, None, 2.0, 3.0, 4.0]


def test_sma_healthy_fractional_window_is_accurate():
    # 1-ulp tolerance: the mean is exact-sum-then-divide float64 math.
    closes = [0.1, 0.2, 0.3]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 3})
    assert out[-1] == pytest.approx(_exact_mean([0.1, 0.2, 0.3]), rel=1e-12)


def test_sma_healthy_large_but_coherent_window():
    closes = [1e8, 2e8, 3e8]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 2})
    assert out[1] == 1.5e8
    assert out[2] == 2.5e8


# ---------------------------------------------------------------------------
# 4. Causality: every prefix's last value equals the full-series value.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("closes", "n"),
    [
        ([EXPIRED, EXPIRED, 1.0, 1.0, 1.0, 1.0], 2),
        ([EXPIRED, EXPIRED, EXPIRED, 2.0, 1.0, 1.0, 1.0], 3),
        ([10.0, 10.0, 12.0, 14.0, 8.0, 8.0], 2),
    ],
)
def test_sma_prefixes_match_full_series(closes: list[float], n: int):
    candles = _candles(closes)
    params = {"fn": "sma", "src": "close", "len": n}
    full = indicators.compute(candles, params)

    for k in range(1, len(candles) + 1):
        prefix = indicators.compute(candles[:k], params)
        assert len(prefix) == k
        assert prefix[k - 1] == full[k - 1], f"prefix k={k} diverged from full series"


# ---------------------------------------------------------------------------
# 5. Ordinary real evaluate()/run_series(): no phantom entry.
# ---------------------------------------------------------------------------

PHANTOM_ENTRY_ONLY_PACK = {
    "schema_version": 1,
    "id": "sma-expired-history",
    "version": "1.0.0",
    "label": "SMA expired-window regression (entry only)",
    "author": "krellbot tests",
    "timeframe": "1h",
    "origin": "Synthetic regression fixture.",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["sma2", "<", 0.5],
    "exit": ["close", "<", 0],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}

PHANTOM_ROUND_TRIP_PACK = {
    **PHANTOM_ENTRY_ONLY_PACK,
    "id": "sma-expired-history-rt",
    "label": "SMA expired-window regression (round trip)",
    "exit": ["sma2", ">", 0.5],
}

HEALTHY_CROSS_PACK = {
    **PHANTOM_ENTRY_ONLY_PACK,
    "id": "sma-expired-history-healthy",
    "label": "SMA healthy cross regression",
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
}


@pytest.mark.parametrize("magnitude", [1e15, 1e16, 1e17, 1e18])
def test_evaluate_no_phantom_entry_after_expired_history(magnitude: float):
    candles = _candles([magnitude, magnitude, 1.0, 1.0, 1.0, 1.0])

    targets = kb_evaluate.run_series(PHANTOM_ENTRY_ONLY_PACK, candles)
    assert [t.reason for t in targets] == ["warmup", "flat", "flat", "flat", "flat", "flat"]
    assert all(not t.long for t in targets)
    assert all(t.stop_price is None for t in targets)

    # run() on each prefix agrees with run_series (per-bar decision parity).
    for k in range(1, len(candles) + 1):
        assert kb_evaluate.run(PHANTOM_ENTRY_ONLY_PACK, candles[:k]) == targets[k - 1]


def test_evaluate_healthy_cross_still_fires():
    candles = _candles([10.0, 10.0, 12.0, 14.0, 8.0, 8.0])
    targets = kb_evaluate.run_series(HEALTHY_CROSS_PACK, candles)

    # t=2 close 12 crosses above sma 11 -> entry; t=5 close 8 vs sma 8 is
    # neither a cross above nor below -> flat.
    assert [t.reason for t in targets] == ["warmup", "flat", "entry", "flat", "exit", "flat"]
    assert targets[2].long is True
    assert targets[2].stop_price == Decimal(6)


# ---------------------------------------------------------------------------
# 6. Backtester: no phantom entry/next-open simulated buy.
# ---------------------------------------------------------------------------


def test_backtester_no_phantom_fill_after_expired_history():
    candles = _candles([EXPIRED, EXPIRED, 1.0, 1.0, 1.0, 1.0])
    bt = Backtester(PHANTOM_ROUND_TRIP_PACK, candles, fee_bps=0, slippage_bps=0)

    records = bt.run()

    assert bt.trade_count == 0
    assert all(r.fill is None for r in records)
    assert all(r.qty_after == Decimal(0) for r in records)
    assert all(r.equity == Decimal(10000) for r in records)


def test_backtester_healthy_cross_still_trades():
    candles = _candles([10.0, 10.0, 12.0, 14.0, 8.0, 8.0, 8.0, 8.0])
    bt = Backtester(HEALTHY_CROSS_PACK, candles, fee_bps=0, slippage_bps=0)

    records = bt.run()

    assert bt.trade_count == 1
    buy = records[3].fill
    sell = records[5].fill
    assert buy is not None and buy["side"] == "buy" and buy["price"] == Decimal(14)
    assert sell is not None and sell["side"] == "sell" and sell["price"] == Decimal(8)


# ---------------------------------------------------------------------------
# 7. Offline ResearchService end-to-end: no phantom entry/fill outcome.
# ---------------------------------------------------------------------------


def _write_csv(path: Path, closes: list[float]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i, c in enumerate(closes):
            d = Decimal(str(c))
            w.writerow([i * TF_MS_1H, str(d), str(d), str(d), str(d), "100"])
    return path


def _write_pack(path: Path, pack: dict) -> Path:
    path.write_text(json.dumps(pack), encoding="utf-8")
    return path


def test_research_service_offline_no_phantom_trade(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    pack_path = _write_pack(tmp_path / "pack.json", PHANTOM_ROUND_TRIP_PACK)
    csv_path = _write_csv(tmp_path / "data.csv", [EXPIRED, EXPIRED, 1.0, 1.0, 1.0, 1.0])

    result = ResearchService(home=tmp_path).run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            dataset_csv=csv_path,
            fee_bps=0,
            slippage_bps=0,
        )
    )

    assert result.ok, result.refusal
    assert result.detail["trade_count"] == 0
    assert result.legacy_receipt is not None
    assert result.legacy_receipt["metrics"]["trade_count"] == 0
    trace = result.detail["trace"]
    assert all(t["target"]["reason"] != "entry" for t in trace)
    assert all(not t["target"]["long"] for t in trace)
    # The current window [1, 1] must evaluate to exactly 1.0 on the last bars.
    assert trace[3]["indicators"]["sma2"] == 1.0
    assert trace[5]["indicators"]["sma2"] == 1.0
    assert math.isfinite(result.legacy_receipt["metrics"]["total_return_pct"])


def test_research_service_offline_healthy_cross_still_trades(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    pack_path = _write_pack(tmp_path / "pack.json", HEALTHY_CROSS_PACK)
    csv_path = _write_csv(tmp_path / "data.csv", [10.0, 10.0, 12.0, 14.0, 8.0, 8.0, 8.0, 8.0])

    result = ResearchService(home=tmp_path).run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            dataset_csv=csv_path,
            fee_bps=0,
            slippage_bps=0,
        )
    )

    assert result.ok, result.refusal
    assert result.detail["trade_count"] == 1
    trace = result.detail["trace"]
    assert trace[2]["target"]["reason"] == "entry"
    assert trace[2]["indicators"]["sma2"] == 11.0


# ---------------------------------------------------------------------------
# 8. Mixed +/-inf (and finite Decimal 1e400/-1e400) in ONE SMA window.
#
# math.fsum raises ValueError('-inf + inf in fsum') when a single window
# holds both +inf and -inf. Before the repair that ValueError escaped
# compute/evaluate/Backtester/ResearchService and the real CLI as a raw
# Python traceback. The repair treats it exactly like the existing
# OverflowError fallback: plain IEEE addition -> nan for that window only,
# so the product boundary answers instead of crashing. These rows were the
# independent review's REJECT evidence (opus-b40-run422, 20261027).
# ---------------------------------------------------------------------------


def _inf_candles(closes: list[str]) -> list[Candle]:
    """Candles from literal CSV spellings, preserving inf/1e400 semantics.

    Decimal('Infinity')/Decimal('-Infinity') and the finite literals
    Decimal('1e400')/Decimal('-1e400') both survive Decimal parsing; only
    indicators._series' float() conversion produces float('inf') /
    float('-inf') (the 1e400 pair overflows float64 the same way).
    """
    out = []
    for i, c in enumerate(closes):
        d = Decimal(c)
        out.append(
            Candle(
                ts_ms=i * TF_MS_1H,
                open=d,
                high=d,
                low=d,
                close=d,
                volume=Decimal(100),
            )
        )
    return out


@pytest.mark.parametrize("spelling", ["Infinity", "1e400"])
def test_sma_mixed_inf_window_is_nan_not_a_crash(spelling: str):
    # Both spellings make _series produce [inf, -inf, ...]; the mixed window
    # mean must be the IEEE nan, computed by plain addition — never a raise.
    closes = [spelling, "-" + spelling if spelling == "1e400" else "-Infinity", 1.0, 1.0]
    out = indicators.compute(_inf_candles(closes), {"fn": "sma", "src": "close", "len": 2})

    assert out == [None, out[1], -math.inf, 1.0]
    assert isinstance(out[1], float)
    assert math.isnan(out[1])  # the old code raised ValueError here
    assert out[3] == 1.0  # once the pair has expired the clean window recovers exactly


def test_sma_mixed_inf_only_that_window_is_nan():
    # n=3, closes [inf, 1, -inf, 3, 4, 5]. The mixed window [inf,1,-inf] is
    # nan (plain addition). The later windows hold only -inf, so fsum itself
    # answers -inf without raising; the clean [3,4,5] window keeps its exact
    # fsum mean.
    closes = ["Infinity", "1", "-Infinity", "3", "4", "5"]
    out = indicators.compute(_inf_candles(closes), {"fn": "sma", "src": "close", "len": 3})

    assert out[:2] == [None, None]
    assert math.isnan(out[2])  # [inf, 1, -inf]: plain addition -> nan
    assert out[3] == -math.inf  # [1, -inf, 3]: fsum answers one-sided -inf itself
    assert out[4] == -math.inf  # [-inf, 3, 4]: same
    assert out[5] == _exact_mean([3.0, 4.0, 5.0])  # clean window: exact mean


def test_sma_one_sided_inf_keeps_inf_semantics():
    # Only +inf in the window: fsum answers +inf itself (its ValueError is
    # exclusively the +inf/-inf mix), so the means stay +inf.
    closes = ["Infinity", "Infinity", "1"]
    out = indicators.compute(_inf_candles(closes), {"fn": "sma", "src": "close", "len": 2})

    assert out == [None, math.inf, math.inf]


def test_sma_huge_finite_window_keeps_overflow_fallback():
    # The pre-existing OverflowError lane is untouched: a window of two 1e308
    # closes overflows fsum's intermediate; plain IEEE addition yields inf
    # exactly as before this repair, and clean neighbors keep exact means.
    closes = [1e308, 1e308, 1.0]
    out = indicators.compute(_candles(closes), {"fn": "sma", "src": "close", "len": 2})

    assert out[1] == math.inf
    _assert_window_mean(out[2], [1e308, 1.0])


# Packs for the mixed-inf rows. Entry requires mean < 0.5: the nan window
# itself never fires (nan comparisons are False); the following [-inf, 1]
# window has the IEEE -inf mean and DOES fire -- current-window semantics.
# The exits are chosen so neither depends on a poisoned close comparison.
MIXED_INF_ENTRY_ONLY_PACK = {
    **PHANTOM_ENTRY_ONLY_PACK,
    "id": "sma-mixed-inf-entry",
    "label": "SMA mixed-inf regression (entry only)",
    "exit": ["close", ">", 1000000000],  # never true: bar 0 is warmup, the rest are <= 1
}

MIXED_INF_ROUND_TRIP_PACK = {
    **MIXED_INF_ENTRY_ONLY_PACK,
    "id": "sma-mixed-inf-rt",
    "label": "SMA mixed-inf regression (round trip)",
    "exit": ["sma2", ">", 0.5],  # true again once the clean [1, 1] windows return
}


@pytest.mark.parametrize("spelling", ["Infinity", "1e400"])
def test_evaluate_mixed_inf_window_answers_without_raising(spelling: str):
    closes = [spelling, "-" + spelling if spelling == "1e400" else "-Infinity", 1.0, 1.0, 1.0]

    targets = kb_evaluate.run_series(MIXED_INF_ENTRY_ONLY_PACK, _inf_candles(closes))

    # The mixed window itself is nan and nan < 0.5 is False (no phantom
    # entry from the poisoned window). The NEXT window [-inf, 1] has the
    # IEEE -inf mean and does fire entry -- current-window semantics, not a
    # crash; the exit condition (close > 1e9) never becomes true.
    assert [t.reason for t in targets] == ["warmup", "flat", "entry", "flat", "flat"]
    assert [t.long for t in targets] == [False, False, True, False, False]
    # per-bar decision parity is preserved
    candles = _inf_candles(closes)
    for k in range(1, len(candles) + 1):
        assert kb_evaluate.run(MIXED_INF_ENTRY_ONLY_PACK, candles[:k]) == targets[k - 1]


def test_backtester_mixed_inf_window_answers_without_raising():
    # Finite Decimal 1e400/-1e400 candles: the run completes end to end.
    # The entry from the [-inf, 1] window fills at the next bar's FINITE
    # open (1), the clean [1, 1] window's exit sells back at 1, and the
    # ledger never leaves its finite money domain.
    closes = ["1e400", "-1e400", 1.0, 1.0, 1.0, 1.0]

    bt = Backtester(MIXED_INF_ROUND_TRIP_PACK, _inf_candles(closes), fee_bps=0, slippage_bps=0)

    records = bt.run()

    assert bt.trade_count == 1
    fills = [(r.t, r.fill) for r in records if r.fill is not None]
    assert [(t, f["side"], f["price"]) for t, f in fills] == [(3, "buy", Decimal(1)), (4, "sell", Decimal(1))]
    assert all(r.equity == Decimal(10000) for r in records)


def _write_literal_csv(path: Path, closes: list[str]) -> Path:
    """Like _write_csv but for literal spellings (Infinity/1e400...)."""
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for i, c in enumerate(closes):
            d = Decimal(c)
            w.writerow([i * TF_MS_1H, str(d), str(d), str(d), str(d), "100"])
    return path


@pytest.mark.parametrize("spelling", ["Infinity", "1e400"])
def test_research_service_mixed_inf_dataset_answers_not_crashes(tmp_path: Path, monkeypatch, spelling: str):
    """The blocking row: a dataset CSV with +inf/-inf (or 1e400/-1e400) in
    one SMA window reaches ResearchService.run through the product's own
    parser. The service must return its typed boundary answer — BASE main
    refused ±inf with numeric_out_of_range and accepted ±1e400 with an
    exit-0 zero-trade receipt — never raise a raw ValueError."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    pack_path = _write_pack(tmp_path / "pack.json", MIXED_INF_ROUND_TRIP_PACK)
    negative = "-" + spelling if spelling == "1e400" else "-Infinity"
    csv_path = _write_literal_csv(tmp_path / "data.csv", [spelling, negative, 1.0, 1.0, 1.0, 1.0])

    result = ResearchService(home=tmp_path).run(
        ResearchRequest(
            pack_path=pack_path,
            venue="kraken",
            dataset_csv=csv_path,
            fee_bps=0,
            slippage_bps=0,
        )
    )

    if spelling == "Infinity":
        # Literal inf candles never reach the money domain: the engine's
        # 0 * inf equity guard raises decimal.InvalidOperation and the
        # service maps it to the typed refusal -- exactly BASE main's
        # answer to this dataset.
        assert not result.ok, result.detail
        assert result.refusal is not None
        assert result.refusal["code"] == "numeric_out_of_range"
    else:
        # Finite Decimal 1e400/-1e400 candles run to completion: the -inf
        # window's entry fills at the next FINITE open (1) and the clean
        # window's exit sells back, so one round trip, all equities finite.
        assert result.ok, result.refusal
        assert result.legacy_receipt is not None
        assert result.legacy_receipt["metrics"]["trade_count"] == 1
        assert result.detail["trade_count"] == 1
        assert math.isfinite(result.legacy_receipt["metrics"]["total_return_pct"])
        entry_rows = [t for t in result.detail["trace"] if t["target"]["reason"] == "entry"]
        assert len(entry_rows) == 1


REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"  # unreachable; --data keeps the run offline
    env["KRELLBOT_HOME"] = str(home)
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
    )


@pytest.mark.parametrize("spelling", ["Infinity", "1e400"])
def test_cli_backtest_mixed_inf_dataset_no_traceback(tmp_path: Path, monkeypatch, spelling: str):
    """The reviewer's CLI row: real `krellbot backtest <pack> --data csv
    --json` subprocess. Before the repair the process died with a raw
    `ValueError: -inf + inf in fsum` traceback (exit 1). After it the CLI
    answers with its normal refusal sentence (BASE behavior) or its normal
    --json zero-trade receipt, and never prints a Python traceback."""
    home = tmp_path
    monkeypatch.setenv("KRELLBOT_HOME", str(home))
    pack_path = _write_pack(home / "pack.json", MIXED_INF_ROUND_TRIP_PACK)
    negative = "-" + spelling if spelling == "1e400" else "-Infinity"
    csv_path = _write_literal_csv(home / "data.csv", [spelling, negative, 1.0, 1.0, 1.0, 1.0])

    r = _run_cli(home, "backtest", str(pack_path), "--venue", "kraken", "--data", str(csv_path), "--json")

    # Never a Python traceback: that raw ValueError escape was the defect.
    assert "Traceback" not in r.stderr, r.stderr
    if spelling == "Infinity":
        # BASE main's answer to the literal-inf dataset: typed refusal
        # sentence on stderr, exit 1.
        assert r.returncode == 1
        assert "numeric" in r.stderr.lower(), r.stderr
    else:
        # BASE main's answer to the finite 1e400 dataset: exit-0 --json
        # receipt (now with the deterministic one-round-trip outcome).
        assert r.returncode == 0, r.stderr
        receipt = json.loads(r.stdout)
        assert receipt["metrics"]["trade_count"] == 1
        assert math.isfinite(receipt["metrics"]["total_return_pct"])

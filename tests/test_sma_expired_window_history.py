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

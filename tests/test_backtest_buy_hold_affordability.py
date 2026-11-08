"""Synthetic benchmark sizing must not borrow cash through quantity rounding."""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import ROUND_DOWN, Decimal

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.backtest.engine import Backtester
from krellbot.backtest.metrics import buy_and_hold_curve, compute_metrics
from krellbot.pack.model import Candle
from tests.test_ns04_research_service import PACK_DICT

STEP = Decimal("0.00000001")


def _bars():
    return [
        Candle(0, Decimal(60000), Decimal(60000), Decimal(60000), Decimal(60000), Decimal(100)),
        Candle(3_600_000, Decimal(60000), Decimal(60000), Decimal(1000), Decimal(1000), Decimal(100)),
        Candle(7_200_000, Decimal(1000), Decimal(1000), Decimal(1000), Decimal(1000), Decimal(100)),
    ]


@pytest.mark.parametrize("units", ["0.4", "0.9", "1", "1.4", "1.5", "1.6", "2", "2.5", "10.9"])
@pytest.mark.parametrize("fee,slip,mult", [(0, 0, 1.0), (40, 0, 1.0), (0, 5, 1.5), (40, 5, 1.5)])
def test_fractional_quantity_boundary_never_overdraws(units, fee, slip, mult):
    bars = _bars()
    before = [asdict(bar) for bar in bars]
    fill = bars[1].open * (1 + Decimal(slip) / 10000 * Decimal(str(mult)))
    unit_cost = STEP * fill * (1 + Decimal(fee) / 10000)
    budget = Decimal(units) * unit_cost
    qty = Decimal(units).to_integral_value(rounding=ROUND_DOWN) * STEP
    cash_after = budget - qty * fill - qty * fill * Decimal(fee) / 10000
    assert cash_after >= 0
    assert (qty + STEP) * fill * (1 + Decimal(fee) / 10000) > budget
    expected = [(bars[0].ts_ms, budget)] + [(bar.ts_ms, cash_after + qty * bar.close) for bar in bars[1:]]
    curve = buy_and_hold_curve(bars, budget, fee, slip, mult)
    assert curve == expected
    assert all(equity >= 0 for _, equity in curve)
    assert [asdict(bar) for bar in bars] == before


@pytest.mark.parametrize("budget", ["0.001", "0.0012", "0.0001", "10000"])
@pytest.mark.parametrize("fee,slip", [(0, 0), (40, 5)])
def test_real_offline_service_benchmark_and_strategy_receipt(home, monkeypatch, fresh_keyring, budget, fee, slip):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)
    pack = {**PACK_DICT, "label": "Synthetic buy-and-hold affordability fixture"}
    pack_path = home / "synthetic-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    bars = _bars()
    csv = home / "synthetic-prices.csv"
    body = "ts_ms,open,high,low,close,volume\n" + "".join(
        f"{b.ts_ms},{b.open},{b.high},{b.low},{b.close},{b.volume}\n" for b in bars
    )
    csv.write_bytes(body.encode())
    cash = Decimal(budget)
    request = ResearchRequest(
        pack_path=pack_path, dataset_csv=csv, venue="kraken", starting_cash=cash, fee_bps=fee, slippage_bps=slip
    )
    result = ResearchService(home=home, fetch=None).run(request)
    assert result.ok, result.refusal
    receipt = result.legacy_receipt
    fill = Decimal(60000) * (1 + Decimal(slip) / 10000)
    unit_cost = fill * (1 + Decimal(fee) / 10000) * STEP
    units = (cash / unit_cost).to_integral_value(rounding=ROUND_DOWN)
    expected_cash = cash - units * unit_cost
    expected_final = expected_cash + units * STEP * Decimal(1000)
    assert expected_cash >= 0
    benchmark = receipt["metrics"]["buy_and_hold"]
    assert benchmark["total_return_pct"] == float((expected_final / cash - 1) * 100)
    assert benchmark["total_return_pct"] >= -100
    engine = Backtester(pack, bars, starting_cash=cash, fee_bps=fee, slippage_bps=slip)
    records = engine.run()
    metrics = compute_metrics(
        [(r.ts_ms, r.equity) for r in records],
        engine.trade_count,
        sum(r.qty_after > 0 for r in records),
        len(records),
        cash,
    )
    assert {k: v for k, v in receipt["metrics"].items() if k != "buy_and_hold"} == asdict(metrics)
    assert receipt["equity_curve"] == [float((r.equity / cash - 1) * 100) for r in records]
    assert receipt["fee_bps"] == fee and receipt["slippage_bps"] == slip
    assert csv.read_bytes() == body.encode()


def test_no_entry_opportunity_preserves_starting_cash():
    bars = _bars()
    assert buy_and_hold_curve([], Decimal("0.001"), 40, 5, 1.0) == []
    assert buy_and_hold_curve(bars[:1], Decimal("0.001"), 40, 5, 1.0) == [(0, Decimal("0.001"))]

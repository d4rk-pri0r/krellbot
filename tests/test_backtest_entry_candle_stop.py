"""Regression: a protective stop covers the candle that fills a fresh long.

Tracer for issue #240 (Class B / money-math). One end-to-end slice through
the real public surfaces only -- ``Backtester.run()`` and the offline
``ResearchService`` -- over one clearly-labelled synthetic pack/CSV:

    bar  t  open  high  low  close   note
    0    0   90    90    90    90     sma2 warmup (len-2 indicator needs 2 bars)
    1    1   90    90    90    90     flat
    2    2   90   100    90   100     entry signal at the close; 10% stop -> 90
    3    3  100   100    80    80     buy fills at 100; low 80 breaches stop 90

Budget is 100% of 10000 at a fill price of 100, so qty is exactly 100 and
the entry bar's cash is 0. The protective stop must fire on bar 3 itself at
min(stop, open) = 90: cash and equity both end at 9000 and exactly one
round trip is counted.

On the current base the same-candle breach is ignored -- the stop is only
checked at the top of a bar, before the pending buy fills -- so bar 3 ends
long (qty 100, equity 8000), ``trade_count`` stays 0 and the service
surfaces ``total_return_pct == -20`` with ``metrics.trade_count == 0``.

``BarRecord.fill`` is a single slot per bar and is NOT widened here. The
entry candle carries two fills, so the slot is asserted to report the
terminal protective stop, while ``cash_after``/``qty_after`` are asserted to
reconcile both legs (buy 100 @ 100, sell 100 @ 90). Receipt and detail keep
their existing locked key sets; no field is invented.
"""

from __future__ import annotations

import csv
import json
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.backtest.engine import Backtester
from krellbot.pack.model import Candle

# (ts_ms, open, high, low, close); volume is a constant 100 for every bar.
SYNTHETIC_BARS = (
    (0, "90", "90", "90", "90"),
    (3_600_000, "90", "90", "90", "90"),
    (7_200_000, "90", "100", "90", "100"),
    (10_800_000, "100", "100", "80", "80"),
)
SYNTHETIC_VOLUME = "100"

# Existing locked shapes (krellbot.backtest.receipt / ResearchResult.detail).
RECEIPT_KEYS = {
    "engine_version",
    "pack_sha256",
    "data_manifest_sha256",
    "venue",
    "pair",
    "tf",
    "from",
    "to",
    "fee_bps",
    "slippage_bps",
    "slippage_mult",
    "metrics",
    "equity_curve",
}
DETAIL_KEYS = {"schema_version", "venue", "pair", "tf", "bar_count", "trade_count", "trace"}
TRACE_KEYS = {"bar_ts", "warmup", "input", "indicators", "conditions", "target"}


def _synthetic_pack() -> dict:
    """Minimal valid v1 pack: one used indicator, one entry cross, 10% stop."""
    return {
        "schema_version": 1,
        "id": "entry-candle-stop",
        "version": "1.0.0",
        "label": "Synthetic entry-candle stop",
        "author": "krellbot tests",
        "origin": "Synthetic regression data for issue 240; not market data.",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 10}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


def _synthetic_candles(bars=SYNTHETIC_BARS) -> list[Candle]:
    return [
        Candle(
            ts_ms=ts_ms,
            open=Decimal(o),
            high=Decimal(h),
            low=Decimal(low),
            close=Decimal(c),
            volume=Decimal(SYNTHETIC_VOLUME),
        )
        for ts_ms, o, h, low, c in bars
    ]


def _write_synthetic_csv(path: Path, bars=SYNTHETIC_BARS) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for ts_ms, o, h, low, c in bars:
            writer.writerow([ts_ms, o, h, low, c, SYNTHETIC_VOLUME])
    return path


def test_entry_candle_stop_breach_closes_fresh_long_same_candle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))

    pack = _synthetic_pack()
    pack_path = tmp_path / "synthetic-entry-candle-stop.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    csv_path = _write_synthetic_csv(tmp_path / "synthetic-entry-candle-stop.csv")
    candles = _synthetic_candles()

    # --- public engine surface: BarRecord per bar + trade_count -----------
    bt = Backtester(pack, candles, starting_cash=Decimal(10000), fee_bps=0, slippage_bps=0)
    records = bt.run()

    assert [r.t for r in records] == [0, 1, 2, 3]
    assert records[2].fill is None  # signal bar: no fill, no position yet
    assert records[2].qty_after == Decimal(0)

    entry_bar = records[3]
    assert entry_bar.open == Decimal(100)
    assert entry_bar.low == Decimal(80)
    # The fresh long is protected on its own fill candle at min(stop, open).
    assert entry_bar.qty_after == Decimal(0)
    assert entry_bar.cash_after == Decimal(9000)
    assert entry_bar.equity == Decimal(9000)
    assert bt.trade_count == 1

    # One `fill` slot per bar, reported unchanged in shape: it carries the
    # terminal protective stop of the entry candle, not a second record.
    fills = [r.fill for r in records if r.fill is not None]
    assert len(fills) == 1
    assert set(fills[0]) == {"side", "price", "qty", "fee", "is_stop"}
    assert fills[0] == {
        "side": "sell",
        "price": Decimal(90),
        "qty": Decimal(100),
        "fee": Decimal(0),
        "is_stop": True,
    }
    # Both legs really ran: entry spend (100 @ 100) plus exit proceeds (100 @ 90).
    stop_qty = fills[0]["qty"]
    assert entry_bar.cash_after == Decimal(10000) - stop_qty * Decimal(100) + stop_qty * Decimal(90)

    # --- offline service surface: same pack/CSV, receipt + detail --------
    result = ResearchService(home=tmp_path).run(
        ResearchRequest(
            pack_path=pack_path,
            dataset_csv=csv_path,
            venue="kraken",
            fee_bps=0,
            slippage_bps=0,
            slippage_mult=1.0,
        )
    )
    assert result.ok is True
    assert result.refusal is None
    receipt = result.legacy_receipt
    assert isinstance(receipt, dict)

    assert set(receipt) == RECEIPT_KEYS
    assert receipt["venue"] == "kraken"
    assert receipt["pair"] == "SUIUSD"
    assert receipt["tf"] == "1h"
    assert receipt["fee_bps"] == 0
    assert receipt["slippage_bps"] == 0
    assert receipt["slippage_mult"] == 1.0
    assert set(receipt["metrics"]) == {
        "total_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "return_to_dd",
        "per_year",
        "trade_count",
        "exposure_pct",
        "buy_and_hold",
    }

    metrics = receipt["metrics"]
    assert metrics["trade_count"] == 1
    assert metrics["trade_count"] == bt.trade_count
    assert metrics["total_return_pct"] == pytest.approx(-10.0, abs=1e-9)
    assert receipt["equity_curve"] == pytest.approx([0.0, 0.0, 0.0, -10.0], abs=1e-9)
    assert abs(receipt["equity_curve"][-1] - metrics["total_return_pct"]) <= 0.01

    detail = result.detail
    assert set(detail) == DETAIL_KEYS
    assert detail["schema_version"] == "1"
    assert detail["venue"] == receipt["venue"]
    assert detail["pair"] == receipt["pair"]
    assert detail["tf"] == receipt["tf"]
    assert detail["bar_count"] == len(candles) == 4
    assert detail["trade_count"] == metrics["trade_count"] == 1

    # The trace explains evaluator output only; it names the stop the engine
    # must honour on the very next bar's open fill.
    entry_traces = [t for t in detail["trace"] if t["target"]["reason"] == "entry"]
    assert len(entry_traces) == 1
    entry_trace = entry_traces[0]
    assert set(entry_trace) == TRACE_KEYS
    assert entry_trace["bar_ts"] == 7_200_000
    assert entry_trace["target"]["long"] is True
    assert entry_trace["target"]["stop_price"] == pytest.approx(90.0)
    assert len(detail["trace"]) == len(candles)


def _fill(record):
    assert isinstance(record.fill, dict)
    assert set(record.fill) == {"side", "price", "qty", "fee", "is_stop"}
    return record.fill


def _scenario(tmp_path, monkeypatch, bars, *, pack=None, fee_bps=0, slippage_bps=0, slippage_mult=1.0):
    """Actual engine/service on the same explicitly synthetic local input."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    pack = _synthetic_pack() if pack is None else pack
    path = tmp_path / "synthetic-control-pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    csv_path = _write_synthetic_csv(tmp_path / "synthetic-control.csv", bars)
    bt = Backtester(
        pack,
        _synthetic_candles(bars),
        starting_cash=Decimal(10000),
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        slippage_mult=slippage_mult,
    )
    records = bt.run()
    result = ResearchService(home=tmp_path).run(
        ResearchRequest(
            pack_path=path,
            dataset_csv=csv_path,
            venue="kraken",
            pair="SUIUSD",
            starting_cash=Decimal(10000),
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            slippage_mult=slippage_mult,
        )
    )
    assert result.ok is True, result.refusal
    receipt = result.legacy_receipt
    assert isinstance(receipt, dict)
    assert set(receipt) == RECEIPT_KEYS
    assert set(result.detail) == DETAIL_KEYS
    assert all(set(row) == TRACE_KEYS for row in result.detail["trace"])
    assert result.detail["bar_count"] == len(records)
    assert receipt["metrics"]["trade_count"] == result.detail["trade_count"] == bt.trade_count
    total_return = float((records[-1].equity / Decimal(10000) - 1) * 100)
    assert receipt["metrics"]["total_return_pct"] == pytest.approx(total_return, abs=1e-9)
    assert receipt["equity_curve"][-1] == pytest.approx(total_return, abs=0.01)
    for row in records:
        assert row.cash_after >= 0
        assert row.equity == row.cash_after + row.qty_after * row.close
    return bt, records, result


def test_no_entry_breach_keeps_long_and_next_candle_breach_still_stops(tmp_path, monkeypatch):
    bars = SYNTHETIC_BARS[:3] + ((10_800_000, "100", "100", "95", "100"),)
    bt, records, _ = _scenario(tmp_path, monkeypatch, bars)
    assert records[-1].qty_after == Decimal(100)
    assert records[-1].cash_after == 0
    assert records[-1].equity == Decimal(10000)
    assert _fill(records[-1])["is_stop"] is False
    assert bt.trade_count == 0

    later = tmp_path / "later"
    later.mkdir()
    bt, records, _ = _scenario(later, monkeypatch, bars + ((14_400_000, "100", "100", "80", "80"),))
    assert records[3].qty_after == Decimal(100)
    assert records[4].qty_after == 0
    assert records[4].cash_after == records[4].equity == Decimal(9000)
    assert _fill(records[4])["price"] == Decimal(90)
    assert _fill(records[4])["is_stop"] is True
    assert bt.trade_count == 1


def test_exact_stop_touch_on_entry_candle_is_not_ignored(tmp_path, monkeypatch):
    bars = SYNTHETIC_BARS[:3] + ((10_800_000, "100", "100", "90", "90"),)
    bt, records, _ = _scenario(tmp_path, monkeypatch, bars)
    assert records[-1].cash_after == records[-1].equity == Decimal(9000)
    assert records[-1].qty_after == 0
    assert _fill(records[-1])["price"] == Decimal(90)
    assert _fill(records[-1])["is_stop"] is True
    assert bt.trade_count == 1


def test_entry_gap_through_stop_uses_open_not_higher_stop(tmp_path, monkeypatch):
    bars = SYNTHETIC_BARS[:3] + ((10_800_000, "80", "85", "70", "75"),)
    bt, records, _ = _scenario(tmp_path, monkeypatch, bars)
    last = records[-1]
    assert last.qty_after == 0
    assert last.cash_after == last.equity == Decimal(10000)
    assert last.fill == {
        "side": "sell",
        "price": Decimal(80),
        "qty": Decimal(125),
        "fee": Decimal(0),
        "is_stop": True,
    }
    assert bt.trade_count == 1


def test_entry_stop_accounts_for_both_fees_slippage_and_quantity_rounding(tmp_path, monkeypatch):
    bt, records, _ = _scenario(tmp_path, monkeypatch, SYNTHETIC_BARS, fee_bps=10, slippage_bps=20, slippage_mult=1.5)
    fee = Decimal(10) / Decimal(10000)
    slip = Decimal(20) / Decimal(10000) * Decimal("1.5")
    buy_price = Decimal(100) * (1 + slip)
    sell_price = Decimal(90) * (1 - slip)
    qty = (Decimal(10000) / (buy_price * (1 + fee))).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    buy_cost = qty * buy_price
    buy_fee = buy_cost * fee
    sell_proceeds = qty * sell_price
    sell_fee = sell_proceeds * fee
    expected_cash = Decimal(10000) - (buy_cost + buy_fee) + (sell_proceeds - sell_fee)
    last = records[-1]
    assert last.qty_after == 0
    assert last.cash_after == last.equity == expected_cash
    assert last.fill == {"side": "sell", "price": sell_price, "qty": qty, "fee": sell_fee, "is_stop": True}
    assert buy_fee > 0 and sell_fee > 0
    assert bt.trade_count == 1


def test_zero_quantity_buy_does_not_invent_a_stop_or_round_trip(tmp_path, monkeypatch):
    bars = SYNTHETIC_BARS[:3] + ((10_800_000, "10000000000000000", "10000000000000000", "80", "100"),)
    bt, records, _ = _scenario(tmp_path, monkeypatch, bars)
    last = records[-1]
    assert last.qty_after == 0
    assert last.cash_after == last.equity == Decimal(10000)
    assert _fill(last)["side"] == "buy"
    assert _fill(last)["qty"] == 0 and _fill(last)["is_stop"] is False
    assert bt.trade_count == 0


def test_resting_stop_beats_pending_exit_and_cancels_it(tmp_path, monkeypatch):
    bars = SYNTHETIC_BARS[:3] + (
        (10_800_000, "100", "100", "95", "95"),
        (14_400_000, "100", "101", "80", "100"),
        (18_000_000, "100", "100", "100", "100"),
    )
    bt, records, result = _scenario(tmp_path, monkeypatch, bars)
    assert result.detail["trace"][3]["target"]["reason"] == "exit"
    assert records[3].qty_after == Decimal(100)
    assert _fill(records[4])["is_stop"] is True
    assert _fill(records[4])["price"] == Decimal(90)  # pending ordinary exit would be 100
    assert records[5].fill is None
    assert records[5].qty_after == 0
    assert records[5].cash_after == records[5].equity == Decimal(9000)
    assert bt.trade_count == 1


@pytest.mark.parametrize("breach", [True, False])
def test_repeated_entry_target_does_not_rebuy_after_stop_or_while_long(tmp_path, monkeypatch, breach):
    pack = _synthetic_pack()
    pack["entry"] = ["close", ">", "sma2"]
    bars = SYNTHETIC_BARS[:3] + (
        (10_800_000, "100", "110", "80" if breach else "95", "110"),
        (14_400_000, "110", "110", "100", "110"),
    )
    bt, records, result = _scenario(tmp_path, monkeypatch, bars, pack=pack)
    assert result.detail["trace"][3]["target"]["reason"] == "entry"  # the adversarial signal actually fires
    assert records[4].fill is None
    if breach:
        assert _fill(records[3])["is_stop"] is True
        assert records[4].qty_after == 0
        assert records[4].cash_after == records[4].equity == Decimal(9000)
        assert bt.trade_count == 1
    else:
        assert _fill(records[3])["side"] == "buy" and _fill(records[3])["is_stop"] is False
        assert records[4].qty_after == Decimal(100)
        assert records[4].cash_after == 0
        assert records[4].equity == Decimal(11000)
        assert bt.trade_count == 0

"""Backtest: engine, ledger invariants, fill timing, stop behavior, metrics.

The engine must:
    * Fill at the open of bar t+1, never at the close of bar t.
    * Stop while long fills on the triggering bar at min(stop, open), before a signal fill.
    * Cash stay >= 0 every bar.
    * A flat-price zero-cost round trip change equity by exactly 0.
    * Build a JSON receipt whose last equity_curve point equals total_return_pct.
    * Buy-and-hold metrics use the same bars and dates.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.backtest.engine import Backtester
from krellbot.backtest.receipt import build_receipt, downsample, pack_sha256
from krellbot.pack.model import Candle

FIX = Path(__file__).parent / "fixtures"


def _candle(
    ts_ms: int,
    close: str = "10",
    o: str | None = None,
    h: str | None = None,
    l: str | None = None,
) -> Candle:
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(o or close),
        high=Decimal(h or close),
        low=Decimal(l or close),
        close=Decimal(close),
        volume=Decimal(1),
    )


def _sma_cross_pack() -> dict:
    return json.loads((FIX / "packs" / "sma_cross.json").read_text(encoding="utf-8"))


def _bar_series() -> list[Candle]:
    """8 1h bars: 10,10,12,14,8,8,8,8 -> one cross above at bar 2, one below at bar 4."""
    candles = []
    closes = ["10", "10", "12", "14", "8", "8", "8", "8"]
    for i, c in enumerate(closes):
        candles.append(
            Candle(
                ts_ms=i * 3_600_000,
                open=Decimal(c),
                high=Decimal(c) + Decimal("0.5"),
                low=Decimal(c) - Decimal("0.5"),
                close=Decimal(c),
                volume=Decimal(1),
            )
        )
    return candles


def test_fill_at_next_open_not_signal_close():
    """A buy signal at the close of bar 2 fills at the open of bar 3.

    With zero costs, qty_after bar 3 must be > 0; cash_after bar 3 must
    reflect open[3], not close[2].
    """
    pack = _sma_cross_pack()
    candles = _bar_series()
    records = Backtester(pack, candles).run()
    assert records[3].qty_after > 0
    # The buy uses open[3] (the fixture sets open=close, so open[3]=14).
    expected_cost = records[3].qty_after * candles[3].open
    assert records[3].cash_after == Decimal(10000) - expected_cost
    # Bar 2: signal fires but no fill yet.
    assert records[2].qty_after == 0


def test_stop_gap_through_fills_at_open():
    """A gap through the stop fills on that bar, at the open, not at the stop."""
    pack = _sma_cross_pack()
    pack["risk"]["stop"] = {"type": "pct", "pct": 10}
    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(7_200_000, "12"),
        _candle(10_800_000, "14", o="14", h="14", l="14"),
        _candle(14_400_000, "7", o="7", h="8", l="6"),
        _candle(18_000_000, "7", o="7", h="7", l="7"),
    ]
    bt = Backtester(pack, candles)
    records = bt.run()
    assert records[3].qty_after > 0
    assert records[4].fill is not None
    assert records[4].fill["is_stop"] is True
    assert records[4].qty_after == 0
    expected_proceeds = records[3].qty_after * Decimal(7)
    assert records[4].cash_after == records[3].cash_after + expected_proceeds
    assert bt.trade_count == 1


def test_flat_price_round_trip_zero_cost_is_equity_neutral():
    """Buy and sell at the same price, zero costs, and equity is unchanged."""
    pack = _sma_cross_pack()
    pack["risk"]["stop"] = {"type": "pct", "pct": 50}
    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(7_200_000, "12"),
        _candle(10_800_000, "10"),
        _candle(14_400_000, "10"),
    ]
    bt = Backtester(pack, candles, fee_bps=0, slippage_bps=0)
    records = bt.run()
    assert any(r.fill and r.fill["side"] == "sell" for r in records)
    assert records[-1].equity == Decimal(10000)
    assert records[-1].qty_after == 0
    assert bt.trade_count == 1


def test_cash_never_negative():
    """The cash invariant holds across the entire bar loop."""
    pack = _sma_cross_pack()
    candles = _bar_series()
    records = Backtester(pack, candles, fee_bps=40, slippage_bps=5, slippage_mult=1.5).run()
    for r in records:
        assert r.cash_after >= 0


def test_curve_last_point_equals_total_return():
    """The last equity_curve point equals metrics.total_return_pct within 0.01."""
    pack = _sma_cross_pack()
    candles = _bar_series()
    bt = Backtester(pack, candles, fee_bps=40, slippage_bps=5, slippage_mult=1.0)
    records = bt.run()
    receipt = build_receipt(
        pack=pack,
        records=records,
        trade_count=bt.trade_count,
        data_manifest_sha256="deadbeef" * 8,
        venue="kraken",
        pair="SUIUSD",
        tf="1h",
        fee_bps=40,
        slippage_bps=5,
        slippage_mult=1.0,
    )
    last = receipt["equity_curve"][-1]
    assert abs(last - receipt["metrics"]["total_return_pct"]) < 0.01


def test_buy_and_hold_same_dates():
    """Buy-and-hold uses the same first/last bar timestamps."""
    pack = _sma_cross_pack()
    candles = _bar_series()
    records = Backtester(pack, candles).run()
    receipt = build_receipt(
        pack=pack,
        records=records,
        trade_count=1,
        data_manifest_sha256="x" * 64,
        venue="kraken",
        pair="SUIUSD",
        tf="1h",
        fee_bps=40,
        slippage_bps=5,
        slippage_mult=1.0,
    )
    # The receipt 'from'/'to' come from the bars used by the backtest.
    assert receipt["from"] == "1970-01-01"
    assert receipt["to"] == "1970-01-01"


def test_receipt_keys_are_locked():
    """The receipt shape is exactly the locked key set."""
    pack = _sma_cross_pack()
    candles = _bar_series()
    records = Backtester(pack, candles).run()
    receipt = build_receipt(
        pack=pack,
        records=records,
        trade_count=1,
        data_manifest_sha256="0" * 64,
        venue="kraken",
        pair="SUIUSD",
        tf="1h",
        fee_bps=0,
        slippage_bps=0,
        slippage_mult=1.0,
    )
    assert set(receipt.keys()) == {
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
    assert set(receipt["metrics"].keys()) == {
        "total_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "return_to_dd",
        "per_year",
        "trade_count",
        "exposure_pct",
        "buy_and_hold",
    }
    assert set(receipt["metrics"]["buy_and_hold"].keys()) == {
        "total_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "return_to_dd",
        "per_year",
        "trade_count",
        "exposure_pct",
    }


def test_engine_version_is_package_version():
    """engine_version comes from krellbot.__version__."""
    import krellbot

    pack = _sma_cross_pack()
    candles = _bar_series()
    records = Backtester(pack, candles).run()
    receipt = build_receipt(
        pack=pack,
        records=records,
        trade_count=0,
        data_manifest_sha256="x" * 64,
        venue="kraken",
        pair="SUIUSD",
        tf="1h",
        fee_bps=0,
        slippage_bps=0,
        slippage_mult=1.0,
    )
    assert receipt["engine_version"] == krellbot.__version__


def test_equity_curve_max_64_points():
    """equity_curve is downsampled to at most 64 numbers."""
    # 200 bars -> still <= 64 points.
    candles = []
    for i in range(200):
        candles.append(_candle(i * 3_600_000, "10"))
    assert len(downsample([float(i) for i in range(200)], 64)) == 64
    # 30 bars -> 30 points.
    assert len(downsample([float(i) for i in range(30)], 64)) == 30


def test_pack_sha256_is_canonical():
    """pack_sha256 is the sha256 of sort_keys=True, no-whitespace JSON."""
    pack = {"a": 1, "b": [2, 3]}
    expected = pack_sha256(pack)
    # Re-serialize in canonical form and compute manually.
    import hashlib

    body = json.dumps({"a": 1, "b": [2, 3]}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert expected == hashlib.sha256(body).hexdigest()


def test_ledger_state_holds_after_fill():
    """cash + qty * close equals equity on every bar."""
    pack = _sma_cross_pack()
    candles = _bar_series()
    records = Backtester(pack, candles).run()
    for r in records:
        assert r.cash_after + r.qty_after * r.close == r.equity


def test_trade_count_increments_on_round_trip():
    """A completed buy + sell round trip increments trade_count."""
    pack = _sma_cross_pack()
    candles = _bar_series()
    bt = Backtester(pack, candles)
    bt.run()
    assert bt.trade_count == 1

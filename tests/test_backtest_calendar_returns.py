"""UTC year-end attribution over synthetic equity and offline candle fixtures."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.backtest.engine import Backtester
from krellbot.backtest.metrics import _per_year, buy_and_hold_curve, compute_metrics
from krellbot.backtest.receipt import build_receipt
from krellbot.pack.model import Candle
from tests.test_ns04_research_service import PACK_DICT


def _ts(value):
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000)


def _return(end, start):
    return float((Decimal(end) / Decimal(start) - 1) * 100) if Decimal(start) > 0 else 0.0


@pytest.mark.parametrize(
    "samples,expected",
    [
        ([], {}),
        ([("2023-12-31T23:00", "100")], {"2023": 0.0}),
        ([("2023-06-01", "80"), ("2023-12-31", "100")], {"2023": _return(100, 80)}),
        (
            [("2023-12-31T22:00", "100"), ("2023-12-31T23:00", "100"), ("2024-01-01", "120")],
            {"2023": 0.0, "2024": _return(120, 100)},
        ),
        (
            [("2023-12-31T22:00", "100"), ("2023-12-31T23:00", "100"), ("2024-01-01", "80")],
            {"2023": 0.0, "2024": _return(80, 100)},
        ),
        (
            [("2023-12-31T22:00", "100"), ("2023-12-31T23:00", "120"), ("2024-01-01", "120")],
            {"2023": _return(120, 100), "2024": 0.0},
        ),
        (
            [("2023-12-31T23:00", "100"), ("2024-01-01", "120"), ("2024-01-01T01:00", "150")],
            {"2023": 0.0, "2024": _return(150, 100)},
        ),
        (
            [("2023-12-31T23:59:59.999", "100"), ("2024-01-01", "100"), ("2025-01-01", "100")],
            {"2023": 0.0, "2024": 0.0, "2025": 0.0},
        ),
        (
            [("2021-06-01", "100"), ("2021-12-30", "120"), ("2023-01-02", "150"), ("2024-06-01", "90")],
            {"2021": _return(120, 100), "2023": _return(150, 120), "2024": _return(90, 150)},
        ),
        (
            [("2023-12-31T22:00", "100"), ("2023-12-31T23:00", "0"), ("2024-01-01", "50")],
            {"2023": _return(0, 100), "2024": 0.0},
        ),
        (
            [("2023-12-31T22:00", "0"), ("2023-12-31T23:00", "100"), ("2024-01-01", "120")],
            {"2023": 0.0, "2024": _return(120, 100)},
        ),
        (
            [("2023-12-31T22:00", "-10"), ("2023-12-31T23:00", "-5"), ("2024-01-01", "20")],
            {"2023": 0.0, "2024": 0.0},
        ),
    ],
)
def test_calendar_boundaries_use_last_observed_year_end(samples, expected):
    curve = [(_ts(date), Decimal(equity)) for date, equity in samples]
    before = list(curve)
    assert _per_year(curve) == pytest.approx(expected)
    assert compute_metrics(curve, 0, 0, len(curve)).per_year == pytest.approx(expected)
    assert curve == before


@pytest.mark.parametrize("fee,slip", [(0, 0), (40, 5)])
@pytest.mark.parametrize(
    "closes",
    [
        [100, 100, 120, 120, 132, 132],  # First new-year gain.
        [100, 100, 120, 120, 108, 108],  # First new-year loss.
        [100, 100, 120, 132, 132, 132],  # Last old-year gain.
        [100, 100, 120, 120, 120, 132],  # Second new-year gain.
        [100, 100, 100, 100, 100, 100],  # Flat/no strategy trade.
    ],
)
def test_offline_service_and_engine_receipts_attribute_both_curves(home, monkeypatch, fresh_keyring, closes, fee, slip):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)
    pack = {**PACK_DICT, "label": "Synthetic calendar attribution fixture"}
    pack_path = home / "synthetic-calendar-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    start = _ts("2023-12-31T20:00")
    candles = [
        Candle(start + i * 3_600_000, Decimal(c), Decimal(c), Decimal(c), Decimal(c), Decimal(100))
        for i, c in enumerate(closes)
    ]
    body = "ts_ms,open,high,low,close,volume\n" + "".join(
        f"{c.ts_ms},{c.open},{c.high},{c.low},{c.close},{c.volume}\n" for c in candles
    )
    csv = home / "synthetic-calendar.csv"
    csv.write_bytes(body.encode())
    digest = hashlib.sha256(body.encode()).hexdigest()
    engine = Backtester(pack, candles, fee_bps=fee, slippage_bps=slip)
    records = engine.run()
    receipt = build_receipt(pack, records, engine.trade_count, digest, "kraken", "SUIUSD", "1h", fee, slip, 1.0)
    result = ResearchService(home=home, fetch=None).run(
        ResearchRequest(pack_path=pack_path, dataset_csv=csv, venue="kraken", fee_bps=fee, slippage_bps=slip)
    )
    assert result.ok, result.refusal
    assert result.legacy_receipt == receipt
    assert csv.read_bytes() == body.encode()
    assert receipt["data_manifest_sha256"] == digest
    curves = [
        (receipt["metrics"], [(r.ts_ms, r.equity) for r in records]),
        (receipt["metrics"]["buy_and_hold"], buy_and_hold_curve(records, Decimal(10000), fee, slip, 1.0)),
    ]
    for metrics, curve in curves:
        assert metrics["per_year"] == pytest.approx(
            {"2023": _return(curve[3][1], curve[0][1]), "2024": _return(curve[-1][1], curve[3][1])}
        )
        assert metrics["total_return_pct"] == _return(curve[-1][1], 10000)
    assert receipt["equity_curve"] == [_return(r.equity, 10000) for r in records]

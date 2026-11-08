"""Synthetic zero-volume windows must stay unavailable, not signal an entry."""

from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.domain.trace import paper_decision_trace, shared_decision_trace
from krellbot.pack.indicators import compute
from krellbot.pack.model import Candle
from tests.test_ns04_research_service import PACK_DICT


def _candles(volumes, closes=None):
    closes = closes or [10, 20, 15, 15, 15, 15, 30, 40][: len(volumes)]
    return [
        Candle(i * 3_600_000, Decimal(c), Decimal(c), Decimal(c), Decimal(c), Decimal(str(v)))
        for i, (c, v) in enumerate(zip(closes, volumes, strict=True))
    ]


@pytest.mark.parametrize("scale", ["1", "10", "1e-15", "1e15"])
def test_zero_window_ignores_expired_volume_and_weight_scaling(scale):
    bars = _candles([Decimal(v) * Decimal(scale) for v in ["0.1", "0.2", "0", "0", "0", "0"]])
    before = [asdict(c) for c in bars]
    values = compute(bars, {"fn": "vwma", "src": "close", "len": 2})
    assert values[:3] == pytest.approx([None, float(Decimal(50) / 3), 20])
    assert values[3:] == [None, None, None]
    assert [asdict(c) for c in bars] == before


@pytest.mark.parametrize("volumes", [["0.1", "0.2", "0", "1e-16"], ["0.1", "0.2", "0", "0", "1e-16", "0.2"]])
def test_real_tiny_positive_volume_and_recovery_are_not_erased(volumes):
    bars = _candles(volumes)
    values = compute(bars, {"fn": "vwma", "src": "close", "len": 2})
    assert values[-1] == pytest.approx(15)
    assert values[-1] is not None


@pytest.mark.parametrize("length", [0, 1, 2, 4, 10])
def test_current_window_reference_prefix_causality_and_shape(length):
    bars = _candles(["0.1", "0.2", "0", "0", "1e-16", "0", "0.3", "0"])
    params = {"fn": "vwma", "src": "close", "len": length}
    values = compute(bars, params)
    assert len(values) == len(bars)
    for i in range(len(bars)):
        assert compute(bars[: i + 1], params) == values[: i + 1]
        if length < 1 or i < length - 1:
            assert values[i] is None
            continue
        window = bars[i - length + 1 : i + 1]
        volume = sum(c.volume for c in window)
        if volume == 0:
            assert values[i] is None
        else:
            expected = float(sum(c.close * c.volume for c in window) / volume)
            assert values[i] == pytest.approx(expected)


def test_offline_research_and_shared_paper_trace_have_no_phantom_entry(home, monkeypatch, fresh_keyring):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)
    bars = _candles(["0.1", "0.2", "0", "0", "0", "0"])
    pack = {
        **PACK_DICT,
        "label": "Synthetic VWMA zero-volume fixture",
        "indicators": {"vw": {"fn": "vwma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "vw"],
        "exit": ["close", "crosses_below", "vw"],
    }
    pack_path = home / "synthetic-vwma-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    csv = home / "synthetic-volume.csv"
    body = "ts_ms,open,high,low,close,volume\n" + "".join(
        f"{c.ts_ms},{c.open},{c.high},{c.low},{c.close},{c.volume}\n" for c in bars
    )
    csv.write_bytes(body.encode())
    result = ResearchService(home=home, fetch=None).run(
        ResearchRequest(pack_path=pack_path, venue="kraken", dataset_csv=csv)
    )
    assert result.ok, result.refusal
    assert result.legacy_receipt["metrics"]["exposure_pct"] == 0
    assert result.legacy_receipt["metrics"]["trade_count"] == 0
    assert result.legacy_receipt["equity_curve"] == [0] * len(bars)
    trace = shared_decision_trace(pack, bars)
    assert result.detail["trace"] == trace == paper_decision_trace(pack, bars)
    for row in trace[3:]:
        assert row["indicators"]["vw"] is None
        assert row["warmup"] is True
        assert row["target"]["long"] is False
        assert all(c["outcome"] == "unknown" for c in row["conditions"])
    assert csv.read_bytes() == body.encode()

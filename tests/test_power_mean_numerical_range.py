"""Ordinary finite synthetic power means must survive intermediate powers."""

import json
from decimal import Decimal

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.pack.indicators import compute
from krellbot.pack.model import Candle
from tests.test_ns04_research_service import PACK_DICT


def _bars(prices):
    return [
        Candle(i * 3_600_000, Decimal(p), Decimal(p), Decimal(p), Decimal(p), Decimal(100))
        for i, p in enumerate(prices)
    ]


@pytest.mark.parametrize("power", [1000, -1000, 2, -2])
@pytest.mark.parametrize("price", ["100", "0.01"])
def test_constant_positive_mean_stays_representable(power, price):
    bars = _bars([price] * 6)
    result = compute(bars, {"fn": "power_mean", "src": "close", "len": 2, "p": power})
    assert result == pytest.approx([None] + [float(price)] * 5)


@pytest.mark.parametrize("power", [1000, -1000, 2, -2])
def test_offline_service_runs_valid_power_mean(home, monkeypatch, fresh_keyring, power):
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "0")
    monkeypatch.chdir(home)
    pack = {
        **PACK_DICT,
        "label": "Synthetic power-mean range fixture",
        "indicators": {"pm": {"fn": "power_mean", "src": "close", "len": 2, "p": power}},
        "entry": ["close", "crosses_above", "pm"],
        "exit": ["close", "crosses_below", "pm"],
    }
    pack_path = home / "synthetic-pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    csv = home / "synthetic-prices.csv"
    csv.write_bytes(
        (
            "ts_ms,open,high,low,close,volume\n" + "".join(f"{i * 3_600_000},100,100,100,100,100\n" for i in range(6))
        ).encode()
    )
    result = ResearchService(home=home, fetch=None).run(
        ResearchRequest(pack_path=pack_path, venue="kraken", dataset_csv=csv)
    )
    assert result.ok, result.refusal
    assert result.legacy_receipt["metrics"]["exposure_pct"] == 0
    assert result.legacy_receipt["equity_curve"] == [0] * 6
    assert all(row["indicators"]["pm"] == pytest.approx(100) for row in result.detail["trace"][1:])


def test_nonpositive_windows_and_zero_power_keep_existing_contract():
    params = {"fn": "power_mean", "src": "close", "len": 2, "p": 1000}
    assert compute(_bars(["0", "100"]), params) == [None, None]
    assert compute(_bars(["-1", "100"]), params) == [None, None]
    with pytest.raises(ValueError, match="non-zero"):
        compute(_bars(["100", "100"]), {**params, "p": 0})

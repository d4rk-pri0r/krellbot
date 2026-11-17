"""Built-in trading modes run Research against pinned fixture CSV.

M15.6: DCA / grid / rebalance packs evaluate offline via ResearchService
with fixture candles. Receipts carry metrics; results are backtest /
pinned-fixture evidence — never live market performance.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.packs import mode_packs

FIX = Path(__file__).parent / "fixtures" / "candles"
PIN_1H = FIX / "mode_research_pin_1h.csv"
PIN_1D = FIX / "mode_research_pin_1d.csv"

LIVE_CLAIM_WORDS = (
    "live market performance",
    "guaranteed return",
    "realized pnl live",
)


def _write_mode_pack(home: Path, kind: str) -> Path:
    pack = mode_packs.load_mode_pack(kind)
    path = home / f"{pack['id']}.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    return path


def _pin_for(timeframe: str) -> Path:
    if timeframe == "1h":
        return PIN_1H
    if timeframe == "1d":
        return PIN_1D
    raise AssertionError(f"unexpected mode timeframe: {timeframe}")


@pytest.mark.parametrize("kind", ["dca", "grid", "rebalance"])
def test_mode_pack_research_runs_on_pinned_csv(home: Path, kind: str) -> None:
    assert kind in mode_packs.available_mode_kinds()
    pack = mode_packs.load_mode_pack(kind)
    pack_path = _write_mode_pack(home, kind)
    pin_src = _pin_for(str(pack["timeframe"]))
    assert pin_src.is_file(), pin_src
    csv_path = home / f"pin-{kind}.csv"
    shutil.copyfile(pin_src, csv_path)

    markets = pack["markets"]
    venue = markets[0]["venue"]
    pair = markets[0]["pair"]

    result = ResearchService(home=home).run(
        ResearchRequest(
            pack_path=pack_path,
            venue=venue,
            pair=pair,
            dataset_csv=csv_path,
        )
    )
    assert result.ok, (result.refusal, result.detail)
    assert result.legacy_receipt is not None
    receipt = result.legacy_receipt
    assert "equity_curve" in receipt
    assert isinstance(receipt["equity_curve"], list)
    assert "metrics" in receipt or "trade_count" in receipt or "trades" in receipt
    detail = result.detail
    assert detail.get("schema_version") == "1"
    assert detail.get("tf") == pack["timeframe"]
    assert detail.get("pair") == pair
    assert detail.get("data_source") == "pinned_csv"
    # Honesty: detail must not invent live-performance claims.
    blob = json.dumps(detail).lower() + json.dumps(receipt).lower()
    for word in LIVE_CLAIM_WORDS:
        assert word not in blob, (kind, word)


def test_pinned_fixture_files_exist_and_are_labeled() -> None:
    for path in (PIN_1H, PIN_1D):
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert text.startswith("ts_ms,open,high,low,close,volume")
        assert len(text.strip().splitlines()) >= 25


def test_all_three_builtin_modes_are_researchable(home: Path) -> None:
    kinds = mode_packs.available_mode_kinds()
    assert set(kinds) >= {"dca", "grid", "rebalance"}

"""Shared paper-stop marker boundaries (issue #111 matrix)."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.pack.model import Candle
from krellbot.venues.base import PairRules
from krellbot.venues.paper import PaperVenue

PAIR = "SUIUSD"
BAR = 3_600_000


def rules(_pair: str) -> PairRules:
    return PairRules(ordermin=Decimal(5), costmin=Decimal("0.5"), lot_decimals=5, price_decimals=4)


def candle(ts: int, *, low: str = "9", open_: str = "10", close: str = "10") -> Candle:
    return Candle(
        ts_ms=ts,
        open=Decimal(open_),
        high=max(Decimal(open_), Decimal(close)) + 1,
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal(100),
    )


def history() -> list[Candle]:
    return [candle(0, low="4"), candle(BAR)]


class Reader:
    def __init__(self, candles: list[Candle]) -> None:
        self.candles = candles

    def __call__(self, _venue: str, _pair: str) -> list[Candle]:
        return list(self.candles)


def venue_at(home: Path, reader: Reader) -> PaperVenue:
    return PaperVenue(
        "kraken",
        rules_provider=rules,
        candle_reader=reader,
        home=home,
        starting_cash=Decimal(1000),
        clock=lambda: 3600,
    )


def saved(home: Path) -> dict:
    return json.loads((home / "run" / "paper-kraken.json").read_text())


class RecordingPaperVenue(PaperVenue):
    """Count real disk writes to enforce the single-save placement contract."""

    def _persist(self) -> None:
        super()._persist()
        self.writes.append(saved(self._home))

    def __init__(self, home: Path, reader: Reader) -> None:
        self.writes: list[dict] = []
        super().__init__(
            "kraken", rules_provider=rules, candle_reader=reader, home=home, starting_cash=Decimal(1000)
        )
        self.writes.clear()


def assert_holding(venue: PaperVenue) -> None:
    truth = venue.snapshot()
    assert venue.owned_qty(PAIR) == Decimal(5)
    assert venue.resting_stop(PAIR) == Decimal(8)
    assert len(truth.open_orders) == 1
    assert [fill.side for fill in truth.recent_fills] == ["buy"]


def write_legacy_stop(home: Path) -> None:
    path = home / "run" / "paper-kraken.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "venue": "kraken",
                "seeded": True,
                "balances": {"USD": "949.7749", "SUI": "5"},
                "recent_fills": [],
                "open_orders": [
                    {"coid": "legacy", "pair": PAIR, "side": "sell", "qty": "5", "stop_price": "8", "ts_ms": 1}
                ],
            }
        )
    )


def test_row1_entry_next_snapshot_ignores_older_low(tmp_path):
    venue = venue_at(tmp_path, Reader(history()))
    venue.place_entry_with_stop("entry", Decimal(5), Decimal(8), pair=PAIR)
    assert_holding(venue)
    assert_holding(venue)


def test_rows1_2_entry_marker_is_in_the_single_placement_save(tmp_path):
    venue = RecordingPaperVenue(tmp_path, Reader(history()))
    venue.place_entry_with_stop("entry", Decimal(5), Decimal(8), pair=PAIR)
    assert len(venue.writes) == 1
    assert venue.writes[0].get("last_applied_ts") == BAR
    assert_holding(venue)


def test_row2_disk_restart_ignores_older_low(tmp_path):
    venue = venue_at(tmp_path, Reader(history()))
    venue.place_entry_with_stop("entry", Decimal(5), Decimal(8), pair=PAIR)
    restarted = venue_at(tmp_path, Reader(history()))
    assert_holding(restarted)
    assert saved(tmp_path)["last_applied_ts"] == BAR


@pytest.mark.parametrize("restart", [False, True])
def test_row3_repaired_stop_ignores_older_low(tmp_path, restart):
    reader = Reader(history())
    venue = venue_at(tmp_path, reader)
    venue.place_entry_with_stop("entry", Decimal(5), Decimal(8), pair=PAIR)
    venue.cancel_stops(PAIR)
    # Simulate a recovered balance with no prior stop-application boundary.
    path = tmp_path / "run" / "paper-kraken.json"
    state = saved(tmp_path)
    state.pop("last_applied_ts", None)
    path.write_text(json.dumps(state))
    venue = venue_at(tmp_path, reader)
    venue.place_stop("repair", Decimal(5), Decimal(8), pair=PAIR)
    if restart:
        venue = venue_at(tmp_path, Reader(history()))
    assert_holding(venue)
    assert saved(tmp_path)["last_applied_ts"] == BAR


def test_row3_repair_marker_is_in_the_single_placement_save(tmp_path):
    venue = RecordingPaperVenue(tmp_path, Reader(history()))
    venue.place_stop("repair", Decimal(5), Decimal(8), pair=PAIR)
    assert len(venue.writes) == 1
    assert venue.writes[0].get("last_applied_ts") == BAR
    assert venue.snapshot().recent_fills == []


def test_row4_legacy_stop_ignores_existing_history(tmp_path):
    write_legacy_stop(tmp_path)
    venue = venue_at(tmp_path, Reader(history()))
    truth = venue.snapshot()
    assert venue.owned_qty(PAIR) == Decimal(5)
    assert venue.resting_stop(PAIR) == Decimal(8)
    assert len(truth.open_orders) == 1
    assert truth.recent_fills == []


def test_row4_legacy_boundary_persists_before_snapshot_and_survives_restart(tmp_path):
    write_legacy_stop(tmp_path)
    venue_at(tmp_path, Reader(history()))
    assert saved(tmp_path)["last_applied_ts"] == BAR
    reader = Reader(history() + [candle(2 * BAR, low="7", open_="7", close="7")])
    restarted = venue_at(tmp_path, reader)
    assert saved(tmp_path)["last_applied_ts"] == BAR
    truth = restarted.snapshot()
    assert restarted.owned_qty(PAIR) == Decimal(0)
    assert restarted.resting_stop(PAIR) is None
    assert len(truth.recent_fills) == 1
    assert truth.recent_fills[0].price == Decimal("6.9965")

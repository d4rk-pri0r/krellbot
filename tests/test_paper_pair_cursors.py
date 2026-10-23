"""Synthetic, offline paper stop cursors: one monotonic boundary per market."""

import builtins
import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.data.instruments import METADATA_UNAVAILABLE, InstrumentMetadataError
from krellbot.pack.model import Candle
from krellbot.venues import paper
from krellbot.venues.base import PairRules
from krellbot.venues.paper import PaperVenue

PAIRS = ("ADAUSD", "SUIUSD")


def rules(_pair: str) -> PairRules:
    return PairRules(ordermin=Decimal(5), costmin=Decimal("0.5"), lot_decimals=5, price_decimals=4)


def bar(ts: int, low: str = "9", open_: str = "10") -> Candle:
    return Candle(ts_ms=ts, open=Decimal(open_), high=Decimal(11), low=Decimal(low),
                  close=Decimal(10), volume=Decimal(100))


class Reader:
    def __init__(self, bars: dict[str, list[Candle] | None]) -> None:
        self.bars = bars

    def __call__(self, _venue: str, pair: str) -> list[Candle] | None:
        return self.bars.get(pair)


def venue_at(home: Path, reader: Reader, rules_provider=rules) -> PaperVenue:
    return PaperVenue("kraken", rules_provider=rules_provider, candle_reader=reader, home=home,
                      starting_cash=Decimal(1000), clock=lambda: 1)


def saved(home: Path) -> dict:
    return json.loads((home / "run/paper-kraken.json").read_text())


def legacy_state(home: Path, **markers) -> None:
    path = home / "run/paper-kraken.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "venue": "kraken", "seeded": True,
        "balances": {"USD": "900", "ADA": "5", "SUI": "5"}, "recent_fills": [],
        "open_orders": [{"coid": f"legacy-{pair}", "pair": pair, "side": "sell", "qty": "5",
                         "stop_price": "8", "ts_ms": 1} for pair in PAIRS], **markers,
    }))


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("overlap", [False, True])
def test_each_pair_processes_its_own_new_bars_in_either_pair_iteration(tmp_path, monkeypatch, reverse, overlap):
    # Reverse production pair iteration without reversing chronological candle sorting.
    def ordered(values, **kwargs):
        values = list(values)
        if reverse and all(isinstance(value, str) for value in values):
            return builtins.sorted(values, reverse=True, **kwargs)
        return builtins.sorted(values, **kwargs)

    monkeypatch.setattr(paper, "sorted", ordered, raising=False)
    reader = Reader({PAIRS[0]: [bar(100)], PAIRS[1]: [bar(100 if overlap else 10)]})
    venue = venue_at(tmp_path, reader)
    for pair in reversed(PAIRS):
        venue.place_entry_with_stop(f"entry-{pair}", Decimal(5), Decimal(8), pair=pair)
    second_ts = 200 if overlap else 20
    reader.bars = {PAIRS[0]: [bar(200, "7", "7"), bar(100)],
                   PAIRS[1]: [bar(second_ts, "6", "6"), bar(100 if overlap else 10)]}
    truth = venue.snapshot()
    assert {fill.pair: fill.price for fill in truth.recent_fills if fill.side == "sell"} == {
        PAIRS[0]: Decimal("6.9965"), PAIRS[1]: Decimal("5.9970"),
    }
    assert truth.open_orders == []
    assert saved(tmp_path)["last_applied_ts_by_pair"] == {PAIRS[0]: 200, PAIRS[1]: second_ts}
    assert venue.snapshot() == truth


def test_out_of_order_bars_choose_first_chronological_trigger_and_monotonic_max(tmp_path):
    reader = Reader({pair: [bar(100), bar(0, "1")] for pair in PAIRS})
    venue = venue_at(tmp_path, reader)
    for pair in PAIRS:
        venue.place_entry_with_stop(f"entry-{pair}", Decimal(5), Decimal(8), pair=pair)
    # Maximum timestamp, not the final element, excludes all placement history.
    assert len(venue.snapshot().recent_fills) == 2
    reader.bars = {pair: [bar(300, "5", "5"), bar(200, "7", "7"), bar(100)] for pair in PAIRS}
    truth = venue.snapshot()
    sells = [fill for fill in truth.recent_fills if fill.side == "sell"]
    assert {fill.coid for fill in sells} == {f"stop-{pair}-200" for pair in PAIRS}
    assert all(fill.price == Decimal("6.9965") for fill in sells)
    assert saved(tmp_path)["last_applied_ts_by_pair"] == dict.fromkeys(PAIRS, 300)


@pytest.mark.parametrize("placement", ["entry", "repair"])
def test_new_placement_does_not_rewind_another_pair(tmp_path, placement):
    reader = Reader({PAIRS[0]: [bar(100)], PAIRS[1]: [bar(10)]})
    venue = venue_at(tmp_path, reader)
    venue.place_entry_with_stop("first", Decimal(5), Decimal(8), pair=PAIRS[0])
    reader.bars[PAIRS[0]] = [bar(50, "1"), bar(100)]
    if placement == "entry":
        venue.place_entry_with_stop("second", Decimal(5), Decimal(8), pair=PAIRS[1])
    else:
        venue.place_stop("second", Decimal(5), Decimal(8), pair=PAIRS[1])
    venue.snapshot()
    assert venue.owned_qty(PAIRS[0]) == Decimal(5)
    assert venue.resting_stop(PAIRS[0]) == Decimal(8)
    assert saved(tmp_path)["last_applied_ts_by_pair"] == {PAIRS[0]: 100, PAIRS[1]: 10}


@pytest.mark.parametrize("placement", ["entry", "repair"])
def test_duplicate_placement_is_a_noop_and_cannot_skip_a_new_trigger(tmp_path, placement):
    reader = Reader({PAIRS[0]: [bar(10)]})
    venue = venue_at(tmp_path, reader)
    place = venue.place_entry_with_stop if placement == "entry" else venue.place_stop
    place("same", Decimal(5), Decimal(8), pair=PAIRS[0])
    before = saved(tmp_path)
    reader.bars[PAIRS[0]] = [bar(20, "7", "7")]
    place("same", Decimal(5), Decimal(8), pair=PAIRS[0])
    assert saved(tmp_path) == before
    truth = venue.snapshot()
    assert len([fill for fill in truth.recent_fills if fill.side == "sell"]) == 1
    assert truth.open_orders == []


@pytest.mark.parametrize("missing", [None, []])
def test_missing_reader_repair_seeds_only_own_pair_and_first_bar_remains_eligible(tmp_path, missing):
    reader = Reader({PAIRS[0]: [bar(100)], PAIRS[1]: missing})
    venue = venue_at(tmp_path, reader)
    venue.place_stop("first", Decimal(5), Decimal(8), pair=PAIRS[0])
    venue.place_stop("missing", Decimal(5), Decimal(8), pair=PAIRS[1])
    assert saved(tmp_path)["last_applied_ts_by_pair"] == {PAIRS[0]: 100, PAIRS[1]: -1}
    reader.bars[PAIRS[1]] = [bar(0, "7", "7")]
    truth = venue.snapshot()
    assert [fill.pair for fill in truth.recent_fills] == [PAIRS[1]]
    assert venue.resting_stop(PAIRS[0]) == Decimal(8)


@pytest.mark.parametrize("placement", ["entry", "repair"])
def test_replacement_with_older_or_empty_reader_never_regresses_own_cursor(tmp_path, placement):
    reader = Reader({PAIRS[0]: [bar(100)]})
    venue = venue_at(tmp_path, reader)
    venue.place_entry_with_stop("original", Decimal(5), Decimal(8), pair=PAIRS[0])
    venue.cancel_stops(PAIRS[0])
    reader.bars[PAIRS[0]] = [bar(10)] if placement == "entry" else None
    place = venue.place_entry_with_stop if placement == "entry" else venue.place_stop
    place("replacement", Decimal(5), Decimal(8), pair=PAIRS[0])
    assert saved(tmp_path)["last_applied_ts_by_pair"][PAIRS[0]] == 100
    reader.bars[PAIRS[0]] = [bar(50, "1"), bar(100)]
    assert all(fill.side == "buy" for fill in venue.snapshot().recent_fills)
    assert venue.resting_stop(PAIRS[0]) == Decimal(8)


@pytest.mark.parametrize("markers,expected", [
    ({"last_applied_ts": 100}, {PAIRS[0]: 100, PAIRS[1]: 100}),
    ({}, {PAIRS[0]: 30, PAIRS[1]: -1}),
    ({"last_applied_ts": 100, "last_applied_ts_by_pair": {PAIRS[0]: 0}}, {PAIRS[0]: 0, PAIRS[1]: 100}),
    ({"last_applied_ts_by_pair": {PAIRS[0]: -1}}, {PAIRS[0]: -1, PAIRS[1]: -1}),
])
def test_frozen_legacy_and_mixed_migration_matrix(tmp_path, markers, expected):
    legacy_state(tmp_path, **markers)
    reader = Reader({PAIRS[0]: [bar(30), bar(10)], PAIRS[1]: None})
    venue = venue_at(tmp_path, reader)
    venue.snapshot()
    # Safe bars can advance an authoritative older entry, not a conservative newer one.
    expected_after = {PAIRS[0]: max(expected[PAIRS[0]], 30), PAIRS[1]: expected[PAIRS[1]]}
    assert saved(tmp_path)["last_applied_ts_by_pair"] == expected_after
    assert venue.snapshot().recent_fills == []
    reader.bars = {pair: [bar(expected_after[pair] + 1, "7", "7")] for pair in PAIRS}
    assert len(venue.snapshot().recent_fills) == 2


def test_authoritative_mapping_ignores_scalar_and_is_not_reseeded_on_restart(tmp_path):
    legacy_state(tmp_path, last_applied_ts=999, last_applied_ts_by_pair={PAIRS[0]: 0, PAIRS[1]: 10})
    reader = Reader({PAIRS[0]: [bar(1, "7", "7")], PAIRS[1]: [bar(11, "6", "6")]})
    venue = venue_at(tmp_path, reader)
    assert saved(tmp_path)["last_applied_ts_by_pair"] == {PAIRS[0]: 0, PAIRS[1]: 10}
    assert len(venue.snapshot().recent_fills) == 2
    assert venue_at(tmp_path, reader).snapshot() == venue.snapshot()


@pytest.mark.parametrize("placement", ["entry", "repair"])
def test_pair_cursor_and_order_land_in_same_atomic_placement_image(tmp_path, monkeypatch, placement):
    reader = Reader({PAIRS[0]: [bar(20), bar(10)]})
    venue = venue_at(tmp_path, reader)
    writes = []
    real_write = paper.kb_paths.atomic_write

    def capture(path, body):
        writes.append(json.loads(body))
        real_write(path, body)

    monkeypatch.setattr(paper.kb_paths, "atomic_write", capture)
    place = venue.place_entry_with_stop if placement == "entry" else venue.place_stop
    place("placed", Decimal(5), Decimal(8), pair=PAIRS[0])
    assert len(writes) == 1
    assert writes[0]["last_applied_ts_by_pair"] == {PAIRS[0]: 20}
    assert len(writes[0]["open_orders"]) == 1
    assert len(writes[0]["recent_fills"]) == (1 if placement == "entry" else 0)


def test_failed_atomic_fill_preserves_cursor_balance_stop_and_retries_after_restart(tmp_path, monkeypatch):
    import os

    reader = Reader({pair: [bar(10)] for pair in PAIRS})
    venue = venue_at(tmp_path, reader)
    for pair in PAIRS:
        venue.place_entry_with_stop(pair, Decimal(5), Decimal(8), pair=pair)
    before = saved(tmp_path)
    reader.bars = {pair: [bar(20, "7", "7")] for pair in PAIRS}

    def fail_replace(*_args):
        raise OSError("injected replace failure")

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_replace)
        with pytest.raises(OSError, match="injected replace failure"):
            venue.snapshot()
    assert saved(tmp_path) == before
    assert not (tmp_path / "run/paper-kraken.json.tmp").exists()
    restarted = venue_at(tmp_path, reader)
    assert len([fill for fill in restarted.snapshot().recent_fills if fill.side == "sell"]) == 2
    assert saved(tmp_path)["last_applied_ts_by_pair"] == dict.fromkeys(PAIRS, 20)
    assert all(restarted.owned_qty(pair) == 0 for pair in PAIRS)


def test_missing_metadata_repair_still_lands_protection_with_own_cursor(tmp_path):
    def refuse(_pair):
        raise InstrumentMetadataError(METADATA_UNAVAILABLE, "kraken", _pair, "synthetic missing metadata")

    reader = Reader({PAIRS[0]: [bar(100)], PAIRS[1]: []})
    venue = venue_at(tmp_path, reader, rules_provider=refuse)
    for pair in PAIRS:
        venue.place_stop(pair, Decimal("5.123456"), Decimal("8.123456"), pair=pair)
    assert saved(tmp_path)["last_applied_ts_by_pair"] == {PAIRS[0]: 100, PAIRS[1]: -1}
    assert all(venue.resting_stop(pair) == Decimal("8.123456") for pair in PAIRS)
    assert venue.snapshot().recent_fills == []

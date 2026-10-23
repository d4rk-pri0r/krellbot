"""Shared paper-stop marker boundaries (issue #111 matrix)."""

import json
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

from krellbot.config import load_config, save_config
from krellbot.pack.model import Candle
from krellbot.run import arm_pack, tick
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


def saved(home: Path, market: str = "kraken") -> dict:
    return json.loads((home / "run" / f"paper-{market}.json").read_text())


class RecordingPaperVenue(PaperVenue):
    """Count real disk writes to enforce the single-save placement contract."""

    def _persist(self) -> None:
        super()._persist()
        self.writes.append(saved(self._home))

    def __init__(self, home: Path, reader: Reader) -> None:
        self.writes: list[dict] = []
        super().__init__("kraken", rules_provider=rules, candle_reader=reader, home=home, starting_cash=Decimal(1000))
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


@pytest.mark.parametrize("market,fee_rate", [("kraken", "0.004"), ("coinbase", "0.012")])
@pytest.mark.parametrize("open_", ["10", "7.123456"])
def test_rows5_8_compat_new_bar_fills_once_with_exact_decimal_accounting(tmp_path, market, fee_rate, open_):
    reader = Reader(history())
    venue = PaperVenue(market, rules_provider=rules, candle_reader=reader, home=tmp_path, starting_cash=Decimal(1000))
    qty = Decimal("5.1234567")
    rounded_qty = Decimal("5.12345")
    venue.place_entry_with_stop("entry", qty, Decimal("8.1234567"), pair=PAIR)
    buy_price = Decimal("10.0050")
    buy_fee = (qty * buy_price * Decimal(fee_rate)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    assert venue.balances() == {"USD": Decimal(1000) - qty * buy_price - buy_fee, "SUI": qty}
    assert venue.order_by_coid("entry").qty == rounded_qty
    assert venue.resting_stop(PAIR) == Decimal("8.1234")
    reader.candles.append(candle(2 * BAR, low="6", open_=open_, close="7"))
    truth = venue.snapshot()
    fill_price = (min(Decimal("8.1234"), Decimal(open_)) * Decimal("0.9995")).quantize(
        Decimal("0.0001"), rounding=ROUND_DOWN
    )
    sell_fee = (rounded_qty * fill_price * Decimal(fee_rate)).quantize(Decimal("0.0001"), rounding=ROUND_DOWN)
    assert truth.open_orders == []
    assert [(fill.side, fill.qty, fill.price) for fill in truth.recent_fills] == [
        ("buy", rounded_qty, buy_price),
        ("sell", rounded_qty, fill_price),
    ]
    assert venue.balances() == {
        "USD": Decimal(1000) - qty * buy_price - buy_fee + rounded_qty * fill_price - sell_fee,
        "SUI": qty - rounded_qty,
    }
    assert all(isinstance(value, Decimal) for value in venue.balances().values())
    state = saved(tmp_path, market)
    assert state["last_applied_ts"] == 2 * BAR
    assert venue.snapshot() == truth
    venue.place_entry_with_stop("entry", qty, Decimal(8), pair=PAIR)
    assert saved(tmp_path, market) == state
    assert venue.snapshot() == truth


def test_row6_compat_entry_bar_low_cannot_fill_attached_stop(tmp_path):
    venue = venue_at(tmp_path, Reader([candle(0, low="1")]))
    venue.place_entry_with_stop("entry", Decimal(5), Decimal(8), pair=PAIR)
    assert_holding(venue)
    assert_holding(venue)


def test_row7_compat_raise_cancel_and_entry_idempotence(tmp_path):
    reader = Reader(history())
    venue = venue_at(tmp_path, reader)
    venue.place_entry_with_stop("entry", Decimal(5), Decimal(8), pair=PAIR)
    before = saved(tmp_path)
    venue.place_entry_with_stop("entry", Decimal(5), Decimal(8), pair=PAIR)
    assert saved(tmp_path) == before
    venue.raise_stop(PAIR, Decimal("7.99999"))
    assert venue.resting_stop(PAIR) == Decimal(8)
    venue.raise_stop(PAIR, Decimal("8.55559"))
    assert venue.resting_stop(PAIR) == Decimal("8.5555")
    assert venue.owned_qty(PAIR) == Decimal(5)
    assert len(venue.snapshot().recent_fills) == 1
    venue.cancel_stops(PAIR)
    reader.candles.append(candle(2 * BAR, low="1"))
    assert venue.snapshot().open_orders == []
    assert venue.resting_stop(PAIR) is None
    assert venue.owned_qty(PAIR) == Decimal(5)
    assert len(venue.snapshot().recent_fills) == 1


def write_pack(home: Path) -> Path:
    path = home / "marker-pack.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "marker-pack",
                "version": "1.0.0",
                "label": "Marker boundary test",
                "author": "issue111 tests",
                "timeframe": "1h",
                "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
                "entry": ["close", ">", "sma2"],
                "exit": ["close", "<", "sma2"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 50}},
                "markets": [{"venue": "kraken", "pair": PAIR}],
            }
        )
    )
    return path


def arm_test_pack(home: Path) -> None:
    assert (
        arm_pack(
            write_pack(home),
            venue="kraken",
            mode="paper",
            paper_balance=Decimal(1000),
            requires_license=False,
            home=home,
        )
        == 0
    )


def engine_tick(home: Path, venue: PaperVenue, reader: Reader) -> None:
    assert (
        tick(venue="kraken", venue_obj=venue, reader=reader, clock=lambda: reader.candles[-1].ts_ms / 1000, home=home)
        == 0
    )


def test_row7_compat_paused_flat_pack_suppresses_entry_then_resumes(home):
    arm_test_pack(home)
    config = load_config(home)
    config.armed[0].entries_paused = True
    save_config(home, config)
    reader = Reader([candle(0), candle(BAR, low="11", close="12")])
    venue = venue_at(home, reader)
    engine_tick(home, venue, reader)
    assert venue.owned_qty(PAIR) == Decimal(0)
    assert venue.snapshot().recent_fills == []
    assert load_config(home).armed[0].entries_paused is True
    config = load_config(home)
    config.armed[0].entries_paused = False
    save_config(home, config)
    reader.candles.append(candle(2 * BAR, low="12", close="14"))
    engine_tick(home, venue, reader)
    assert venue.owned_qty(PAIR) > 0
    assert venue.resting_stop(PAIR) == Decimal(7)
    assert [fill.side for fill in venue.snapshot().recent_fills] == ["buy"]


@pytest.mark.parametrize("next_close,next_low,stop_fires", [("9", "8", False), ("5", "4", True)])
def test_rows7_9_compat_paused_holding_restart_keeps_protection_and_signal_exits(
    home, next_close, next_low, stop_fires
):
    arm_test_pack(home)
    reader = Reader([candle(0), candle(BAR, low="11", close="12")])
    venue = venue_at(home, reader)
    engine_tick(home, venue, reader)
    qty = venue.owned_qty(PAIR)
    assert qty > 0
    assert load_config(home).armed[0].owned_qty == qty
    reader.candles.append(candle(2 * BAR, low="11", close="12"))
    venue.snapshot()
    config = load_config(home)
    config.armed[0].entries_paused = True
    save_config(home, config)
    marker = saved(home)["last_applied_ts"]
    balances = venue.balances()
    stop = venue.resting_stop(PAIR)
    restarted = venue_at(home, Reader(list(reader.candles)))
    assert restarted.balances() == balances
    assert restarted.owned_qty(PAIR) == qty
    assert restarted.resting_stop(PAIR) == stop == Decimal(6)
    assert saved(home)["last_applied_ts"] == marker == 2 * BAR
    assert load_config(home).armed[0].entries_paused is True
    reader.candles.append(candle(3 * BAR, low=next_low, close=next_close))
    # Reconstruct with the new candle already visible: a valid marker must not advance on load.
    restarted = venue_at(home, reader)
    assert saved(home)["last_applied_ts"] == marker
    engine_tick(home, restarted, reader)
    assert restarted.owned_qty(PAIR) == Decimal(0)
    assert restarted.resting_stop(PAIR) is None
    truth = restarted.snapshot()
    assert [fill.side for fill in truth.recent_fills] == ["buy", "sell"]
    assert truth.recent_fills[-1].qty == qty
    assert saved(home)["recent_fills"][-1].get("kind") == ("stop" if stop_fires else None)
    assert truth.recent_fills[-1].price == (Decimal(6) if stop_fires else Decimal(next_close)) * Decimal("0.9995")
    assert load_config(home).armed[0].entries_paused is True


@pytest.mark.parametrize("marker", [-1, 0, BAR])
def test_rows4_9_existing_marker_is_not_legacy_and_new_bar_still_fills(tmp_path, marker):
    write_legacy_stop(tmp_path)
    state = saved(tmp_path)
    state["last_applied_ts"] = marker
    path = tmp_path / "run" / "paper-kraken.json"
    path.write_text(json.dumps(state))
    original = path.read_bytes()
    venue = venue_at(tmp_path, Reader([candle(marker + BAR, low="7", open_="7", close="7")]))
    assert path.read_bytes() == original
    assert venue.owned_qty(PAIR) == Decimal(5)
    truth = venue.snapshot()
    assert venue.owned_qty(PAIR) == Decimal(0)
    assert venue.resting_stop(PAIR) is None
    assert len(truth.recent_fills) == 1
    assert truth.recent_fills[0].price == Decimal("6.9965")


def test_row4_empty_legacy_reader_does_not_skip_the_first_new_bar(tmp_path):
    write_legacy_stop(tmp_path)
    venue_at(tmp_path, Reader([]))
    assert saved(tmp_path)["last_applied_ts"] == -1
    restarted = venue_at(tmp_path, Reader([candle(0, low="7", open_="7", close="7")]))
    truth = restarted.snapshot()
    assert restarted.owned_qty(PAIR) == Decimal(0)
    assert restarted.resting_stop(PAIR) is None
    assert len(truth.recent_fills) == 1


def test_row4_no_marker_without_a_stop_does_not_rewrite_flat_state(tmp_path):
    venue_at(tmp_path, Reader(history()))
    path = tmp_path / "run" / "paper-kraken.json"
    original = path.read_bytes()
    restarted = venue_at(tmp_path, Reader(history()))
    assert path.read_bytes() == original
    assert "last_applied_ts" not in saved(tmp_path)
    assert restarted.snapshot().recent_fills == []

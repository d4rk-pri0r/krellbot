"""Phase 5 review regressions. These failed on the worker's first cut."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from krellbot.pack.model import Candle


def _candle(ts_ms: int, close: str, *, low: str | None = None, open_: str | None = None) -> Candle:
    close_d = Decimal(close)
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(open_ or close),
        high=close_d + Decimal(1),
        low=Decimal(low or close),
        close=close_d,
        volume=Decimal(100),
    )


def test_paper_snapshot_fills_a_stop_the_bar_already_hit(home):
    from krellbot.venues.base import PairRules
    from krellbot.venues.paper import PaperVenue

    entry = [_candle(0, "10", low="9", open_="10")]
    reader = {"candles": list(entry)}

    def read(_venue, _pair):
        return list(reader["candles"])

    venue = PaperVenue(
        "kraken",
        rules_provider=lambda _pair: PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal("0.5"),
            lot_decimals=5,
            price_decimals=4,
        ),
        candle_reader=read,
        home=home,
        starting_cash=Decimal(1000),
    )
    venue.place_entry_with_stop("coid-1", Decimal(5), Decimal("4.5"), pair="SUIUSD")
    reader["candles"] = entry + [_candle(3_600_000, "4.5", low="4.0", open_="9")]

    snap = venue.snapshot()
    assert not [o for o in snap.open_orders if o.stop_price is not None]
    sells = [f for f in snap.recent_fills if f.side == "sell"]
    assert len(sells) == 1
    assert sells[0].price == (Decimal("4.5") * (Decimal(1) - Decimal("0.0005"))).quantize(
        Decimal("0.0001"), rounding=ROUND_DOWN
    )


def test_tick_does_not_sell_coins_the_pack_did_not_buy(home):
    import json

    from krellbot import journal
    from krellbot.run import arm_pack, tick

    pack = home / "packs"
    pack.mkdir()
    body = {
        "schema_version": 1,
        "id": "sma-cross",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    path = pack / "sma_cross.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert arm_pack(path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False) == 0
    journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "sma-cross",
            "bar_ts": 0,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )

    class _Venue:
        def __init__(self):
            self.exit_qty = None
            self.balances = {"USD": Decimal(1000), "SUI": Decimal(50)}
            self.orders = [
                {"coid": "stop-1", "pair": "SUIUSD", "side": "sell", "qty": Decimal(5), "stop_price": Decimal(5)}
            ]

        def rules(self, _pair):
            from krellbot.venues.base import PairRules

            return PairRules(
                ordermin=Decimal("0.0001"),
                costmin=Decimal("0.5"),
                lot_decimals=8,
                price_decimals=5,
            )

        def snapshot(self):
            from krellbot.venues.base import Balance, OpenOrder, Truth

            return Truth(
                balances=[Balance(asset=k, free=v) for k, v in self.balances.items() if v > 0],
                open_orders=[
                    OpenOrder(
                        id=o["coid"],
                        coid=o["coid"],
                        pair=o["pair"],
                        side=o["side"],
                        qty=o["qty"],
                        stop_price=o.get("stop_price"),
                    )
                    for o in self.orders
                ],
                recent_fills=[],
            )

        def place_exit(self, coid, qty, *, pair):
            self.exit_qty = qty
            return {"id": coid}

        def cancel_stops(self, pair):
            self.orders = []

        def place_stop(self, coid, qty, stop, *, pair):
            raise AssertionError("stop already rests")

        def place_entry_with_stop(self, coid, qty, stop, *, pair):
            raise AssertionError("must not enter on an exit bar")

        def raise_stop(self, pair, new_stop):
            return None

        def order_by_coid(self, coid):
            return None

    venue = _Venue()
    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "12"),
        _candle(7_200_000, "12"),
        _candle(10_800_000, "9"),
    ]
    tick(venue="kraken", venue_obj=venue, reader=lambda _v, _p: candles, clock=lambda: 10_800)
    assert venue.exit_qty == Decimal(5)


def test_pending_version_stays_while_the_venue_still_holds_the_pack(home):
    import json

    from krellbot.config import load_config, save_config
    from krellbot.run import arm_pack, tick

    pack = home / "packs"
    pack.mkdir()
    body = {
        "schema_version": 1,
        "id": "v1",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    path = pack / "v1.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    arm_pack(path, venue="kraken", mode="paper", paper_balance=Decimal(1000), requires_license=False)
    config = load_config(home)
    config.armed[0].pending_version = "2.0.0"
    config.armed[0].owned_qty = Decimal(0)
    save_config(home, config)
    journal_path = home / "journal"
    journal_path.mkdir(exist_ok=True)
    (journal_path / "2026-09.jsonl").write_text(
        json.dumps(
            {
                "ts": 1,
                "kind": "tick",
                "venue": "kraken",
                "pack": "v1",
                "bar_ts": 1,
                "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class _Hold:
        def rules(self, _pair):
            from krellbot.venues.base import PairRules

            return PairRules(
                ordermin=Decimal(1),
                costmin=Decimal("0.5"),
                lot_decimals=5,
                price_decimals=4,
            )

        def snapshot(self):
            from krellbot.venues.base import Balance, OpenOrder, Truth

            return Truth(
                balances=[Balance(asset="SUI", free=Decimal(5)), Balance(asset="USD", free=Decimal(100))],
                open_orders=[
                    OpenOrder(
                        id="s",
                        coid="s",
                        pair="SUIUSD",
                        side="sell",
                        qty=Decimal(5),
                        stop_price=Decimal(4),
                    )
                ],
                recent_fills=[],
            )

        def place_stop(self, *args, **kwargs):
            raise AssertionError("stop already rests")

        def place_entry_with_stop(self, *args, **kwargs):
            raise AssertionError("already long")

        def place_exit(self, *args, **kwargs):
            raise AssertionError("flat bar must not exit")

        def cancel_stops(self, pair):
            return None

        def raise_stop(self, pair, new_stop):
            return None

        def order_by_coid(self, coid):
            return None

    tick(
        venue="kraken",
        venue_obj=_Hold(),
        reader=lambda _v, _p: [_candle(0, "10"), _candle(3_600_000, "10")],
        clock=lambda: 3600,
    )
    saved = load_config(home)
    assert saved.armed[0].pending_version == "2.0.0"
    assert saved.armed[0].pack_version == "1.0.0"


def test_paper_default_rules_use_the_kraken_sui_minimum():
    from krellbot.venues.paper import default_rules

    rules = default_rules("SUIUSD")
    assert rules.ordermin == Decimal(5)
    assert rules.costmin == Decimal("0.5")
    assert rules.lot_decimals == 5
    assert rules.price_decimals == 4


def test_repeat_paper_entry_does_not_buy_twice(home):
    from krellbot.venues.base import PairRules
    from krellbot.venues.paper import PaperVenue

    venue = PaperVenue(
        "kraken",
        rules_provider=lambda _pair: PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal("0.5"),
            lot_decimals=5,
            price_decimals=4,
        ),
        candle_reader=lambda _v, _p: [_candle(0, "10")],
        home=home,
        starting_cash=Decimal(1000),
    )
    venue.place_entry_with_stop("same", Decimal(5), Decimal(4), pair="SUIUSD")
    venue.place_entry_with_stop("same", Decimal(5), Decimal(4), pair="SUIUSD")
    assert venue.owned_qty("SUIUSD") == Decimal(5)


def test_live_tick_does_not_paper_trade(home, monkeypatch, fresh_keyring):
    import json

    from krellbot.cli import cmd_tick
    from krellbot.config import ArmedPack, Config, save_config

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    pack = home / "pack.json"
    pack.write_text("{}", encoding="utf-8")
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack),
                    pack_sha256="0" * 64,
                    pack_id="sma-cross",
                    pack_version="1.0.0",
                    venue="kraken",
                    pair="SUIUSD",
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode="live",
                    starting_cash=None,
                    requires_license=False,
                    armed_at_ts=1,
                )
            ]
        ),
    )
    candles = home / "candles.csv"
    candles.write_text("ts_ms,open,high,low,close,volume\n0,10,11,9,10,1\n", encoding="utf-8")
    rc = cmd_tick(["--venue", "kraken", "--offline-candles", str(candles)])
    assert rc == 1
    assert not list((home / "run").glob("paper-*.json")) if (home / "run").exists() else True
    assert json.dumps({"mode": "live"})

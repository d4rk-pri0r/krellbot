"""Coinbase paper arm: BTC-USD instrument rules + tick/metadata parity.

M11.2: paper-arming a pack on the agreed Coinbase BTC/USD product
(``BTC-USD``) must persist ``$KRELLBOT_HOME/run/instrument-rules.json``
via the public product path (fake transport in tests) on a production
paper tick, must not journal ``metadata_refusal`` solely because rules
were missing, and must book base inventory under ``BTC`` (not ``BTC-``).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.data.instruments import (
    PAPER_WAVE_COINBASE_BTC_USD,
    SNAPSHOT_FILENAME,
)

# Labeled Coinbase Advanced Trade public product shape for BTC-USD.
# Values mirror public minima/increments; the transport is fake.
COINBASE_BTC_USD_PRODUCT = {
    "product_id": "BTC-USD",
    "base_currency_id": "BTC",
    "quote_currency_id": "USD",
    "base_min_size": "0.00000001",
    "quote_min_size": "1",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
}


class _CoinbaseBtcProductTransport:
    """Serves the wave BTC-USD product; records every call."""

    def __init__(self, *, product: dict | None = None) -> None:
        self.product = dict(product) if product is not None else dict(COINBASE_BTC_USD_PRODUCT)
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        url_s = str(url)
        if "market/products" in url_s or "/products/" in url_s:
            if self.product.get("error") or self.product.get("message"):
                return dict(self.product)
            return dict(self.product)
        return {}

    def post(self, url, body=None, headers=None, form=None):
        self.calls.append(("POST", str(url)))
        return {}


def _write_wave_pack(home: Path, *, pack_id: str = "coinbase-btc-wave") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Coinbase BTC wave",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "coinbase", "pair": PAPER_WAVE_COINBASE_BTC_USD}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path, *, paper_balance: Decimal = Decimal(1000)) -> None:
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue="coinbase",
        mode="paper",
        paper_balance=paper_balance,
        correlation_id=f"arm-{pack_path.stem}",
    )
    assert result.ok, (result.code, result.message)


def _three_bar_entry_candles() -> list:
    from krellbot.pack.model import Candle

    hour = 3_600_000
    return [
        Candle(0 * hour, Decimal(11), Decimal(12), Decimal(10), Decimal(11), Decimal(100)),
        Candle(1 * hour, Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(100)),
        Candle(2 * hour, Decimal(13), Decimal(14), Decimal(12), Decimal(13), Decimal(100)),
    ]


def _tick_journal_records(home: Path) -> list[dict]:
    records: list[dict] = []
    journal_dir = home / "journal"
    if not journal_dir.is_dir():
        return records
    for path in sorted(journal_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "tick":
                records.append(rec)
    return records


def test_agreed_coinbase_btc_usd_symbol_is_product_id() -> None:
    """Wave Coinbase BTC/USD spelling is the Advanced Trade product id."""
    assert PAPER_WAVE_COINBASE_BTC_USD == "BTC-USD"


def test_paper_arm_records_coinbase_btc_usd(home, fresh_keyring) -> None:
    """Paper arm accepts a pack market on coinbase / BTC-USD."""
    from krellbot import config as kb_config

    pack_path = _write_wave_pack(home)
    _arm_paper(home, pack_path)

    config = kb_config.load_config(home)
    armed = kb_config.find_armed(config, "coinbase", PAPER_WAVE_COINBASE_BTC_USD)
    assert armed is not None
    assert armed.mode == "paper"
    assert armed.venue == "coinbase"
    assert armed.pair == PAPER_WAVE_COINBASE_BTC_USD


def test_paper_tick_persists_instrument_rules_for_coinbase_btc_usd(home, fresh_keyring) -> None:
    """Production paper tick writes instrument-rules.json for BTC-USD.

    Fake product transport supplies the wave pair. After one tick the
    snapshot file exists under ``run/`` and covers ``coinbase`` /
    ``BTC-USD``. The tick must not journal ``metadata_refusal`` solely
    because rules were missing before the write.
    """
    from krellbot.cli import cmd_tick

    pack_path = _write_wave_pack(home)
    _arm_paper(home, pack_path)

    snapshot_before = home / "run" / SNAPSHOT_FILENAME
    assert not snapshot_before.exists(), "arm must not be the only writer; tick persists rules"

    candles = _three_bar_entry_candles()

    def fetch(venue, pair, tf, transport):
        assert venue == "coinbase"
        assert pair == PAPER_WAVE_COINBASE_BTC_USD
        return list(candles)

    transport = _CoinbaseBtcProductTransport()
    rc = cmd_tick(["--venue", "coinbase"], fetch=fetch, transport=transport)
    assert rc == 0, rc

    snapshot_path = home / "run" / SNAPSHOT_FILENAME
    assert snapshot_path.is_file(), "production paper tick must write run/instrument-rules.json"
    body = json.loads(snapshot_path.read_text(encoding="utf-8"))
    records = body.get("records") or {}
    coinbase = records.get("coinbase") or {}
    assert PAPER_WAVE_COINBASE_BTC_USD in coinbase, coinbase.keys()
    wave = coinbase[PAPER_WAVE_COINBASE_BTC_USD]
    assert wave["canonical_pair"] == PAPER_WAVE_COINBASE_BTC_USD
    assert wave["venue_symbol"] == PAPER_WAVE_COINBASE_BTC_USD
    assert Decimal(wave["min_quantity"]) == Decimal("0.00000001")
    assert Decimal(wave["min_notional"]) == Decimal(1)
    assert Decimal(wave["quantity_increment"]) == Decimal("0.00000001")
    assert Decimal(wave["price_increment"]) == Decimal("0.01")
    assert any("products" in url for _, url in transport.calls)

    tick_records = _tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == PAPER_WAVE_COINBASE_BTC_USD]
    assert pair_records, "engine must journal a tick for the wave pair"
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") is None, detail


def test_paper_tick_coinbase_btc_usd_without_product_still_refuses_missing_rules(home, fresh_keyring) -> None:
    """When public metadata cannot supply rules, refusal remains honest.

    An empty/error product fake must not invent BTC minima; the tick still
    journals ``metadata_unavailable`` rather than silently evaluating.
    """
    from krellbot.cli import cmd_tick
    from krellbot.data.instruments import METADATA_UNAVAILABLE

    pack_path = _write_wave_pack(home, pack_id="coinbase-btc-missing")
    _arm_paper(home, pack_path)

    candles = _three_bar_entry_candles()

    def fetch(venue, pair, tf, transport):
        return list(candles)

    transport = _CoinbaseBtcProductTransport(product={"message": "NotFound"})
    rc = cmd_tick(["--venue", "coinbase"], fetch=fetch, transport=transport)
    assert rc == 0

    tick_records = _tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == PAPER_WAVE_COINBASE_BTC_USD]
    assert pair_records
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") == METADATA_UNAVAILABLE, detail
    assert not (home / "run" / SNAPSHOT_FILENAME).exists()


def test_coinbase_paper_fill_books_btc_not_hyphenated_base(home) -> None:
    """Paper venue splits ``BTC-USD`` so inventory lands under ``BTC``.

    Without the hyphen-aware split, balances would key as ``BTC-`` and
    ownership / status projection would disagree with Coinbase assets.
    """
    from krellbot.application.paper import base_quote
    from krellbot.pack.model import Candle
    from krellbot.run import _base_quote as run_base_quote
    from krellbot.venues.base import PairRules
    from krellbot.venues.paper import PaperVenue, _base_quote

    assert _base_quote(PAPER_WAVE_COINBASE_BTC_USD) == ("BTC", "USD")
    assert base_quote(PAPER_WAVE_COINBASE_BTC_USD) == ("BTC", "USD")
    assert run_base_quote(PAPER_WAVE_COINBASE_BTC_USD) == ("BTC", "USD")

    candle = Candle(
        ts_ms=0,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(10),
    )

    def rules(_pair: str) -> PairRules:
        return PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal(1),
            lot_decimals=8,
            price_decimals=2,
        )

    venue = PaperVenue(
        "coinbase",
        rules_provider=rules,
        candle_reader=lambda _v, _p: [candle],
        home=home,
        starting_cash=Decimal(1000),
    )
    venue.place_entry_with_stop(
        "coid-cb-1",
        Decimal("0.01"),
        Decimal(90),
        pair=PAPER_WAVE_COINBASE_BTC_USD,
    )
    snap = venue.snapshot()
    assets = {b.asset: b.free for b in snap.balances}
    assert "BTC" in assets, assets
    assert "BTC-" not in assets, assets
    assert assets["BTC"] == Decimal("0.01")
    assert "USD" in assets


def test_offline_candles_coinbase_paper_tick_does_not_fetch_product(home, fresh_keyring) -> None:
    """``--offline-candles`` must not contact the Coinbase product endpoint."""
    from krellbot.cli import cmd_tick

    pack_path = _write_wave_pack(home, pack_id="offline-coinbase-btc")
    _arm_paper(home, pack_path)

    csv_path = home / "candles.csv"
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n0,11,12,10,11,100\n3600000,10,11,9,10,100\n7200000,13,14,12,13,100\n",
        encoding="utf-8",
    )

    transport = _CoinbaseBtcProductTransport()

    def fetch(_venue, _pair, _tf, _transport):
        raise AssertionError("fetch must not run under --offline-candles")

    rc = cmd_tick(
        ["--venue", "coinbase", "--offline-candles", str(csv_path)],
        fetch=fetch,
        transport=transport,
    )
    assert rc == 0
    assert transport.calls == [], f"offline tick must not hit product metadata; calls={transport.calls!r}"
    assert not (home / "run" / SNAPSHOT_FILENAME).exists()

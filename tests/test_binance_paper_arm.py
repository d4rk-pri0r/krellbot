"""Binance paper arm: BTCUSDT arm + tick without metadata_refusal when rules present.

M14.3: paper-arming a pack on the agreed Binance BTC/USDT symbol
(``BTCUSDT``) must be accepted; once instrument rules for that pair are
present, a paper tick must not journal ``metadata_refusal`` solely because
rules were missing; fills must book base inventory under ``BTC`` (not
``BTCU``).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.data.instruments import (
    PAPER_WAVE_BINANCE_BTC_USDT,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
)

# Labeled Binance spot minima/increments for BTCUSDT (mirrors fake exchangeInfo).
BINANCE_BTC_USDT_RULES = {
    "schema_version": SCHEMA_VERSION,
    "venue": "binance",
    "canonical_pair": PAPER_WAVE_BINANCE_BTC_USDT,
    "venue_symbol": PAPER_WAVE_BINANCE_BTC_USDT,
    "base_asset": "BTC",
    "quote_asset": "USDT",
    "min_quantity": "0.00001",
    "min_notional": "5",
    "quantity_increment": "0.00001",
    "price_increment": "0.01",
    "source": {
        "endpoint": "https://api.binance.com/api/v3/exchangeInfo",
        "retrieved_at": "2099-01-01T00:00:00Z",
        "source_version": "a" * 16,
        "payload_sha256": "a" * 64,
    },
    "usable_until": "2099-01-01T00:00:00Z",
}


def _write_wave_pack(home: Path, *, pack_id: str = "binance-btc-wave") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Binance BTC wave",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "binance", "pair": PAPER_WAVE_BINANCE_BTC_USDT}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path, *, paper_balance: Decimal = Decimal(1000)) -> None:
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue="binance",
        mode="paper",
        paper_balance=paper_balance,
        correlation_id=f"arm-{pack_path.stem}",
    )
    assert result.ok, (result.code, result.message)


def _seed_instrument_rules(home: Path) -> Path:
    path = home / "run" / SNAPSHOT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": SCHEMA_VERSION,
        "records": {"binance": {PAPER_WAVE_BINANCE_BTC_USDT: dict(BINANCE_BTC_USDT_RULES)}},
    }
    path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return path


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


def test_agreed_binance_btc_usdt_symbol_is_concatenated() -> None:
    """Wave Binance BTC/USDT spelling is the spot exchangeInfo symbol."""
    assert PAPER_WAVE_BINANCE_BTC_USDT == "BTCUSDT"


def test_paper_arm_records_binance_btc_usdt(home, fresh_keyring) -> None:
    """Paper arm accepts a pack market on binance / BTCUSDT."""
    from krellbot import config as kb_config

    pack_path = _write_wave_pack(home)
    _arm_paper(home, pack_path)

    config = kb_config.load_config(home)
    armed = kb_config.find_armed(config, "binance", PAPER_WAVE_BINANCE_BTC_USDT)
    assert armed is not None
    assert armed.mode == "paper"
    assert armed.venue == "binance"
    assert armed.pair == PAPER_WAVE_BINANCE_BTC_USDT


def test_paper_tick_with_rules_present_does_not_metadata_refuse_binance_btc_usdt(home, fresh_keyring) -> None:
    """Once rules for BTCUSDT are present, a paper tick must not refuse metadata.

    M14.3 pins arm + tick honesty when rules already exist. Production
    persistence of those rules from exchangeInfo is M14.4.
    """
    from krellbot.cli import cmd_tick

    pack_path = _write_wave_pack(home)
    _arm_paper(home, pack_path)
    _seed_instrument_rules(home)

    csv_path = home / "candles.csv"
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n0,11,12,10,11,100\n3600000,10,11,9,10,100\n7200000,13,14,12,13,100\n",
        encoding="utf-8",
    )

    def fetch(_venue, _pair, _tf, _transport):
        raise AssertionError("offline candles must not call fetch")

    rc = cmd_tick(
        ["--venue", "binance", "--offline-candles", str(csv_path)],
        fetch=fetch,
        transport=object(),
    )
    assert rc == 0, rc

    tick_records = _tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == PAPER_WAVE_BINANCE_BTC_USDT]
    assert pair_records, "engine must journal a tick for the wave pair"
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") is None, detail


def test_paper_tick_binance_btc_usdt_without_rules_still_refuses(home, fresh_keyring) -> None:
    """Without instrument rules, refusal remains honest for BTCUSDT."""
    from krellbot.cli import cmd_tick
    from krellbot.data.instruments import METADATA_UNAVAILABLE

    pack_path = _write_wave_pack(home, pack_id="binance-btc-missing")
    _arm_paper(home, pack_path)

    csv_path = home / "candles.csv"
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n0,11,12,10,11,100\n3600000,10,11,9,10,100\n7200000,13,14,12,13,100\n",
        encoding="utf-8",
    )

    rc = cmd_tick(
        ["--venue", "binance", "--offline-candles", str(csv_path)],
        fetch=lambda *_a, **_k: [],
        transport=object(),
    )
    assert rc == 0

    tick_records = _tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == PAPER_WAVE_BINANCE_BTC_USDT]
    assert pair_records
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") == METADATA_UNAVAILABLE, detail


def test_binance_paper_fill_books_btc_not_btcu(home) -> None:
    """Paper venue splits ``BTCUSDT`` so inventory lands under ``BTC`` / ``USDT``.

    Without the USDT-before-USD split, balances would key as ``BTCU`` / ``SDT``.
    """
    from krellbot.application.paper import base_quote
    from krellbot.pack.model import Candle
    from krellbot.run import _base_quote as run_base_quote
    from krellbot.venues.base import PairRules
    from krellbot.venues.paper import PaperVenue, _base_quote

    assert _base_quote(PAPER_WAVE_BINANCE_BTC_USDT) == ("BTC", "USDT")
    assert base_quote(PAPER_WAVE_BINANCE_BTC_USDT) == ("BTC", "USDT")
    assert run_base_quote(PAPER_WAVE_BINANCE_BTC_USDT) == ("BTC", "USDT")

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
            ordermin=Decimal("0.00001"),
            costmin=Decimal(5),
            lot_decimals=5,
            price_decimals=2,
        )

    venue = PaperVenue(
        "binance",
        rules_provider=rules,
        candle_reader=lambda _v, _p: [candle],
        home=home,
        starting_cash=Decimal(1000),
    )
    venue.place_entry_with_stop(
        "coid-bn-1",
        Decimal("0.1"),
        Decimal(90),
        pair=PAPER_WAVE_BINANCE_BTC_USDT,
    )
    snap = venue.snapshot()
    assets = {b.asset: b.free for b in snap.balances}
    assert "BTC" in assets, assets
    assert "BTCU" not in assets, assets
    assert "SDT" not in assets, assets
    assert assets["BTC"] == Decimal("0.1")
    assert "USDT" in assets
    assert "USD" not in assets

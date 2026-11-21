"""Bybit paper arm: BTCUSDT arm + tick without metadata_refusal when rules present.

Paper-arming a pack on the agreed Bybit BTC/USDT symbol (``BTCUSDT``)
must be accepted. Once instrument rules for that pair are present, a
paper tick must not journal ``metadata_refusal`` solely because rules
were missing. Fills book base inventory under ``BTC``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.application.live_preflight import CODE_PREFLIGHT_BLOCKED, build_venue_preflight_transport, evaluate
from krellbot.data.instruments import (
    BYBIT_INSTRUMENTS_URL,
    PAPER_WAVE_BYBIT_BTC_USDT,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
)

BYBIT_BTC_USDT_RULES = {
    "schema_version": SCHEMA_VERSION,
    "venue": "bybit",
    "canonical_pair": PAPER_WAVE_BYBIT_BTC_USDT,
    "venue_symbol": PAPER_WAVE_BYBIT_BTC_USDT,
    "base_asset": "BTC",
    "quote_asset": "USDT",
    "min_quantity": "0.000011",
    "min_notional": "5",
    "quantity_increment": "0.000001",
    "price_increment": "0.1",
    "source": {
        "endpoint": BYBIT_INSTRUMENTS_URL,
        "retrieved_at": "2099-01-01T00:00:00Z",
        "source_version": "a" * 16,
        "payload_sha256": "a" * 64,
    },
    "usable_until": "2099-01-01T00:00:00Z",
}


def _write_wave_pack(home: Path, *, pack_id: str = "bybit-btc-wave") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Bybit BTC wave",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "bybit", "pair": PAPER_WAVE_BYBIT_BTC_USDT}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path) -> None:
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue="bybit",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id=f"arm-{pack_path.stem}",
    )
    assert result.ok, (result.code, result.message)


def _seed_instrument_rules(home: Path) -> None:
    path = home / "run" / SNAPSHOT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": SCHEMA_VERSION,
        "records": {"bybit": {PAPER_WAVE_BYBIT_BTC_USDT: dict(BYBIT_BTC_USDT_RULES)}},
    }
    path.write_text(json.dumps(body), encoding="utf-8")


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
            rec = json.loads(line)
            if rec.get("kind") == "tick":
                records.append(rec)
    return records


def test_paper_arm_records_bybit_btc_usdt(home, fresh_keyring) -> None:
    """Paper arm accepts a pack market on bybit / BTCUSDT."""
    from krellbot import config as kb_config

    pack_path = _write_wave_pack(home)
    _arm_paper(home, pack_path)
    armed = kb_config.find_armed(kb_config.load_config(home), "bybit", PAPER_WAVE_BYBIT_BTC_USDT)
    assert armed is not None
    assert armed.mode == "paper"
    assert armed.venue == "bybit"
    assert armed.pair == PAPER_WAVE_BYBIT_BTC_USDT


def test_paper_tick_with_rules_present_does_not_metadata_refuse_bybit_btc_usdt(home, fresh_keyring) -> None:
    """Once rules for BTCUSDT are present, a paper tick must not refuse metadata."""
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
        ["--venue", "bybit", "--offline-candles", str(csv_path)],
        fetch=fetch,
        transport=object(),
    )
    assert rc == 0, rc
    pair_records = [
        r for r in _tick_journal_records(home) if (r.get("detail") or {}).get("pair") == PAPER_WAVE_BYBIT_BTC_USDT
    ]
    assert pair_records, "engine must journal a tick for the wave pair"
    assert (pair_records[-1].get("detail") or {}).get("metadata_refusal") is None


def test_paper_tick_bybit_btc_usdt_without_rules_still_refuses(home, fresh_keyring) -> None:
    """Without instrument rules, refusal remains honest for BTCUSDT."""
    from krellbot.cli import cmd_tick
    from krellbot.data.instruments import METADATA_UNAVAILABLE

    pack_path = _write_wave_pack(home, pack_id="bybit-btc-missing")
    _arm_paper(home, pack_path)
    csv_path = home / "candles.csv"
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n0,11,12,10,11,100\n3600000,10,11,9,10,100\n7200000,13,14,12,13,100\n",
        encoding="utf-8",
    )
    rc = cmd_tick(
        ["--venue", "bybit", "--offline-candles", str(csv_path)],
        fetch=lambda *_a, **_k: [],
        transport=object(),
    )
    assert rc == 0
    pair_records = [
        r for r in _tick_journal_records(home) if (r.get("detail") or {}).get("pair") == PAPER_WAVE_BYBIT_BTC_USDT
    ]
    assert pair_records
    assert (pair_records[-1].get("detail") or {}).get("metadata_refusal") == METADATA_UNAVAILABLE


def test_bybit_paper_fill_books_btc_and_seeds_usdt(home) -> None:
    """Paper venue splits ``BTCUSDT`` and seeds USDT, not USD."""
    from krellbot.pack.model import Candle
    from krellbot.venues.base import PairRules
    from krellbot.venues.paper import PaperVenue

    candle = Candle(
        ts_ms=0,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(10),
    )
    venue = PaperVenue(
        "bybit",
        rules_provider=lambda _pair: PairRules(
            ordermin=Decimal("0.000011"),
            costmin=Decimal(5),
            lot_decimals=6,
            price_decimals=1,
        ),
        candle_reader=lambda _v, _p: [candle],
        home=home,
        starting_cash=Decimal(1000),
    )
    venue.place_entry_with_stop("coid-bybit-1", Decimal("0.1"), Decimal(90), pair=PAPER_WAVE_BYBIT_BTC_USDT)
    assets = {b.asset: b.free for b in venue.snapshot().balances}
    assert assets["BTC"] == Decimal("0.1")
    assert "USDT" in assets
    assert "USD" not in assets


def test_bybit_preflight_factory_stays_blocked(fresh_keyring) -> None:
    """Live preflight does not treat Bybit as a qualified venue."""
    del fresh_keyring
    transport = build_venue_preflight_transport(venue="bybit", http_transport=object())
    result = evaluate(
        account_id="bybit",
        revision_id="rev-bybit",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is False
    assert result.code == CODE_PREFLIGHT_BLOCKED
    assert "unsupported" in (result.message or "").lower()

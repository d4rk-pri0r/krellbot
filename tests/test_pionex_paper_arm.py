"""Pionex paper arm: BTC-USDT arm + tick without metadata_refusal when rules present.

Paper-arming a pack on the agreed Pionex pack pair (``BTC-USDT``) must be
accepted. Once instrument rules for that pair are present, a paper tick
must not journal ``metadata_refusal`` solely because rules were missing.
Fills book base inventory under ``BTC``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.application.live_preflight import CODE_PREFLIGHT_BLOCKED, build_venue_preflight_transport, evaluate
from krellbot.application.paper import _PAPER_TAKER_BPS
from krellbot.data.instruments import (
    PAPER_WAVE_PIONEX_BTC_USDT,
    PIONEX_SYMBOLS_URL,
    SCHEMA_VERSION,
    SNAPSHOT_FILENAME,
)

PIONEX_BTC_USDT_RULES = {
    "schema_version": SCHEMA_VERSION,
    "venue": "pionex",
    "canonical_pair": PAPER_WAVE_PIONEX_BTC_USDT,
    "venue_symbol": "BTC_USDT",
    "base_asset": "BTC",
    "quote_asset": "USDT",
    "min_quantity": "0.000001",
    "min_notional": "10",
    "quantity_increment": "0.000001",
    "price_increment": "0.01",
    "source": {
        "endpoint": PIONEX_SYMBOLS_URL,
        "retrieved_at": "2099-01-01T00:00:00Z",
        "source_version": "a" * 16,
        "payload_sha256": "a" * 64,
    },
    "usable_until": "2099-01-01T00:00:00Z",
}


def _write_wave_pack(home: Path, *, pack_id: str = "pionex-btc-wave") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Pionex BTC wave",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "pionex", "pair": PAPER_WAVE_PIONEX_BTC_USDT}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path) -> None:
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue="pionex",
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
        "records": {"pionex": {PAPER_WAVE_PIONEX_BTC_USDT: dict(PIONEX_BTC_USDT_RULES)}},
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


def test_paper_taker_bps_pins_published_pionex_regular_rate() -> None:
    """Published regular spot taker is 0.05%. Paper pins 5 bps."""
    assert _PAPER_TAKER_BPS["pionex"] == 5


def test_paper_arm_records_pionex_btc_usdt(home, fresh_keyring) -> None:
    """Paper arm accepts a pack market on pionex / BTC-USDT."""
    from krellbot import config as kb_config

    pack_path = _write_wave_pack(home)
    _arm_paper(home, pack_path)
    armed = kb_config.find_armed(kb_config.load_config(home), "pionex", PAPER_WAVE_PIONEX_BTC_USDT)
    assert armed is not None
    assert armed.mode == "paper"
    assert armed.venue == "pionex"
    assert armed.pair == PAPER_WAVE_PIONEX_BTC_USDT


def test_paper_tick_with_rules_present_does_not_metadata_refuse_pionex_btc_usdt(home, fresh_keyring) -> None:
    """Once rules for BTC-USDT are present, a paper tick must not refuse metadata."""
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
        ["--venue", "pionex", "--offline-candles", str(csv_path)],
        fetch=fetch,
        transport=object(),
    )
    assert rc == 0, rc
    pair_records = [
        r for r in _tick_journal_records(home) if (r.get("detail") or {}).get("pair") == PAPER_WAVE_PIONEX_BTC_USDT
    ]
    assert pair_records, "engine must journal a tick for the wave pair"
    assert (pair_records[-1].get("detail") or {}).get("metadata_refusal") is None


def test_paper_tick_pionex_btc_usdt_without_rules_still_refuses(home, fresh_keyring) -> None:
    """Without instrument rules, refusal remains honest for BTC-USDT."""
    from krellbot.cli import cmd_tick
    from krellbot.data.instruments import METADATA_UNAVAILABLE

    pack_path = _write_wave_pack(home, pack_id="pionex-btc-missing")
    _arm_paper(home, pack_path)
    csv_path = home / "candles.csv"
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n0,11,12,10,11,100\n3600000,10,11,9,10,100\n7200000,13,14,12,13,100\n",
        encoding="utf-8",
    )
    rc = cmd_tick(
        ["--venue", "pionex", "--offline-candles", str(csv_path)],
        fetch=lambda *_a, **_k: [],
        transport=object(),
    )
    assert rc == 0
    pair_records = [
        r for r in _tick_journal_records(home) if (r.get("detail") or {}).get("pair") == PAPER_WAVE_PIONEX_BTC_USDT
    ]
    assert pair_records
    assert (pair_records[-1].get("detail") or {}).get("metadata_refusal") == METADATA_UNAVAILABLE


def test_pionex_paper_fill_books_btc_and_seeds_usdt(home) -> None:
    """Paper venue splits ``BTC-USDT`` and seeds USDT, not USD."""
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
        "pionex",
        rules_provider=lambda _pair: PairRules(
            ordermin=Decimal("0.000001"),
            costmin=Decimal(10),
            lot_decimals=6,
            price_decimals=2,
        ),
        candle_reader=lambda _v, _p: [candle],
        home=home,
        starting_cash=Decimal(1000),
    )
    venue.place_entry_with_stop("coid-pionex-1", Decimal("0.1"), Decimal(90), pair=PAPER_WAVE_PIONEX_BTC_USDT)
    assets = {b.asset: b.free for b in venue.snapshot().balances}
    assert assets["BTC"] == Decimal("0.1")
    assert "USDT" in assets
    assert "USD" not in assets


def test_pionex_preflight_factory_stays_blocked(fresh_keyring) -> None:
    """Live preflight does not treat Pionex as a qualified venue."""
    del fresh_keyring
    transport = build_venue_preflight_transport(venue="pionex", http_transport=object())
    result = evaluate(
        account_id="pionex",
        revision_id="rev-pionex",
        mode="sandbox",
        transport=transport,
    )
    assert result.ok is False
    assert result.code == CODE_PREFLIGHT_BLOCKED
    assert "unsupported" in (result.message or "").lower()

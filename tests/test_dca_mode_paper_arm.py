"""DCA mode pack paper-arms on the Kraken wave pair and ticks with fakes.

M15.7: built-in ``mode-dca`` paper-arms on ``XXBTZUSD`` behind fakes; a
tick evaluates without ``metadata_refusal`` solely for missing mode
support. Starters catalogue lists the mode under additive ``modes``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.data.instruments import PAPER_WAVE_KRAKEN_BTC_USD, SNAPSHOT_FILENAME
from krellbot.packs import mode_packs

# Labeled Kraken AssetPairs shape for the paper wave pair (fake only).
KRAKEN_XXBTZUSD_PAYLOAD = {
    "altname": "XBTUSD",
    "wsname": "XBT/USD",
    "base": "XXBT",
    "quote": "ZUSD",
    "ordermin": "0.0001",
    "costmin": "0.5",
    "lot_decimals": 8,
    "pair_decimals": 1,
}


class _KrakenBtcAssetPairsTransport:
    """Serves AssetPairs for XXBTZUSD; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if "AssetPairs" in str(url):
            return {"error": [], "result": {"XXBTZUSD": dict(KRAKEN_XXBTZUSD_PAYLOAD)}}
        return {"error": [], "result": {}}

    def post(self, url, form, headers):
        self.calls.append(("POST", str(url)))
        return {"error": [], "result": {}}


def _write_builtin_dca_pack(home: Path) -> Path:
    pack = mode_packs.load_mode_pack("dca")
    target = home / f"{pack['id']}.json"
    target.write_text(json.dumps(pack), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path, *, paper_balance: Decimal = Decimal(1000)) -> None:
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=paper_balance,
        correlation_id=f"arm-{pack_path.stem}",
    )
    assert result.ok, (result.code, result.message)


def _three_day_candles() -> list:
    """Enough bars for SMA(2); positive closes satisfy DCA entry gates."""
    from krellbot.pack.model import Candle

    day = 86_400_000
    return [
        Candle(0 * day, Decimal(100), Decimal(105), Decimal(95), Decimal(100), Decimal(10)),
        Candle(1 * day, Decimal(100), Decimal(110), Decimal(98), Decimal(108), Decimal(12)),
        Candle(2 * day, Decimal(108), Decimal(112), Decimal(106), Decimal(110), Decimal(11)),
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


def test_builtin_dca_targets_wave_pair() -> None:
    pack = mode_packs.load_mode_pack("dca")
    assert PAPER_WAVE_KRAKEN_BTC_USD == "XXBTZUSD"
    markets = pack["markets"]
    assert any(m.get("venue") == "kraken" and m.get("pair") == PAPER_WAVE_KRAKEN_BTC_USD for m in markets)


def test_starters_catalogue_lists_dca_mode(tmp_path: Path) -> None:
    from krellbot.packs import catalogue as starter_catalogue

    doc = starter_catalogue.catalogue_document()
    assert "modes" in doc
    mode_ids = [row["id"] for row in doc["modes"]]
    assert "mode-dca" in mode_ids
    dca_row = next(row for row in doc["modes"] if row["id"] == "mode-dca")
    assert set(dca_row.keys()) == {"id", "label", "description", "pack"}
    assert dca_row["pack"]["mode"]["kind"] == "dca"
    assert "no profit or return claim" in dca_row["description"].lower()


def test_dca_mode_paper_arm_records_wave_pair(home, fresh_keyring) -> None:
    from krellbot import config as kb_config

    pack_path = _write_builtin_dca_pack(home)
    _arm_paper(home, pack_path)

    config = kb_config.load_config(home)
    armed = kb_config.find_armed(config, "kraken", PAPER_WAVE_KRAKEN_BTC_USD)
    assert armed is not None
    assert armed.mode == "paper"
    assert armed.pack_id == "mode-dca"
    assert armed.pair == PAPER_WAVE_KRAKEN_BTC_USD


def test_dca_mode_paper_tick_evaluates_without_mode_support_refusal(home, fresh_keyring) -> None:
    """Paper tick on armed DCA must not refuse solely for missing mode support."""
    from krellbot.cli import cmd_tick

    pack_path = _write_builtin_dca_pack(home)
    _arm_paper(home, pack_path)

    candles = _three_day_candles()

    def fetch(venue, pair, tf, transport):
        assert venue == "kraken"
        assert pair == PAPER_WAVE_KRAKEN_BTC_USD
        assert tf == "1d"
        return list(candles)

    transport = _KrakenBtcAssetPairsTransport()
    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=transport)
    assert rc == 0, rc

    tick_records = _tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == PAPER_WAVE_KRAKEN_BTC_USD]
    assert pair_records, "engine must journal a tick for the DCA wave pair"
    detail = pair_records[-1].get("detail") or {}
    refusal = detail.get("metadata_refusal")
    assert refusal is None, detail
    # Explicit: refusal must not be a mode-support gap.
    assert refusal not in {"missing_mode_support", "unsupported_mode", "mode_unsupported"}
    # Instrument rules should have been written by the production tick path.
    snapshot_path = home / "run" / SNAPSHOT_FILENAME
    assert snapshot_path.is_file(), "paper tick should persist instrument rules for the wave pair"

"""Paper BTC/USD instrument rules: production snapshot write + tick.

M2.4: a paper tick on the wave Kraken BTC/USD pair (``XXBTZUSD``, the
owned-strategy paper-arm default) must persist
``$KRELLBOT_HOME/run/instrument-rules.json`` via the public AssetPairs
path (fake transport in tests) and must not journal ``metadata_refusal``
solely because rules were missing.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from krellbot.data.instruments import (
    PAPER_WAVE_KRAKEN_BTC_USD,
    SNAPSHOT_FILENAME,
)

# Labeled Kraken AssetPairs shape for XXBTZUSD (response key / altname /
# wsname match the wave pair). Values mirror public Kraken minima shape;
# the transport is fake — no live endpoint is contacted.
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
    """Serves AssetPairs for the wave BTC/USD pair; records every call."""

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


def _write_wave_pack(home: Path, *, pack_id: str = "paper-btc-wave") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Paper BTC wave",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": PAPER_WAVE_KRAKEN_BTC_USD}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
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


def test_paper_tick_persists_instrument_rules_for_wave_btc_usd(home, fresh_keyring) -> None:
    """Production paper tick writes instrument-rules.json for XXBTZUSD.

    Fake AssetPairs transport supplies the wave pair. After one tick the
    snapshot file exists under ``run/`` and covers ``kraken`` /
    ``XXBTZUSD``. The tick must not journal ``metadata_refusal`` solely
    because rules were missing before the write.
    """
    from krellbot.cli import cmd_tick

    assert PAPER_WAVE_KRAKEN_BTC_USD == "XXBTZUSD"
    pack_path = _write_wave_pack(home)
    _arm_paper(home, pack_path)

    snapshot_before = home / "run" / SNAPSHOT_FILENAME
    assert not snapshot_before.exists(), "arm must not be the only writer; tick persists rules"

    candles = _three_bar_entry_candles()

    def fetch(venue, pair, tf, transport):
        assert pair == PAPER_WAVE_KRAKEN_BTC_USD
        return list(candles)

    transport = _KrakenBtcAssetPairsTransport()
    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=transport)
    assert rc == 0, rc

    snapshot_path = home / "run" / SNAPSHOT_FILENAME
    assert snapshot_path.is_file(), "production paper tick must write run/instrument-rules.json"
    body = json.loads(snapshot_path.read_text(encoding="utf-8"))
    records = body.get("records") or {}
    kraken = records.get("kraken") or {}
    assert PAPER_WAVE_KRAKEN_BTC_USD in kraken, kraken.keys()
    wave = kraken[PAPER_WAVE_KRAKEN_BTC_USD]
    assert wave["canonical_pair"] == PAPER_WAVE_KRAKEN_BTC_USD
    assert wave["min_quantity"] == "0.0001"
    assert wave["min_notional"] == "0.5"
    assert any("AssetPairs" in url for _, url in transport.calls)

    tick_records = _tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == PAPER_WAVE_KRAKEN_BTC_USD]
    assert pair_records, "engine must journal a tick for the wave pair"
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") is None, detail


def test_paper_tick_wave_btc_usd_without_asset_pairs_still_refuses_missing_rules(home, fresh_keyring) -> None:
    """When public metadata cannot supply rules, refusal remains honest.

    An empty AssetPairs fake must not invent BTC minima; the tick still
    journals ``metadata_unavailable`` rather than silently evaluating.
    """
    from krellbot.cli import cmd_tick
    from krellbot.data.instruments import METADATA_UNAVAILABLE

    pack_path = _write_wave_pack(home, pack_id="paper-btc-missing")
    _arm_paper(home, pack_path)

    candles = _three_bar_entry_candles()

    def fetch(venue, pair, tf, transport):
        return list(candles)

    class _EmptyAssetPairs:
        def get(self, url, headers=None):
            if "AssetPairs" in str(url):
                return {"error": ["EQuery:Unknown asset pair"], "result": {}}
            return {"error": [], "result": {}}

        def post(self, url, form, headers):
            return {"error": [], "result": {}}

    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=_EmptyAssetPairs())
    assert rc == 0

    tick_records = _tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == PAPER_WAVE_KRAKEN_BTC_USD]
    assert pair_records
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") == METADATA_UNAVAILABLE, detail
    assert not (home / "run" / SNAPSHOT_FILENAME).exists()


def test_offline_candles_paper_tick_does_not_fetch_asset_pairs(home, fresh_keyring) -> None:
    """``--offline-candles`` must not contact public AssetPairs.

    Journey harnesses refuse off-loopback DNS; offline paper ticks therefore
    must not call ``ensure_instrument_rules`` / AssetPairs. SUIUSD still
    evaluates via the labeled ``default_rules`` fallback.
    """
    from krellbot.cli import cmd_tick

    pack_body = {
        "schema_version": 1,
        "id": "offline-sui",
        "version": "1.0.0",
        "label": "Offline SUI",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    pack_path = home / "offline-sui.json"
    pack_path.write_text(json.dumps(pack_body), encoding="utf-8")
    _arm_paper(home, pack_path)

    csv_path = home / "candles.csv"
    csv_path.write_text(
        "ts_ms,open,high,low,close,volume\n0,11,12,10,11,100\n3600000,10,11,9,10,100\n7200000,13,14,12,13,100\n",
        encoding="utf-8",
    )

    transport = _KrakenBtcAssetPairsTransport()

    def fetch(_venue, _pair, _tf, _transport):
        raise AssertionError("fetch must not run under --offline-candles")

    rc = cmd_tick(
        ["--venue", "kraken", "--offline-candles", str(csv_path)],
        fetch=fetch,
        transport=transport,
    )
    assert rc == 0
    assert transport.calls == [], f"offline tick must not hit AssetPairs; calls={transport.calls!r}"
    assert not (home / "run" / SNAPSHOT_FILENAME).exists()

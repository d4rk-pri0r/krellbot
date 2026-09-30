"""NS05 — verified multi-instrument paper rules.

The metadata client fetches per-venue/per-pair minimums and precision from
public endpoints only. No authenticated order call. Stale or malformed
metadata refuses new risk with a typed code; the persisted snapshot is
only usable in explicit offline mode.

All transports are scripted. Tests do not touch the real Kraken or Coinbase
endpoints. Labeled fixtures (`KRK-FIX-A`, `KRK-FIX-B`, `CBP-FIX-A`,
`CBP-FIX-B`) are synthetic-but-shaped; the contract states that
production symbols must not be invented to make a test pass.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

NS05_CLOCK = datetime(2026, 9, 28, 12, tzinfo=timezone.utc).timestamp()


@pytest.fixture(autouse=True)
def pin_metadata_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Read snapshots at 2026-09-28T12:00:00Z.

    The default fixture expires at 2026-09-29T00:00:00Z. Consumers that
    omit a clock use ``_default_now``. Pin that clock inside the fresh
    window. Tests that pass their own clock, including the stale-record
    refusal, keep that clock.
    """

    monkeypatch.setattr("krellbot.data.instruments._default_now", lambda: NS05_CLOCK)


from krellbot.data.instruments import (
    METADATA_INVALID,
    METADATA_STALE,
    METADATA_SYMBOL_MISMATCH,
    METADATA_UNAVAILABLE,
    InstrumentMetadataClient,
    InstrumentMetadataError,
    InstrumentRulesSnapshot,
    InstrumentRulesV1,
    OfflineModeRequired,
    derive_decimal_places,
    pairrules_from_instrument,
)

# ---- scripted transports ------------------------------------------------


class _ScriptedKrakenTransport:
    """Records every call; serves configured AssetPairs.

    `asset_pairs` maps response key to payload. When the queue is empty,
    the transport reports an unknown-pair error so an
    `unavailable` refusal can be exercised. When it is non-empty, the
    transport returns the entire map regardless of the queried pair, so
    a "publisher returned a different symbol than requested" scenario
    can be modeled for the symbol-mismatch test.
    """

    def __init__(self, *, asset_pairs: dict | None = None) -> None:
        self._asset_pairs = dict(asset_pairs or {})
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if "AssetPairs" in url:
            if not self._asset_pairs:
                return {"error": ["EQuery:Unknown asset pair"], "result": {}}
            return {"error": [], "result": dict(self._asset_pairs)}
        return {"error": [], "result": {}}

    def post(self, url, form, headers):
        self.calls.append(("POST", str(url)))
        return {"error": [], "result": {}}


class _ScriptedCoinbaseTransport:
    """Records every call; serves configured product payloads.

    Empty queue → 404-style refusal. Non-empty queue: when the URL
    matches `/products/<pair>`, the matching payload is returned. When
    the URL doesn't match any registered pair, the FIRST registered
    payload is returned, so the symbol-mismatch scenario (publisher
    returns the wrong product) can be modeled.
    """

    def __init__(self, *, products: dict | None = None) -> None:
        self._products = dict(products or {})
        self.calls: list[tuple[str, str]] = []

    def get(self, url, headers=None):
        self.calls.append(("GET", str(url)))
        if not self._products:
            return {"error": ["product not found"]}
        for pair, payload in self._products.items():
            if f"/products/{pair}" in url:
                return payload
        return next(iter(self._products.values()))

    def post(self, url, body, headers):
        self.calls.append(("POST", str(url)))
        return {}


def _query_value(url: str, key: str) -> str:
    marker = f"{key}="
    if marker not in url:
        return ""
    return url.split(marker, 1)[1].split("&", 1)[0]


# ---- fixture payloads (labeled; no production symbol) -------------------


KRAKEN_FIX_A_PAYLOAD = {
    "altname": "KRK-FIX-A",
    "wsname": "KRK/FIX/A",
    "base": "FIXA",
    "quote": "ZUSD",
    "ordermin": "5",
    "costmin": "0.5",
    "lot_decimals": 5,
    "pair_decimals": 4,
}

KRAKEN_FIX_B_PAYLOAD = {
    "altname": "KRK-FIX-B",
    "wsname": "KRK/FIX/B",
    "base": "FIXB",
    "quote": "ZUSD",
    "ordermin": "10",
    "costmin": "1.0",
    "lot_decimals": 4,
    "pair_decimals": 2,
}

COINBASE_FIX_A_PAYLOAD = {
    "product_id": "CBP-FIX-A",
    "base_currency_id": "FIXA",
    "quote_currency_id": "USD",
    "base_increment": "0.1",
    "quote_increment": "0.0001",
    "base_min_size": "5",
    "quote_min_size": "0.5",
}

COINBASE_FIX_B_PAYLOAD = {
    "product_id": "CBP-FIX-B",
    "base_currency_id": "FIXB",
    "quote_currency_id": "USD",
    "base_increment": "0.01",
    "quote_increment": "0.01",
    "base_min_size": "10",
    "quote_min_size": "1.0",
}


def _make_record(
    *,
    venue: str,
    canonical: str,
    venue_symbol: str | None = None,
    min_q: str = "5",
    min_n: str = "0.5",
    q_inc: str = "0.00001",
    p_inc: str = "0.0001",
    retrieved_at: str = "2026-09-28T00:00:00Z",
    usable_until: str = "2026-09-29T00:00:00Z",
    endpoint: str = "https://example.test/instruments",
    payload_sha: str = "deadbeef" * 8,
    source_version: str = "v1",
    base_asset: str = "BASE",
    quote_asset: str = "QUOTE",
) -> InstrumentRulesV1:
    return InstrumentRulesV1(
        schema_version="1",
        venue=venue,
        canonical_pair=canonical,
        venue_symbol=venue_symbol or canonical,
        base_asset=base_asset,
        quote_asset=quote_asset,
        min_quantity=min_q,
        min_notional=min_n,
        quantity_increment=q_inc,
        price_increment=p_inc,
        source={
            "endpoint": endpoint,
            "retrieved_at": retrieved_at,
            "source_version": source_version,
            "payload_sha256": payload_sha,
        },
        usable_until=usable_until,
    )


# ---- 1. two symbols on each venue normalize without float conversion -----


def test_kraken_two_symbols_normalize_without_float_conversion() -> None:
    """Two Kraken fixtures with different minima/precision normalize to
    distinct InstrumentRulesV1 records. Every numeric field is a Decimal
    string, never a float.
    """
    transport = _ScriptedKrakenTransport(
        asset_pairs={
            "KRK-FIX-A": KRAKEN_FIX_A_PAYLOAD,
            "KRK-FIX-B": KRAKEN_FIX_B_PAYLOAD,
        }
    )
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)

    record_a = client.fetch_rules("kraken", "KRK-FIX-A")
    record_b = client.fetch_rules("kraken", "KRK-FIX-B")

    # Decimal strings, never float.
    assert record_a.min_quantity == "5"
    assert record_a.min_notional == "0.5"
    assert record_a.quantity_increment == "0.00001"
    assert record_a.price_increment == "0.0001"
    assert record_b.min_quantity == "10"
    assert record_b.min_notional == "1.0"
    assert record_b.quantity_increment == "0.0001"
    assert record_b.price_increment == "0.01"

    for attr in ("min_quantity", "min_notional", "quantity_increment", "price_increment"):
        assert isinstance(getattr(record_a, attr), str), f"{attr} must be a string"
        assert isinstance(getattr(record_b, attr), str)

    # Distinct records; canonical_pair and venue_symbol are preserved.
    assert record_a.canonical_pair == "KRK-FIX-A"
    assert record_a.venue_symbol == "KRK-FIX-A"
    assert record_b.canonical_pair == "KRK-FIX-B"
    assert record_b.venue_symbol == "KRK-FIX-B"

    # Different rules, never the SUIUSD fallback.
    assert record_a.min_quantity != record_b.min_quantity
    assert Decimal(record_a.min_quantity) != Decimal(5) or record_b.canonical_pair != "SUIUSD"


def test_coinbase_two_symbols_normalize_without_float_conversion() -> None:
    transport = _ScriptedCoinbaseTransport(
        products={
            "CBP-FIX-A": COINBASE_FIX_A_PAYLOAD,
            "CBP-FIX-B": COINBASE_FIX_B_PAYLOAD,
        }
    )
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)

    record_a = client.fetch_rules("coinbase", "CBP-FIX-A")
    record_b = client.fetch_rules("coinbase", "CBP-FIX-B")

    assert record_a.min_quantity == "5"
    assert record_a.min_notional == "0.5"
    assert record_a.quantity_increment == "0.1"
    assert record_a.price_increment == "0.0001"
    assert record_b.min_quantity == "10"
    assert record_b.min_notional == "1.0"
    assert record_b.quantity_increment == "0.01"
    assert record_b.price_increment == "0.01"

    for attr in ("min_quantity", "min_notional", "quantity_increment", "price_increment"):
        assert isinstance(getattr(record_a, attr), str)


def test_record_carries_source_endpoint_retrieved_at_and_sha256() -> None:
    """Each record carries provenance: endpoint, retrieved_at, payload_sha256."""
    transport = _ScriptedKrakenTransport(asset_pairs={"KRK-FIX-A": KRAKEN_FIX_A_PAYLOAD})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    record = client.fetch_rules("kraken", "KRK-FIX-A")
    assert "AssetPairs" in record.source["endpoint"]
    assert record.source["retrieved_at"]
    assert len(record.source["payload_sha256"]) == 64
    # Reproducible from the raw payload bytes.
    assert all(c in "0123456789abcdef" for c in record.source["payload_sha256"])


# ---- 2. unknown / mismatched / malformed / stale refuse ----------------


def test_unknown_symbol_refuses_metadata_unavailable() -> None:
    transport = _ScriptedKrakenTransport(asset_pairs={})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        client.fetch_rules("kraken", "DOES-NOT-EXIST")
    assert excinfo.value.code == METADATA_UNAVAILABLE
    assert excinfo.value.venue == "kraken"
    assert excinfo.value.pair == "DOES-NOT-EXIST"


def test_coinbase_unknown_product_refuses_metadata_unavailable() -> None:
    transport = _ScriptedCoinbaseTransport(products={})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        client.fetch_rules("coinbase", "CBP-DOES-NOT-EXIST")
    assert excinfo.value.code == METADATA_UNAVAILABLE


def test_symbol_mismatch_refuses() -> None:
    """When the publisher's response carries a different symbol than the
    one requested (response key, altname, wsname, product_id), refuse.
    """
    transport = _ScriptedKrakenTransport(asset_pairs={"KRK-FIX-A": KRAKEN_FIX_A_PAYLOAD})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        client.fetch_rules("kraken", "KRK-FIX-DIFFERENT")
    assert excinfo.value.code == METADATA_SYMBOL_MISMATCH


def test_malformed_kraken_payload_refuses() -> None:
    transport = _ScriptedKrakenTransport(
        asset_pairs={"KRK-BAD": {"altname": "KRK-BAD"}}  # missing ordermin, costmin, decimals
    )
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        client.fetch_rules("kraken", "KRK-BAD")
    assert excinfo.value.code == METADATA_INVALID


def test_malformed_coinbase_payload_refuses() -> None:
    transport = _ScriptedCoinbaseTransport(
        products={"CBP-BAD": {"product_id": "CBP-BAD"}}  # missing increments/sizes
    )
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        client.fetch_rules("coinbase", "CBP-BAD")
    assert excinfo.value.code == METADATA_INVALID


def test_zero_or_negative_minimum_refuses_metadata_invalid() -> None:
    """Zero/negative minima are not valid instrument rules."""
    transport = _ScriptedKrakenTransport(
        asset_pairs={
            "KRK-FIX-A": {**KRAKEN_FIX_A_PAYLOAD, "ordermin": "0"},
        }
    )
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        client.fetch_rules("kraken", "KRK-FIX-A")
    assert excinfo.value.code == METADATA_INVALID


def test_stale_record_refuses_metadata_stale(home) -> None:
    """A record whose usable_until is in the past refuses with metadata_stale."""
    snap = InstrumentRulesSnapshot(home=home)
    stale = _make_record(
        venue="kraken",
        canonical="KRK-FIX-A",
        retrieved_at="2026-09-27T00:00:00Z",
        usable_until="2026-09-27T12:00:00Z",
    )
    snap.write({"kraken": {"KRK-FIX-A": stale}})

    # Now is later than the usable_until.
    now = _iso_to_unix("2026-09-28T00:00:00Z")
    snap2 = InstrumentRulesSnapshot(home=home, clock=lambda: now)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        snap2.read_pair("kraken", "KRK-FIX-A", offline=True)
    assert excinfo.value.code == METADATA_STALE


# ---- 3. snapshot offline behavior --------------------------------------


def test_snapshot_read_requires_offline_mode(home) -> None:
    snap = InstrumentRulesSnapshot(home=home)
    with pytest.raises(OfflineModeRequired):
        snap.read_pair("kraken", "KRK-FIX-A")


def test_snapshot_offline_cache_miss_refuses(home) -> None:
    snap = InstrumentRulesSnapshot(home=home)
    with pytest.raises(InstrumentMetadataError) as excinfo:
        snap.read_pair("kraken", "KRK-FIX-A", offline=True)
    assert excinfo.value.code == METADATA_UNAVAILABLE


def test_snapshot_offline_cache_hit_returns_record(home) -> None:
    snap = InstrumentRulesSnapshot(home=home)
    record = _make_record(venue="kraken", canonical="KRK-FIX-A")
    snap.write({"kraken": {"KRK-FIX-A": record}})

    snap2 = InstrumentRulesSnapshot(home=home)
    got = snap2.read_pair("kraken", "KRK-FIX-A", offline=True)
    assert got == record


def test_snapshot_restart_reloads_persisted_snapshot(home) -> None:
    """Restarting the snapshot instance re-loads records from disk."""
    snap1 = InstrumentRulesSnapshot(home=home)
    record = _make_record(venue="kraken", canonical="KRK-FIX-A")
    snap1.write({"kraken": {"KRK-FIX-A": record}})

    snap2 = InstrumentRulesSnapshot(home=home)
    got = snap2.read_pair("kraken", "KRK-FIX-A", offline=True)
    assert got == record


def test_snapshot_persists_multiple_pairs_per_venue(home) -> None:
    snap = InstrumentRulesSnapshot(home=home)
    rec_a = _make_record(venue="kraken", canonical="KRK-FIX-A")
    rec_b = _make_record(venue="kraken", canonical="KRK-FIX-B", min_q="10", min_n="1.0")
    snap.write({"kraken": {"KRK-FIX-A": rec_a, "KRK-FIX-B": rec_b}})

    snap2 = InstrumentRulesSnapshot(home=home)
    assert snap2.read_pair("kraken", "KRK-FIX-A", offline=True) == rec_a
    assert snap2.read_pair("kraken", "KRK-FIX-B", offline=True) == rec_b


def test_snapshot_persists_across_two_venues(home) -> None:
    snap = InstrumentRulesSnapshot(home=home)
    rec_k = _make_record(venue="kraken", canonical="KRK-FIX-A")
    rec_c = _make_record(venue="coinbase", canonical="CBP-FIX-A")
    snap.write({"kraken": {"KRK-FIX-A": rec_k}, "coinbase": {"CBP-FIX-A": rec_c}})

    snap2 = InstrumentRulesSnapshot(home=home)
    assert snap2.read_pair("kraken", "KRK-FIX-A", offline=True) == rec_k
    assert snap2.read_pair("coinbase", "CBP-FIX-A", offline=True) == rec_c


# ---- 4. transport log: only public GETs --------------------------------


def test_metadata_transport_log_has_only_public_gets_kraken() -> None:
    """The metadata client never POSTs and never hits private order URLs."""
    transport = _ScriptedKrakenTransport(asset_pairs={"KRK-FIX-A": KRAKEN_FIX_A_PAYLOAD})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    client.fetch_rules("kraken", "KRK-FIX-A")

    methods = {method for method, _ in transport.calls}
    assert methods == {"GET"}, f"only GET expected, got {methods}"

    for _, url in transport.calls:
        assert "/0/private/" not in url, f"no private endpoint expected, got {url}"
        assert "/AddOrder" not in url
        assert "/CancelOrder" not in url
        assert "/GetApiKeyInfo" not in url

    asset_pairs_calls = [url for _, url in transport.calls if "AssetPairs" in url]
    assert len(asset_pairs_calls) == 1


def test_metadata_transport_log_has_only_public_gets_coinbase() -> None:
    transport = _ScriptedCoinbaseTransport(products={"CBP-FIX-A": COINBASE_FIX_A_PAYLOAD})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    client.fetch_rules("coinbase", "CBP-FIX-A")

    methods = {method for method, _ in transport.calls}
    assert methods == {"GET"}, f"only GET expected, got {methods}"

    for _, url in transport.calls:
        assert "/api/v3/brokerage/orders" not in url
        assert "/key_permissions" not in url
        assert "/api/v3/brokerage/accounts" not in url

    market_products_calls = [url for _, url in transport.calls if "/market/products/" in url]
    assert len(market_products_calls) == 1


# ---- 5. None transport does not silently call the network ---------------


def test_metadata_client_requires_transport() -> None:
    """A None transport refuses to operate; no urllib call."""
    with pytest.raises((TypeError, ValueError)):
        InstrumentMetadataClient(transport=None)


def test_default_rules_keeps_suiusd_labeled_fixture() -> None:
    """The paper venue's `default_rules` SUIUSD fallback is unchanged: it
    returns the labeled fixture so the existing engine tests keep passing.
    A non-SUIUSD pair still raises; no rule for a different pair ever
    silently falls back to SUIUSD.
    """
    from krellbot.venues.paper import default_rules

    rules = default_rules("SUIUSD")
    assert rules.ordermin == Decimal(5)
    assert rules.costmin == Decimal("0.5")

    with pytest.raises(ValueError):
        default_rules("KRK-FIX-A")


# ---- 6. derivation helper preserves increments -------------------------


def test_derive_decimal_places_from_increments() -> None:
    assert derive_decimal_places("0.00001") == 5
    assert derive_decimal_places("0.0001") == 4
    assert derive_decimal_places("0.1") == 1
    assert derive_decimal_places("0.01") == 2
    assert derive_decimal_places("1") == 0


def test_pairrules_derives_decimals_from_increments() -> None:
    """pairrules_from_instrument derives lot_decimals and price_decimals."""
    record = _make_record(
        venue="coinbase",
        canonical="CBP-FIX-A",
        min_q="5",
        min_n="0.5",
        q_inc="0.1",
        p_inc="0.0001",
    )
    rules = pairrules_from_instrument(record)
    assert rules.ordermin == Decimal(5)
    assert rules.costmin == Decimal("0.5")
    assert rules.lot_decimals == 1
    assert rules.price_decimals == 4


# ---- 7. metadata client does not invent rounding policy ----------------


def test_metadata_client_returns_unmodified_publisher_values() -> None:
    """The metadata client returns raw publisher values; no rounding added.

    The existing venue adapter does its own quantization (see
    `_quantize_qty`/`_quantize_price` in `krellbot.venues.kraken` and
    `krellbot.venues.coinbase`). The metadata path must not introduce
    a second rounding layer.
    """
    transport = _ScriptedKrakenTransport(asset_pairs={"KRK-FIX-A": KRAKEN_FIX_A_PAYLOAD})
    client = InstrumentMetadataClient(transport=transport, clock=lambda: 1_700_000_000.0)
    record = client.fetch_rules("kraken", "KRK-FIX-A")
    # min_quantity matches the publisher's "5" exactly, not quantized further.
    assert record.min_quantity == "5"
    # quantity_increment is derived from lot_decimals=5 only; the publisher's
    # value was not normalized against min_quantity.
    assert record.quantity_increment == "0.00001"


def test_below_minimum_via_existing_paper_adapter(home) -> None:
    """Below-minimum orders are caught by the existing paper adapter.

    The metadata layer does not enforce minimums itself; the venue adapter
    does. With a rules provider that maps every pair to a PairRules with
    ordermin=5, a qty=1 entry must raise ValueError ("qty below ordermin").
    """
    from krellbot.venues.base import PairRules
    from krellbot.venues.paper import PaperVenue

    rules = PairRules(
        ordermin=Decimal(5),
        costmin=Decimal("0.5"),
        lot_decimals=5,
        price_decimals=4,
    )
    venue = PaperVenue(
        "kraken",
        rules_provider=lambda _pair: rules,
        candle_reader=lambda _v, _p: [],
        home=home,
    )
    with pytest.raises(ValueError, match="ordermin"):
        venue.place_entry_with_stop("coid-x", Decimal(1), Decimal(1), pair="KRK-FIX-A")


# ---- 8. paper tick wiring uses verified snapshot rules ----------------
#
# A verified snapshot for the requested pair must win over the SUIUSD
# labeled fixture. The two cmd_tick sites that build PaperVenue use the
# same rules provider closure, which:
#   1. wins on snapshot for the requested pair,
#   2. falls back to default_rules('SUIUSD') for SUIUSD only,
#   3. refuses with metadata_unavailable for every other pair without a
#      snapshot.
#
# run.tick must skip a new entry on metadata refusal while letting an
# already-owned position's protective stop still be placed — the rules()
# call sits BELOW the ensure-stop branch in run.tick, so the snapshot
# path must not disable ownership protection.
#
# The non-SUI pair is named ``FIXUSD`` so the engine's pair-parsing helper
# (which infers ``base``/``quote`` by stripping a trailing USD suffix) lands
# the cash lookup on the actual USD balance that paper venue seeded.


def _write_krk_pack(home: Path, *, pair: str, pack_id: str = "ns05-krk") -> Path:
    """A runnable DSL pack on Kraken for `pair` that fires an entry on the
    third candle (crosses_above sma2). Mirrors `tests/test_tick_candles.py`.
    """
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "NS05 verified rules",
        "author": "krellbot ns05 tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_via_service(home: Path, pack_path: Path, *, paper_balance: Decimal = Decimal(1000)) -> None:
    from krellbot.application.paper import PaperService

    service = PaperService(home=home)
    result = service.arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=paper_balance,
        correlation_id=f"arm-{pack_path.stem}",
    )
    assert result.ok, (result.code, result.message)


def _capture_tick_journal_records(home: Path) -> list[dict]:
    """Read every JSONL tick record under `<home>/journal`."""
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


class _SilentTransport:
    def get(self, url, headers=None):
        return {"error": [], "result": {}}

    def post(self, url, form, headers):
        return {"error": [], "result": {}}


def _three_bar_entry_candles() -> list:
    """Three candles that fire ``crosses_above sma2``: 11 / 10 / 13."""
    from krellbot.pack.model import Candle

    hour = 3_600_000
    return [
        Candle(0 * hour, Decimal(11), Decimal(12), Decimal(10), Decimal(11), Decimal(100)),
        Candle(1 * hour, Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(100)),
        Candle(2 * hour, Decimal(13), Decimal(14), Decimal(12), Decimal(13), Decimal(100)),
    ]


def test_paper_tick_uses_verified_snapshot_for_non_sui_pair(home, fresh_keyring) -> None:
    """Ticking a non-SUI pair with a verified snapshot uses that pair's
    rules. Pre-fix, the cli.py paper factory passed
    ``rules_provider=lambda _p: default_rules(_p)`` which raises
    ``ValueError`` for any non-SUI pair; the engine never reaches the
    entry decision because ``venue_obj.rules(pair)`` propagates that
    ValueError out of run.tick. With the snapshot wired in, the engine
    uses the snapshot-derived ``PairRules`` and places an entry fill.
    """
    from krellbot.cli import cmd_tick

    snap = InstrumentRulesSnapshot(home=home)
    record = _make_record(
        venue="kraken",
        canonical="FIXUSD",
        min_q="0.01",
        min_n="0.5",
        q_inc="0.001",
        p_inc="0.01",
    )
    snap.write({"kraken": {"FIXUSD": record}})

    pack_path = _write_krk_pack(home, pair="FIXUSD", pack_id="ns05-tick-a")
    _arm_via_service(home, pack_path)

    candles = _three_bar_entry_candles()

    def fetch(venue, pair, tf, transport):
        return list(candles)

    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=_SilentTransport())
    assert rc == 0, rc

    paper_state = home / "run" / "paper-kraken.json"
    assert paper_state.exists(), "expected paper venue to persist its state"
    body = json.loads(paper_state.read_text(encoding="utf-8"))
    entries = [f for f in body.get("recent_fills", []) if f.get("side") == "buy"]
    assert entries, (
        f"expected an entry fill; the rules provider must have used the verified snapshot, "
        f"not the SUIUSD fixture (which would raise ValueError for FIXUSD). fills={body.get('recent_fills')!r}"
    )

    tick_records = _capture_tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == "FIXUSD"]
    assert pair_records, "engine must journal a tick record for the armed pack"
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") is None, detail
    assert detail.get("entry_qty") not in ("0", "0.0"), detail


def test_paper_tick_refuses_entry_when_no_snapshot_for_non_sui_pair(home, fresh_keyring) -> None:
    """A non-SUI pair with no verified snapshot must refuse new entries
    with a stable refusal code. Without the wiring, ``default_rules``
    raises ``ValueError`` for any pair other than SUIUSD and the tick
    crashes out non-zero with no journal record. With the wiring, the
    closure raises ``InstrumentMetadataError`` which run.tick catches and
    surfaces in the tick record as ``metadata_refusal``.
    """
    from krellbot.cli import cmd_tick

    pack_path = _write_krk_pack(home, pair="FIXUSD", pack_id="ns05-tick-b")
    _arm_via_service(home, pack_path)

    candles = _three_bar_entry_candles()

    def fetch(venue, pair, tf, transport):
        return list(candles)

    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=_SilentTransport())
    assert rc == 0

    tick_records = _capture_tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == "FIXUSD"]
    assert pair_records, "engine must still journal a tick record on metadata refusal"
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") == METADATA_UNAVAILABLE, detail
    assert detail.get("entry_qty") in ("0", "0.0"), detail

    paper_state = home / "run" / "paper-kraken.json"
    if paper_state.exists():
        body = json.loads(paper_state.read_text(encoding="utf-8"))
        assert not [f for f in body.get("recent_fills", []) if f.get("side") == "buy" and f.get("pair") == "FIXUSD"], (
            "metadata refusal must not place an entry fill"
        )


def test_paper_tick_protective_stop_still_runs_when_metadata_refuses_entry(home, fresh_keyring) -> None:
    """The rules() call lives below the ensure-stop branch in run.tick,
    so a metadata refusal on a fresh entry must NOT block the protective
    stop on an already-owned position. Seed an owned qty for a non-SUI
    pair (no snapshot), tick, and prove both the refusal AND the stop
    order landed.
    """
    from krellbot import journal as kb_journal
    from krellbot.cli import cmd_tick
    from krellbot.config import load_config, save_config

    pack_path = _write_krk_pack(home, pair="FIXUSD", pack_id="ns05-tick-c")
    _arm_via_service(home, pack_path)

    kb_journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "ns05-tick-c",
            "bar_ts": 1,
            "detail": {"pair": "FIXUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )
    config = load_config(home)
    for armed in config.armed:
        if armed.venue == "kraken":
            armed.owned_qty = Decimal(5)
    save_config(home, config)

    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    paper_state = run_dir / "paper-kraken.json"
    paper_state.write_text(
        json.dumps(
            {
                "venue": "kraken",
                "balances": {"USD": "1000", "FIX": "5"},
                "open_orders": [],
                "recent_fills": [],
                "seeded": True,
            }
        ),
        encoding="utf-8",
    )

    candles = _three_bar_entry_candles()

    def fetch(venue, pair, tf, transport):
        return list(candles)

    rc = cmd_tick(["--venue", "kraken"], fetch=fetch, transport=_SilentTransport())
    assert rc == 0

    assert paper_state.exists()
    body = json.loads(paper_state.read_text(encoding="utf-8"))
    stops = [o for o in body.get("open_orders", []) if o.get("pair") == "FIXUSD" and o.get("stop_price") is not None]
    assert stops, (
        "owned-position protection must run even when metadata refuses the new entry; "
        f"open_orders={body.get('open_orders')!r}"
    )

    tick_records = _capture_tick_journal_records(home)
    pair_records = [r for r in tick_records if (r.get("detail") or {}).get("pair") == "FIXUSD"]
    detail = pair_records[-1].get("detail") or {}
    assert detail.get("metadata_refusal") == METADATA_UNAVAILABLE, detail
    assert detail.get("entry_qty") in ("0", "0.0"), detail
    assert detail.get("ensure_stop_failed") is False, detail


# ---- helpers ------------------------------------------------------------


def _iso_to_unix(iso: str) -> float:
    """Convert an ISO-8601 UTC timestamp (with optional trailing Z) to a
    Unix timestamp float. Matches the kind of clock the metadata client
    and snapshot accept in tests.
    """
    return time.mktime(time.strptime(iso, "%Y-%m-%dT%H:%M:%SZ"))

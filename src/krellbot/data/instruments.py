"""Verified per-venue/per-pair instrument rules (public metadata only).

This module is the metadata layer the paper venue consults to load trading
rules for one (venue, pair). It reaches public, unauthenticated endpoints
only — Kraken `AssetPairs`, the Coinbase Advanced public product,
Binance spot `exchangeInfo`, Gate spot currency pairs, Pionex spot
symbols, and OKX public instruments. It never
POSTs, never hits a private/order endpoint, and never imports a
venue-specific auth path. A `None`
transport refuses to operate instead of silently falling through to
`urllib`.

Provenance (`endpoint`, `retrieved_at`, `source_version`, `payload_sha256`)
is recorded on every record so a downstream consumer can see the source
and age. Records carry Decimal-string increments as authoritative; the
existing `PairRules` adapter shape is preserved unchanged by deriving the
lot/price decimal-place counts from the increments via
`pairrules_from_instrument`.

The persisted snapshot at `$KRELLBOT_HOME/run/instrument-rules.json` is
only readable in explicit offline mode. Without `offline=True`, the
snapshot refuses; a public endpoint must be used instead. A missing
record refuses with `metadata_unavailable`; a record whose `usable_until`
is in the past refuses with `metadata_stale`. A persisted snapshot is a
labeled cache, not production truth.

Production paper ticks call `ensure_instrument_rules` before evaluating
entries so armed pairs (including the wave Kraken BTC/USD spelling
``XXBTZUSD``, the wave Coinbase BTC/USD product ``BTC-USD``, the wave
Binance BTC/USDT symbol ``BTCUSDT``, and the wave Gate pack pair
``BTC-USDT``) are fetched from public AssetPairs / product /
exchangeInfo / currency-pair metadata and written into that
snapshot. Without that write, a non-SUI paper arm journals
``metadata_refusal`` for missing rules forever.

Stable refusal codes:

    metadata_unavailable, metadata_stale, metadata_symbol_mismatch,
    metadata_invalid, minimum_not_met.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
import urllib.parse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from krellbot import paths as kb_paths
from krellbot.venues.base import PairRules

# Wave Kraken BTC/USD spelling used by the owned-strategy paper arm default
# (`frontend` `DEFAULT_PAIR`). AssetPairs also accepts altname ``XBTUSD``.
PAPER_WAVE_KRAKEN_BTC_USD = "XXBTZUSD"

# Wave Coinbase BTC/USD product id for the Coinbase paper-arm path (M11.2).
# Advanced Trade public product metadata uses this exact ``product_id``.
PAPER_WAVE_COINBASE_BTC_USD = "BTC-USD"

# Wave Binance BTC/USDT symbol for the Binance paper-arm path (M14.3 / M14.4).
# Spot exchangeInfo uses this exact concatenated ``symbol`` spelling.
PAPER_WAVE_BINANCE_BTC_USDT = "BTCUSDT"

# Wave Gate BTC/USDT pack pair. Gate's currency pair is ``BTC_USDT``.
PAPER_WAVE_GATE_BTC_USDT = "BTC-USDT"
PAPER_WAVE_PIONEX_BTC_USDT = "BTC-USDT"
# Wave OKX BTC/USDT instId for the OKX paper-arm path.
# Public instruments use this exact ``instId`` spelling.
PAPER_WAVE_OKX_BTC_USDT = "BTC-USDT"

SCHEMA_VERSION = "1"
DEFAULT_TTL_SECONDS = 24 * 60 * 60  # 24h

# Stable refusal codes from the instrument contract.
METADATA_UNAVAILABLE = "metadata_unavailable"
METADATA_STALE = "metadata_stale"
METADATA_SYMBOL_MISMATCH = "metadata_symbol_mismatch"
METADATA_INVALID = "metadata_invalid"
MINIMUM_NOT_MET = "minimum_not_met"

REFUSAL_CODES = frozenset(
    {
        METADATA_UNAVAILABLE,
        METADATA_STALE,
        METADATA_SYMBOL_MISMATCH,
        METADATA_INVALID,
        MINIMUM_NOT_MET,
    }
)

# Publisher endpoints. Documented in NS05 report.md.
KRAKEN_ASSET_PAIRS_URL = "https://api.kraken.com/0/public/AssetPairs"
COINBASE_PRODUCT_URL = "https://api.coinbase.com/api/v3/brokerage/market/products"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
GATE_CURRENCY_PAIR_URL = "https://api.gateio.ws/api/v4/spot/currency_pairs"
PIONEX_SYMBOLS_URL = "https://api.pionex.com/api/v1/common/symbols"
OKX_INSTRUMENTS_URL = "https://www.okx.com/api/v5/public/instruments"
# OKX public instruments omit a quote minimum. Paper pins 1 quote unit.
OKX_PAPER_MIN_NOTIONAL = "1"

SNAPSHOT_FILENAME = "instrument-rules.json"


# ---- errors ------------------------------------------------------------


class InstrumentMetadataError(RuntimeError):
    """One of the five stable refusal codes from the instrument contract.

    `code` is one of `METADATA_UNAVAILABLE`, `METADATA_STALE`,
    `METADATA_SYMBOL_MISMATCH`, `METADATA_INVALID`, `MINIMUM_NOT_MET`.
    `venue` and `pair` identify the failing record so callers can route
    on the code without parsing the message text.
    """

    def __init__(self, code: str, venue: str, pair: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.venue = venue
        self.pair = pair


class OfflineModeRequired(RuntimeError):
    """Raised when the snapshot is read without explicit offline=True."""


# ---- record ------------------------------------------------------------


@dataclass(frozen=True)
class InstrumentRulesV1:
    """A verified instrument record per the contract.

    Decimal strings are authoritative. `usable_until` is an ISO-8601 UTC
    timestamp; the snapshot refuses reads past that time. `source` is a
    dict with exactly four non-empty keys: `endpoint`, `retrieved_at`,
    `source_version`, `payload_sha256`.
    """

    schema_version: str
    venue: str
    canonical_pair: str
    venue_symbol: str
    base_asset: str
    quote_asset: str
    min_quantity: str
    min_notional: str
    quantity_increment: str
    price_increment: str
    source: dict
    usable_until: str

    def __post_init__(self) -> None:  # type: ignore[no-untyped-def]
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"instrument: unsupported schema_version {self.schema_version!r}")
        for name in ("min_quantity", "min_notional", "quantity_increment", "price_increment"):
            value = getattr(self, name)
            try:
                d = Decimal(value)
            except Exception as exc:
                raise ValueError(f"instrument: {name} is not a valid Decimal: {value!r}") from exc
            if not d.is_finite() or d <= 0:
                raise ValueError(f"instrument: {name} must be a positive finite Decimal, got {value!r}")
        if not isinstance(self.source, dict):
            raise TypeError("instrument: source must be a dict")
        for key in ("endpoint", "retrieved_at", "source_version", "payload_sha256"):
            if key not in self.source:
                raise ValueError(f"instrument: source is missing {key!r}")
            if not isinstance(self.source[key], str) or not self.source[key]:
                raise ValueError(f"instrument: source.{key} must be a non-empty string")
        if len(self.source["payload_sha256"]) != 64:
            raise ValueError("instrument: source.payload_sha256 must be a 64-char hex digest")
        if not isinstance(self.usable_until, str) or not self.usable_until:
            raise ValueError("instrument: usable_until must be a non-empty ISO-8601 UTC string")
        if not isinstance(self.canonical_pair, str) or not self.canonical_pair:
            raise ValueError("instrument: canonical_pair must be a non-empty string")
        if not isinstance(self.venue_symbol, str) or not self.venue_symbol:
            raise ValueError("instrument: venue_symbol must be a non-empty string")
        if self.venue not in ("kraken", "coinbase", "binance", "gate", "pionex", "okx"):
            raise ValueError(f"instrument: unsupported venue {self.venue!r}")


# ---- transport ----------------------------------------------------------


class Transport:
    """Anything with `get(url)` returning a parsed JSON dict.

    Implementations must NOT require authentication. The metadata client
    only uses this surface; the venue adapters' private/order endpoints
    are never reached from this module.
    """

    def get(self, url: str, headers: dict[str, str] | None = None) -> dict: ...


# ---- client ------------------------------------------------------------


class InstrumentMetadataClient:
    """Fetch per-venue/per-pair instrument rules from public metadata.

    The transport is mandatory; passing `None` raises immediately rather
    than silently falling through to `urllib`. The client never POSTs and
    never hits private/order endpoints.
    """

    def __init__(
        self,
        transport: Transport,
        *,
        clock: Callable[[], float] | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> None:
        if transport is None:
            raise ValueError("instrument: transport is required; None must not silently call the network")
        self._transport = transport
        self._clock = clock or _default_now
        self._ttl_seconds = int(ttl_seconds)

    def fetch_rules(self, venue: str, canonical_pair: str) -> InstrumentRulesV1:
        """Fetch and normalize one (venue, pair) record.

        Returns an `InstrumentRulesV1`. Raises `InstrumentMetadataError`
        with one of the five stable refusal codes on failure.
        """
        if not isinstance(venue, str) or not venue:
            raise ValueError("instrument: venue must be a non-empty string")
        if not isinstance(canonical_pair, str) or not canonical_pair:
            raise ValueError("instrument: canonical_pair must be a non-empty string")
        if venue == "kraken":
            return self._fetch_kraken(canonical_pair)
        if venue == "coinbase":
            return self._fetch_coinbase(canonical_pair)
        if venue == "binance":
            return self._fetch_binance(canonical_pair)
        if venue == "gate":
            return self._fetch_gate(canonical_pair)
        if venue == "pionex":
            return self._fetch_pionex(canonical_pair)
        if venue == "okx":
            return self._fetch_okx(canonical_pair)
        raise InstrumentMetadataError(
            METADATA_UNAVAILABLE,
            venue,
            canonical_pair,
            f"instrument: unsupported venue {venue!r}",
        )

    # ---- internal: Kraken ----------------------------------------------

    def _fetch_kraken(self, canonical_pair: str) -> InstrumentRulesV1:
        url = f"{KRAKEN_ASSET_PAIRS_URL}?pair={urllib.parse.quote(canonical_pair)}"
        payload = self._transport.get(url, {}) or {}
        if not isinstance(payload, dict):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "kraken",
                canonical_pair,
                "instrument: kraken AssetPairs body is not a JSON object",
            )
        errs = payload.get("error")
        if isinstance(errs, list) and errs:
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "kraken",
                canonical_pair,
                "instrument: kraken AssetPairs refused the request",
            )
        result = payload.get("result")
        if not isinstance(result, dict) or not result:
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "kraken",
                canonical_pair,
                "instrument: kraken AssetPairs returned no pair data",
            )

        row, response_key = _find_kraken_row(result, canonical_pair)
        if row is None:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "kraken",
                canonical_pair,
                "instrument: kraken AssetPairs response did not contain the requested pair",
            )

        # Re-verify the matched row's identity matches what we asked for.
        altname = str(row.get("altname", ""))
        wsname = str(row.get("wsname", ""))
        if not _kraken_symbol_matches(response_key, altname, wsname, canonical_pair):
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "kraken",
                canonical_pair,
                "instrument: kraken AssetPairs returned a different symbol than requested",
            )

        try:
            ordermin = _required_decimal_string(row, "ordermin")
            costmin = _required_decimal_string(row, "costmin")
            lot_decimals = int(row["lot_decimals"])
            pair_decimals = int(row["pair_decimals"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "kraken",
                canonical_pair,
                "instrument: kraken AssetPairs payload missing required fields",
            ) from exc

        if Decimal(ordermin) <= 0 or Decimal(costmin) <= 0:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "kraken",
                canonical_pair,
                "instrument: kraken minima must be positive",
            )

        base_asset = str(row.get("base", ""))
        quote_asset = str(row.get("quote", ""))

        retrieved_at = _unix_to_iso(self._clock())
        usable_until = _unix_to_iso(self._clock() + self._ttl_seconds)
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

        return InstrumentRulesV1(
            schema_version=SCHEMA_VERSION,
            venue="kraken",
            canonical_pair=canonical_pair,
            venue_symbol=response_key or canonical_pair,
            base_asset=base_asset,
            quote_asset=quote_asset,
            min_quantity=ordermin,
            min_notional=costmin,
            quantity_increment=_decimals_to_increment(lot_decimals),
            price_increment=_decimals_to_increment(pair_decimals),
            source={
                "endpoint": KRAKEN_ASSET_PAIRS_URL,
                "retrieved_at": retrieved_at,
                "source_version": payload_sha256[:16],
                "payload_sha256": payload_sha256,
            },
            usable_until=usable_until,
        )

    # ---- internal: Coinbase -------------------------------------------

    def _fetch_coinbase(self, canonical_pair: str) -> InstrumentRulesV1:
        url = f"{COINBASE_PRODUCT_URL}/{urllib.parse.quote(canonical_pair)}"
        payload = self._transport.get(url, {}) or {}
        if not isinstance(payload, dict):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "coinbase",
                canonical_pair,
                "instrument: coinbase product body is not a JSON object",
            )
        if payload.get("error") or payload.get("message"):
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "coinbase",
                canonical_pair,
                "instrument: coinbase product endpoint refused the request",
            )
        product_id = str(payload.get("product_id", ""))
        if product_id != canonical_pair:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "coinbase",
                canonical_pair,
                "instrument: coinbase product response did not match the requested pair",
            )
        try:
            base_min_size = _required_decimal_string(payload, "base_min_size")
            quote_min_size = _required_decimal_string(payload, "quote_min_size")
            base_increment = _required_decimal_string(payload, "base_increment")
            quote_increment = _required_decimal_string(payload, "quote_increment")
        except KeyError as exc:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "coinbase",
                canonical_pair,
                "instrument: coinbase product payload missing required fields",
            ) from exc

        if (
            Decimal(base_min_size) <= 0
            or Decimal(quote_min_size) <= 0
            or Decimal(base_increment) <= 0
            or Decimal(quote_increment) <= 0
        ):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "coinbase",
                canonical_pair,
                "instrument: coinbase minima and increments must be positive",
            )

        base_asset = str(payload.get("base_currency_id", "") or payload.get("base_currency", ""))
        quote_asset = str(payload.get("quote_currency_id", "") or payload.get("quote_currency", ""))

        retrieved_at = _unix_to_iso(self._clock())
        usable_until = _unix_to_iso(self._clock() + self._ttl_seconds)
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

        return InstrumentRulesV1(
            schema_version=SCHEMA_VERSION,
            venue="coinbase",
            canonical_pair=canonical_pair,
            venue_symbol=product_id,
            base_asset=base_asset,
            quote_asset=quote_asset,
            min_quantity=base_min_size,
            min_notional=quote_min_size,
            quantity_increment=base_increment,
            price_increment=quote_increment,
            source={
                "endpoint": COINBASE_PRODUCT_URL,
                "retrieved_at": retrieved_at,
                "source_version": payload_sha256[:16],
                "payload_sha256": payload_sha256,
            },
            usable_until=usable_until,
        )

    # ---- internal: Binance ---------------------------------------------

    def _fetch_binance(self, canonical_pair: str) -> InstrumentRulesV1:
        url = f"{BINANCE_EXCHANGE_INFO_URL}?symbol={urllib.parse.quote(canonical_pair)}"
        payload = self._transport.get(url, {}) or {}
        if not isinstance(payload, dict):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "binance",
                canonical_pair,
                "instrument: binance exchangeInfo body is not a JSON object",
            )
        # Binance error bodies use numeric ``code`` plus ``msg``.
        if payload.get("code") not in (None, 0, "0"):
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "binance",
                canonical_pair,
                "instrument: binance exchangeInfo refused the request",
            )

        symbol_row = _find_binance_symbol(payload, canonical_pair)
        if symbol_row is None:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "binance",
                canonical_pair,
                "instrument: binance exchangeInfo response did not contain the requested symbol",
            )
        venue_symbol = str(symbol_row.get("symbol") or "")
        if venue_symbol != canonical_pair:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "binance",
                canonical_pair,
                "instrument: binance exchangeInfo returned a different symbol than requested",
            )

        filters = symbol_row.get("filters") if isinstance(symbol_row.get("filters"), list) else []
        lot = _binance_filter(filters, "LOT_SIZE")
        price = _binance_filter(filters, "PRICE_FILTER")
        notional = _binance_filter(filters, "NOTIONAL") or _binance_filter(filters, "MIN_NOTIONAL")
        if lot is None or price is None:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "binance",
                canonical_pair,
                "instrument: binance exchangeInfo missing LOT_SIZE or PRICE_FILTER",
            )
        try:
            min_quantity = _required_decimal_string(lot, "minQty")
            quantity_increment = _required_decimal_string(lot, "stepSize")
            price_increment = _required_decimal_string(price, "tickSize")
            if notional is None:
                raise KeyError("minNotional")
            min_notional = _required_decimal_string(notional, "minNotional")
        except (KeyError, ValueError) as exc:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "binance",
                canonical_pair,
                "instrument: binance exchangeInfo payload missing required fields",
            ) from exc

        if (
            Decimal(min_quantity) <= 0
            or Decimal(min_notional) <= 0
            or Decimal(quantity_increment) <= 0
            or Decimal(price_increment) <= 0
        ):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "binance",
                canonical_pair,
                "instrument: binance minima and increments must be positive",
            )

        base_asset = str(symbol_row.get("baseAsset") or "")
        quote_asset = str(symbol_row.get("quoteAsset") or "")

        retrieved_at = _unix_to_iso(self._clock())
        usable_until = _unix_to_iso(self._clock() + self._ttl_seconds)
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

        return InstrumentRulesV1(
            schema_version=SCHEMA_VERSION,
            venue="binance",
            canonical_pair=canonical_pair,
            venue_symbol=venue_symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            min_quantity=min_quantity,
            min_notional=min_notional,
            quantity_increment=quantity_increment,
            price_increment=price_increment,
            source={
                "endpoint": BINANCE_EXCHANGE_INFO_URL,
                "retrieved_at": retrieved_at,
                "source_version": payload_sha256[:16],
                "payload_sha256": payload_sha256,
            },
            usable_until=usable_until,
        )

    # ---- internal: Gate ------------------------------------------------

    def _fetch_gate(self, canonical_pair: str) -> InstrumentRulesV1:
        symbol = canonical_pair.replace("-", "_") if "_" not in canonical_pair else canonical_pair
        url = f"{GATE_CURRENCY_PAIR_URL}/{urllib.parse.quote(symbol)}"
        payload = self._transport.get(url, {}) or {}
        if not isinstance(payload, dict):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "gate",
                canonical_pair,
                "instrument: gate currency pair body is not a JSON object",
            )
        if payload.get("label"):
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "gate",
                canonical_pair,
                "instrument: gate currency pair refused the request",
            )
        venue_symbol = str(payload.get("id") or "")
        if venue_symbol != symbol:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "gate",
                canonical_pair,
                "instrument: gate currency pair returned a different id than requested",
            )
        try:
            min_quantity = _required_decimal_string(payload, "min_base_amount")
            min_notional = _required_decimal_string(payload, "min_quote_amount")
            amount_precision = int(payload["amount_precision"])
            price_precision = int(payload["precision"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "gate",
                canonical_pair,
                "instrument: gate currency pair payload missing required fields",
            ) from exc
        quantity_increment = _decimals_to_increment(amount_precision)
        price_increment = _decimals_to_increment(price_precision)
        if (
            Decimal(min_quantity) <= 0
            or Decimal(min_notional) <= 0
            or Decimal(quantity_increment) <= 0
            or Decimal(price_increment) <= 0
        ):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "gate",
                canonical_pair,
                "instrument: gate minima and increments must be positive",
            )
        base_asset = str(payload.get("base") or "")
        quote_asset = str(payload.get("quote") or "")
        if not base_asset or not quote_asset:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "gate",
                canonical_pair,
                "instrument: gate currency pair missing base or quote",
            )
        retrieved_at = _unix_to_iso(self._clock())
        usable_until = _unix_to_iso(self._clock() + self._ttl_seconds)
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        return InstrumentRulesV1(
            schema_version=SCHEMA_VERSION,
            venue="gate",
            canonical_pair=canonical_pair,
            venue_symbol=venue_symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            min_quantity=min_quantity,
            min_notional=min_notional,
            quantity_increment=quantity_increment,
            price_increment=price_increment,
            source={
                "endpoint": GATE_CURRENCY_PAIR_URL,
                "retrieved_at": retrieved_at,
                "source_version": payload_sha256[:16],
                "payload_sha256": payload_sha256,
            },
            usable_until=usable_until,
        )

    # ---- internal: Pionex ---------------------------------------------

    def _fetch_pionex(self, canonical_pair: str) -> InstrumentRulesV1:
        symbol = canonical_pair.replace("-", "_") if "_" not in canonical_pair else canonical_pair
        query = urllib.parse.urlencode({"symbols": symbol, "type": "SPOT"})
        url = f"{PIONEX_SYMBOLS_URL}?{query}"
        payload = self._transport.get(url, {}) or {}
        if not isinstance(payload, dict):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "pionex",
                canonical_pair,
                "instrument: pionex symbols body is not a JSON object",
            )
        if payload.get("result") is False or payload.get("code"):
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "pionex",
                canonical_pair,
                "instrument: pionex symbols refused the request",
            )
        data = payload.get("data")
        rows = data.get("symbols") if isinstance(data, dict) else None
        row = None
        if isinstance(rows, list):
            for item in rows:
                if isinstance(item, dict) and str(item.get("symbol") or "") == symbol:
                    row = item
                    break
        if row is None:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "pionex",
                canonical_pair,
                "instrument: pionex symbols returned a different symbol than requested",
            )
        if row.get("enable") is False:
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "pionex",
                canonical_pair,
                "instrument: pionex symbol is not enabled for spot",
            )
        try:
            min_quantity = _required_decimal_string(row, "minTradeSize")
            min_notional = _required_decimal_string(row, "minAmount")
            price_precision = int(row["quotePrecision"])
            exponent = Decimal(min_quantity).normalize().as_tuple().exponent
            lot_places = -exponent if isinstance(exponent, int) and exponent < 0 else 0
        except (KeyError, TypeError, ValueError) as exc:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "pionex",
                canonical_pair,
                "instrument: pionex symbol payload missing required fields",
            ) from exc
        quantity_increment = _decimals_to_increment(lot_places)
        price_increment = _decimals_to_increment(price_precision)
        if (
            Decimal(min_quantity) <= 0
            or Decimal(min_notional) <= 0
            or Decimal(quantity_increment) <= 0
            or Decimal(price_increment) <= 0
        ):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "pionex",
                canonical_pair,
                "instrument: pionex minima and increments must be positive",
            )
        base_asset = str(row.get("baseCurrency") or "")
        quote_asset = str(row.get("quoteCurrency") or "")
        if not base_asset or not quote_asset:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "pionex",
                canonical_pair,
                "instrument: pionex symbol missing base or quote",
            )
        retrieved_at = _unix_to_iso(self._clock())
        usable_until = _unix_to_iso(self._clock() + self._ttl_seconds)
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        return InstrumentRulesV1(
            schema_version=SCHEMA_VERSION,
            venue="pionex",
            canonical_pair=canonical_pair,
            venue_symbol=symbol,
            base_asset=base_asset,
            quote_asset=quote_asset,
            min_quantity=min_quantity,
            min_notional=min_notional,
            quantity_increment=quantity_increment,
            price_increment=price_increment,
            source={
                "endpoint": PIONEX_SYMBOLS_URL,
                "retrieved_at": retrieved_at,
                "source_version": payload_sha256[:16],
                "payload_sha256": payload_sha256,
            },
            usable_until=usable_until,
        )

    # ---- internal: OKX -------------------------------------------------

    def _fetch_okx(self, canonical_pair: str) -> InstrumentRulesV1:
        query = urllib.parse.urlencode({"instType": "SPOT", "instId": canonical_pair})
        url = f"{OKX_INSTRUMENTS_URL}?{query}"
        payload = self._transport.get(url, {}) or {}
        if not isinstance(payload, dict):
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "okx",
                canonical_pair,
                "instrument: okx instruments body is not a JSON object",
            )
        if str(payload.get("code") or "") not in {"", "0"}:
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                "okx",
                canonical_pair,
                "instrument: okx instruments refused the request",
            )
        row = _find_okx_instrument(payload, canonical_pair)
        if row is None:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "okx",
                canonical_pair,
                "instrument: okx instruments response did not contain the requested instId",
            )
        venue_symbol = str(row.get("instId") or "")
        if venue_symbol != canonical_pair:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                "okx",
                canonical_pair,
                "instrument: okx instruments returned a different instId than requested",
            )
        try:
            min_quantity = _required_decimal_string(row, "minSz")
            quantity_increment = _required_decimal_string(row, "lotSz")
            price_increment = _required_decimal_string(row, "tickSz")
        except (KeyError, ValueError) as exc:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "okx",
                canonical_pair,
                "instrument: okx instruments payload missing required fields",
            ) from exc
        if Decimal(min_quantity) <= 0 or Decimal(quantity_increment) <= 0 or Decimal(price_increment) <= 0:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                "okx",
                canonical_pair,
                "instrument: okx minima and increments must be positive",
            )
        retrieved_at = _unix_to_iso(self._clock())
        usable_until = _unix_to_iso(self._clock() + self._ttl_seconds)
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        return InstrumentRulesV1(
            schema_version=SCHEMA_VERSION,
            venue="okx",
            canonical_pair=canonical_pair,
            venue_symbol=venue_symbol,
            base_asset=str(row.get("baseCcy") or ""),
            quote_asset=str(row.get("quoteCcy") or ""),
            min_quantity=min_quantity,
            min_notional=OKX_PAPER_MIN_NOTIONAL,
            quantity_increment=quantity_increment,
            price_increment=price_increment,
            source={
                "endpoint": OKX_INSTRUMENTS_URL,
                "retrieved_at": retrieved_at,
                "source_version": payload_sha256[:16],
                "payload_sha256": payload_sha256,
            },
            usable_until=usable_until,
        )


# ---- snapshot ----------------------------------------------------------


class InstrumentRulesSnapshot:
    """Persisted snapshot of verified instrument records.

    Reading a record requires `offline=True`. Without it, the snapshot
    refuses (a public endpoint must be used instead). With it, a missing
    record refuses with `METADATA_UNAVAILABLE`; a record whose
    `usable_until` is in the past refuses with `METADATA_STALE`.

    The persisted file is `$KRELLBOT_HOME/run/instrument-rules.json`,
    written atomically so a crash mid-write never leaves a half-baked
    snapshot. The snapshot does NOT make network calls; it never fetches
    from Kraken or Coinbase.
    """

    def __init__(
        self,
        home: Path,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._home = Path(home)
        self._clock = clock or _default_now

    def _path(self) -> Path:
        run = self._home / "run"
        run.mkdir(parents=True, exist_ok=True)
        return run / SNAPSHOT_FILENAME

    def read_pair(
        self,
        venue: str,
        canonical_pair: str,
        *,
        offline: bool = False,
    ) -> InstrumentRulesV1:
        if not offline:
            raise OfflineModeRequired(
                "instrument snapshot read requires offline=True; a public endpoint must be used otherwise"
            )
        records = self._load()
        venue_records = records.get(venue) or {}
        record = venue_records.get(canonical_pair)
        if record is None:
            raise InstrumentMetadataError(
                METADATA_UNAVAILABLE,
                venue,
                canonical_pair,
                f"instrument: no persisted record for {venue} {canonical_pair}",
            )
        if record.venue != venue or record.canonical_pair != canonical_pair:
            raise InstrumentMetadataError(
                METADATA_SYMBOL_MISMATCH,
                venue,
                canonical_pair,
                f"instrument: persisted record identity does not match {venue} {canonical_pair}",
            )
        if _iso_to_unix(record.usable_until) <= self._clock():
            raise InstrumentMetadataError(
                METADATA_STALE,
                venue,
                canonical_pair,
                f"instrument: persisted record for {venue} {canonical_pair} is past usable_until",
            )
        return record

    def write(self, records: dict) -> None:
        """Persist `records` (a nested dict: venue -> pair -> InstrumentRulesV1)."""
        serializable: dict[str, dict[str, dict]] = {}
        for venue, by_pair in records.items():
            venue_map: dict[str, dict] = {}
            for pair, record in by_pair.items():
                venue_map[pair] = dataclasses.asdict(record)
            serializable[venue] = venue_map
        body = {
            "schema_version": SCHEMA_VERSION,
            "records": serializable,
        }
        path = self._path()
        kb_paths.atomic_write(path, json.dumps(body, sort_keys=True).encode("utf-8"))

    def _load(self) -> dict[str, dict[str, InstrumentRulesV1]]:
        path = self._path()
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict[str, dict[str, InstrumentRulesV1]] = {}
        records = raw.get("records") or {}
        if not isinstance(records, dict):
            return {}
        for venue, by_pair in records.items():
            if not isinstance(by_pair, dict):
                continue
            venue_map: dict[str, InstrumentRulesV1] = {}
            for pair, payload in by_pair.items():
                if not isinstance(payload, dict):
                    continue
                try:
                    venue_map[pair] = _record_from_dict(payload)
                except ValueError:
                    continue
            if venue_map:
                out[venue] = venue_map
        return out


def ensure_instrument_rules(
    home: Path,
    *,
    venue: str,
    pairs: Sequence[str],
    transport,
    clock: Callable[[], float] | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> Path | None:
    """Fetch and persist public instrument rules for each ``(venue, pair)``.

    Writes (or merges into) ``$KRELLBOT_HOME/run/instrument-rules.json``.
    Fresh existing records are left alone. Missing or stale records are
    refreshed via ``InstrumentMetadataClient``. Fetch failures leave that
    pair unchanged so a later paper tick can still surface
    ``metadata_unavailable`` / ``metadata_stale`` through the rules
    provider — this helper never invents minima.

    Returns the snapshot path when at least one record was written or the
    file already existed after a no-op refresh; ``None`` when nothing was
    persisted (empty ``pairs``, or every fetch failed with no prior file).
    """
    home = Path(home)
    unique_pairs = [p for p in dict.fromkeys(pairs) if isinstance(p, str) and p]
    if not unique_pairs or not isinstance(venue, str) or not venue:
        path = home / "run" / SNAPSHOT_FILENAME
        return path if path.exists() else None

    snap = InstrumentRulesSnapshot(home=home, clock=clock)
    client = InstrumentMetadataClient(
        transport=transport,
        clock=clock,
        ttl_seconds=ttl_seconds,
    )
    now = (clock or _default_now)()
    records = snap._load()
    venue_map = dict(records.get(venue) or {})
    dirty = False
    for pair in unique_pairs:
        existing = venue_map.get(pair)
        if existing is not None and _iso_to_unix(existing.usable_until) > now:
            continue
        try:
            venue_map[pair] = client.fetch_rules(venue, pair)
        except (InstrumentMetadataError, TypeError, ValueError, OSError, RuntimeError, KeyError):
            continue
        dirty = True
    if dirty:
        records[venue] = venue_map
        snap.write(records)
    path = home / "run" / SNAPSHOT_FILENAME
    return path if path.exists() else None


# ---- derivation helpers -------------------------------------------------


def derive_decimal_places(increment: str) -> int:
    """Number of decimal places in a Decimal-string increment.

    Examples: ``"0.00001"`` -> 5, ``"0.1"`` -> 1, ``"1"`` -> 0.
    Raises `ValueError` on a non-Decimal or non-positive input.
    """
    d = Decimal(increment)
    if not d.is_finite() or d <= 0:
        raise ValueError(f"instrument: increment must be a positive finite Decimal, got {increment!r}")
    exp = d.as_tuple().exponent
    if not isinstance(exp, int) or exp >= 0:
        return 0
    return -exp


def pairrules_from_instrument(record: InstrumentRulesV1) -> PairRules:
    """Derive a `PairRules` adapter from a verified instrument record.

    Decimal increments are authoritative; decimal-place counts are
    derived for the existing adapter shape. Use this only after the
    record's freshness has been verified by the caller.
    """

    def representable_places(field: str) -> int:
        increment = getattr(record, field)
        _sign, digits, exponent = Decimal(increment).as_tuple()
        assert isinstance(exponent, int)  # InstrumentRulesV1 already validates finite, positive increments.
        while len(digits) > 1 and digits[-1] == 0:
            digits = digits[:-1]
            exponent += 1
        if digits != (1,) or exponent > 0:
            raise InstrumentMetadataError(
                METADATA_INVALID,
                record.venue,
                record.canonical_pair,
                f"instrument: {field} {increment!r} cannot be represented by decimal-count paper rules",
            )
        return -exponent

    return PairRules(
        ordermin=Decimal(record.min_quantity),
        costmin=Decimal(record.min_notional),
        lot_decimals=representable_places("quantity_increment"),
        price_decimals=representable_places("price_increment"),
    )


# ---- internals ---------------------------------------------------------


def _required_decimal_string(row: dict, key: str) -> str:
    if key not in row:
        raise KeyError(key)
    raw = row[key]
    if raw in (None, ""):
        raise ValueError(f"{key} is empty")
    return str(Decimal(str(raw)))


def _decimals_to_increment(decimals: int) -> str:
    if decimals <= 0:
        return "1"
    return "0." + "0" * (decimals - 1) + "1"


def _find_okx_instrument(payload: dict, canonical_pair: str) -> dict | None:
    """Return the instruments row whose ``instId`` is ``canonical_pair``."""
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and str(item.get("instId") or "") == canonical_pair:
                return item
    if str(payload.get("instId") or "") == canonical_pair:
        return payload
    return None


def _find_binance_symbol(payload: dict, canonical_pair: str) -> dict | None:
    """Return the exchangeInfo symbol object matching ``canonical_pair``.

    Accepts either the full ``symbols`` list shape or a single-symbol
    object at the top level (some test fakes).
    """
    symbols = payload.get("symbols")
    if isinstance(symbols, list):
        matches = [
            item for item in symbols if isinstance(item, dict) and str(item.get("symbol") or "") == canonical_pair
        ]
        if len(matches) == 1:
            return matches[0]
        return None
    if str(payload.get("symbol") or "") == canonical_pair and isinstance(payload, dict):
        return payload
    return None


def _binance_filter(filters: list, name: str) -> dict | None:
    for item in filters:
        if isinstance(item, dict) and item.get("filterType") == name:
            return item
    return None


def _find_kraken_row(result: dict, canonical_pair: str) -> tuple[dict | None, str | None]:
    """Find the row whose response key, altname, or wsname matches `canonical_pair`.

    Returns `(row, response_key)`. Returns `(None, None)` when no entry
    matches. Multiple matching entries are treated as malformed.
    """
    matches: list[tuple[dict, str]] = []
    for k, v in result.items():
        if not isinstance(v, dict):
            continue
        altname = str(v.get("altname", ""))
        wsname = str(v.get("wsname", ""))
        if _kraken_symbol_matches(k, altname, wsname, canonical_pair):
            matches.append((v, k))
    if len(matches) == 1:
        return matches[0]
    return None, None


def _kraken_symbol_matches(response_key: str, altname: str, wsname: str, canonical: str) -> bool:
    """True when any of response_key/altname/wsname equals `canonical`.

    `wsname` is compared both verbatim and with `/` stripped; Kraken's
    public `wsname` for XBTUSD is "XBT/USD" but the altname "XBTUSD" is
    the canonical form. A future Kraken change that adds a new mapping
    that does not equal `canonical` falls through and refuses with
    `METADATA_SYMBOL_MISMATCH`.
    """
    return (
        response_key == canonical
        or altname == canonical
        or wsname == canonical
        or bool(wsname)
        and wsname.replace("/", "") == canonical
    )


def _default_now() -> float:
    return time.time()


def _unix_to_iso(unix_seconds: float) -> str:
    dt = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_to_unix(iso: str) -> float:
    s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _record_from_dict(payload: dict) -> InstrumentRulesV1:
    """Rehydrate an `InstrumentRulesV1` from a JSON dict."""
    source_raw = payload.get("source") if isinstance(payload, dict) else None
    source = source_raw if isinstance(source_raw, dict) else {}
    return InstrumentRulesV1(
        schema_version=str(payload.get("schema_version", "")),
        venue=str(payload.get("venue", "")),
        canonical_pair=str(payload.get("canonical_pair", "")),
        venue_symbol=str(payload.get("venue_symbol", "")),
        base_asset=str(payload.get("base_asset", "")),
        quote_asset=str(payload.get("quote_asset", "")),
        min_quantity=str(payload.get("min_quantity", "")),
        min_notional=str(payload.get("min_notional", "")),
        quantity_increment=str(payload.get("quantity_increment", "")),
        price_increment=str(payload.get("price_increment", "")),
        source={
            "endpoint": str(source.get("endpoint", "")),
            "retrieved_at": str(source.get("retrieved_at", "")),
            "source_version": str(source.get("source_version", "")),
            "payload_sha256": str(source.get("payload_sha256", "")),
        },
        usable_until=str(payload.get("usable_until", "")),
    )

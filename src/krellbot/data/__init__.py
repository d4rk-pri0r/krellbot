"""Public candle sources and verified instrument metadata for the local engine.

Submodules:
    * `candles`    - parse_timestamp, drop_forming, TF_MS
    * `kraken_public`  - Kraken OHLC JSON + OHLCVT zip parsers
    * `coinbase_public` - Coinbase public candles (transport injected)
    * `cache`      - CSV cache + JSON manifest
    * `gaps`       - gap detection (refuses >1% missing unless allow_gaps=True)
    * `instruments` - verified per-venue/per-pair instrument rules (public metadata)
"""

from __future__ import annotations

from .cache import cache_path, manifest_path, read_cache, sha256_bytes, write_cache
from .candles import TF_MS, drop_forming, parse_timestamp
from .coinbase_public import fetch_coinbase_candles, parse_coinbase_candles
from .gaps import GapError, check_gaps
from .instruments import (
    METADATA_INVALID,
    METADATA_STALE,
    METADATA_SYMBOL_MISMATCH,
    METADATA_UNAVAILABLE,
    MINIMUM_NOT_MET,
    InstrumentMetadataClient,
    InstrumentMetadataError,
    InstrumentRulesSnapshot,
    InstrumentRulesV1,
    OfflineModeRequired,
    derive_decimal_places,
    pairrules_from_instrument,
)
from .kraken_public import (
    fetch_kraken_ohlc,
    import_kraken_ohlcvt_zip,
    parse_kraken_ohlc,
)

__all__ = [
    "METADATA_INVALID",
    "METADATA_STALE",
    "METADATA_SYMBOL_MISMATCH",
    "METADATA_UNAVAILABLE",
    "MINIMUM_NOT_MET",
    "TF_MS",
    "GapError",
    "InstrumentMetadataClient",
    "InstrumentMetadataError",
    "InstrumentRulesSnapshot",
    "InstrumentRulesV1",
    "OfflineModeRequired",
    "cache_path",
    "check_gaps",
    "derive_decimal_places",
    "drop_forming",
    "fetch_coinbase_candles",
    "fetch_kraken_ohlc",
    "import_kraken_ohlcvt_zip",
    "manifest_path",
    "pairrules_from_instrument",
    "parse_coinbase_candles",
    "parse_kraken_ohlc",
    "parse_timestamp",
    "read_cache",
    "sha256_bytes",
    "write_cache",
]

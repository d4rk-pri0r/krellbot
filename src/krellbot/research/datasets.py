"""Content-addressed dataset manifest.

A `DatasetManifest` binds a hex sha256 of the raw dataset bytes to the
metadata the caller passed about the source and the window. The same raw
bytes always produce the same digest; different bytes produce a different
digest. The record does not parse the raw bytes: it does not invent
`close` or `volume`, and it does not synthesize a missing-bar tuple. A
caller-supplied `missing_bars` is preserved as a tuple of integer
timestamps; an empty tuple stays empty, and a `0` stays `0` only when the
caller actually passed `0`.

`coverage_label` is the only derived view: it returns the literal string
`"complete"` when `missing_bars` is empty and `"incomplete"` otherwise.
It never returns a number.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass


def _sha256_hex(data: bytes) -> str:
    """Hex sha256 of `data`."""
    return hashlib.sha256(data).hexdigest()


def _coerce_missing_bars(missing_bars: Iterable[int]) -> tuple[int, ...]:
    """Return a tuple of the caller's integer timestamps.

    An empty input stays empty. A ``0`` stays ``0`` only when the caller
    passed the integer ``0``. A float, bool, or other type raises
    ``TypeError`` and is not stored.
    """
    stored: list[int] = []
    for timestamp in missing_bars:
        if type(timestamp) is not int:
            raise TypeError(f"missing bar timestamp must be int; got {type(timestamp).__name__}")
        stored.append(timestamp)
    return tuple(stored)


@dataclass(frozen=True)
class DatasetManifest:
    """The content-addressed dataset record.

    Fields:
        content_sha256: hex sha256 of the raw dataset bytes.
        source:         opaque source identifier (e.g. "kraken-public").
        source_version: opaque source-version string.
        venue:          exchange venue key (e.g. "kraken").
        pair:           trading pair (e.g. "SUIUSD").
        tf:             timeframe key (e.g. "1h").
        window_from_ms: inclusive lower bound of the data window in ms.
        window_to_ms:   inclusive upper bound of the data window in ms.
        timestamp_semantic: what each timestamp means (e.g. "bar_close").
        missing_bars:   tuple of integer timestamps the caller marked as
                        missing. Empty when none. Never fabricated.
    """

    content_sha256: str
    source: str
    source_version: str
    venue: str
    pair: str
    tf: str
    window_from_ms: int
    window_to_ms: int
    timestamp_semantic: str
    missing_bars: tuple[int, ...]


def manifest_for(
    raw: bytes,
    *,
    source: str,
    source_version: str,
    venue: str,
    pair: str,
    tf: str,
    window_from_ms: int,
    window_to_ms: int,
    timestamp_semantic: str,
    missing_bars: Iterable[int],
) -> DatasetManifest:
    """Build a `DatasetManifest` from raw bytes + caller metadata.

    The function is pure: it does not read the OS keyring, open a network
    transport, or parse `raw`. The raw bytes are taken at face value for
    `content_sha256`; the metadata fields are stored exactly as given.
    `missing_bars` is coerced to a tuple of ints. An empty input stays
    empty; a `0` stays `0` only when the caller passed `0`.
    """
    return DatasetManifest(
        content_sha256=_sha256_hex(raw),
        source=source,
        source_version=source_version,
        venue=venue,
        pair=pair,
        tf=tf,
        window_from_ms=window_from_ms,
        window_to_ms=window_to_ms,
        timestamp_semantic=timestamp_semantic,
        missing_bars=_coerce_missing_bars(missing_bars),
    )


def coverage_label(manifest: DatasetManifest) -> str:
    """Return `"complete"` when `missing_bars` is empty, `"incomplete"` otherwise.

    Never returns a number: the label is always a string literal.
    """
    if not manifest.missing_bars:
        return "complete"
    return "incomplete"


__all__ = ["DatasetManifest", "coverage_label", "manifest_for"]

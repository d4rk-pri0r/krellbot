"""NS16a: content-addressed dataset manifest.

`manifest_for` is a pure function: given raw bytes plus metadata, it returns
a record whose `content_sha256` is the hex sha256 of the raw bytes. The same
bytes always produce the same digest; different bytes produce a different
digest. The record preserves every metadata field exactly as given and never
invents `close` or `volume`. `missing_bars` is stored as a tuple of integer
timestamps; an empty list stays empty, and a missing timestamp of `0` stays
`0` only when the caller passed `0`.

`coverage_label(manifest)` returns the literal string `"complete"` when
`missing_bars` is empty and `"incomplete"` otherwise. It never returns a
number.
"""

from __future__ import annotations

import hashlib

import pytest

from krellbot.research.datasets import DatasetManifest, coverage_label, manifest_for

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


RAW_A = b"ts_ms,open,high,low,close,volume\n0,1,1,1,1,1\n"
RAW_B = b"ts_ms,open,high,low,close,volume\n0,1,1,1,1,1\n3_600_000,2,2,2,2,2\n"


def _kwargs(**overrides):
    """Defaults that match the brief; tests override individual fields."""
    base = {
        "source": "kraken-public",
        "source_version": "v1",
        "venue": "kraken",
        "pair": "SUIUSD",
        "tf": "1h",
        "window_from_ms": 0,
        "window_to_ms": 3_600_000,
        "timestamp_semantic": "bar_close",
        "missing_bars": (),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. content_sha256 is the hex sha256 of the raw bytes.
# ---------------------------------------------------------------------------


def test_content_sha256_matches_hashlib_for_raw_bytes():
    raw = RAW_A
    m = manifest_for(raw, **_kwargs())
    assert m.content_sha256 == hashlib.sha256(raw).hexdigest()


def test_same_bytes_produce_same_digest():
    m1 = manifest_for(RAW_A, **_kwargs())
    m2 = manifest_for(RAW_A, **_kwargs())
    assert m1.content_sha256 == m2.content_sha256


def test_different_bytes_produce_different_digest():
    m1 = manifest_for(RAW_A, **_kwargs())
    m2 = manifest_for(RAW_B, **_kwargs())
    assert m1.content_sha256 != m2.content_sha256


def test_content_sha256_is_64_hex_chars():
    m = manifest_for(RAW_A, **_kwargs())
    digest = m.content_sha256
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_one_bit_flip_changes_digest():
    """Single-byte difference flips the digest (sha256 avalanche)."""
    near_a = bytearray(RAW_A)
    near_a[-1] = (near_a[-1] + 1) % 256
    m1 = manifest_for(RAW_A, **_kwargs())
    m2 = manifest_for(bytes(near_a), **_kwargs())
    assert m1.content_sha256 != m2.content_sha256


# ---------------------------------------------------------------------------
# 2. Metadata is preserved exactly; no close / volume invented.
# ---------------------------------------------------------------------------


def test_metadata_preserved_exactly():
    m = manifest_for(
        RAW_A,
        source="kraken-public",
        source_version="v2",
        venue="kraken",
        pair="BTCUSD",
        tf="4h",
        window_from_ms=1_700_000_000_000,
        window_to_ms=1_700_003_600_000,
        timestamp_semantic="bar_open",
        missing_bars=(1_700_001_800_000,),
    )
    assert m.source == "kraken-public"
    assert m.source_version == "v2"
    assert m.venue == "kraken"
    assert m.pair == "BTCUSD"
    assert m.tf == "4h"
    assert m.window_from_ms == 1_700_000_000_000
    assert m.window_to_ms == 1_700_003_600_000
    assert m.timestamp_semantic == "bar_open"


def test_manifest_does_not_invent_close_or_volume():
    """The manifest record has no `close` or `volume` fields. The raw bytes
    are not parsed; the manifest only carries the metadata the caller passed
    plus the content digest and the missing-bar tuple."""
    m = manifest_for(RAW_A, **_kwargs())
    field_names = {f for f in m.__dataclass_fields__}
    assert "close" not in field_names
    assert "volume" not in field_names
    # And no top-level attributes for either.
    assert not hasattr(m, "close")
    assert not hasattr(m, "volume")


def test_manifest_is_a_dataset_manifest_record():
    m = manifest_for(RAW_A, **_kwargs())
    assert isinstance(m, DatasetManifest)


def test_manifest_is_frozen():
    """The record is frozen: equality + hashability + no in-place mutation."""
    m = manifest_for(RAW_A, **_kwargs())
    with pytest.raises((AttributeError, TypeError)):
        m.content_sha256 = "deadbeef"  # type: ignore[misc]
    # Frozen dataclasses are hashable when all fields are hashable.
    assert hash(m) == hash(m)


# ---------------------------------------------------------------------------
# 3. missing_bars is stored as a tuple; empty stays empty; 0 stays 0.
# ---------------------------------------------------------------------------


def test_missing_bars_empty_stays_empty():
    m = manifest_for(RAW_A, **_kwargs(missing_bars=()))
    assert m.missing_bars == ()
    assert isinstance(m.missing_bars, tuple)


def test_missing_bars_list_is_coerced_to_tuple():
    m = manifest_for(RAW_A, **_kwargs(missing_bars=[1, 2, 3]))
    assert m.missing_bars == (1, 2, 3)
    assert isinstance(m.missing_bars, tuple)


def test_missing_bars_zero_stays_zero():
    """A missing timestamp of `0` stays `0` only when the caller passed `0`."""
    m = manifest_for(RAW_A, **_kwargs(missing_bars=(0,)))
    assert m.missing_bars == (0,)


def test_missing_bars_float_is_not_stored_as_zero():
    with pytest.raises(TypeError):
        manifest_for(RAW_A, **_kwargs(missing_bars=(0.0,)))


def test_missing_bars_empty_is_not_replaced_with_zero():
    """An empty missing list stays empty. It is never replaced with `(0,)`
    or with any default sentinel."""
    m = manifest_for(RAW_A, **_kwargs(missing_bars=()))
    assert m.missing_bars == ()
    assert 0 not in m.missing_bars
    assert len(m.missing_bars) == 0


def test_missing_bars_preserves_arbitrary_ints():
    times = (1_700_000_000_000, 1_700_000_003_600_000, 42)
    m = manifest_for(RAW_A, **_kwargs(missing_bars=times))
    assert m.missing_bars == times
    assert all(isinstance(t, int) for t in m.missing_bars)


# ---------------------------------------------------------------------------
# 4. coverage_label returns complete / incomplete, never a number.
# ---------------------------------------------------------------------------


def test_coverage_label_complete_when_no_missing():
    m = manifest_for(RAW_A, **_kwargs(missing_bars=()))
    label = coverage_label(m)
    assert label == "complete"
    assert isinstance(label, str)


def test_coverage_label_incomplete_when_missing_present():
    m = manifest_for(RAW_A, **_kwargs(missing_bars=(1_700_000_000_000,)))
    label = coverage_label(m)
    assert label == "incomplete"
    assert isinstance(label, str)


def test_coverage_label_incomplete_for_zero_in_tuple():
    """`(0,)` is non-empty, so coverage is incomplete even when the only
    missing timestamp is 0."""
    m = manifest_for(RAW_A, **_kwargs(missing_bars=(0,)))
    label = coverage_label(m)
    assert label == "incomplete"


def test_coverage_label_never_returns_a_number():
    m_complete = manifest_for(RAW_A, **_kwargs(missing_bars=()))
    m_incomplete = manifest_for(RAW_A, **_kwargs(missing_bars=(1,)))
    for m in (m_complete, m_incomplete):
        label = coverage_label(m)
        assert not isinstance(label, int)
        assert not isinstance(label, bool)
        assert not isinstance(label, float)


# ---------------------------------------------------------------------------
# 5. Determinism + isolation.
# ---------------------------------------------------------------------------


def test_metadata_change_does_not_change_content_sha256():
    """Same raw bytes + different metadata -> same digest; metadata lives
    alongside the digest, not inside it."""
    m1 = manifest_for(RAW_A, **_kwargs(venue="kraken"))
    m2 = manifest_for(RAW_A, **_kwargs(venue="coinbase"))
    assert m1.content_sha256 == m2.content_sha256
    assert m1.venue != m2.venue


def test_manifest_is_pure():
    """Calling `manifest_for` twice with identical inputs returns equal records."""
    a = manifest_for(RAW_A, **_kwargs())
    b = manifest_for(RAW_A, **_kwargs())
    assert a == b

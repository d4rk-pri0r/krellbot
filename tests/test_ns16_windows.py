"""NS16b: scored-window pin.

`pin_window(store, experiment_id, manifest)` records the `(venue, pair,
window_from_ms, window_to_ms)` quad from the manifest against
`experiment_id` in `store`. The store is a `MutableMapping[str, bytes]`;
each pin is the deterministic JSON serialization of the four fields.

Pinning the same `experiment_id` again with the same quad returns the
existing pin bytes and leaves the store unchanged. Pinning with a
different venue, pair, or window raises `WindowChanged` and leaves the
stored pin byte-identical to the first pin (no partial mutation).
Different `experiment_id`s may use different windows in the same store.

The module does not import `krellbot.venues` and does not open a network
connection.
"""

from __future__ import annotations

import json

import pytest

from krellbot.research.datasets import DatasetManifest, manifest_for
from krellbot.research.windows import WindowChanged, pin_window

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


RAW = b"ts_ms,open,high,low,close,volume\n0,1,1,1,1,1\n"


def _make_manifest(**overrides) -> DatasetManifest:
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
    return manifest_for(RAW, **base)


# ---------------------------------------------------------------------------
# 1. Records venue, pair, window_from_ms, window_to_ms from the manifest.
# ---------------------------------------------------------------------------


def test_pin_window_records_venue_pair_and_window():
    store: dict[str, bytes] = {}
    m = _make_manifest(
        venue="kraken",
        pair="SUIUSD",
        window_from_ms=1_700_000_000_000,
        window_to_ms=1_700_003_600_000,
    )
    stored = pin_window(store, "exp-001", m)

    payload = json.loads(stored.decode("utf-8"))
    assert payload["venue"] == "kraken"
    assert payload["pair"] == "SUIUSD"
    assert payload["window_from_ms"] == 1_700_000_000_000
    assert payload["window_to_ms"] == 1_700_003_600_000


def test_pin_window_does_not_record_other_manifest_fields():
    """The pin only carries the four brief fields. `source`, `tf`,
    `missing_bars`, etc. are not persisted as part of the pin."""
    store: dict[str, bytes] = {}
    m = _make_manifest(
        source="kraken-public",
        source_version="v2",
        tf="1h",
        timestamp_semantic="bar_close",
    )
    stored = pin_window(store, "exp-001", m)

    payload = json.loads(stored.decode("utf-8"))
    assert set(payload.keys()) == {"venue", "pair", "window_from_ms", "window_to_ms"}


def test_pin_window_stored_bytes_are_canonical():
    """Re-pinning a fresh store with the same quad produces the exact same
    bytes (deterministic JSON, sorted keys, compact separators)."""
    store_a: dict[str, bytes] = {}
    store_b: dict[str, bytes] = {}
    m = _make_manifest(venue="kraken", pair="SUIUSD")
    a = pin_window(store_a, "exp-001", m)
    b = pin_window(store_b, "exp-001", m)
    assert a == b


# ---------------------------------------------------------------------------
# 2. Same experiment_id + same window returns existing pin, no change.
# ---------------------------------------------------------------------------


def test_pin_window_same_quad_returns_existing_pin():
    store: dict[str, bytes] = {}
    m = _make_manifest(venue="kraken", pair="SUIUSD", window_from_ms=0, window_to_ms=3_600_000)
    first = pin_window(store, "exp-001", m)
    second = pin_window(store, "exp-001", m)
    assert second == first
    assert store["exp-001"] == first


def test_pin_window_same_quad_does_not_mutate_store():
    """A second pin with the same quad must not produce a new bytes object
    overwriting the original; the store entry is the same object as the
    first call returned."""
    store: dict[str, bytes] = {}
    m = _make_manifest()
    first = pin_window(store, "exp-001", m)
    second = pin_window(store, "exp-001", m)
    assert store["exp-001"] is first
    assert second is first


def test_pin_window_same_quad_is_idempotent():
    """Three successive pins with the same quad all return identical bytes."""
    store: dict[str, bytes] = {}
    m = _make_manifest()
    a = pin_window(store, "exp-001", m)
    b = pin_window(store, "exp-001", m)
    c = pin_window(store, "exp-001", m)
    assert a == b == c
    assert len(store) == 1


# ---------------------------------------------------------------------------
# 3. Different venue / pair / window raises WindowChanged, pin byte-identical.
# ---------------------------------------------------------------------------


def test_pin_window_different_venue_raises_window_changed():
    store: dict[str, bytes] = {}
    pin_window(store, "exp-001", _make_manifest(venue="kraken", pair="SUIUSD"))
    before = store["exp-001"]
    with pytest.raises(WindowChanged):
        pin_window(store, "exp-001", _make_manifest(venue="coinbase", pair="SUIUSD"))
    assert store["exp-001"] == before
    assert store["exp-001"] is before


def test_pin_window_different_pair_raises_window_changed():
    store: dict[str, bytes] = {}
    pin_window(store, "exp-001", _make_manifest(venue="kraken", pair="SUIUSD"))
    before = store["exp-001"]
    with pytest.raises(WindowChanged):
        pin_window(store, "exp-001", _make_manifest(venue="kraken", pair="BTCUSD"))
    assert store["exp-001"] == before


def test_pin_window_different_window_from_raises_window_changed():
    store: dict[str, bytes] = {}
    pin_window(store, "exp-001", _make_manifest(window_from_ms=0, window_to_ms=3_600_000))
    before = store["exp-001"]
    with pytest.raises(WindowChanged):
        pin_window(store, "exp-001", _make_manifest(window_from_ms=60_000, window_to_ms=3_600_000))
    assert store["exp-001"] == before


def test_pin_window_different_window_to_raises_window_changed():
    store: dict[str, bytes] = {}
    pin_window(store, "exp-001", _make_manifest(window_from_ms=0, window_to_ms=3_600_000))
    before = store["exp-001"]
    with pytest.raises(WindowChanged):
        pin_window(store, "exp-001", _make_manifest(window_from_ms=0, window_to_ms=7_200_000))
    assert store["exp-001"] == before


def test_pin_window_changed_leaves_pin_byte_identical():
    """After a refused re-pin, `store[experiment_id]` is byte-identical
    to the bytes that were stored before the call."""
    store: dict[str, bytes] = {}
    m1 = _make_manifest(venue="kraken", pair="SUIUSD", window_from_ms=0, window_to_ms=3_600_000)
    first = pin_window(store, "exp-001", m1)
    m2 = _make_manifest(venue="coinbase", pair="BTCUSD", window_from_ms=0, window_to_ms=86_400_000)
    with pytest.raises(WindowChanged):
        pin_window(store, "exp-001", m2)
    assert store["exp-001"] == first


def test_window_changed_is_an_exception_subclass():
    """`WindowChanged` is a regular `Exception` subclass, not a `BaseException`."""
    assert issubclass(WindowChanged, Exception)
    store: dict[str, bytes] = {}
    pin_window(store, "exp-001", _make_manifest(venue="kraken"))
    with pytest.raises(WindowChanged) as excinfo:
        pin_window(store, "exp-001", _make_manifest(venue="coinbase"))
    assert "kraken" in str(excinfo.value)
    assert "coinbase" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Different experiment_id may use a different window in the same store.
# ---------------------------------------------------------------------------


def test_pin_window_different_experiment_ids_use_different_windows():
    store: dict[str, bytes] = {}
    a = pin_window(store, "exp-A", _make_manifest(venue="kraken", pair="SUIUSD"))
    b = pin_window(store, "exp-B", _make_manifest(venue="coinbase", pair="BTCUSD"))
    c = pin_window(store, "exp-C", _make_manifest(venue="kraken", pair="ETHUSD", window_to_ms=7_200_000))

    assert a != b
    assert a != c
    assert b != c
    assert len(store) == 3

    payload_a = json.loads(store["exp-A"].decode("utf-8"))
    payload_b = json.loads(store["exp-B"].decode("utf-8"))
    payload_c = json.loads(store["exp-C"].decode("utf-8"))
    assert payload_a["pair"] == "SUIUSD"
    assert payload_b["venue"] == "coinbase"
    assert payload_c["window_to_ms"] == 7_200_000


def test_pin_window_other_experiment_unaffected_by_failed_repin():
    """A failed re-pin on `exp-A` does not touch `exp-B`."""
    store: dict[str, bytes] = {}
    pin_window(store, "exp-A", _make_manifest(venue="kraken", pair="SUIUSD"))
    b_before = pin_window(store, "exp-B", _make_manifest(venue="coinbase", pair="BTCUSD"))
    a_before = store["exp-A"]
    with pytest.raises(WindowChanged):
        pin_window(store, "exp-A", _make_manifest(venue="kraken", pair="BTCUSD"))
    assert store["exp-A"] == a_before
    assert store["exp-B"] == b_before


# ---------------------------------------------------------------------------
# 5. Network isolation.
# ---------------------------------------------------------------------------


def test_pin_window_does_not_import_venues():
    """`krellbot.research.windows` must not import `krellbot.venues`."""
    import ast
    import inspect

    import krellbot.research.windows as windows_mod

    source = inspect.getsource(windows_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "venues" not in alias.name, f"krellbot.research.windows imports {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "krellbot.venues", "krellbot.research.windows does a from-import from krellbot.venues"
            for alias in node.names:
                assert "venues" not in alias.name, (
                    f"krellbot.research.windows imports {alias.name!r} from {node.module!r}"
                )

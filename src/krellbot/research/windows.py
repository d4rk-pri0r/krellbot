"""Scored-window pin store.

A `pin_window(store, experiment_id, manifest)` call records the
`(venue, pair, window_from_ms, window_to_ms)` quad from `manifest`
against `experiment_id` in `store`. The store is a
`MutableMapping[str, bytes]`; each value is the deterministic JSON
serialization of the four pin fields.

Pinning the same `experiment_id` again with the same quad returns the
existing pin bytes and leaves the store unchanged. Pinning with a
different venue, pair, or window raises `WindowChanged` and leaves the
stored pin byte-identical to the first pin (no partial mutation).
Different `experiment_id`s may use different windows in the same store.

The module does not import `krellbot.venues`, the OS keyring, the
network stack, or any clock. The only IO it performs is reading and
writing the caller-supplied `store`.
"""

from __future__ import annotations

import json
from collections.abc import MutableMapping

from .datasets import DatasetManifest


class WindowChanged(Exception):
    """The pin for `experiment_id` was already recorded with a different
    venue, pair, or window. The stored pin is byte-identical to the first
    pin; the failed re-pin did not mutate the store.
    """

    def __init__(
        self,
        experiment_id: str,
        stored: tuple[str, str, int, int],
        requested: tuple[str, str, int, int],
    ) -> None:
        self.experiment_id = experiment_id
        self.stored = stored
        self.requested = requested
        super().__init__(
            f"window for {experiment_id!r} already pinned to "
            f"venue={stored[0]!r} pair={stored[1]!r} "
            f"window_from_ms={stored[2]} window_to_ms={stored[3]}; "
            f"refused venue={requested[0]!r} pair={requested[1]!r} "
            f"window_from_ms={requested[2]} window_to_ms={requested[3]}"
        )


def _pin_quad(manifest: DatasetManifest) -> tuple[str, str, int, int]:
    """Return the four-field pin tuple from `manifest`."""
    return (
        manifest.venue,
        manifest.pair,
        manifest.window_from_ms,
        manifest.window_to_ms,
    )


def _encode_pin(quad: tuple[str, str, int, int]) -> bytes:
    """Canonical JSON encoding of the pin quad.

    `sort_keys=True` and compact separators give a deterministic byte
    sequence so two equal quads always serialize to the same bytes.
    """
    payload = {
        "venue": quad[0],
        "pair": quad[1],
        "window_from_ms": quad[2],
        "window_to_ms": quad[3],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def pin_window(
    store: MutableMapping[str, bytes],
    experiment_id: str,
    manifest: DatasetManifest,
) -> bytes:
    """Record the `(venue, pair, window_from_ms, window_to_ms)` pin for
    `experiment_id` in `store`.

    Returns the stored pin bytes. If the same `experiment_id` is pinned
    again with the same quad, the existing bytes are returned and the
    store is not mutated. If the quad differs in any of `venue`, `pair`,
    `window_from_ms`, or `window_to_ms`, `WindowChanged` is raised and
    the store is left byte-identical to its prior state.

    `store` is a `MutableMapping[str, bytes]`. The function performs no
    network IO and does not import `krellbot.venues`.
    """
    requested = _pin_quad(manifest)
    requested_bytes = _encode_pin(requested)
    existing = store.get(experiment_id)
    if existing is None:
        store[experiment_id] = requested_bytes
        return requested_bytes
    if existing == requested_bytes:
        return existing
    raise WindowChanged(experiment_id, _decode_quad(existing), requested)


def _decode_quad(pin_bytes: bytes) -> tuple[str, str, int, int]:
    """Decode the stored pin bytes back into the four-field tuple.

    Used only to populate `WindowChanged.stored`. The bytes are assumed
    to have been produced by `_encode_pin`, so the schema is fixed.
    """
    payload = json.loads(pin_bytes.decode("utf-8"))
    return (
        str(payload["venue"]),
        str(payload["pair"]),
        int(payload["window_from_ms"]),
        int(payload["window_to_ms"]),
    )


__all__ = ["WindowChanged", "pin_window"]

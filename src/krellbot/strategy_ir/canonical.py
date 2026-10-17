"""NS19f — canonical configuration round-trip.

``canonical_bytes(graph)`` returns the UTF-8 bytes of a JSON document
built from ``strip_editor(graph)`` (NS19c), with sorted keys and
``(",", ":")`` separators. The function is the canonical serializer
the NS19 leaves share: ``execution_id`` (NS19b) builds a *subset*
of this canonical document (the three identity-bearing keys) and
hashes it, while ``canonical_bytes`` here emits the full stripped
graph. Both leaves agree on what counts as canvas state: the four
editor / layout keys the v1 decision engine must never see —
``layout``, ``x``, ``y``, and ``editor``.

The canonical form has three guarantees:

1. **Round-trip stability.** Parsing the bytes and calling
   ``canonical_bytes`` again returns the same bytes. The parse
   produces a dict whose key set is exactly the keys the first
   ``canonical_bytes`` saw (after the editor-key strip), and the
   second serialize with sorted keys and ``(",", ":")`` separators
   reproduces the same byte sequence.
2. **Editor-key invariance.** Adding, removing, or changing any of
   ``layout``, ``x``, ``y``, or ``editor`` at the top level does
   not change the bytes. The strip happens before the encode.
3. **Type preservation.** ``schema_version`` is encoded as the
   integer ``1`` (not ``"1"``, not ``1.0``) and parses back as the
   integer ``1`` — ``json.dumps(1)`` is ``"1"`` and ``json.loads("1")``
   gives back the int. The brief pins the type: a refused clock
   check is not a return, and a coerced clock check would silently
   rewrite the v1 graph.

The module is a pure JSON transform. It does not import
``krellbot.venues``, ``krellbot.pack.evaluate``, or
``krellbot.run``; it does not read the clock, touch the keyring,
or open a network transport. It depends only on the stdlib
``json`` module and on the local ``strip_editor`` leaf.
"""

from __future__ import annotations

import json
from typing import Any

from .v1 import strip_editor

# The separator pair the brief pins. ``(",", ":")`` removes every
# space the default encoder would otherwise insert between tokens;
# the canonical form is byte-stable across callers and pretty
# printers. ``sort_keys=True`` normalises dict key order; both
# together make ``canonical_bytes`` idempotent under ``parse ∘
# canonical_bytes``.
_CANONICAL_SEPARATORS = (",", ":")


def canonical_bytes(graph: Any) -> bytes:
    """Return the UTF-8 bytes of the canonical JSON for ``graph``.

    The canonical document is the result of:

    1. ``strip_editor(graph)`` — the four editor / layout keys
       (``layout``, ``x``, ``y``, ``editor``) are removed from the
       top level. The caller's mapping is not mutated.
    2. ``json.dumps(stripped, sort_keys=True, separators=(",", ":"))``
       — the resulting mapping is rendered as compact JSON with
       lexicographically sorted keys, recursively.
    3. ``.encode("utf-8")`` — the JSON text is encoded as UTF-8
       bytes.

    The output has the following properties:

    - ``canonical_bytes(graph) == canonical_bytes(json.loads(canonical_bytes(graph)))``
      — the canonical form is a fixed point under ``parse ∘
      canonical_bytes``.
    - The bytes do not change when ``layout``, ``x``, ``y``, or
      ``editor`` is added, removed, or modified at the top level.
    - The bytes do change when ``schema_version``, ``id``, ``entry``,
      ``exit``, ``risk``, ``markets``, ``indicators``, ``timeframe``,
      ``version``, ``label``, ``author``, or any other non-editor
      top-level key is added, removed, or modified.
    - ``schema_version`` stays the integer ``1`` through the round
      trip; ``json.dumps(1)`` is ``"1"`` and ``json.loads("1")`` is
      ``1`` (int).

    ``graph`` must be a mapping. A non-mapping input — ``None``, a
    string, a list, a tuple, a number, a boolean — raises
    ``TypeError`` rather than being silently coerced; the brief
    pins the function as a mapping transform and refuses to guess
    at intent.

    The function is a pure JSON transform. It does not import
    ``krellbot.venues``, ``krellbot.pack.evaluate``, or
    ``krellbot.run``; it does not read the clock, touch the
    keyring, or open a network transport. The IR layer owns the
    canonical form; downstream callers (venues, the evaluator, the
    runtime) consume the bytes later.
    """
    if not isinstance(graph, dict):
        raise TypeError(f"graph must be a mapping, got {type(graph).__name__}")
    stripped = strip_editor(graph)
    return json.dumps(stripped, sort_keys=True, separators=_CANONICAL_SEPARATORS).encode("utf-8")


__all__ = ["canonical_bytes"]

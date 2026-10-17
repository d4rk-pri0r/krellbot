"""NS19b — execution_id ignores editor / layout metadata.

``execution_id(graph)`` is the hex sha256 of a canonical JSON
document built from ``id``, ``entry``, and ``exit`` only. The
canonical document is the strict subset of the graph that names the
identity-bearing fields, rendered as UTF-8 JSON with sorted keys
and ``(",", ":")`` separators, then hashed with sha256. Layout and
editor state — ``layout``, ``x``, ``y``, ``editor``, and any other
key not in the identity-bearing set — is excluded, so moving a
node on the canvas, swapping the editor theme, or storing a
``layout`` string does not change the id.

The module is a pure predicate over the graph shape. It does not
import ``krellbot.venues`` or ``krellbot.pack.evaluate``, it does
not read the clock, touch the keyring, or open a network
transport. The strategy IR owns its identity; venues and pack
evaluation consume the id later.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Identity-bearing keys. Listed in sorted order so the canonical
# document has a stable top-level layout independent of input
# dict insertion order. ``__all__`` below is also sorted.
_IDENTITY_KEYS = ("entry", "exit", "id")


def _canonical_bytes(graph: Any) -> bytes:
    """Render the canonical JSON for the identity-bearing subset of
    ``graph``.

    Picks ``id``, ``entry``, and ``exit`` in that order from the
    graph (when present), then renders the resulting mapping as
    UTF-8 JSON with sorted keys and ``(",", ":")`` separators. Any
    key not in the identity-bearing set — ``layout``, ``x``, ``y``,
    ``editor``, nested node lists, edge lists, viewport state — is
    dropped before the hash.
    """
    if not isinstance(graph, dict):
        raise TypeError(f"graph must be a mapping, got {type(graph).__name__}")
    picked = {key: graph[key] for key in _IDENTITY_KEYS if key in graph}
    return json.dumps(picked, sort_keys=True, separators=(",", ":")).encode("utf-8")


def execution_id(graph: Any) -> str:
    """Return the hex sha256 of a canonical JSON document built from
    ``id``, ``entry``, and ``exit`` only.

    The canonical document is UTF-8 JSON with sorted keys and
    ``(",", ":")`` separators, restricted to the three
    identity-bearing fields. Layout and editor metadata
    (``layout``, ``x``, ``y``, ``editor``, and any other key not in
    the identity-bearing set) is excluded, so a move on the canvas
    does not change the id. Changing ``entry`` or ``exit`` does
    change the id.

    ``graph`` must be a mapping. Anything else — ``None``, a
    string, a list, a tuple, a number — raises ``TypeError``. The
    function is a pure predicate; it does not import
    ``krellbot.venues`` or ``krellbot.pack.evaluate``, and it does
    not read the clock, touch the keyring, or open a network
    transport.
    """
    return hashlib.sha256(_canonical_bytes(graph)).hexdigest()


__all__ = ["execution_id"]

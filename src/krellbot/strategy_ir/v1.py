"""NS19c — editor / layout keys do not change a v1 decision.

``strip_editor(pack)`` returns a new mapping that has every key the
input ``pack`` carries, except the four editor / layout keys the v1
decision engine should never see: ``layout``, ``x``, ``y``, and
``editor``. The caller's dict is untouched; the function never
imports ``krellbot.venues``, ``krellbot.run``, or
``krellbot.pack.evaluate``, and the stripped mapping is fed to
``krellbot.pack.evaluate.run`` by callers that want a decision
uncontaminated by canvas state.

The v1 evaluator only reads ``indicators``, ``entry``, ``exit``,
``risk``, and ``markets``; the four dropped keys carry canvas /
viewport state that the evaluator has never consumed. Even so, the
strip is pinned at the IR layer rather than left to the caller:
moving a node, switching the editor theme, or storing a ``layout``
string must never change a v1 decision, and the strip is the
guarantee. ``strip_editor`` is a pure mapping transform; it does
not read the clock, touch the keyring, or open a network transport.
"""

from __future__ import annotations

from typing import Any

# Editor / layout keys the v1 decision engine must not see. The list
# matches the field set the NS19b execution_id already excludes from
# its canonical document, so the two IR leaves agree on what counts
# as canvas state. ``__all__`` below is also sorted.
_EDITOR_KEYS = frozenset({"editor", "layout", "x", "y"})


def strip_editor(pack: Any) -> dict:
    """Return a new dict with the editor / layout keys removed.

    The result is a fresh ``dict`` whose keys are exactly the keys of
    ``pack`` minus ``layout``, ``x``, ``y``, and ``editor``. The
    caller's mapping is never mutated: a copy is built first, the
    four editor keys are popped, and the copy is returned. Any other
    key — ``id``, ``indicators``, ``entry``, ``exit``, ``risk``,
    ``markets``, ``version``, ``label``, ``timeframe``, nested node
    or edge lists, viewport state under non-editor keys — is carried
    through verbatim.

    ``pack`` must be a mapping. A non-mapping input — ``None``, a
    string, a list, a tuple, a number — raises ``TypeError`` rather
    than being silently coerced; the brief pins the function as a
    mapping transform and refuses to guess at intent. The function
    is a pure mapping transform; it does not import
    ``krellbot.venues``, ``krellbot.run``, or
    ``krellbot.pack.evaluate``, and it does not read the clock,
    touch the keyring, or open a network transport.
    """
    if not isinstance(pack, dict):
        raise TypeError(f"pack must be a mapping, got {type(pack).__name__}")
    result = dict(pack)
    for key in _EDITOR_KEYS:
        result.pop(key, None)
    return result


__all__ = ["strip_editor"]

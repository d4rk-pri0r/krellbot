"""NS19c / NS19d — the v1 IR surface.

``strip_editor(pack)`` returns a new mapping that has every key the
input ``pack`` carries, except the four editor / layout keys the v1
decision engine should never see: ``layout``, ``x``, ``y``, and
``editor``. The caller's dict is untouched; the function never
imports ``krellbot.venues``, ``krellbot.run``, or
``krellbot.pack.evaluate``, and the stripped mapping is fed to
``krellbot.pack.evaluate.run`` by callers that want a decision
uncontaminated by canvas state.

``prepare_v1(pack, nodes, decision_bar, evaluate)`` is the compose
step: it strips the editor / layout keys, then walks ``nodes`` and
calls ``check_availability(node, decision_bar)`` for each one. If any
node references a bar that is not yet closed at ``decision_bar`` —
or a node that is missing its bar reference — ``prepare_v1`` raises
``FutureData`` and never reaches ``evaluate``. If every node is
available, ``prepare_v1`` calls ``evaluate`` exactly once with the
stripped pack and returns its result. The evaluator is supplied by
the caller so the IR module never imports
``krellbot.pack.evaluate``; the brief pins the IR layer as a pure
compile surface.

The v1 evaluator only reads ``indicators``, ``entry``, ``exit``,
``risk``, and ``markets``; the four dropped keys carry canvas /
viewport state that the evaluator has never consumed. Even so, the
strip is pinned at the IR layer rather than left to the caller:
moving a node, switching the editor theme, or storing a ``layout``
string must never change a v1 decision, and the strip is the
guarantee. ``strip_editor`` and ``prepare_v1`` are pure mapping
transforms; neither reads the clock, touches the keyring, nor
opens a network transport.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .availability import check_availability

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


def prepare_v1(
    pack: Any,
    nodes: list,
    decision_bar: int,
    evaluate: Callable[[dict], Any],
) -> Any:
    """Strip editor keys, refuse future bars, then evaluate.

    The compose step on top of ``strip_editor`` (NS19c) and
    ``check_availability`` (NS19a): strip the four editor / layout
    keys off ``pack`` first, then walk ``nodes`` and call
    ``check_availability(node, decision_bar)`` for each one. If any
    node references a bar that is not yet closed at ``decision_bar``
    — or a node that is missing its bar reference entirely — the
    ``FutureData`` raised by ``check_availability`` propagates and
    ``evaluate`` is never called.

    If every node is available, ``evaluate`` is invoked exactly once
    with the stripped pack and the function returns its result. The
    evaluator is supplied by the caller; ``prepare_v1`` does not
    import ``krellbot.pack.evaluate`` (or ``krellbot.venues`` or
    ``krellbot.run``), so the IR layer stays a pure compile surface.

    ``pack`` must be a mapping; ``strip_editor`` raises ``TypeError``
    for a non-mapping input and ``prepare_v1`` propagates that error
    without calling ``evaluate``. ``nodes`` is iterated in order;
    an empty list trivially satisfies the per-node check.
    ``decision_bar`` is an integer passed straight to
    ``check_availability``. The function is a pure compose step; it
    does not read the clock, touch the keyring, or open a network
    transport.
    """
    stripped = strip_editor(pack)
    for node in nodes:
        check_availability(node, decision_bar)
    return evaluate(stripped)


__all__ = ["prepare_v1", "strip_editor"]

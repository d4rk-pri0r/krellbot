"""NS19g — refuse an unbounded condition tree.

``check_bounds(condition, *, max_nodes, max_depth)`` returns ``None``
only when the v1 condition tree has at most ``max_nodes`` nodes and at
most ``max_depth`` nesting levels. A v1 condition is either a 3-item
leaf array ``[operand, operator, operand]`` or an object with exactly
one of ``all`` or ``any`` whose value is an array of conditions — the
shape lives in ``src/krellbot/pack/schema.json``. A leaf array counts as
one node at the current depth; an ``all`` or ``any`` object counts as
one node and each child sits one level deeper. The root sits at depth
1; the very first node visited is ``count`` 1.

A node count above ``max_nodes`` raises ``GraphTooLarge`` carrying
``kind="nodes"`` and the offending count (the first count to exceed
the bound — always ``max_nodes + 1`` because walking stops the moment
the bound is exceeded). A nesting depth above ``max_depth`` raises
``GraphTooLarge`` carrying ``kind="depth"`` and the offending depth
(again the first depth past the bound, ``max_depth + 1``). The
exception carries ``kind``, ``limit``, ``value``, and ``reason`` and
no ``equity``, ``return_pct``, or ``pnl`` — a refused size check is
not a return.

The bound arguments ``max_nodes`` and ``max_depth`` must be exact
integers. ``True`` and ``1.0`` raise ``TypeError`` and are not
coerced; the check uses ``type(value) is int`` because ``bool`` is a
subclass of ``int`` in Python (``isinstance(True, int)`` is ``True``),
and ``int(1.0)`` would coerce the float to the integer ``1``. The
validation runs before walking so a non-int bound refuses the call
without traversing the tree at all.

Walking stops the moment either bound is exceeded — the function
never recurses without a bound, so a maliciously wide tree (with
millions of children) cannot exhaust the iteration budget past
``max_nodes``, and a maliciously deep tree (a long linear chain)
cannot overflow the stack past ``max_depth``. The bound is checked at
the top of every recursive step before any descent.

The module is a pure predicate over the condition shape. It does
not import ``krellbot.venues``, ``krellbot.pack.evaluate``, or
``krellbot.run``; it does not read the clock, touch the keyring, or
open a network transport.
"""

from __future__ import annotations

from typing import Any


class GraphTooLarge(Exception):
    """The condition tree exceeds the configured size bound.

    Carries ``kind`` (``"nodes"`` for a node-count violation,
    ``"depth"`` for a nesting-depth violation), ``limit`` (the bound
    that was violated, verbatim — ``max_nodes`` or ``max_depth``),
    ``value`` (the offending value: the first count to exceed
    ``max_nodes``, or the first depth to exceed ``max_depth``), and
    ``reason`` (a short human-readable explanation). The exception
    carries no ``equity``, ``return_pct``, or ``pnl`` attribute — a
    refused size check is not a return.
    """

    def __init__(self, kind: str, limit: int, value: int, reason: str) -> None:
        self.kind = kind
        self.limit = limit
        self.value = value
        self.reason = reason
        super().__init__(f"condition-tree refusal: {kind} {value} exceeds limit {limit} ({reason})")


def _require_int(name: str, value: Any) -> None:
    """Verify ``value`` is the exact integer type.

    ``type(value) is int`` is used (not ``isinstance``) because
    ``bool`` is a subclass of ``int`` in Python — ``isinstance(True,
    int)`` is ``True`` and would let ``True`` through, and ``True``
    is not a legal size bound. The check does not coerce ``1.0`` to
    ``1``: floats (including ``1.0``) raise ``TypeError`` rather than
    being silently narrowed. A ``TypeError`` names the bound so the
    caller can diagnose without a stack trace.
    """
    if type(value) is not int:
        raise TypeError(f"{name} must be an int (got {type(value).__name__}: {value!r})")


def _walk(
    condition: Any,
    *,
    depth: int,
    count: int,
    max_nodes: int,
    max_depth: int,
) -> int:
    """Walk the condition tree, enforcing the size bounds at every
    recursive step.

    Returns the running node count after visiting ``condition`` and
    all of its descendants. Raises ``GraphTooLarge`` the first time
    either bound is exceeded. The check runs at the top of every
    recursive step — *before* any descent — so the recursion never
    proceeds past the bound.
    """
    # The count check is listed first in the brief; it is also the
    # cheaper of the two checks (a single integer comparison versus a
    # function call into the shape validators). Both checks must pass
    # before any further walking happens.
    if count > max_nodes:
        raise GraphTooLarge(
            "nodes",
            max_nodes,
            count,
            f"node count {count} exceeds max_nodes={max_nodes}",
        )
    if depth > max_depth:
        raise GraphTooLarge(
            "depth",
            max_depth,
            depth,
            f"depth {depth} exceeds max_depth={max_depth}",
        )

    if _is_leaf(condition):
        return count

    children = _children(condition)
    for child in children:
        count = _walk(
            child,
            depth=depth + 1,
            count=count + 1,
            max_nodes=max_nodes,
            max_depth=max_depth,
        )
    return count


def _is_leaf(condition: Any) -> bool:
    """A leaf is a 3-item array.

    The contents (``operand, operator, operand``) are the v1 leaf
    shape — operand validation lives in the other NS19 leaves
    (clock, availability). ``check_bounds`` only enforces the size
    bounds, not the operand shapes; the array length is the only
    property the function inspects to distinguish a leaf from a
    compound node.
    """
    return isinstance(condition, list) and len(condition) == 3


def _children(condition: Any) -> list:
    """Return the child array of a compound (``all`` / ``any``)
    condition.

    Raises ``TypeError`` when the condition is not a valid v1 shape —
    not a 3-item leaf and not an object with exactly one of ``all``
    or ``any``. The check is deliberately strict: an empty ``all`` or
    ``any`` array is rejected because the schema's ``minItems: 1``
    applies, and a missing key, an extra key, or a non-array value
    for the one present key is rejected because the shape is not a
    legal v1 condition. The size check is not the right tool for
    shape validity, so the refusal is a ``TypeError`` rather than a
    ``GraphTooLarge``.
    """
    if not isinstance(condition, dict):
        raise TypeError(
            "condition must be a 3-item leaf array or an object with exactly "
            f"one of 'all' or 'any' (got {type(condition).__name__})"
        )
    keys = set(condition.keys())
    if keys == {"all"}:
        return _validate_child_array("all", condition["all"])
    if keys == {"any"}:
        return _validate_child_array("any", condition["any"])
    raise TypeError(
        "condition must be a 3-item leaf array or an object with exactly one "
        f"of 'all' or 'any' (got keys {sorted(keys)!r})"
    )


def _validate_child_array(key: str, value: Any) -> list:
    """Verify ``condition[key]`` is a non-empty array of conditions.

    An empty array is rejected because the schema's ``minItems: 1``
    applies — an ``all`` or ``any`` with no children is not a legal
    v1 condition. A non-array value is rejected for the same reason.
    The children themselves are walked by ``_walk``; this helper only
    validates the immediate shape.
    """
    if not isinstance(value, list) or not value:
        raise TypeError(
            f"condition '{key}' must be a non-empty array of conditions (got {type(value).__name__}: {value!r})"
        )
    return value


def check_bounds(condition: Any, *, max_nodes: int, max_depth: int) -> None:
    """Refuse a condition tree that exceeds ``max_nodes`` or
    ``max_depth``.

    Returns ``None`` only when the tree fits both bounds. The first
    bound that is exceeded raises ``GraphTooLarge`` with ``kind``
    (``"nodes"`` or ``"depth"``), ``limit`` (the bound that was
    violated), and ``value`` (the offending count or depth). The
    function never recurses past either bound: a wide tree stops the
    moment the count exceeds ``max_nodes``; a deep tree stops the
    moment the depth exceeds ``max_depth``.

    ``max_nodes`` and ``max_depth`` must be exact integers. ``True``
    and ``1.0`` raise ``TypeError`` and are not coerced — the
    validation uses ``type(value) is int`` so a ``bool`` (a subclass
    of ``int``) does not pass and a float is not narrowed to an
    integer. A non-int bound is refused before the tree is walked at
    all.

    An invalid condition shape (anything that is not a 3-item leaf
    array or an object with exactly one non-empty ``all`` or ``any``
    array) raises ``TypeError``. The size check is not the right
    tool for shape validity; the shape rule lives in
    ``src/krellbot/pack/schema.json``.

    ``GraphTooLarge`` carries ``kind``, ``limit``, ``value``, and
    ``reason``; it carries no ``equity``, ``return_pct``, or ``pnl``
    because a refused size check is not a return. The module is a
    pure predicate over the condition shape: it does not import
    ``krellbot.venues``, ``krellbot.pack.evaluate``, or
    ``krellbot.run``, and it does not read the clock, touch the
    keyring, or open a network transport.
    """
    _require_int("max_nodes", max_nodes)
    _require_int("max_depth", max_depth)
    _walk(
        condition,
        depth=1,
        count=1,
        max_nodes=max_nodes,
        max_depth=max_depth,
    )


__all__ = ["GraphTooLarge", "check_bounds"]

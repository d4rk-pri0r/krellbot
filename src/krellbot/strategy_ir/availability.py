"""NS19a — refuse a node that reads a future bar.

``check_availability(node, decision_bar)`` returns ``None`` when every
referenced bar index in ``node`` is less than or equal to
``decision_bar``. A referenced bar index greater than ``decision_bar``
raises ``FutureData``; the exception carries the node id and the
illegal index, and carries no ``equity``, ``return_pct``, or ``pnl``
because a refused availability check is not a return. A missing bar
index raises ``FutureData`` rather than being silently treated as bar
zero — a node that has not named its bar is not a legal source of any
value, including bar 0.

A node is a small mapping with a string ``id`` and either a single
``bar_index`` (an ``int``) or a ``bar_indices`` list of ``int``. The
function is a pure predicate over the node shape and the integer
``decision_bar``. It does not import ``krellbot.venues``,
``krellbot.run``, or ``krellbot.pack.evaluate``; it does not read the
clock, touch the keyring, or open a network transport.
"""

from __future__ import annotations

from typing import Any


class FutureData(Exception):
    """The node references a bar that is not yet closed at ``decision_bar``.

    The exception carries the node id (``node_id``) and the offending
    bar index (``index``) as attributes so the caller can identify
    which node failed the availability check and which bar it
    attempted to read. It does not carry ``equity``, ``return_pct``,
    or ``pnl``: a refused availability is not a return, and the brief
    forbids inventing one.
    """

    def __init__(self, node_id: Any, index: Any, reason: str) -> None:
        self.node_id = node_id
        self.index = index
        self.reason = reason
        super().__init__(
            f"future-bar refusal: node {node_id!r} references "
            f"bar {index!r} which is not closed at decision_bar "
            f"({reason})"
        )


def _coerce_index(raw: Any) -> int | None:
    """Return the bar index from a raw ``bar_index`` value, or ``None``
    when the value is missing or not an integer.

    Booleans are not integers here: ``True`` is not a legal bar index,
    nor is ``False``. The brief forbids treating a missing index as
    bar 0, and the same rule forbids treating a boolean as a numeric
    sentinel.
    """
    if isinstance(raw, bool):
        return None
    if not isinstance(raw, int):
        return None
    return raw


def _node_id(node: Any) -> Any:
    """Return the node id as carried by the node, or a sentinel
    ``"<unknown>"`` when the node is missing its id.

    The brief requires the exception to name the node id, so the
    function always returns a string-shaped label.
    """
    if isinstance(node, dict):
        return node.get("id", "<unknown>")
    return "<unknown>"


def check_availability(node: Any, decision_bar: int) -> None:
    """Refuse a node that references a bar beyond ``decision_bar``.

    Returns ``None`` when every referenced bar index in ``node`` is
    less than or equal to ``decision_bar``. A referenced bar index
    greater than ``decision_bar`` raises ``FutureData`` whose
    ``node_id`` and ``index`` attributes name the failing node and the
    offending bar. A missing bar index (absent key, ``None``, or empty
    list) also raises ``FutureData`` — a missing reference is not a
    license to read bar 0.

    A node is a small mapping that carries its identity in an ``id``
    field and its bar reference in either a single ``bar_index``
    (``int``) or a ``bar_indices`` list of ``int``. The function is
    a pure predicate over the node shape and the integer
    ``decision_bar``: no IO, no clock, no keyring, no network, no
    import of ``krellbot.venues``, ``krellbot.run``, or
    ``krellbot.pack.evaluate``.
    """
    node_id = _node_id(node)

    if not isinstance(node, dict):
        raise FutureData(node_id, "<missing>", "node is not a mapping")

    if "bar_index" in node:
        raw = node["bar_index"]
        index = _coerce_index(raw)
        if index is None:
            raise FutureData(node_id, "<missing>", "bar_index missing or not an int")
        if index > decision_bar:
            raise FutureData(node_id, index, "bar_index is after decision_bar")
        return

    if "bar_indices" in node:
        raw_list = node["bar_indices"]
        if not isinstance(raw_list, list) or not raw_list:
            raise FutureData(node_id, "<missing>", "bar_indices missing or empty")
        for raw in raw_list:
            index = _coerce_index(raw)
            if index is None:
                raise FutureData(node_id, "<missing>", "bar_indices entry missing or not an int")
            if index > decision_bar:
                raise FutureData(node_id, index, "bar_indices entry is after decision_bar")
        return

    raise FutureData(node_id, "<missing>", "node has no bar_index or bar_indices")


__all__ = ["FutureData", "check_availability"]

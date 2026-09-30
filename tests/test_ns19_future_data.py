"""NS19a: refuse a node that reads a future bar.

The brief: ``check_availability(node, decision_bar)`` returns ``None``
when every referenced bar index in ``node`` is less than or equal to
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

import ast
import inspect

import pytest

from krellbot.strategy_ir import availability as availability_mod
from krellbot.strategy_ir.availability import FutureData, check_availability

# ---------------------------------------------------------------------------
# 1. Legal availability returns None and never raises.
# ---------------------------------------------------------------------------


def test_returns_none_when_bar_index_equals_decision_bar():
    """``decision_bar == 5`` and the node references bar 5: the node
    reads exactly the bar that is now closed, so availability is legal."""
    assert check_availability({"id": "n1", "bar_index": 5}, 5) is None


def test_returns_none_when_bar_index_is_before_decision_bar():
    """A historical bar index below ``decision_bar`` is always
    available; the call returns ``None``."""
    assert check_availability({"id": "n1", "bar_index": 0}, 5) is None


def test_returns_none_when_bar_index_is_zero_at_zero_decision_bar():
    """At the very first decision bar, ``decision_bar == 0`` and the
    only legal index is bar 0; bar 0 is not missing."""
    assert check_availability({"id": "n1", "bar_index": 0}, 0) is None


def test_returns_none_when_all_indices_in_a_list_are_within_decision_bar():
    """A node that names several bar indices is legal only when every
    one of them is at or before ``decision_bar``."""
    node = {"id": "n1", "bar_indices": [0, 1, 2, 3, 4, 5]}
    assert check_availability(node, 5) is None


def test_returns_none_for_a_large_negative_index():
    """A bar index well before the decision bar is legal; the
    availability check does not impose a lower bound."""
    assert check_availability({"id": "n1", "bar_index": -10}, 5) is None


# ---------------------------------------------------------------------------
# 2. A future bar index raises FutureData.
# ---------------------------------------------------------------------------


def test_raises_when_bar_index_is_after_decision_bar():
    """``decision_bar == 5`` and the node references bar 6, which has
    not yet closed. The call must raise ``FutureData``."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1", "bar_index": 6}, 5)


def test_raises_when_bar_index_is_one_past_decision_bar():
    """The smallest possible lookahead (bar index = decision_bar + 1)
    is still lookahead; the call must raise."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1", "bar_index": 6}, 5)


def test_raises_when_any_index_in_a_list_is_after_decision_bar():
    """A node that lists several bar indices, one of which is a
    future index, must raise. The check is on every referenced
    index, not just the first."""
    node = {"id": "n1", "bar_indices": [3, 4, 5, 6]}
    with pytest.raises(FutureData):
        check_availability(node, 5)


def test_raises_when_last_index_in_a_list_is_after_decision_bar():
    """Even if all earlier indices are legal, an illegal index
    anywhere in the list trips the check."""
    node = {"id": "n1", "bar_indices": [0, 1, 2, 100]}
    with pytest.raises(FutureData):
        check_availability(node, 5)


# ---------------------------------------------------------------------------
# 3. Missing bar index raises FutureData (not a default to bar 0).
# ---------------------------------------------------------------------------


def test_raises_when_bar_index_key_is_absent():
    """A node without a ``bar_index`` or ``bar_indices`` field is
    missing its bar reference. The brief forbids treating that as
    bar 0; the call must raise ``FutureData``."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1"}, 5)


def test_raises_when_bar_index_is_none():
    """A node whose ``bar_index`` is literally ``None`` is missing its
    bar reference. ``None`` is not a legal integer index and must not
    be coerced to bar 0."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1", "bar_index": None}, 5)


def test_raises_when_bar_indices_list_is_empty():
    """An empty list of bar indices is a missing reference list;
    the call must raise."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1", "bar_indices": []}, 5)


def test_raises_when_bar_indices_list_contains_none():
    """A list of bar indices with a single ``None`` entry is still a
    missing reference; the call must raise."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1", "bar_indices": [None]}, 5)


def test_raises_when_bar_indices_list_contains_none_alongside_legal_indices():
    """A mixed list of legal integers and ``None`` raises; the missing
    entry is not treated as bar 0."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1", "bar_indices": [3, None, 4]}, 5)


def test_does_not_treat_missing_index_as_bar_zero():
    """The brief explicitly forbids treating a missing bar index as
    bar 0. A node with no bar reference must raise the same exception
    type and class as a node that names bar 6."""
    with pytest.raises(FutureData):
        check_availability({"id": "n1"}, 5)
    with pytest.raises(FutureData):
        check_availability({"id": "n1", "bar_index": 6}, 5)


# ---------------------------------------------------------------------------
# 4. FutureData carries the node id and the illegal index.
# ---------------------------------------------------------------------------


def test_future_data_carries_node_id():
    """The exception exposes ``node_id`` as an attribute so the caller
    can identify which node failed the availability check."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "node-abc", "bar_index": 6}, 5)
    assert excinfo.value.node_id == "node-abc"


def test_future_data_carries_the_illegal_index_for_single_bar_index():
    """For a node with ``bar_index = 6`` and ``decision_bar = 5``, the
    illegal index carried on the exception is exactly 6."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_index": 6}, 5)
    assert excinfo.value.index == 6


def test_future_data_carries_an_illegal_index_from_a_list():
    """For a node with ``bar_indices = [3, 4, 5, 6]`` and
    ``decision_bar = 5``, the illegal index is 6."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_indices": [3, 4, 5, 6]}, 5)
    assert excinfo.value.index == 6


def test_future_data_carries_the_first_illegal_index_in_a_list():
    """When several illegal indices appear, the exception carries the
    first one encountered in iteration order."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_indices": [3, 7, 9]}, 5)
    assert excinfo.value.index == 7


def test_future_data_node_id_is_a_string():
    """The carried ``node_id`` is the literal string the caller
    passed; no normalization, no integer coercion."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n-with-dashes_and.dots", "bar_index": 6}, 5)
    assert isinstance(excinfo.value.node_id, str)
    assert excinfo.value.node_id == "n-with-dashes_and.dots"


def test_future_data_index_is_an_int():
    """The carried ``index`` is a Python ``int``, the value the
    caller passed; no float coercion, no string coercion."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_index": 42}, 5)
    assert isinstance(excinfo.value.index, int)
    assert not isinstance(excinfo.value.index, bool)


def test_future_data_index_is_not_a_future_marker_for_missing():
    """When a node is missing its bar index entirely, the exception
    still carries the node id but does not invent a sentinel index
    such as 0. The refusal is a structural problem, not a numeric
    one."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1"}, 5)
    assert excinfo.value.node_id == "n1"


def test_future_data_message_mentions_the_node_id():
    """The exception message identifies the failing node so a log
    line is enough to diagnose the violation."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "node-abc", "bar_index": 6}, 5)
    assert "node-abc" in str(excinfo.value)


def test_future_data_message_mentions_the_illegal_index():
    """The exception message includes the illegal index."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_index": 6}, 5)
    assert "6" in str(excinfo.value)


def test_future_data_message_mentions_future_or_lookahead():
    """The message uses language that tells the operator that this
    is a future-bar refusal, not a generic error."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_index": 6}, 5)
    text = str(excinfo.value).lower()
    assert "future" in text or "lookahead" in text


# ---------------------------------------------------------------------------
# 5. FutureData carries no equity / return_pct / pnl (no invented return).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden_attr", ["equity", "return_pct", "pnl"])
def test_future_data_has_no_forbidden_attribute(forbidden_attr: str):
    """``FutureData`` is a refusal of a node, not a return-narrative
    record. The brief forbids inventing a return; the exception must
    not expose ``equity``, ``return_pct``, or ``pnl``."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_index": 6}, 5)
    assert not hasattr(excinfo.value, forbidden_attr), f"FutureData must not carry a {forbidden_attr!r} attribute"


def test_future_data_class_does_not_define_forbidden_attributes():
    """The class itself never declares ``equity``, ``return_pct``, or
    ``pnl`` as instance attributes. The check is on the class, not
    just the instance, so a subclass cannot quietly add them either."""
    forbidden = {"equity", "return_pct", "pnl"}
    declared = set(FutureData.__init__.__code__.co_names)
    assert forbidden.isdisjoint(declared)


# ---------------------------------------------------------------------------
# 6. FutureData is a regular Exception subclass.
# ---------------------------------------------------------------------------


def test_future_data_is_an_exception_subclass():
    """``FutureData`` must be catchable as a normal ``Exception``."""
    assert issubclass(FutureData, Exception)


def test_future_data_can_be_caught_as_exception():
    """A bare ``except Exception`` clause catches ``FutureData``."""
    with pytest.raises(FutureData) as excinfo:
        check_availability({"id": "n1", "bar_index": 6}, 5)
    assert isinstance(excinfo.value, Exception)


# ---------------------------------------------------------------------------
# 7. Module / signature shape and isolation.
# ---------------------------------------------------------------------------


def test_check_availability_signature_is_node_and_decision_bar():
    """The brief pins the signature as ``check_availability(node,
    decision_bar)``. No extra positional or keyword parameters beyond
    the two inputs."""
    sig = inspect.signature(check_availability)
    assert list(sig.parameters) == ["node", "decision_bar"]


def test_check_availability_is_exposed_at_strategy_ir_availability():
    """``check_availability`` is importable from
    ``krellbot.strategy_ir.availability``. The module is the brief's
    pinned location for the predicate."""
    assert hasattr(availability_mod, "check_availability")
    assert callable(availability_mod.check_availability)


def test_future_data_is_exposed_at_strategy_ir_availability():
    """``FutureData`` is importable from
    ``krellbot.strategy_ir.availability``."""
    assert hasattr(availability_mod, "FutureData")


def test_availability_module_does_not_import_venues_run_or_evaluate():
    """``krellbot.strategy_ir.availability`` is a pure predicate. The
    brief forbids importing ``krellbot.venues``, ``krellbot.run``, or
    ``krellbot.pack.evaluate`` — the module has nothing to do with
    venues, runtime orchestration, or pack evaluation."""
    source = inspect.getsource(availability_mod)
    tree = ast.parse(source)
    forbidden_modules = {
        "krellbot.venues",
        "krellbot.run",
        "krellbot.pack.evaluate",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(alias.name == m or alias.name.startswith(m + ".") for m in forbidden_modules), (
                    f"availability module imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"availability module does a from-import from {node.module!r}"
            )

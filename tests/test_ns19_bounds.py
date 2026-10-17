"""NS19g: refuse an unbounded condition tree.

The brief: ``check_bounds(condition, *, max_nodes, max_depth)`` returns
``None`` only when the v1 condition tree has at most ``max_nodes`` nodes
and at most ``max_depth`` nesting levels. A v1 condition is either a
3-item leaf array ``[operand, operator, operand]`` or an object with
exactly one of ``all`` or ``any``, whose value is an array of
conditions. A leaf counts as one node at the current depth; an ``all``
or ``any`` object counts as one node, and each child is one level
deeper.

The function raises ``GraphTooLarge`` with ``kind="nodes"`` and the
offending count when the node count exceeds ``max_nodes``; it raises
``GraphTooLarge`` with ``kind="depth"`` and the offending depth when
the nesting depth exceeds ``max_depth``. Walking stops the moment
either bound is exceeded — the function does not recurse without a
bound.

The bound arguments ``max_nodes`` and ``max_depth`` must be exact
integers. ``True`` and ``1.0`` raise ``TypeError`` and are not coerced;
the check uses ``type(value) is int`` so a ``bool`` (which is a
subclass of ``int`` in Python) does not pass.

``GraphTooLarge`` carries ``kind``, ``limit``, and ``value`` attributes
but no ``equity``, ``return_pct``, or ``pnl`` — a refused size check
is not a return.

The module is a pure predicate over the condition shape. It does not
import ``krellbot.venues``, ``krellbot.pack.evaluate``, or
``krellbot.run``; it does not read the clock, touch the keyring, or
open a network transport.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from krellbot.strategy_ir import bounds as bounds_mod
from krellbot.strategy_ir.bounds import GraphTooLarge, check_bounds

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _leaf(a: str = "close", op: str = "crosses_above", b: str = "sma2") -> list:
    """A 3-item leaf condition ``[a, op, b]``. The values are arbitrary
    operands — ``check_bounds`` does not validate operand shapes; the
    availability / clock checks live in the other NS19 leaves."""
    return [a, op, b]


def _all(*children) -> dict:
    """An ``all`` object with ``children`` as its array. The function
    only inspects the ``all`` / ``any`` key and the array length."""
    return {"all": list(children)}


def _any(*children) -> dict:
    """An ``any`` object with ``children`` as its array."""
    return {"any": list(children)}


# ---------------------------------------------------------------------------
# 1. Module / signature shape and surface exposure.
# ---------------------------------------------------------------------------


def test_check_bounds_is_exposed_at_strategy_ir_bounds():
    """``check_bounds`` is importable from
    ``krellbot.strategy_ir.bounds`` — the brief's pinned module."""
    assert hasattr(bounds_mod, "check_bounds")
    assert callable(bounds_mod.check_bounds)


def test_check_bounds_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``check_bounds`` so callers
    can reach the size check through the package surface, the same way
    the other NS19 leaves are exposed."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "check_bounds")
    assert strategy_ir_pkg.check_bounds is bounds_mod.check_bounds


def test_graph_too_large_is_exposed_at_strategy_ir_bounds():
    """``GraphTooLarge`` is importable from
    ``krellbot.strategy_ir.bounds``."""
    assert hasattr(bounds_mod, "GraphTooLarge")
    assert inspect.isclass(bounds_mod.GraphTooLarge)


def test_graph_too_large_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``GraphTooLarge`` so callers
    can catch it the same way they catch the other NS19 exceptions."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "GraphTooLarge")
    assert strategy_ir_pkg.GraphTooLarge is bounds_mod.GraphTooLarge


def test_check_bounds_signature_pins_condition_and_keyword_bounds():
    """The brief pins the signature as
    ``check_bounds(condition, *, max_nodes, max_depth)``: a single
    positional argument plus two keyword-only integer bounds. No extra
    positional or keyword parameters."""
    sig = inspect.signature(check_bounds)
    params = list(sig.parameters)
    assert params == ["condition", "max_nodes", "max_depth"]
    assert sig.parameters["condition"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD
    assert sig.parameters["max_nodes"].kind is inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["max_depth"].kind is inspect.Parameter.KEYWORD_ONLY


def test_graph_too_large_is_an_exception_subclass():
    """``GraphTooLarge`` is an ``Exception`` subclass — it can be raised
    and caught the same way other NS19 exceptions are caught."""
    assert issubclass(GraphTooLarge, Exception)


# ---------------------------------------------------------------------------
# 2. Returns None when both bounds are satisfied.
# ---------------------------------------------------------------------------


def test_returns_none_for_a_single_leaf_within_bounds():
    """A leaf array at depth 1 with max_nodes=1 and max_depth=1 is
    within bounds. ``check_bounds`` returns ``None``."""
    assert check_bounds(_leaf(), max_nodes=1, max_depth=1) is None


def test_returns_none_for_a_single_all_node_within_bounds():
    """An ``all`` object with a single leaf child has 2 nodes and depth
    2. With max_nodes=2 and max_depth=2 it is within bounds."""
    cond = _all(_leaf())
    assert check_bounds(cond, max_nodes=2, max_depth=2) is None


def test_returns_none_for_a_single_any_node_within_bounds():
    """An ``any`` object with a single leaf child has 2 nodes and depth
    2. With max_nodes=2 and max_depth=2 it is within bounds."""
    cond = _any(_leaf())
    assert check_bounds(cond, max_nodes=2, max_depth=2) is None


def test_returns_none_for_two_leaves_under_all_within_bounds():
    """An ``all`` object with two leaf children has 3 nodes (root + two
    leaves) and depth 2. With max_nodes=3 and max_depth=2 it is
    within bounds."""
    cond = _all(_leaf(), _leaf("close", "crosses_below", "sma99"))
    assert check_bounds(cond, max_nodes=3, max_depth=2) is None


def test_returns_none_for_a_three_level_tree_within_bounds():
    """A three-level tree ``{"all": [{"any": [leaf]}]}`` has 3 nodes
    and depth 3. With max_nodes=3 and max_depth=3 it is within bounds."""
    cond = _all(_any(_leaf()))
    assert check_bounds(cond, max_nodes=3, max_depth=3) is None


def test_returns_none_for_a_balanced_tree_within_bounds():
    """A balanced two-level tree — root ``all`` with eight leaf
    children — has 1 root + 8 leaves = 9 nodes and depth 2. With
    max_nodes=9 and max_depth=2 it is within bounds."""
    leaves = [_leaf("close", ">", str(i)) for i in range(8)]
    cond = {"all": leaves}
    assert check_bounds(cond, max_nodes=9, max_depth=2) is None


# ---------------------------------------------------------------------------
# 3. Boundary conditions: exactly at the bound is allowed.
# ---------------------------------------------------------------------------


def test_exactly_at_max_nodes_returns_none():
    """A tree with exactly max_nodes nodes returns ``None``. The bound
    is inclusive — ``max_nodes=1`` allows a single leaf."""
    assert check_bounds(_leaf(), max_nodes=1, max_depth=10) is None


def test_exactly_at_max_depth_returns_none():
    """A tree whose deepest leaf is exactly at max_depth returns
    ``None``. The bound is inclusive — ``max_depth=1`` allows a
    leaf at depth 1."""
    assert check_bounds(_leaf(), max_nodes=10, max_depth=1) is None


def test_two_level_tree_at_max_depth_2_returns_none():
    """A two-level tree (root ``all`` at depth 1, leaf at depth 2) is
    allowed when max_depth=2."""
    cond = _all(_leaf())
    assert check_bounds(cond, max_nodes=10, max_depth=2) is None


def test_three_level_tree_at_max_depth_3_returns_none():
    """A three-level tree (``all`` → ``any`` → leaf) has a leaf at
    depth 3; with max_depth=3 the tree is within bounds."""
    cond = _all(_any(_leaf()))
    assert check_bounds(cond, max_nodes=10, max_depth=3) is None


# ---------------------------------------------------------------------------
# 4. Exceeding max_nodes raises GraphTooLarge(kind="nodes").
# ---------------------------------------------------------------------------


def test_single_node_above_max_nodes_raises_nodes_kind():
    """A single leaf with max_nodes=0 exceeds the bound (1 > 0).
    ``check_bounds`` raises ``GraphTooLarge`` with ``kind="nodes"``."""
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(_leaf(), max_nodes=0, max_depth=10)
    assert excinfo.value.kind == "nodes"


def test_two_node_tree_above_max_nodes_1_raises_nodes_kind():
    """An ``all`` object with one leaf child has 2 nodes; with
    max_nodes=1 the second node (the leaf at depth 2) is the first to
    exceed. ``check_bounds`` raises ``GraphTooLarge(kind="nodes")``
    and stops walking at that point."""
    cond = _all(_leaf())
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=1, max_depth=10)
    assert excinfo.value.kind == "nodes"


def test_nodes_kind_carries_offending_count():
    """The exception carries the offending count — the first count to
    exceed max_nodes. For max_nodes=1 and a 2-node tree, the
    offending count is 2 (the second node visited)."""
    cond = _all(_leaf())
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=1, max_depth=10)
    assert excinfo.value.kind == "nodes"
    assert excinfo.value.value == 2


def test_nodes_kind_carries_offending_count_for_three_node_tree():
    """For max_nodes=2 and a 3-node tree, the offending count is 3
    (the third node visited)."""
    cond = _all(_leaf(), _leaf("close", ">", "sma2"))
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=2, max_depth=10)
    assert excinfo.value.kind == "nodes"
    assert excinfo.value.value == 3


def test_nodes_kind_carries_the_max_nodes_limit():
    """The exception carries the max_nodes limit that was violated,
    so the caller can report the bound without re-deriving it."""
    leaves = [_leaf("close", ">", str(i)) for i in range(10)]
    cond = {"all": leaves}
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=5, max_depth=10)
    assert excinfo.value.kind == "nodes"
    assert excinfo.value.limit == 5


def test_two_children_under_all_above_max_nodes_2_raises():
    """An ``all`` object with two leaf children has 3 nodes; with
    max_nodes=2 the third node is the first to exceed. The exception
    reports ``kind="nodes"`` and ``value=3``."""
    cond = _all(_leaf(), _leaf("close", "<", "sma99"))
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=2, max_depth=10)
    assert excinfo.value.kind == "nodes"
    assert excinfo.value.value == 3


# ---------------------------------------------------------------------------
# 5. Exceeding max_depth raises GraphTooLarge(kind="depth").
# ---------------------------------------------------------------------------


def test_single_leaf_above_max_depth_0_raises_depth_kind():
    """A leaf at depth 1 with max_depth=0 exceeds the bound (1 > 0).
    ``check_bounds`` raises ``GraphTooLarge`` with ``kind="depth"``."""
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(_leaf(), max_nodes=10, max_depth=0)
    assert excinfo.value.kind == "depth"


def test_two_level_tree_above_max_depth_1_raises_depth_kind():
    """A root ``all`` at depth 1 with one leaf child: the leaf sits at
    depth 2, which exceeds max_depth=1. ``check_bounds`` raises
    ``GraphTooLarge(kind="depth")`` and stops walking at that
    point."""
    cond = _all(_leaf())
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=10, max_depth=1)
    assert excinfo.value.kind == "depth"


def test_depth_kind_carries_offending_depth():
    """The exception carries the offending depth — the first depth to
    exceed max_depth. For max_depth=1 and a 2-level tree, the
    offending depth is 2 (the leaf child at depth 2)."""
    cond = _all(_leaf())
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=10, max_depth=1)
    assert excinfo.value.kind == "depth"
    assert excinfo.value.value == 2


def test_depth_kind_carries_offending_depth_for_three_level_tree():
    """For max_depth=2 and a 3-level tree, the offending depth is 3
    (the leaf at depth 3)."""
    cond = _all(_any(_leaf()))
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=100, max_depth=2)
    assert excinfo.value.kind == "depth"
    assert excinfo.value.value == 3


def test_depth_kind_carries_the_max_depth_limit():
    """The exception carries the max_depth limit that was violated."""
    cond = _all(_any(_leaf()))
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=100, max_depth=2)
    assert excinfo.value.kind == "depth"
    assert excinfo.value.limit == 2


def test_three_level_tree_above_max_depth_2_raises():
    """A three-level tree (``all`` → ``any`` → leaf) with max_depth=2:
    the leaf at depth 3 is the first to exceed. The exception reports
    ``kind="depth"`` and ``value=3``."""
    cond = _all(_any(_leaf()))
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=100, max_depth=2)
    assert excinfo.value.kind == "depth"
    assert excinfo.value.value == 3


# ---------------------------------------------------------------------------
# 6. Stop walking: bounds check fires before unbounded recursion.
# ---------------------------------------------------------------------------


def test_deep_tree_stops_at_depth_bound_without_infinite_recursion():
    """A linear chain ``all(any(all(any(... leaf))))`` of arbitrary
    length must not recurse past max_depth. The bound is hit at
    max_depth+1 and the function raises ``GraphTooLarge(kind="depth")``
    rather than overflowing the stack."""
    depth = 200
    cur = _leaf()
    for _ in range(depth):
        cur = _any(cur)
    # The tree is 1 + depth nodes and depth+1 levels. With max_depth=5
    # the function must stop at depth 6 and raise.
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cur, max_nodes=10_000, max_depth=5)
    assert excinfo.value.kind == "depth"
    assert excinfo.value.value == 6


def test_wide_tree_stops_at_node_bound_without_infinite_recursion():
    """A root ``all`` with 10_000 leaf children has 10_001 nodes.
    With max_nodes=10 the bound is hit at node 11 and the function
    raises ``GraphTooLarge(kind="nodes")`` rather than walking the
    whole array."""
    leaves = [_leaf("close", ">", str(i)) for i in range(10_000)]
    cond = {"all": leaves}
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=10, max_depth=100)
    assert excinfo.value.kind == "nodes"
    assert excinfo.value.value == 11


def test_walking_stops_at_the_first_exceeded_bound():
    """A tree that exceeds max_nodes on its first extra node raises
    with ``kind="nodes"`` — the function does not keep walking and
    later raise with ``kind="depth"``. The first violation wins."""
    cond = _all(_leaf(), _leaf("close", ">", "sma2"))
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=2, max_depth=100)
    assert excinfo.value.kind == "nodes"


# ---------------------------------------------------------------------------
# 7. Bounds validation: max_nodes / max_depth must be exact integers.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [True, 1.0, "10", None, 1.5, [], {"k": 1}])
def test_max_nodes_must_be_an_int(bad):
    """``max_nodes`` must be the exact integer type. ``True`` and
    ``1.0`` raise ``TypeError``; strings, ``None``, floats, lists, and
    dicts also raise. ``bool`` is a subclass of ``int`` in Python, so
    ``type(value) is int`` is required to refuse ``True`` /
    ``False``."""
    with pytest.raises(TypeError):
        check_bounds(_leaf(), max_nodes=bad, max_depth=10)


@pytest.mark.parametrize("bad", [True, 1.0, "10", None, 1.5, [], {"k": 1}])
def test_max_depth_must_be_an_int(bad):
    """``max_depth`` must be the exact integer type. Same refusal set
    as ``max_nodes``."""
    with pytest.raises(TypeError):
        check_bounds(_leaf(), max_nodes=10, max_depth=bad)


def test_max_nodes_true_raises_type_error_not_coerced():
    """``True`` raises ``TypeError`` — it is not coerced to ``1``.
    ``isinstance(True, int)`` is ``True`` in Python (bool is a
    subclass of int), but the brief requires ``type(value) is int``."""
    with pytest.raises(TypeError):
        check_bounds(_leaf(), max_nodes=True, max_depth=10)


def test_max_nodes_one_point_zero_raises_type_error_not_coerced():
    """``1.0`` raises ``TypeError`` — it is not coerced to ``1``.
    ``int(1.0)`` would coerce, but the brief forbids coercion."""
    with pytest.raises(TypeError):
        check_bounds(_leaf(), max_nodes=1.0, max_depth=10)


def test_max_depth_true_raises_type_error_not_coerced():
    """``True`` raises ``TypeError`` for ``max_depth`` — the same rule
    applies to the depth bound."""
    with pytest.raises(TypeError):
        check_bounds(_leaf(), max_nodes=10, max_depth=True)


def test_max_depth_one_point_zero_raises_type_error_not_coerced():
    """``1.0`` raises ``TypeError`` for ``max_depth``."""
    with pytest.raises(TypeError):
        check_bounds(_leaf(), max_nodes=10, max_depth=1.0)


def test_negative_max_nodes_is_an_int():
    """The brief only pins the type of the bounds, not the sign. A
    negative ``max_nodes`` is still an ``int`` and the function
    raises ``GraphTooLarge(kind="nodes")`` on the very first node."""
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(_leaf(), max_nodes=-1, max_depth=10)
    assert excinfo.value.kind == "nodes"


def test_negative_max_depth_is_an_int():
    """A negative ``max_depth`` is still an ``int`` and the function
    raises ``GraphTooLarge(kind="depth")`` on the very first node."""
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(_leaf(), max_nodes=10, max_depth=-1)
    assert excinfo.value.kind == "depth"


def test_bounds_validation_runs_before_walking():
    """A non-int bound raises ``TypeError`` even when the condition is
    invalid — the bound check is the first thing the function does."""
    with pytest.raises(TypeError):
        check_bounds("not a condition", max_nodes=True, max_depth=True)


def test_type_error_message_names_max_nodes():
    """The ``TypeError`` for a non-int ``max_nodes`` names the bound
    so the caller can diagnose without a stack trace."""
    with pytest.raises(TypeError) as excinfo:
        check_bounds(_leaf(), max_nodes=True, max_depth=10)
    assert "max_nodes" in str(excinfo.value)


def test_type_error_message_names_max_depth():
    """The ``TypeError`` for a non-int ``max_depth`` names the bound."""
    with pytest.raises(TypeError) as excinfo:
        check_bounds(_leaf(), max_nodes=10, max_depth=True)
    assert "max_depth" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 8. The kind / limit / value attributes of GraphTooLarge.
# ---------------------------------------------------------------------------


def test_graph_too_large_carries_kind_attribute():
    """``GraphTooLarge`` exposes the violation kind via a ``kind``
    attribute — ``"nodes"`` for node-count violations, ``"depth"`` for
    nesting-depth violations."""
    err = GraphTooLarge(kind="nodes", limit=1, value=2, reason="test")
    assert err.kind == "nodes"


def test_graph_too_large_carries_limit_attribute():
    """``GraphTooLarge`` exposes the violated bound (``limit``) so the
    caller can report the rule without re-deriving it."""
    err = GraphTooLarge(kind="nodes", limit=5, value=6, reason="test")
    assert err.limit == 5


def test_graph_too_large_carries_value_attribute():
    """``GraphTooLarge`` exposes the offending value (``value``) — the
    count that exceeded max_nodes, or the depth that exceeded
    max_depth."""
    err = GraphTooLarge(kind="depth", limit=2, value=3, reason="test")
    assert err.value == 3


def test_graph_too_large_carries_reason_attribute():
    """``GraphTooLarge`` exposes a human-readable ``reason`` string
    suitable for logging or error messages."""
    err = GraphTooLarge(kind="nodes", limit=1, value=2, reason="too big")
    assert err.reason == "too big"


def test_graph_too_large_has_no_equity_attribute():
    """The brief forbids inventing ``equity`` on ``GraphTooLarge``. A
    refused size check is not a return."""
    err = GraphTooLarge(kind="nodes", limit=1, value=2, reason="test")
    assert not hasattr(err, "equity")


def test_graph_too_large_has_no_return_pct_attribute():
    """The brief forbids inventing ``return_pct`` on
    ``GraphTooLarge``."""
    err = GraphTooLarge(kind="nodes", limit=1, value=2, reason="test")
    assert not hasattr(err, "return_pct")


def test_graph_too_large_has_no_pnl_attribute():
    """The brief forbids inventing ``pnl`` on ``GraphTooLarge``."""
    err = GraphTooLarge(kind="nodes", limit=1, value=2, reason="test")
    assert not hasattr(err, "pnl")


def test_graph_too_large_str_message_mentions_kind_and_value():
    """The string form names the ``kind`` and ``value`` so the caller
    can see what failed without poking at attributes."""
    err = GraphTooLarge(kind="nodes", limit=1, value=2, reason="test")
    msg = str(err)
    assert "nodes" in msg
    assert "2" in msg


# ---------------------------------------------------------------------------
# 9. Counting model: nodes and depth match the brief's contract.
# ---------------------------------------------------------------------------


def test_single_leaf_counts_as_one_node():
    """A leaf array is one node — verified by the max_nodes=1
    boundary and the max_nodes=0 rejection."""
    assert check_bounds(_leaf(), max_nodes=1, max_depth=10) is None
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(_leaf(), max_nodes=0, max_depth=10)
    assert excinfo.value.value == 1


def test_all_object_counts_as_one_node_plus_children():
    """An ``all`` object is one node at the current depth, and each
    child is one level deeper. ``{"all": [leaf]}`` therefore has 2
    nodes total."""
    cond = _all(_leaf())
    assert check_bounds(cond, max_nodes=2, max_depth=10) is None
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=1, max_depth=10)
    assert excinfo.value.value == 2


def test_any_object_counts_as_one_node_plus_children():
    """An ``any`` object is one node at the current depth, and each
    child is one level deeper. ``{"any": [leaf]}`` therefore has 2
    nodes total."""
    cond = _any(_leaf())
    assert check_bounds(cond, max_nodes=2, max_depth=10) is None
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=1, max_depth=10)
    assert excinfo.value.value == 2


def test_root_is_at_depth_1():
    """The root of any tree is at depth 1, regardless of whether it is
    a leaf or an ``all`` / ``any`` object. With max_depth=1 a leaf
    root is accepted; with max_depth=0 the same root is rejected."""
    assert check_bounds(_leaf(), max_nodes=10, max_depth=1) is None
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(_leaf(), max_nodes=10, max_depth=0)
    assert excinfo.value.value == 1


def test_nested_all_any_increases_depth_one_level_per_object():
    """Each ``all`` or ``any`` ancestor adds one level of nesting. A
    chain ``all → any → leaf`` has the leaf at depth 3, accepted with
    max_depth=3 and rejected with max_depth=2."""
    cond = _all(_any(_leaf()))
    assert check_bounds(cond, max_nodes=100, max_depth=3) is None
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=100, max_depth=2)
    assert excinfo.value.kind == "depth"
    assert excinfo.value.value == 3


def test_deeper_chain_reports_offending_depth():
    """A four-level chain ``all(any(all(any leaf)))`` has the leaf at
    depth 4. With max_depth=2 the offending depth is 3 (the first
    depth past the limit)."""
    leaf = _leaf()
    cond = {"all": [{"any": [{"all": [{"any": [leaf]}]}]}]}
    with pytest.raises(GraphTooLarge) as excinfo:
        check_bounds(cond, max_nodes=100, max_depth=2)
    assert excinfo.value.kind == "depth"
    assert excinfo.value.value == 3


# ---------------------------------------------------------------------------
# 10. Condition shape: invalid conditions raise TypeError.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        None,
        "leaf",
        42,
        3.14,
        True,
        False,
        ["close", ">", "sma2", "extra"],
        ["close", ">"],
        [],
        {"all": []},
        {"any": []},
        {"all": [_leaf()], "any": [_leaf()]},
        {"both": [_leaf()]},
        {},
    ],
)
def test_invalid_condition_shape_raises_type_error(bad):
    """A condition that is not a 3-item leaf array or an object with
    exactly one of ``all`` or ``any`` is not a valid v1 condition.
    ``check_bounds`` refuses it with ``TypeError``. The size check is
    not the right tool, so the function does not raise
    ``GraphTooLarge`` for an invalid shape."""
    with pytest.raises(TypeError):
        check_bounds(bad, max_nodes=10, max_depth=10)


def test_type_error_for_invalid_shape_runs_before_bounds_check():
    """An invalid condition shape raises ``TypeError`` even when the
    bounds are themselves invalid — the condition shape is checked
    first because the function must walk a valid condition to count
    nodes and depth."""
    with pytest.raises(TypeError):
        check_bounds("not a condition", max_nodes=True, max_depth=1.0)


# ---------------------------------------------------------------------------
# 11. The brief's forbidden import set: bounds must not pull venues,
#     evaluate, or run into the IR.
# ---------------------------------------------------------------------------


def test_bounds_module_does_not_import_venues_run_or_evaluate():
    """``krellbot.strategy_ir.bounds`` stays a pure compile surface.
    The brief forbids importing ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` — the size check
    is a pure predicate over the condition shape."""
    source = inspect.getsource(bounds_mod)
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
                    f"bounds module imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"bounds module does a from-import from {node.module!r}"
            )


def test_strategy_ir_package_does_not_import_venues_run_or_evaluate_via_bounds():
    """The package ``__init__`` does not pull ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` into the IR layer.
    The bounds module is a pure compile surface and the package
    surface stays pure as a consequence."""
    import krellbot.strategy_ir as strategy_ir_pkg

    source = inspect.getsource(strategy_ir_pkg)
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
                    f"strategy_ir package imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"strategy_ir package does a from-import from {node.module!r}"
            )


def test_bounds_module_does_not_open_files_or_touch_the_clock():
    """``check_bounds`` is a pure in-memory predicate. No ``open``,
    no ``pathlib.Path.read_*``, no ``os.environ``, no ``time``, no
    ``datetime``, no ``keyring``, no ``requests``. The size check is
    synchronous, in-memory, and side-effect-free."""
    source = inspect.getsource(bounds_mod)
    tree = ast.parse(source)
    forbidden_calls = {"open", "read_text", "read_bytes", "time", "datetime", "keyring"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in forbidden_calls:
            assert node.value.id not in forbidden_calls, f"bounds module calls {node.value.id}.{node.attr}"


# ---------------------------------------------------------------------------
# 12. Composition with the other NS19 leaves.
# ---------------------------------------------------------------------------


def test_check_bounds_is_independent_of_other_leaves():
    """``check_bounds`` (NS19g) is independent of ``canonical_bytes``
    (NS19f), ``require_v1_clock`` (NS19e), ``prepare_v1`` (NS19d),
    ``strip_editor`` (NS19c), ``execution_id`` (NS19b), and
    ``check_availability`` (NS19a). The leaves remain importable from
    their own modules and are not coupled by the new module."""
    from krellbot.strategy_ir.availability import check_availability
    from krellbot.strategy_ir.canonical import canonical_bytes
    from krellbot.strategy_ir.identity import execution_id
    from krellbot.strategy_ir.units import require_v1_clock
    from krellbot.strategy_ir.v1 import prepare_v1, strip_editor

    assert callable(check_bounds)
    assert callable(canonical_bytes)
    assert callable(strip_editor)
    assert callable(prepare_v1)
    assert callable(check_availability)
    assert callable(execution_id)
    assert callable(require_v1_clock)


def test_check_bounds_accepts_a_v1_pack_entry_condition():
    """End-to-end property: the entry condition of the fixture pack
    ``sma_cross.json`` is a 3-item leaf. ``check_bounds`` accepts it
    under any reasonable bound."""
    import json
    from pathlib import Path

    fixture_path = Path(__file__).parent / "fixtures" / "packs" / "sma_cross.json"
    graph = json.loads(fixture_path.read_text())
    assert check_bounds(graph["entry"], max_nodes=1, max_depth=1) is None
    assert check_bounds(graph["exit"], max_nodes=1, max_depth=1) is None


def test_check_bounds_accepts_a_nested_v1_pack_condition():
    """End-to-end property: a hand-built nested condition
    ``{"all": [{"any": [leaf, leaf]}, {"all": [leaf]}]}`` has 6 nodes
    (1 root + 2 compound children + 3 leaves) and depth 3. With
    max_nodes=6 and max_depth=3 it is within bounds."""
    cond = {
        "all": [
            {"any": [_leaf("close", ">", "sma2"), _leaf("close", "<", "sma2")]},
            {"all": [_leaf("close", "crosses_above", "sma99")]},
        ]
    }
    assert check_bounds(cond, max_nodes=6, max_depth=3) is None

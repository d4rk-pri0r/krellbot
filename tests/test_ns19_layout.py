"""NS19b: layout metadata does not change the execution id.

The brief: ``execution_id(graph)`` is the hex sha256 of a canonical
JSON document built from ``id``, ``entry``, and ``exit`` only.
Changing ``layout``, ``x``, ``y``, or ``editor`` does not change
``execution_id``. Changing ``entry`` or ``exit`` does change
``execution_id``. The function is a pure predicate over the graph
shape; it does not import ``krellbot.venues`` or
``krellbot.pack.evaluate``, it does not read the clock, touch the
keyring, or open a network transport.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from krellbot.strategy_ir import identity as identity_mod
from krellbot.strategy_ir.identity import execution_id

_HEX = set("0123456789abcdef")


def _base_graph() -> dict:
    """A small graph with the three identity-bearing fields filled in."""
    return {"id": "g1", "entry": "a", "exit": "b"}


# ---------------------------------------------------------------------------
# 1. The output shape: a 64-char lowercase hex sha256.
# ---------------------------------------------------------------------------


def test_execution_id_returns_a_string():
    """The function returns a string (a hex sha256)."""
    assert isinstance(execution_id(_base_graph()), str)


def test_execution_id_is_a_64_char_string():
    """A sha256 in hex is exactly 64 characters."""
    assert len(execution_id(_base_graph())) == 64


def test_execution_id_is_lowercase_hex():
    """The hex sha256 is lowercase. The brief pins hex; mixed case would
    be legal hex but is not what the brief intends and would surprise
    callers comparing the id as a string."""
    result = execution_id(_base_graph())
    assert all(c in _HEX for c in result), f"non-hex character in {result!r}"


def test_execution_id_is_64_chars_for_a_nested_graph():
    """A graph with nested ``entry`` and ``exit`` structures still
    produces a 64-character hex id."""
    graph = {
        "id": "g1",
        "entry": {"all": [{"op": ">", "lhs": "close", "rhs": 100}]},
        "exit": {"any": [{"op": "<", "lhs": "rsi", "rhs": 30}]},
    }
    assert len(execution_id(graph)) == 64


# ---------------------------------------------------------------------------
# 2. Determinism: same identity-bearing fields, same id.
# ---------------------------------------------------------------------------


def test_same_graph_yields_the_same_id():
    """The id is a pure function of the graph; calling it twice on the
    same graph returns the same id."""
    g = _base_graph()
    assert execution_id(g) == execution_id(g)


def test_two_independent_copies_yield_the_same_id():
    """Two distinct dicts with the same ``id`` / ``entry`` / ``exit``
    fields yield the same id — the canonical document normalizes key
    order, and the id is not bound to object identity."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g1", "entry": "a", "exit": "b"}
    assert g1 is not g2
    assert execution_id(g1) == execution_id(g2)


def test_key_order_in_top_level_graph_input_does_not_matter():
    """The top-level keys of the graph dict may appear in any order.
    The canonical document is sorted, so the id is identical."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"exit": "b", "id": "g1", "entry": "a"}
    g3 = {"entry": "a", "exit": "b", "id": "g1"}
    assert execution_id(g1) == execution_id(g2) == execution_id(g3)


def test_key_order_in_nested_entry_value_does_not_matter():
    """Nested keys inside ``entry`` are normalized by the canonical JSON
    encoder as well — two semantically equal ``entry`` values with
    different key orders yield the same id."""
    g1 = {
        "id": "g1",
        "entry": {"all": [{"op": ">", "lhs": "close", "rhs": 100}]},
        "exit": "b",
    }
    g2 = {
        "id": "g1",
        "entry": {"all": [{"lhs": "close", "op": ">", "rhs": 100}]},
        "exit": "b",
    }
    assert execution_id(g1) == execution_id(g2)


# ---------------------------------------------------------------------------
# 3. Changing entry or exit changes the id.
# ---------------------------------------------------------------------------


def test_changing_entry_changes_the_id():
    """The id is built from ``entry``, so changing ``entry`` changes the
    id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g1", "entry": "X", "exit": "b"}
    assert execution_id(g1) != execution_id(g2)


def test_changing_exit_changes_the_id():
    """The id is built from ``exit``, so changing ``exit`` changes the
    id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g1", "entry": "a", "exit": "Y"}
    assert execution_id(g1) != execution_id(g2)


def test_changing_id_changes_the_id():
    """The id is built from ``id``, so changing ``id`` changes the id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g2", "entry": "a", "exit": "b"}
    assert execution_id(g1) != execution_id(g2)


def test_changing_entry_and_exit_together_changes_the_id():
    """Both fields are part of the id; changing either or both must
    change it."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g1", "entry": "X", "exit": "Y"}
    assert execution_id(g1) != execution_id(g2)


def test_adding_entry_to_a_graph_without_it_changes_the_id():
    """A graph without ``entry`` and a graph with ``entry`` differ in
    the canonical document and therefore in the id."""
    g1 = {"id": "g1", "exit": "b"}
    g2 = {"id": "g1", "entry": "a", "exit": "b"}
    assert execution_id(g1) != execution_id(g2)


def test_adding_exit_to_a_graph_without_it_changes_the_id():
    """A graph without ``exit`` and a graph with ``exit`` differ in
    the canonical document and therefore in the id."""
    g1 = {"id": "g1", "entry": "a"}
    g2 = {"id": "g1", "entry": "a", "exit": "b"}
    assert execution_id(g1) != execution_id(g2)


# ---------------------------------------------------------------------------
# 4. Layout metadata does not change the id.
# ---------------------------------------------------------------------------


def test_adding_layout_does_not_change_the_id():
    """``layout`` is editor state, not identity-bearing. Adding it to a
    graph must not change the id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g1", "entry": "a", "exit": "b", "layout": "tree"}
    assert execution_id(g1) == execution_id(g2)


def test_changing_layout_value_does_not_change_the_id():
    """Replacing ``layout`` with a different value still yields the same
    id — the field is editor state, not identity."""
    g1 = {"id": "g1", "entry": "a", "exit": "b", "layout": "tree"}
    g2 = {"id": "g1", "entry": "a", "exit": "b", "layout": "grid"}
    assert execution_id(g1) == execution_id(g2)


def test_adding_x_does_not_change_the_id():
    """``x`` is editor state — a node coordinate on the canvas. Adding
    it must not change the id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g1", "entry": "a", "exit": "b", "x": 100}
    assert execution_id(g1) == execution_id(g2)


def test_changing_x_value_does_not_change_the_id():
    """Moving a node on the canvas is not a semantic change."""
    g1 = {"id": "g1", "entry": "a", "exit": "b", "x": 0}
    g2 = {"id": "g1", "entry": "a", "exit": "b", "x": 9999}
    assert execution_id(g1) == execution_id(g2)


def test_adding_y_does_not_change_the_id():
    """``y`` is editor state — a node coordinate on the canvas. Adding
    it must not change the id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {"id": "g1", "entry": "a", "exit": "b", "y": -50}
    assert execution_id(g1) == execution_id(g2)


def test_changing_y_value_does_not_change_the_id():
    """Moving a node vertically is not a semantic change."""
    g1 = {"id": "g1", "entry": "a", "exit": "b", "y": 0}
    g2 = {"id": "g1", "entry": "a", "exit": "b", "y": -250}
    assert execution_id(g1) == execution_id(g2)


def test_adding_editor_does_not_change_the_id():
    """``editor`` is editor state — viewport, panels, selection. Adding
    it must not change the id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {
        "id": "g1",
        "entry": "a",
        "exit": "b",
        "editor": {"zoom": 1.5, "panels": ["left", "right"]},
    }
    assert execution_id(g1) == execution_id(g2)


def test_changing_editor_value_does_not_change_the_id():
    """Changing the editor state — zoom, selected node, panel layout —
    is not a semantic change."""
    g1 = {
        "id": "g1",
        "entry": "a",
        "exit": "b",
        "editor": {"zoom": 1.0, "selected": "n1"},
    }
    g2 = {
        "id": "g1",
        "entry": "a",
        "exit": "b",
        "editor": {"zoom": 2.5, "selected": "n9", "theme": "dark"},
    }
    assert execution_id(g1) == execution_id(g2)


def test_all_layout_fields_together_do_not_change_the_id():
    """``layout``, ``x``, ``y``, and ``editor`` are all editor state.
    Adding or changing any combination of them — including all four at
    once — must not change the id."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {
        "id": "g1",
        "entry": "a",
        "exit": "b",
        "layout": "grid",
        "x": 12,
        "y": 34,
        "editor": {"theme": "dark", "panels": ["a", "b", "c"]},
    }
    assert execution_id(g1) == execution_id(g2)


def test_nested_layout_keys_do_not_change_the_id():
    """Even if the layout metadata is deeply nested inside a list or
    mapping, the id ignores it."""
    g1 = {"id": "g1", "entry": "a", "exit": "b"}
    g2 = {
        "id": "g1",
        "entry": "a",
        "exit": "b",
        "nodes": [
            {"id": "n1", "x": 0, "y": 0, "data": "value"},
            {"id": "n2", "x": 10, "y": 10, "data": "value2"},
        ],
        "edges": [{"from": "n1", "to": "n2"}],
    }
    assert execution_id(g1) == execution_id(g2)


def test_layout_change_alongside_entry_change_changes_the_id():
    """When the layout metadata is unchanged but ``entry`` is, the id
    changes. The layout fields do not mask a real semantic change."""
    g1 = {"id": "g1", "entry": "a", "exit": "b", "layout": "tree"}
    g2 = {"id": "g1", "entry": "X", "exit": "b", "layout": "tree"}
    assert execution_id(g1) != execution_id(g2)


def test_layout_change_alongside_exit_change_changes_the_id():
    """Layout metadata does not mask a change to ``exit``."""
    g1 = {"id": "g1", "entry": "a", "exit": "b", "x": 100}
    g2 = {"id": "g1", "entry": "a", "exit": "Y", "x": 100}
    assert execution_id(g1) != execution_id(g2)


# ---------------------------------------------------------------------------
# 5. Edge cases.
# ---------------------------------------------------------------------------


def test_id_only_graph_yields_a_deterministic_id():
    """A graph with only ``id`` and layout state still has a stable id,
    and the id is unaffected by the layout state."""
    g1 = {"id": "g1"}
    g2 = {"id": "g1", "layout": "tree", "x": 5, "y": 5, "editor": {}}
    assert execution_id(g1) == execution_id(g2)
    assert len(execution_id(g1)) == 64


def test_entry_only_graph_yields_a_deterministic_id():
    """A graph with only ``entry`` and editor state has a stable id."""
    g1 = {"entry": "a"}
    g2 = {"entry": "a", "x": 100, "y": 200, "layout": "grid"}
    assert execution_id(g1) == execution_id(g2)


def test_exit_only_graph_yields_a_deterministic_id():
    """A graph with only ``exit`` and editor state has a stable id."""
    g1 = {"exit": "b"}
    g2 = {"exit": "b", "editor": {"zoom": 1.0}}
    assert execution_id(g1) == execution_id(g2)


def test_empty_graph_yields_a_deterministic_id():
    """An empty graph is a valid input and yields a deterministic id."""
    assert len(execution_id({})) == 64
    assert execution_id({}) == execution_id({})


def test_empty_graph_with_layout_metadata_yields_the_same_id():
    """Adding layout metadata to an empty graph does not change the id."""
    assert execution_id({}) == execution_id({"layout": "tree", "x": 0, "y": 0, "editor": {}})


def test_graph_with_only_arbitrary_keys_yields_a_deterministic_id():
    """A graph whose only fields are not in the identity-bearing set
    has a stable id regardless of what those fields carry."""
    g1 = {"foo": "bar"}
    g2 = {"foo": "completely different value", "extra": [1, 2, 3]}
    assert execution_id(g1) == execution_id(g2)


def test_value_of_entry_can_be_arbitrary_json():
    """``entry`` can carry an arbitrary JSON value — string, dict,
    list, number, boolean, null — without breaking the function."""
    base = {"id": "g1", "exit": "b"}
    cases = [
        "a",
        {"all": [{"op": ">", "lhs": "close", "rhs": 100}]},
        [1, 2, 3],
        42,
        3.14,
        True,
        False,
        None,
    ]
    ids = {execution_id({**base, "entry": value}) for value in cases}
    assert len(ids) == len(cases), f"each distinct entry value must yield a distinct id; got collisions: {ids}"


def test_value_of_exit_can_be_arbitrary_json():
    """``exit`` can carry an arbitrary JSON value — string, dict,
    list, number, boolean, null — without breaking the function."""
    base = {"id": "g1", "entry": "a"}
    cases = [
        "b",
        {"any": [{"op": "<", "lhs": "rsi", "rhs": 30}]},
        [4, 5, 6],
        99,
        2.71,
        True,
        False,
        None,
    ]
    ids = {execution_id({**base, "exit": value}) for value in cases}
    assert len(ids) == len(cases), f"each distinct exit value must yield a distinct id; got collisions: {ids}"


def test_value_of_id_can_be_arbitrary_json():
    """``id`` can carry an arbitrary JSON value — string, number, etc —
    without breaking the function."""
    base = {"entry": "a", "exit": "b"}
    cases = [
        "g1",
        "another-strategy",
        1,
        42,
        3.14,
        True,
        False,
        None,
    ]
    ids = {execution_id({**base, "id": value}) for value in cases}
    assert len(ids) == len(cases), f"each distinct id value must yield a distinct execution id; got collisions: {ids}"


def test_non_mapping_graph_raises_type_error():
    """A non-mapping graph is not a valid graph. The function raises
    ``TypeError`` rather than guessing at intent."""
    for bad in [None, "not a graph", 42, [1, 2, 3], ("a", "b")]:
        with pytest.raises(TypeError):
            execution_id(bad)


def test_entry_equal_to_exit_yields_a_distinct_id_from_id_only():
    """A graph with ``entry == exit`` is a different canonical document
    from a graph with the same ``id`` and no entry/exit, because the
    document still carries both fields when present."""
    g1 = {"id": "g1"}
    g2 = {"id": "g1", "entry": "x", "exit": "x"}
    assert execution_id(g1) != execution_id(g2)


# ---------------------------------------------------------------------------
# 6. Module / signature shape and isolation.
# ---------------------------------------------------------------------------


def test_execution_id_is_exposed_at_strategy_ir_identity():
    """``execution_id`` is importable from
    ``krellbot.strategy_ir.identity``. The module is the brief's pinned
    location for the predicate."""
    assert hasattr(identity_mod, "execution_id")
    assert callable(identity_mod.execution_id)


def test_execution_id_signature_is_graph_only():
    """The brief pins the signature as ``execution_id(graph)``. No
    extra positional or keyword parameters beyond the one input."""
    sig = inspect.signature(execution_id)
    assert list(sig.parameters) == ["graph"]


def test_execution_id_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``execution_id`` so callers
    can reach the function through the package surface, the same way
    the NS19a predicate is exposed via ``krellbot.strategy_ir``."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "execution_id")
    assert strategy_ir_pkg.execution_id is identity_mod.execution_id


def test_identity_module_does_not_import_venues_or_evaluate():
    """``krellbot.strategy_ir.identity`` is a pure predicate. The brief
    forbids importing ``krellbot.venues`` or
    ``krellbot.pack.evaluate`` — the module has nothing to do with
    venues or pack evaluation."""
    source = inspect.getsource(identity_mod)
    tree = ast.parse(source)
    forbidden_modules = {
        "krellbot.venues",
        "krellbot.pack.evaluate",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(alias.name == m or alias.name.startswith(m + ".") for m in forbidden_modules), (
                    f"identity module imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"identity module does a from-import from {node.module!r}"
            )


def test_strategy_ir_package_does_not_import_venues_or_evaluate():
    """The package ``__init__`` does not pull ``krellbot.venues`` or
    ``krellbot.pack.evaluate`` into the IR layer. The identity module
    is a pure predicate and the package surface stays pure as a
    consequence."""
    import krellbot.strategy_ir as strategy_ir_pkg

    source = inspect.getsource(strategy_ir_pkg)
    tree = ast.parse(source)
    forbidden_modules = {
        "krellbot.venues",
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

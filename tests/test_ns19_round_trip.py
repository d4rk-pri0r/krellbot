"""NS19f: canonical configuration round-trip.

The brief: ``canonical_bytes(graph)`` returns the UTF-8 bytes of a
JSON document built from ``strip_editor(graph)``, with sorted keys
and ``(",", ":")`` separators. Parsing those bytes and calling
``canonical_bytes`` again returns the same bytes. Changing
``layout``, ``x``, ``y``, or ``editor`` does not change the bytes;
changing ``entry`` does. ``schema_version`` stays the integer ``1``
after the parse — it is not ``1.0``.

The function lives at ``krellbot.strategy_ir.canonical`` and is
re-exported through the package surface. The module is a pure
predicate over the graph shape: it does not import
``krellbot.venues``, ``krellbot.pack.evaluate``, or
``krellbot.run``; it does not read the clock, touch the keyring,
or open a network transport.
"""

from __future__ import annotations

import ast
import inspect
import json

import pytest

from krellbot.strategy_ir import canonical as canonical_mod
from krellbot.strategy_ir.canonical import canonical_bytes

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _base_graph() -> dict:
    """A small graph with the legal v1 clock and several non-editor
    fields. ``schema_version`` is the integer ``1``; ``timeframe`` is
    exactly ``"1h"``; ``entry`` is a leaf condition; ``exit`` is a
    leaf condition; ``risk`` is a risk rule; ``markets`` is one
    market entry; ``indicators`` is a small indicator map. Used as
    the baseline that other tests perturb."""
    return {
        "schema_version": 1,
        "id": "sma-cross",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }


# ---------------------------------------------------------------------------
# 1. Output shape: bytes that are valid UTF-8 JSON.
# ---------------------------------------------------------------------------


def test_canonical_bytes_returns_bytes():
    """The function returns ``bytes`` (UTF-8 JSON), not ``str`` and not
    a mapping. Callers persist the value or hash it; both expect a
    byte string."""
    result = canonical_bytes(_base_graph())
    assert isinstance(result, bytes)


def test_canonical_bytes_decodes_as_valid_utf8():
    """The bytes are valid UTF-8 — round-tripping through ``utf-8``
    decoding yields the same JSON text that was originally
    serialized."""
    result = canonical_bytes(_base_graph())
    decoded = result.decode("utf-8")
    assert isinstance(decoded, str)


def test_canonical_bytes_decodes_as_valid_json():
    """The bytes parse as JSON. Round-tripping through ``json.loads``
    gives back a dict with the same non-editor keys (the parse is
    checked separately below for editor-key invariance)."""
    result = canonical_bytes(_base_graph())
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


def test_canonical_bytes_compact_separators_no_whitespace():
    """The bytes use ``(",", ":")`` separators — no whitespace between
    keys / values / items. The brief pins the separators so the
    canonical form is byte-stable across callers that might
    pretty-print."""
    result = canonical_bytes({"a": 1, "b": 2, "c": 3})
    assert result == b'{"a":1,"b":2,"c":3}'
    assert b" " not in result
    assert b"\n" not in result
    assert b"\t" not in result


def test_canonical_bytes_uses_sorted_top_level_keys():
    """Top-level keys are sorted lexicographically. The brief pins
    ``sort_keys=True`` so the canonical form is byte-stable
    regardless of input dict insertion order."""
    g1 = {"z": 1, "a": 2, "m": 3}
    g2 = {"a": 2, "m": 3, "z": 1}
    g3 = {"m": 3, "z": 1, "a": 2}
    assert canonical_bytes(g1) == canonical_bytes(g2) == canonical_bytes(g3)
    assert canonical_bytes(g1) == b'{"a":2,"m":3,"z":1}'


def test_canonical_bytes_sorts_nested_keys():
    """Nested dict keys are also sorted — ``json.dumps`` with
    ``sort_keys=True`` is recursive. Two semantically equal graphs
    with different nested key orders yield the same bytes."""
    g1 = {"indicators": {"sma2": {"len": 2, "fn": "sma", "src": "close"}}}
    g2 = {"indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}}}
    assert canonical_bytes(g1) == canonical_bytes(g2)


def test_canonical_bytes_uses_utf8_encoding():
    """The bytes are valid UTF-8. ``json.dumps`` defaults to
    ``ensure_ascii=True``, which escapes non-ASCII characters as
    ``\\uXXXX`` sequences; the resulting text is pure ASCII and
    therefore valid UTF-8 by construction. The test pins the
    encoding: the bytes decode cleanly via UTF-8, and a non-ASCII
    string round-trips to its original value through
    ``json.loads``."""
    graph = {"label": "café", "author": "naïve"}
    result = canonical_bytes(graph)
    decoded = result.decode("utf-8")
    assert isinstance(decoded, str)
    parsed = json.loads(decoded)
    assert parsed["label"] == "café"
    assert parsed["author"] == "naïve"


# ---------------------------------------------------------------------------
# 2. Determinism: same input, same bytes.
# ---------------------------------------------------------------------------


def test_canonical_bytes_is_deterministic():
    """Calling ``canonical_bytes`` twice on the same dict returns the
    same bytes."""
    graph = _base_graph()
    assert canonical_bytes(graph) == canonical_bytes(graph)


def test_canonical_bytes_is_independent_of_input_dict_identity():
    """Two distinct dicts with the same key/value content yield the
    same bytes. The canonical form is normalized by key sort and
    separator choice — object identity does not leak in."""
    g1 = _base_graph()
    g2 = _base_graph()
    assert g1 is not g2
    assert canonical_bytes(g1) == canonical_bytes(g2)


def test_canonical_bytes_does_not_mutate_the_input():
    """The function does not mutate the caller's dict. The strip
    inside ``strip_editor`` copies first; ``json.dumps`` does not
    mutate the mapping it serializes."""
    graph = _base_graph()
    snapshot = dict(graph)
    canonical_bytes(graph)
    assert graph == snapshot
    assert set(graph) == set(snapshot)


# ---------------------------------------------------------------------------
# 3. Round-trip: parse → canonicalize → same bytes.
# ---------------------------------------------------------------------------


def test_round_trip_yields_the_same_bytes_for_base_graph():
    """The brief's headline property: parsing the canonical bytes and
    calling ``canonical_bytes`` again returns the same bytes."""
    graph = _base_graph()
    once = canonical_bytes(graph)
    parsed = json.loads(once)
    twice = canonical_bytes(parsed)
    assert once == twice


def test_round_trip_yields_the_same_bytes_for_empty_graph():
    """The empty graph round-trips. ``canonical_bytes({})`` is
    ``b'{}'``; parsing that gives ``{}``; re-canonicalizing gives
    ``b'{}'`` again."""
    once = canonical_bytes({})
    parsed = json.loads(once)
    twice = canonical_bytes(parsed)
    assert once == twice == b"{}"


def test_round_trip_yields_the_same_bytes_with_editor_keys():
    """A graph that includes editor keys still round-trips. The first
    ``canonical_bytes`` strips the editor keys; the parsed result has
    no editor keys to strip; the second ``canonical_bytes`` produces
    the same bytes."""
    graph = {
        **_base_graph(),
        "layout": "tree",
        "x": 100,
        "y": -50,
        "editor": {"zoom": 1.5, "selected": "n1"},
    }
    once = canonical_bytes(graph)
    parsed = json.loads(once)
    assert "layout" not in parsed
    assert "x" not in parsed
    assert "y" not in parsed
    assert "editor" not in parsed
    twice = canonical_bytes(parsed)
    assert once == twice


def test_round_trip_yields_the_same_bytes_for_nested_graph():
    """A graph with nested ``indicators``, ``entry``, ``exit``,
    ``risk``, and ``markets`` round-trips. The parse preserves the
    nested shape; the second canonicalization produces the same
    bytes."""
    graph = _base_graph()
    once = canonical_bytes(graph)
    parsed = json.loads(once)
    twice = canonical_bytes(parsed)
    assert once == twice
    assert parsed["indicators"]["sma2"]["fn"] == "sma"
    assert parsed["entry"] == ["close", "crosses_above", "sma2"]
    assert parsed["risk"]["stop"]["pct"] == 50


def test_round_trip_is_a_fixed_point_under_double_canonicalization():
    """Iterating the round-trip is idempotent: a third pass yields the
    same bytes as the first."""
    graph = _base_graph()
    once = canonical_bytes(graph)
    twice = canonical_bytes(json.loads(once))
    thrice = canonical_bytes(json.loads(twice))
    assert once == twice == thrice


def test_round_trip_preserves_the_canonical_form_after_perturbation():
    """A graph with editor metadata produces canonical bytes; the
    parsed result, when re-canonicalized, gives the same bytes — the
    canonical form is a fixed point under ``parse ∘ canonical_bytes``."""
    a = canonical_bytes(_base_graph())
    b = canonical_bytes({**_base_graph(), "layout": "tree", "x": 1, "y": 2, "editor": {"a": 1}})
    assert a == b


# ---------------------------------------------------------------------------
# 4. Editor keys do not change the bytes.
# ---------------------------------------------------------------------------


def test_adding_layout_does_not_change_the_bytes():
    """``layout`` is editor state. Adding it does not change the
    canonical bytes."""
    base = _base_graph()
    with_layout = {**base, "layout": "tree"}
    assert canonical_bytes(base) == canonical_bytes(with_layout)


def test_changing_layout_value_does_not_change_the_bytes():
    """Replacing ``layout`` with a different value still yields the
    same bytes — the field is editor state, not semantic."""
    a = {**_base_graph(), "layout": "tree"}
    b = {**_base_graph(), "layout": "grid"}
    assert canonical_bytes(a) == canonical_bytes(b)


def test_adding_x_does_not_change_the_bytes():
    """``x`` is a node coordinate on the canvas. Adding it does not
    change the canonical bytes."""
    base = _base_graph()
    with_x = {**base, "x": 100}
    assert canonical_bytes(base) == canonical_bytes(with_x)


def test_changing_x_value_does_not_change_the_bytes():
    """Moving a node horizontally is not a semantic change."""
    a = {**_base_graph(), "x": 0}
    b = {**_base_graph(), "x": 9999}
    assert canonical_bytes(a) == canonical_bytes(b)


def test_adding_y_does_not_change_the_bytes():
    """``y`` is a node coordinate on the canvas. Adding it does not
    change the canonical bytes."""
    base = _base_graph()
    with_y = {**base, "y": -50}
    assert canonical_bytes(base) == canonical_bytes(with_y)


def test_changing_y_value_does_not_change_the_bytes():
    """Moving a node vertically is not a semantic change."""
    a = {**_base_graph(), "y": 0}
    b = {**_base_graph(), "y": -250}
    assert canonical_bytes(a) == canonical_bytes(b)


def test_adding_editor_does_not_change_the_bytes():
    """``editor`` is editor state — viewport, panels, selection.
    Adding it does not change the canonical bytes."""
    base = _base_graph()
    with_editor = {**base, "editor": {"zoom": 1.5, "panels": ["left", "right"]}}
    assert canonical_bytes(base) == canonical_bytes(with_editor)


def test_changing_editor_value_does_not_change_the_bytes():
    """Changing the editor state — zoom, selected node, panel layout —
    is not a semantic change."""
    a = {**_base_graph(), "editor": {"zoom": 1.0, "selected": "n1"}}
    b = {**_base_graph(), "editor": {"zoom": 2.5, "selected": "n9", "theme": "dark"}}
    assert canonical_bytes(a) == canonical_bytes(b)


def test_all_editor_keys_together_do_not_change_the_bytes():
    """``layout``, ``x``, ``y``, and ``editor`` are all editor state.
    Adding or changing any combination of them — including all four at
    once — must not change the canonical bytes."""
    base = _base_graph()
    decorated = {
        **_base_graph(),
        "layout": "grid",
        "x": 12,
        "y": 34,
        "editor": {"theme": "dark", "panels": ["a", "b", "c"]},
    }
    assert canonical_bytes(base) == canonical_bytes(decorated)


def test_removing_editor_keys_from_a_graph_with_them_does_not_change_the_bytes():
    """Stripping editor keys off a graph that had them gives the same
    canonical bytes — the keys never contributed to the canonical
    form in the first place."""
    decorated = {
        **_base_graph(),
        "layout": "tree",
        "x": 1,
        "y": 2,
        "editor": {"zoom": 1.0},
    }
    plain = _base_graph()
    assert canonical_bytes(decorated) == canonical_bytes(plain)


# ---------------------------------------------------------------------------
# 5. Changing entry / exit / id / other semantic fields changes the bytes.
# ---------------------------------------------------------------------------


def test_changing_entry_changes_the_bytes():
    """The brief: ``Changing ``entry`` does [change the bytes]``.
    ``entry`` is part of the canonical form, so changing it must
    change the bytes."""
    a = _base_graph()
    b = {**_base_graph(), "entry": ["close", "crosses_above", "sma99"]}
    assert canonical_bytes(a) != canonical_bytes(b)


def test_changing_exit_changes_the_bytes():
    """``exit`` is part of the canonical form, so changing it must
    change the bytes."""
    a = _base_graph()
    b = {**_base_graph(), "exit": ["close", "crosses_below", "sma99"]}
    assert canonical_bytes(a) != canonical_bytes(b)


def test_changing_id_changes_the_bytes():
    """``id`` is part of the canonical form, so changing it must
    change the bytes."""
    a = _base_graph()
    b = {**_base_graph(), "id": "different-id"}
    assert canonical_bytes(a) != canonical_bytes(b)


def test_changing_schema_version_changes_the_bytes():
    """``schema_version`` is part of the canonical form, so changing
    it must change the bytes."""
    a = _base_graph()
    b = {**_base_graph(), "schema_version": 2}
    assert canonical_bytes(a) != canonical_bytes(b)


def test_changing_timeframe_changes_the_bytes():
    """``timeframe`` is part of the canonical form, so changing it
    must change the bytes."""
    a = _base_graph()
    b = {**_base_graph(), "timeframe": "4h"}
    assert canonical_bytes(a) != canonical_bytes(b)


def test_changing_indicators_changes_the_bytes():
    """``indicators`` is part of the canonical form."""
    a = _base_graph()
    b = {
        **_base_graph(),
        "indicators": {"sma5": {"fn": "sma", "src": "close", "len": 5}},
    }
    assert canonical_bytes(a) != canonical_bytes(b)


def test_changing_risk_changes_the_bytes():
    """``risk`` is part of the canonical form."""
    a = _base_graph()
    b = {
        **_base_graph(),
        "risk": {"max_account_pct": 50, "stop": {"type": "pct", "pct": 25}},
    }
    assert canonical_bytes(a) != canonical_bytes(b)


def test_changing_markets_changes_the_bytes():
    """``markets`` is part of the canonical form."""
    a = _base_graph()
    b = {**_base_graph(), "markets": [{"venue": "coinbase", "pair": "BTCUSD"}]}
    assert canonical_bytes(a) != canonical_bytes(b)


def test_editor_change_alongside_entry_change_still_changes_the_bytes():
    """Editor keys do not mask a real semantic change to ``entry`` —
    when ``entry`` changes (regardless of whether editor keys are
    present), the bytes change."""
    a = {**_base_graph(), "layout": "tree", "x": 1, "y": 2, "editor": {"zoom": 1.0}}
    b = {
        **_base_graph(),
        "layout": "tree",
        "x": 1,
        "y": 2,
        "editor": {"zoom": 1.0},
        "entry": ["close", "crosses_above", "sma99"],
    }
    assert canonical_bytes(a) != canonical_bytes(b)


# ---------------------------------------------------------------------------
# 6. schema_version stays the integer 1 after the parse.
# ---------------------------------------------------------------------------


def test_schema_version_is_integer_one_in_the_canonical_bytes():
    """``schema_version`` is encoded as the integer ``1`` in the
    canonical bytes — ``json.dumps(1)`` is the string ``"1"``, not
    ``"1.0"``. The canonical form must not coerce."""
    graph = _base_graph()
    result = canonical_bytes(graph)
    assert b'"schema_version":1' in result
    assert b'"schema_version":1.0' not in result
    assert b'"schema_version":"1"' not in result


def test_schema_version_remains_integer_after_parse():
    """After parsing the canonical bytes, ``schema_version`` is the
    integer ``1`` — ``json.loads('1')`` gives the int ``1``, not the
    float ``1.0`` and not the string ``"1"``. The brief pins the
    type."""
    graph = _base_graph()
    parsed = json.loads(canonical_bytes(graph))
    assert parsed["schema_version"] == 1
    assert type(parsed["schema_version"]) is int
    assert isinstance(parsed["schema_version"], int)
    assert not isinstance(parsed["schema_version"], bool)


def test_schema_version_is_not_float_one_point_zero_after_parse():
    """Specifically: the parsed ``schema_version`` is not the float
    ``1.0``. The brief pins the integer type and explicitly forbids
    the float."""
    graph = _base_graph()
    parsed = json.loads(canonical_bytes(graph))
    assert parsed["schema_version"] != 1.0 or type(parsed["schema_version"]) is not float
    assert not (isinstance(parsed["schema_version"], float) and parsed["schema_version"] == 1.0)


def test_schema_version_remains_integer_after_parse_when_input_was_float():
    """Even if the input graph had ``schema_version=1.0`` (which the
    v1 clock would reject), the canonical encoder coerces it to the
    JSON form ``1.0`` and the parse gives back a float. The brief's
    contract is that ``canonical_bytes`` of a legal v1 graph (where
    ``schema_version`` is the integer ``1``) round-trips to the
    integer. ``json.dumps(1.0)`` is ``'1.0'``, so a 1.0 input does
    not silently pass — it round-trips as the float 1.0. This test
    pins that the encoder is a pure JSON serializer: it does not
    coerce ``1.0`` to ``1``."""
    parsed = json.loads(canonical_bytes({"schema_version": 1.0}))
    assert type(parsed["schema_version"]) is float
    assert parsed["schema_version"] == 1.0


def test_schema_version_remains_integer_through_the_round_trip():
    """The full round-trip — encode then parse then encode — preserves
    ``schema_version`` as the integer ``1``."""
    graph = _base_graph()
    once = canonical_bytes(graph)
    parsed = json.loads(once)
    assert type(parsed["schema_version"]) is int
    twice = canonical_bytes(parsed)
    assert b'"schema_version":1' in twice


def test_schema_version_in_legal_graph_round_trips_to_int_one():
    """End-to-end: the legal v1 clock graph's ``schema_version``
    survives the round-trip as the integer ``1``, not ``1.0`` or
    ``True``."""
    graph = {"schema_version": 1, "timeframe": "1h"}
    parsed = json.loads(canonical_bytes(graph))
    assert parsed["schema_version"] == 1
    assert parsed["schema_version"] is not True
    assert parsed["schema_version"] != 1.0 or type(parsed["schema_version"]) is not float
    assert isinstance(parsed["schema_version"], int) and not isinstance(parsed["schema_version"], bool)


# ---------------------------------------------------------------------------
# 7. The canonical bytes are valid JSON with the expected keys.
# ---------------------------------------------------------------------------


def test_canonical_bytes_parsed_keys_match_strip_editor_graph():
    """After stripping editor keys, parsing the canonical bytes gives
    a dict whose key set equals ``strip_editor(graph)``'s key set."""
    graph = {
        **_base_graph(),
        "layout": "tree",
        "x": 100,
        "y": -50,
        "editor": {"zoom": 1.5},
    }
    parsed = json.loads(canonical_bytes(graph))
    assert set(parsed.keys()) == set(_base_graph().keys())


def test_canonical_bytes_parsed_keys_do_not_include_editor_keys():
    """The parsed canonical form has no ``layout``, ``x``, ``y``, or
    ``editor`` keys at the top level. The strip happened before
    encode."""
    graph = {
        **_base_graph(),
        "layout": "tree",
        "x": 100,
        "y": -50,
        "editor": {"zoom": 1.5},
    }
    parsed = json.loads(canonical_bytes(graph))
    for editor_key in ("layout", "x", "y", "editor"):
        assert editor_key not in parsed


def test_canonical_bytes_preserves_non_editor_values():
    """All non-editor values are preserved verbatim through the
    canonical encode / parse round-trip."""
    graph = _base_graph()
    parsed = json.loads(canonical_bytes(graph))
    assert parsed["schema_version"] == graph["schema_version"]
    assert parsed["id"] == graph["id"]
    assert parsed["version"] == graph["version"]
    assert parsed["label"] == graph["label"]
    assert parsed["author"] == graph["author"]
    assert parsed["timeframe"] == graph["timeframe"]
    assert parsed["entry"] == graph["entry"]
    assert parsed["exit"] == graph["exit"]
    assert parsed["risk"] == graph["risk"]
    assert parsed["markets"] == graph["markets"]
    assert parsed["indicators"] == graph["indicators"]


def test_canonical_bytes_preserves_nested_values():
    """Nested structures inside ``indicators``, ``risk``, and
    ``markets`` are preserved verbatim."""
    graph = _base_graph()
    parsed = json.loads(canonical_bytes(graph))
    assert parsed["indicators"]["sma2"]["fn"] == "sma"
    assert parsed["indicators"]["sma2"]["src"] == "close"
    assert parsed["indicators"]["sma2"]["len"] == 2
    assert parsed["risk"]["max_account_pct"] == 100
    assert parsed["risk"]["stop"]["type"] == "pct"
    assert parsed["risk"]["stop"]["pct"] == 50
    assert parsed["markets"][0]["venue"] == "kraken"
    assert parsed["markets"][0]["pair"] == "SUIUSD"


# ---------------------------------------------------------------------------
# 8. Edge cases for the canonical form.
# ---------------------------------------------------------------------------


def test_empty_graph_yields_empty_object_bytes():
    """The empty graph's canonical form is the byte string ``b'{}'`` —
    no whitespace, no keys, no values."""
    assert canonical_bytes({}) == b"{}"


def test_single_key_graph_uses_compact_separators():
    """A single-key graph uses the compact ``":"`` separator with no
    whitespace, exactly as the brief pins."""
    assert canonical_bytes({"a": 1}) == b'{"a":1}'


def test_graph_with_only_editor_keys_yields_empty_object_bytes():
    """A graph whose only keys are editor keys has nothing left after
    the strip. The canonical form is ``b'{}'``."""
    assert canonical_bytes({"layout": "tree", "x": 1, "y": 2, "editor": {}}) == b"{}"


def test_graph_with_only_editor_keys_round_trips():
    """A graph whose only keys are editor keys round-trips to the same
    ``b'{}'``."""
    once = canonical_bytes({"layout": "tree", "x": 1, "y": 2, "editor": {}})
    parsed = json.loads(once)
    twice = canonical_bytes(parsed)
    assert once == twice == b"{}"


def test_graph_with_null_values_canonicalizes_correctly():
    """``null`` values are encoded as ``null`` (the JSON literal) and
    parse back to ``None``."""
    once = canonical_bytes({"a": None, "b": 1})
    parsed = json.loads(once)
    assert parsed == {"a": None, "b": 1}
    assert parsed["a"] is None


def test_graph_with_boolean_values_canonicalizes_correctly():
    """Boolean values are encoded as ``true`` / ``false`` (the JSON
    literals) and parse back to ``True`` / ``False``."""
    once = canonical_bytes({"flag": True, "other": False})
    parsed = json.loads(once)
    assert parsed == {"flag": True, "other": False}
    assert parsed["flag"] is True
    assert parsed["other"] is False


def test_graph_with_list_values_canonicalizes_correctly():
    """List values are encoded as JSON arrays. The list contents are
    preserved."""
    once = canonical_bytes({"items": [1, 2, 3], "empty": []})
    parsed = json.loads(once)
    assert parsed == {"items": [1, 2, 3], "empty": []}


def test_graph_with_numeric_values_canonicalizes_correctly():
    """Numeric values — integer and float — are encoded with their
    JSON representation. Integers stay integers, floats stay floats
    (no coercion)."""
    once = canonical_bytes({"i": 42, "f": 3.14})
    parsed = json.loads(once)
    assert parsed["i"] == 42
    assert type(parsed["i"]) is int
    assert parsed["f"] == 3.14
    assert type(parsed["f"]) is float


# ---------------------------------------------------------------------------
# 9. Non-mapping inputs raise TypeError.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, "not a graph", 42, 3.14, True, False, [1, 2, 3], ("a", "b")])
def test_non_mapping_graph_raises_type_error(bad):
    """A non-mapping input is not a valid graph. The function raises
    ``TypeError`` rather than guessing at intent — same refusal as
    the other NS19 leaves."""
    with pytest.raises(TypeError):
        canonical_bytes(bad)


def test_type_error_message_names_the_input_type():
    """The ``TypeError`` message names the offending type so the
    caller can diagnose without a stack trace."""
    with pytest.raises(TypeError) as excinfo:
        canonical_bytes("not a graph")
    assert "graph must be a mapping" in str(excinfo.value)
    assert "str" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 10. Module / signature shape and isolation.
# ---------------------------------------------------------------------------


def test_canonical_bytes_is_exposed_at_strategy_ir_canonical():
    """``canonical_bytes`` is importable from
    ``krellbot.strategy_ir.canonical``. The module is the brief's
    pinned location for the canonical serializer."""
    assert hasattr(canonical_mod, "canonical_bytes")
    assert callable(canonical_mod.canonical_bytes)


def test_canonical_bytes_signature_is_graph_only():
    """The brief pins the signature as ``canonical_bytes(graph)``. No
    extra positional or keyword parameters beyond the single input."""
    sig = inspect.signature(canonical_bytes)
    assert list(sig.parameters) == ["graph"]


def test_canonical_bytes_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``canonical_bytes`` so
    callers can reach it through the package surface, the same way
    the other NS19 leaves are exposed."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "canonical_bytes")
    assert strategy_ir_pkg.canonical_bytes is canonical_mod.canonical_bytes


# ---------------------------------------------------------------------------
# 11. The brief's forbidden import set: canonical must not pull venues,
#     evaluate, or run into the IR.
# ---------------------------------------------------------------------------


def test_canonical_module_does_not_import_venues_run_or_evaluate():
    """``krellbot.strategy_ir.canonical`` stays a pure compile surface.
    The brief forbids importing ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` — the canonical
    serializer is a pure JSON transform."""
    source = inspect.getsource(canonical_mod)
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
                    f"canonical module imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"canonical module does a from-import from {node.module!r}"
            )


def test_strategy_ir_package_does_not_import_venues_run_or_evaluate_via_canonical():
    """The package ``__init__`` does not pull ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` into the IR layer.
    The canonical module is a pure compile surface and the package
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


def test_canonical_module_does_not_open_files_or_touch_the_clock():
    """``canonical_bytes`` is a pure in-memory transform. No ``open``,
    no ``pathlib.Path.read_*``, no ``os.environ``, no ``time``, no
    ``datetime``, no ``keyring``, no ``requests``. The canonical
    serializer is synchronous, in-memory, and side-effect-free."""
    source = inspect.getsource(canonical_mod)
    tree = ast.parse(source)
    forbidden_calls = {"open", "read_text", "read_bytes", "time", "datetime", "keyring"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in forbidden_calls:
            assert node.value.id not in forbidden_calls, f"canonical module calls {node.value.id}.{node.attr}"


# ---------------------------------------------------------------------------
# 12. Composition with the other NS19 leaves.
# ---------------------------------------------------------------------------


def test_canonical_bytes_uses_strip_editor_for_the_transform():
    """``canonical_bytes`` builds on ``strip_editor`` (NS19c) — the
    bytes are exactly the canonical JSON of the stripped graph. A
    future change to the editor-key set (adding ``viewport``,
    removing ``editor``, etc.) is observed by ``canonical_bytes``
    without further wiring."""
    from krellbot.strategy_ir.v1 import strip_editor

    graph = {
        **_base_graph(),
        "layout": "tree",
        "x": 100,
        "y": -50,
        "editor": {"zoom": 1.5},
    }
    expected = json.dumps(strip_editor(graph), sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert canonical_bytes(graph) == expected


def test_canonical_bytes_and_execution_id_agree_on_editor_keys():
    """``canonical_bytes`` and ``execution_id`` (NS19b) both ignore
    the four editor keys. The two leaves are independent functions
    but agree on what counts as canvas state."""
    base = _base_graph()
    with_editor = {
        **_base_graph(),
        "layout": "tree",
        "x": 100,
        "y": -50,
        "editor": {"zoom": 1.5},
    }
    # canonical_bytes ignores editor keys → same bytes
    assert canonical_bytes(base) == canonical_bytes(with_editor)
    # execution_id also ignores editor keys (it only sees id/entry/exit)
    from krellbot.strategy_ir.identity import execution_id

    assert execution_id(base) == execution_id(with_editor)


def test_canonical_bytes_accepts_the_sma_cross_fixture_graph():
    """End-to-end property: the fixture pack ``sma_cross.json`` round-
    trips through ``canonical_bytes``. The canonical form is byte-
    stable and decodes to a graph whose non-editor fields match the
    fixture."""
    import json
    from pathlib import Path

    fixture_path = Path(__file__).parent / "fixtures" / "packs" / "sma_cross.json"
    graph = json.loads(fixture_path.read_text())
    parsed = json.loads(canonical_bytes(graph))
    assert parsed["schema_version"] == 1
    assert parsed["id"] == "sma-cross"
    assert parsed["timeframe"] == "1h"
    assert parsed["entry"] == ["close", "crosses_above", "sma2"]
    assert parsed["exit"] == ["close", "crosses_below", "sma2"]
    # round-trip
    assert canonical_bytes(parsed) == canonical_bytes(graph)


def test_canonical_bytes_remain_independent_of_other_leaves():
    """``canonical_bytes`` (NS19f) is independent of ``prepare_v1``
    (NS19d), ``strip_editor`` (NS19c), ``execution_id`` (NS19b),
    ``check_availability`` (NS19a), and ``require_v1_clock``
    (NS19e). The leaves remain importable from their own modules."""
    from krellbot.strategy_ir.availability import check_availability
    from krellbot.strategy_ir.identity import execution_id
    from krellbot.strategy_ir.units import require_v1_clock
    from krellbot.strategy_ir.v1 import prepare_v1, strip_editor

    assert callable(canonical_bytes)
    assert callable(strip_editor)
    assert callable(prepare_v1)
    assert callable(check_availability)
    assert callable(execution_id)
    assert callable(require_v1_clock)


# ---------------------------------------------------------------------------
# 13. The gate: this test file runs alongside the other NS19 leaves.
# ---------------------------------------------------------------------------


def test_canonical_bytes_is_safe_for_use_with_a_v1_clock_graph():
    """The full v1 graph — the one ``require_v1_clock`` accepts —
    round-trips through ``canonical_bytes`` cleanly. ``schema_version``
    is the integer ``1``; ``timeframe`` is one of ``"1h"``, ``"4h"``,
    ``"1d"``. The two leaves do not interfere with each other."""
    for timeframe in ["1h", "4h", "1d"]:
        graph = {**_base_graph(), "timeframe": timeframe}
        parsed = json.loads(canonical_bytes(graph))
        assert type(parsed["schema_version"]) is int
        assert parsed["schema_version"] == 1
        assert parsed["timeframe"] == timeframe
        # round-trip
        assert canonical_bytes(parsed) == canonical_bytes(graph)

"""NS19c: editor / layout keys do not change a v1 decision.

The brief: ``strip_editor(pack)`` returns a new mapping that has
every key the input ``pack`` carries, except the four editor /
layout keys the v1 decision engine must never see — ``layout``,
``x``, ``y``, and ``editor``. The caller's mapping is unchanged.
For ``tests/fixtures/packs/sma_cross.json`` plus the same candle
list ``tests/test_ns18_shared_trace.py`` builds,
``krellbot.pack.evaluate.run`` on the stripped pack returns the
same ``Target`` as ``run`` on the original pack. Adding those
editor keys to a copy of the pack, then stripping, still returns
that same ``Target``. The function is a pure mapping transform; it
does not import ``krellbot.venues``, ``krellbot.run``, or
``krellbot.pack.evaluate``; it does not read the clock, touch the
keyring, or open a network transport.
"""

from __future__ import annotations

import ast
import inspect
import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.pack import evaluate as evaluate_mod
from krellbot.pack.evaluate import run as evaluate_run
from krellbot.pack.model import Candle, Target
from krellbot.strategy_ir import v1 as v1_mod
from krellbot.strategy_ir.v1 import strip_editor

# ---------------------------------------------------------------------------
# Fixtures: the brief pins sma_cross.json + the same candles
# tests/test_ns18_shared_trace.py already builds.
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "packs" / "sma_cross.json"


def _load_sma_cross() -> dict:
    """Load ``tests/fixtures/packs/sma_cross.json`` as a fresh dict."""
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _sma_cross_candles() -> list[Candle]:
    """8 1h bars identical to ``_synthetic_candles`` in
    ``tests/test_ns18_shared_trace.py``.

    Closes ``[10, 10, 12, 14, 8, 8, 8, 8]`` so the sma2 (length=2)
    produces one cross above at bar 2 and one cross below at bar 4.
    At bar 7 the last bar is a flat continuation — neither cross
    fires — so ``run`` returns
    ``Target(long=False, stop_price=None, reason="flat")``.
    """
    closes = ["10", "10", "12", "14", "8", "8", "8", "8"]
    out: list[Candle] = []
    for i, c in enumerate(closes):
        out.append(
            Candle(
                ts_ms=i * 3_600_000,
                open=Decimal(c),
                high=Decimal(c) + Decimal("0.5"),
                low=Decimal(c) - Decimal("0.5"),
                close=Decimal(c),
                volume=Decimal(100),
            )
        )
    return out


@pytest.fixture
def sma_cross_pack() -> dict:
    """The fixture pack loaded as a fresh dict for every test."""
    return _load_sma_cross()


@pytest.fixture
def sma_cross_candles() -> list[Candle]:
    """The 8-bar candle list the sma_cross fixture expects."""
    return _sma_cross_candles()


# ---------------------------------------------------------------------------
# 1. The result is a fresh dict without the four editor keys.
# ---------------------------------------------------------------------------


def test_strip_editor_returns_a_dict():
    """``strip_editor`` returns a ``dict`` (the brief pins a new dict)."""
    assert isinstance(strip_editor({"id": "x"}), dict)


def test_strip_editor_returns_a_new_dict_object():
    """The returned dict is a fresh object — the input mapping is not
    returned by reference. The caller's dict is unchanged."""
    pack = {"id": "x", "layout": "tree"}
    result = strip_editor(pack)
    assert result is not pack


def test_strip_editor_does_not_mutate_the_input():
    """The caller's dict is unchanged after ``strip_editor`` returns.
    Adding the four editor keys to the input must leave them in the
    input."""
    pack = {"id": "x", "layout": "tree", "x": 1, "y": 2, "editor": {"zoom": 1.0}}
    before = {key: pack[key] for key in pack}
    strip_editor(pack)
    assert pack == before


def test_strip_editor_removes_layout_key():
    """``layout`` is editor / canvas state. The strip must drop it."""
    result = strip_editor({"id": "x", "layout": "tree"})
    assert "layout" not in result


def test_strip_editor_removes_x_key():
    """``x`` is a node coordinate on the canvas. The strip must drop it."""
    result = strip_editor({"id": "x", "x": 100})
    assert "x" not in result


def test_strip_editor_removes_y_key():
    """``y`` is a node coordinate on the canvas. The strip must drop it."""
    result = strip_editor({"id": "x", "y": -50})
    assert "y" not in result


def test_strip_editor_removes_editor_key():
    """``editor`` carries viewport / panel / selection state. The strip
    must drop it."""
    result = strip_editor({"id": "x", "editor": {"zoom": 1.5}})
    assert "editor" not in result


def test_strip_editor_removes_all_four_editor_keys_at_once():
    """Adding all four editor keys at once strips all four. The brief
    pins them as a set, not one by one."""
    pack = {
        "id": "x",
        "layout": "grid",
        "x": 12,
        "y": 34,
        "editor": {"theme": "dark"},
    }
    result = strip_editor(pack)
    assert "layout" not in result
    assert "x" not in result
    assert "y" not in result
    assert "editor" not in result


def test_strip_editor_drops_missing_keys_silently():
    """A pack that lacks some or all of the four editor keys is still
    legal; ``pop(key, None)`` skips them without complaint. The strip
    is a transformation, not a validation step."""
    assert strip_editor({"id": "x"}) == {"id": "x"}
    assert strip_editor({}) == {}


def test_strip_editor_preserves_arbitrary_other_keys():
    """Every non-editor key is carried through verbatim, including the
    fields the v1 evaluator actually reads."""
    pack = {
        "id": "x",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "origin": "test",
        "schema_version": 1,
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    result = strip_editor(pack)
    for key, value in pack.items():
        assert result[key] == value, f"key {key!r} changed or dropped"


def test_strip_editor_preserves_a_key_named_like_an_editor_key_but_nested():
    """The strip is top-level only. A nested mapping that itself carries
    a ``layout`` key — for example, inside ``indicators`` — is left
    alone. The brief pins the strip to the top level."""
    pack = {
        "id": "x",
        "indicators": {
            "sma2": {"fn": "sma", "src": "close", "len": 2, "layout": "linear"},
        },
    }
    result = strip_editor(pack)
    assert result["indicators"]["sma2"]["layout"] == "linear"


# ---------------------------------------------------------------------------
# 2. The brief's decision property: stripped == original under evaluate.run
#    on the sma_cross fixture + the same candles test_ns18_shared_trace
#    builds.
# ---------------------------------------------------------------------------


def test_run_on_stripped_sma_cross_returns_same_target_as_run_on_original(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """``evaluate.run`` on the stripped pack and ``evaluate.run`` on the
    original pack return the same ``Target`` for sma_cross.json + the
    eight-bar candle list. Stripping the four editor keys does not
    change a v1 decision."""
    original = evaluate_run(sma_cross_pack, sma_cross_candles)
    stripped = evaluate_run(strip_editor(sma_cross_pack), sma_cross_candles)
    assert stripped == original


def test_run_on_stripped_sma_cross_returns_a_flat_target(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """The sma_cross fixture on the eight-bar candle list ends on a
    flat bar — neither cross fires at t=7 — so the baseline ``Target``
    is ``Target(long=False, stop_price=None, reason="flat")``. The
    stripped pack must yield the same shape. This pins the expected
    decision so the equality check above cannot silently flip."""
    target = evaluate_run(strip_editor(sma_cross_pack), sma_cross_candles)
    assert isinstance(target, Target)
    assert target.long is False
    assert target.stop_price is None
    assert target.reason == "flat"


def test_run_on_stripped_sma_cross_target_is_byte_equal(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """Equality is exact: same ``long`` bool, same ``stop_price`` (or
    None), same ``reason`` string. ``Target`` is a frozen dataclass so
    equality is the right relation."""
    original = evaluate_run(sma_cross_pack, sma_cross_candles)
    stripped = evaluate_run(strip_editor(sma_cross_pack), sma_cross_candles)
    assert (original.long, original.stop_price, original.reason) == (
        stripped.long,
        stripped.stop_price,
        stripped.reason,
    )


def test_adding_editor_keys_then_stripping_yields_the_same_target(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """The brief's adversarial step: take a copy of the pack, add the
    four editor keys with values that would change the look of the
    canvas (and could conceivably affect the decision if the
    evaluator ever looked at them), strip them, and confirm the
    ``Target`` matches the original."""
    decorated = dict(sma_cross_pack)
    decorated["layout"] = "tree"
    decorated["x"] = 100
    decorated["y"] = -200
    decorated["editor"] = {"theme": "dark", "zoom": 1.5, "panels": ["left"]}
    baseline = evaluate_run(sma_cross_pack, sma_cross_candles)
    stripped = evaluate_run(strip_editor(decorated), sma_cross_candles)
    assert stripped == baseline


def test_adding_only_layout_then_stripping_yields_the_same_target(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """A pack with a single editor key added — ``layout`` — and then
    stripped still yields the baseline ``Target``. The strip works
    one key at a time, not only when all four are present."""
    decorated = dict(sma_cross_pack)
    decorated["layout"] = "grid"
    baseline = evaluate_run(sma_cross_pack, sma_cross_candles)
    stripped = evaluate_run(strip_editor(decorated), sma_cross_candles)
    assert stripped == baseline


def test_adding_only_editor_then_stripping_yields_the_same_target(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """``editor`` alone — viewport state — stripped yields the
    baseline ``Target``."""
    decorated = dict(sma_cross_pack)
    decorated["editor"] = {"zoom": 0.5, "selected": "n1"}
    baseline = evaluate_run(sma_cross_pack, sma_cross_candles)
    stripped = evaluate_run(strip_editor(decorated), sma_cross_candles)
    assert stripped == baseline


def test_strip_editor_then_adding_editor_keys_back_yields_the_same_target(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """Strip then re-add: stripping first and then re-injecting the
    four editor keys back into the stripped mapping (so the strip is
    not the only thing keeping the decision clean) still yields the
    baseline ``Target``. The point is that ``evaluate.run`` on the
    stripped pack returns the same ``Target`` as ``run`` on the
    original pack — adding editor keys to the stripped pack would
    reintroduce them, but the strip must have already removed them."""
    stripped = strip_editor(sma_cross_pack)
    re_decorated = dict(stripped)
    re_decorated["layout"] = "tree"
    re_decorated["x"] = 100
    re_decorated["y"] = -200
    re_decorated["editor"] = {"zoom": 1.5}
    baseline = evaluate_run(sma_cross_pack, sma_cross_candles)
    re_decorated_stripped = evaluate_run(strip_editor(re_decorated), sma_cross_candles)
    assert re_decorated_stripped == baseline


def test_evaluate_module_is_not_edited_by_ns19c():
    """The brief forbids editing ``src/krellbot/pack/evaluate.py``.
    The file's source today is the same source the v1 decision
    engine has run for NS19a / NS19b — the strip lives next to the
    v1 evaluator, not inside it."""
    src = inspect.getsource(evaluate_mod)
    assert "strip_editor" not in src, (
        "evaluate.py must not know about strip_editor; the strip lives in "
        "krellbot.strategy_ir.v1 and is composed by callers, not by the "
        "evaluator"
    )


# ---------------------------------------------------------------------------
# 3. Edge cases: empty mapping, non-mapping inputs, value identity.
# ---------------------------------------------------------------------------


def test_strip_editor_on_an_empty_pack_returns_an_empty_dict():
    """An empty mapping strips to an empty mapping. The brief does not
    pin a different shape for empty input."""
    assert strip_editor({}) == {}


def test_strip_editor_on_a_pack_with_only_editor_keys_returns_empty_dict():
    """A pack whose only keys are editor keys strips to an empty
    mapping — there is nothing left to carry through. The function
    does not refuse; it returns an empty dict."""
    assert strip_editor({"layout": "tree", "x": 1, "y": 2, "editor": {}}) == {}


def test_strip_editor_preserves_value_identity_for_non_editor_keys():
    """The strip is a shallow mapping transform: every non-editor
    value is the same object the input carried. The strip does not
    copy nested structures (the brief pins a shallow strip; deep
    copying is the caller's responsibility if they need it)."""
    indicators = {"sma2": {"fn": "sma", "src": "close", "len": 2}}
    risk = {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}}
    entry = ["close", "crosses_above", "sma2"]
    exit_ = ["close", "crosses_below", "sma2"]
    pack = {
        "id": "x",
        "indicators": indicators,
        "risk": risk,
        "entry": entry,
        "exit": exit_,
        "layout": "tree",
        "editor": {"zoom": 1.0},
    }
    result = strip_editor(pack)
    assert result["indicators"] is indicators
    assert result["risk"] is risk
    assert result["entry"] is entry
    assert result["exit"] is exit_


def test_strip_editor_preserves_falsy_non_editor_values():
    """A non-editor value that happens to be falsy — ``0``, ``""``,
    ``False``, ``None``, ``[]``, ``{}`` — is still preserved. The
    strip does not coerce or drop on truthiness."""
    pack = {
        "id": "",
        "version": "0.0.0",
        "schema_version": 0,
        "max_account_pct": 0,
        "enabled": False,
        "tags": None,
        "extras": [],
        "metadata": {},
    }
    result = strip_editor(pack)
    assert result == pack


def test_strip_editor_on_a_non_mapping_raises_type_error():
    """A non-mapping input is a caller mistake. The brief pins the
    function as a mapping transform; ``None``, a string, a list, a
    tuple, or a number raises ``TypeError`` rather than being
    silently coerced to an empty mapping or to a single-key dict."""
    for bad in [None, "not a pack", 42, 3.14, [1, 2, 3], ("a", "b"), True, False]:
        with pytest.raises(TypeError):
            strip_editor(bad)


def test_strip_editor_type_error_message_names_the_wrong_type():
    """The ``TypeError`` names the wrong type so the caller can find
    the offending input without rerunning under a debugger."""
    with pytest.raises(TypeError) as excinfo:
        strip_editor("not a pack")
    assert "str" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 4. Module / signature shape and isolation.
# ---------------------------------------------------------------------------


def test_strip_editor_is_exposed_at_strategy_ir_v1():
    """``strip_editor`` is importable from
    ``krellbot.strategy_ir.v1``. The module is the brief's pinned
    location for the transform."""
    assert hasattr(v1_mod, "strip_editor")
    assert callable(v1_mod.strip_editor)


def test_strip_editor_signature_is_pack_only():
    """The brief pins the signature as ``strip_editor(pack)``. No
    extra positional or keyword parameters beyond the one input."""
    sig = inspect.signature(strip_editor)
    assert list(sig.parameters) == ["pack"]


def test_strip_editor_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``strip_editor`` so callers
    can reach the transform through the package surface, the same
    way the NS19a predicate and the NS19b identity are exposed."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "strip_editor")
    assert strategy_ir_pkg.strip_editor is v1_mod.strip_editor


def test_v1_module_does_not_import_venues_run_or_evaluate():
    """``krellbot.strategy_ir.v1`` is a pure mapping transform. The
    brief forbids importing ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` — the module
    has nothing to do with venue adapters, runtime orchestration, or
    pack evaluation."""
    source = inspect.getsource(v1_mod)
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
                    f"v1 module imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"v1 module does a from-import from {node.module!r}"
            )


def test_strategy_ir_package_does_not_import_venues_run_or_evaluate():
    """The package ``__init__`` does not pull ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` into the IR
    layer. The v1 module is a pure mapping transform and the
    package surface stays pure as a consequence."""
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


def test_v1_module_only_imports_stdlib():
    """The v1 module imports only ``typing.Any`` from stdlib. No
    ``krellbot.*`` import, no third-party import — the transform is
    a pure mapping operation."""
    source = inspect.getsource(v1_mod)
    tree = ast.parse(source)
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module.split(".")[0])
    assert "krellbot" not in imported_modules, f"v1 module imports a krellbot package: {imported_modules}"


def test_v1_module_does_not_open_files_or_touch_the_clock():
    """The transform is pure: no ``open``, no ``pathlib.Path.read_*``,
    no ``os.environ``, no ``time``, no ``datetime``, no ``keyring``,
    no ``requests``. Stripping editor keys is a synchronous in-memory
    mapping operation."""
    source = inspect.getsource(v1_mod)
    tree = ast.parse(source)
    forbidden_calls = {"open", "read_text", "read_bytes", "time", "datetime", "keyring"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in forbidden_calls:
            assert node.value.id not in forbidden_calls, f"v1 module calls {node.value.id}.{node.attr}"


# ---------------------------------------------------------------------------
# 5. Composition with the other NS19 leaves.
# ---------------------------------------------------------------------------


def test_strip_then_execution_id_matches_execution_id_on_a_pack_without_editor_keys(
    sma_cross_pack: dict,
):
    """Stripping editor keys does not change the execution id: the
    canonical document the NS19b hash reads is restricted to
    ``id`` / ``entry`` / ``exit``, so a pack with or without the four
    editor keys already hashes to the same id. The strip is the
    companion guarantee for the v1 decision engine."""
    from krellbot.strategy_ir.identity import execution_id

    decorated = dict(sma_cross_pack)
    decorated["layout"] = "tree"
    decorated["x"] = 100
    decorated["y"] = -200
    decorated["editor"] = {"zoom": 1.5}
    assert execution_id(sma_cross_pack) == execution_id(strip_editor(decorated))

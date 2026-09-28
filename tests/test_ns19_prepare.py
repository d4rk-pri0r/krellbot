"""NS19d: refuse a future bar before evaluation.

The brief: ``prepare_v1(pack, nodes, decision_bar, evaluate)`` strips the
four editor / layout keys the v1 decision engine must never see, then
checks every node with ``check_availability``. If any node references a
bar that is not yet closed at ``decision_bar`` — or a node that is
missing its bar reference entirely — ``prepare_v1`` raises
``FutureData`` and does not call ``evaluate``. If every node is
available, ``prepare_v1`` calls ``evaluate`` exactly once with the
stripped pack and returns its result. The strip and the availability
check are both pinned in the IR layer; the caller supplies the
evaluator so the IR module does not import ``krellbot.pack.evaluate``,
``krellbot.venues``, or ``krellbot.run``.

The IR layer stays a pure compile surface. ``prepare_v1`` is a small
compose step on top of ``strip_editor`` (NS19c) and ``check_availability``
(NS19a); it does no IO, reads no clock, touches no keyring, opens no
network transport. The full evaluation pipeline lives elsewhere —
the IR's job is the two guarantees: editor keys never reach the
evaluator, and a node that would read a future bar refuses before the
evaluator is called.
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
from krellbot.strategy_ir import availability as availability_mod
from krellbot.strategy_ir import v1 as v1_mod
from krellbot.strategy_ir.availability import FutureData, check_availability
from krellbot.strategy_ir.v1 import prepare_v1, strip_editor

# ---------------------------------------------------------------------------
# Fixtures: sma_cross pack + the same candles test_ns18_shared_trace builds.
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


def _make_evaluate(candles: list[Candle]):
    """Build an ``evaluate`` callable bound to the given candles.

    The brief pins the IR layer's purity: ``prepare_v1`` does not
    import ``krellbot.pack.evaluate`` itself; the caller supplies the
    callable. Tests wire ``krellbot.pack.evaluate.run`` through here
    so the gate's behaviour matches the real production wiring.
    """

    def _evaluate(pack: dict) -> Target:
        return evaluate_run(pack, candles)

    return _evaluate


# ---------------------------------------------------------------------------
# 1. prepare_v1 is exposed at the brief's pinned location.
# ---------------------------------------------------------------------------


def test_prepare_v1_is_exposed_at_strategy_ir_v1():
    """``prepare_v1`` is importable from ``krellbot.strategy_ir.v1`` —
    the brief's pinned module for the v1 IR surface."""
    assert hasattr(v1_mod, "prepare_v1")
    assert callable(v1_mod.prepare_v1)


def test_prepare_v1_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``prepare_v1`` so callers
    can reach the compose step through the package surface, the same
    way NS19a / NS19b / NS19c leaves are exposed."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "prepare_v1")
    assert strategy_ir_pkg.prepare_v1 is v1_mod.prepare_v1


def test_prepare_v1_signature_is_pack_nodes_decision_bar_evaluate():
    """The brief pins the signature as
    ``prepare_v1(pack, nodes, decision_bar, evaluate)``. No extra
    positional or keyword parameters beyond the four inputs."""
    sig = inspect.signature(prepare_v1)
    assert list(sig.parameters) == ["pack", "nodes", "decision_bar", "evaluate"]


# ---------------------------------------------------------------------------
# 2. prepare_v1 strips editor keys before calling evaluate.
# ---------------------------------------------------------------------------


def test_prepare_v1_calls_evaluate_with_the_stripped_pack(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """The pack the evaluator receives must be the stripped mapping,
    not the original. ``evaluate`` is replaced with a spy that
    captures the pack it was called with; the spy confirms the four
    editor keys are absent."""
    captured: dict = {}

    def spy(pack: dict) -> Target:
        captured.update(pack)
        return Target(long=False, stop_price=None, reason="flat")

    nodes = [{"id": "n1", "bar_index": 7}]
    prepare_v1(sma_cross_pack, nodes, 7, spy)

    assert "layout" not in captured
    assert "x" not in captured
    assert "y" not in captured
    assert "editor" not in captured


def test_prepare_v1_calls_evaluate_with_a_fresh_dict_not_the_input(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """The pack fed to ``evaluate`` is the fresh dict that
    ``strip_editor`` returns — not the original mapping. The strip is
    a copy; ``evaluate`` does not observe the caller's mapping."""
    captured_ref: list = []

    def spy(pack: dict) -> Target:
        captured_ref.append(pack)
        return Target(long=False, stop_price=None, reason="flat")

    nodes = [{"id": "n1", "bar_index": 7}]
    prepare_v1(sma_cross_pack, nodes, 7, spy)
    assert captured_ref[0] is not sma_cross_pack


def test_prepare_v1_evaluate_pack_equals_strip_editor_pack(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """The pack fed to ``evaluate`` is exactly ``strip_editor(pack)``.
    No additional mutation, no extra keys, no missing keys."""
    captured: dict = {}

    def spy(pack: dict) -> Target:
        captured.update(pack)
        return Target(long=False, stop_price=None, reason="flat")

    nodes = [{"id": "n1", "bar_index": 7}]
    prepare_v1(sma_cross_pack, nodes, 7, spy)
    assert captured == strip_editor(sma_cross_pack)


def test_prepare_v1_does_not_mutate_the_input_pack(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """The caller's mapping is unchanged after ``prepare_v1`` returns.
    Adding the four editor keys to the input must leave them in the
    input."""
    decorated = dict(sma_cross_pack)
    decorated["layout"] = "tree"
    decorated["x"] = 100
    decorated["y"] = -200
    decorated["editor"] = {"zoom": 1.5}
    before = {key: decorated[key] for key in decorated}

    def spy(pack: dict) -> Target:
        return Target(long=False, stop_price=None, reason="flat")

    nodes = [{"id": "n1", "bar_index": 7}]
    prepare_v1(decorated, nodes, 7, spy)

    assert decorated == before


def test_prepare_v1_with_a_pack_without_editor_keys_passes_through_unchanged(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """A pack that already lacks the four editor keys is left as-is
    (modulo the shallow copy that ``strip_editor`` always builds).
    The strip is silent on missing keys; ``prepare_v1`` inherits that
    property."""

    def spy(pack: dict) -> Target:
        return Target(long=False, stop_price=None, reason="flat")

    nodes = [{"id": "n1", "bar_index": 7}]
    prepare_v1(sma_cross_pack, nodes, 7, spy)  # must not raise


# ---------------------------------------------------------------------------
# 3. prepare_v1 raises FutureData on a future bar index and never calls
#    evaluate.
# ---------------------------------------------------------------------------


def test_prepare_v1_raises_future_data_when_a_node_reads_a_future_bar(
    sma_cross_pack: dict,
):
    """A node with ``bar_index = 6`` and ``decision_bar = 5`` reads a
    bar that is not yet closed. ``prepare_v1`` must raise
    ``FutureData`` before calling ``evaluate``."""
    nodes = [{"id": "n1", "bar_index": 6}]

    def must_not_run(pack: dict) -> Target:
        raise AssertionError("evaluate must not be called when a node is unavailable")

    with pytest.raises(FutureData):
        prepare_v1(sma_cross_pack, nodes, 5, must_not_run)


def test_prepare_v1_future_data_carries_the_offending_node_id(
    sma_cross_pack: dict,
):
    """The exception raised by ``prepare_v1`` carries the node id of
    the failing node, taken straight from the underlying
    ``check_availability`` exception."""
    nodes = [{"id": "node-abc", "bar_index": 6}]

    def must_not_run(pack: dict) -> Target:
        raise AssertionError("evaluate must not be called when a node is unavailable")

    with pytest.raises(FutureData) as excinfo:
        prepare_v1(sma_cross_pack, nodes, 5, must_not_run)
    assert excinfo.value.node_id == "node-abc"


def test_prepare_v1_future_data_carries_the_illegal_index(
    sma_cross_pack: dict,
):
    """The exception raised by ``prepare_v1`` carries the offending
    bar index from the underlying ``check_availability`` exception."""
    nodes = [{"id": "n1", "bar_index": 6}]

    def must_not_run(pack: dict) -> Target:
        raise AssertionError("evaluate must not be called when a node is unavailable")

    with pytest.raises(FutureData) as excinfo:
        prepare_v1(sma_cross_pack, nodes, 5, must_not_run)
    assert excinfo.value.index == 6


def test_prepare_v1_raises_when_a_node_has_no_bar_reference(
    sma_cross_pack: dict,
):
    """A node missing its ``bar_index`` / ``bar_indices`` field is
    refused by ``check_availability`` (the brief forbids treating it
    as bar 0). ``prepare_v1`` propagates that refusal."""
    nodes = [{"id": "n1"}]

    def must_not_run(pack: dict) -> Target:
        raise AssertionError("evaluate must not be called when a node is unavailable")

    with pytest.raises(FutureData):
        prepare_v1(sma_cross_pack, nodes, 5, must_not_run)


def test_prepare_v1_raises_when_any_node_in_the_list_is_a_future_bar(
    sma_cross_pack: dict,
):
    """When ``nodes`` contains several nodes and any one of them
    reads a future bar, ``prepare_v1`` must raise. The check covers
    every node, not just the first."""
    nodes = [
        {"id": "n1", "bar_index": 3},
        {"id": "n2", "bar_index": 4},
        {"id": "n3", "bar_index": 6},
    ]

    def must_not_run(pack: dict) -> Target:
        raise AssertionError("evaluate must not be called when a node is unavailable")

    with pytest.raises(FutureData) as excinfo:
        prepare_v1(sma_cross_pack, nodes, 5, must_not_run)
    assert excinfo.value.node_id == "n3"
    assert excinfo.value.index == 6


def test_prepare_v1_raises_when_a_node_in_bar_indices_list_is_a_future_bar(
    sma_cross_pack: dict,
):
    """A node with ``bar_indices = [3, 4, 6]`` and ``decision_bar = 5``
    has a single illegal entry; ``check_availability`` raises, and
    ``prepare_v1`` propagates without calling ``evaluate``."""
    nodes = [{"id": "n1", "bar_indices": [3, 4, 6]}]

    def must_not_run(pack: dict) -> Target:
        raise AssertionError("evaluate must not be called when a node is unavailable")

    with pytest.raises(FutureData) as excinfo:
        prepare_v1(sma_cross_pack, nodes, 5, must_not_run)
    assert excinfo.value.index == 6


def test_prepare_v1_does_not_call_evaluate_when_check_availability_refuses(
    sma_cross_pack: dict,
):
    """The strongest no-call guarantee: ``evaluate`` is invoked zero
    times across the refusal path. The spy tracks every call; the
    test fails if ``prepare_v1`` reaches the evaluator under a refused
    availability check."""
    calls: list = []

    def spy(pack: dict) -> Target:
        calls.append(pack)
        return Target(long=False, stop_price=None, reason="flat")

    nodes = [{"id": "n1", "bar_index": 6}]
    with pytest.raises(FutureData):
        prepare_v1(sma_cross_pack, nodes, 5, spy)
    assert calls == []


# ---------------------------------------------------------------------------
# 4. prepare_v1 calls evaluate exactly once when every node is available.
# ---------------------------------------------------------------------------


def test_prepare_v1_calls_evaluate_once_when_every_node_is_available(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """With all nodes at or before ``decision_bar``, ``prepare_v1``
    invokes ``evaluate`` exactly once and returns its result."""
    evaluate = _make_evaluate(sma_cross_candles)
    nodes = [{"id": "n1", "bar_index": 7}]
    result = prepare_v1(sma_cross_pack, nodes, 7, evaluate)
    assert isinstance(result, Target)


def test_prepare_v1_returns_the_evaluator_result(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """The return value of ``prepare_v1`` is exactly the value the
    supplied ``evaluate`` callable returns."""
    expected = Target(long=False, stop_price=None, reason="flat")

    def evaluate(pack: dict) -> Target:
        return expected

    nodes = [{"id": "n1", "bar_index": 7}]
    assert prepare_v1(sma_cross_pack, nodes, 7, evaluate) is expected


def test_prepare_v1_calls_evaluate_with_a_real_evaluator_yields_flat_target(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """End-to-end: the sma_cross fixture + the eight-bar candle list
    + the real ``evaluate.run`` callable all wired through
    ``prepare_v1`` produce the flat target at bar 7."""
    evaluate = _make_evaluate(sma_cross_candles)
    nodes = [{"id": "n1", "bar_index": 7}]
    target = prepare_v1(sma_cross_pack, nodes, 7, evaluate)
    assert target.long is False
    assert target.stop_price is None
    assert target.reason == "flat"


def test_prepare_v1_strips_editor_keys_then_evaluates_real_evaluator(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """The end-to-end property the brief pins: a pack with editor
    keys added (the canvas decorations NS19c strips) feeds
    ``evaluate.run`` through ``prepare_v1`` and yields the same
    ``Target`` as the original pack."""
    decorated = dict(sma_cross_pack)
    decorated["layout"] = "tree"
    decorated["x"] = 100
    decorated["y"] = -200
    decorated["editor"] = {"zoom": 1.5}

    evaluate = _make_evaluate(sma_cross_candles)
    nodes = [{"id": "n1", "bar_index": 7}]
    decorated_result = prepare_v1(decorated, nodes, 7, evaluate)
    plain_result = prepare_v1(sma_cross_pack, nodes, 7, evaluate)
    assert decorated_result == plain_result


def test_prepare_v1_with_empty_nodes_list_evaluates(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """An empty ``nodes`` list trivially satisfies the per-node
    availability check (no node to fail). ``prepare_v1`` calls
    ``evaluate`` once with the stripped pack."""
    evaluate = _make_evaluate(sma_cross_candles)
    result = prepare_v1(sma_cross_pack, [], 7, evaluate)
    assert isinstance(result, Target)


def test_prepare_v1_calls_evaluate_once_with_multiple_available_nodes(
    sma_cross_pack: dict, sma_cross_candles: list[Candle]
):
    """Several nodes, all legal at ``decision_bar``, still produce a
    single ``evaluate`` call. The brief pins ``exactly once``; the
    compose step is not a loop over nodes that re-invokes the
    evaluator."""
    calls: list = []

    def spy(pack: dict) -> Target:
        calls.append(pack)
        return Target(long=False, stop_price=None, reason="flat")

    nodes = [
        {"id": "n1", "bar_index": 0},
        {"id": "n2", "bar_index": 3},
        {"id": "n3", "bar_indices": [5, 6, 7]},
    ]
    prepare_v1(sma_cross_pack, nodes, 7, spy)
    assert len(calls) == 1


def test_prepare_v1_node_at_exact_decision_bar_is_legal(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """A node whose ``bar_index`` equals ``decision_bar`` reads the
    bar that is now closed. ``check_availability`` accepts it, and
    ``prepare_v1`` does not refuse."""
    evaluate = _make_evaluate(sma_cross_candles)
    nodes = [{"id": "n1", "bar_index": 7}]
    result = prepare_v1(sma_cross_pack, nodes, 7, evaluate)
    assert isinstance(result, Target)


def test_prepare_v1_node_before_decision_bar_is_legal(sma_cross_pack: dict, sma_cross_candles: list[Candle]):
    """A node whose ``bar_index`` is well before ``decision_bar``
    reads a historical bar; ``check_availability`` accepts it, and
    ``prepare_v1`` does not refuse."""
    evaluate = _make_evaluate(sma_cross_candles)
    nodes = [{"id": "n1", "bar_index": 0}]
    result = prepare_v1(sma_cross_pack, nodes, 7, evaluate)
    assert isinstance(result, Target)


# ---------------------------------------------------------------------------
# 5. Non-mapping pack input is refused.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_pack", [None, "not a pack", 42, 3.14, [1, 2, 3], ("a", "b"), True, False])
def test_prepare_v1_on_a_non_mapping_pack_raises_type_error(bad_pack):
    """A non-mapping ``pack`` is a caller mistake; ``strip_editor``
    raises ``TypeError`` and ``prepare_v1`` propagates without calling
    ``evaluate``."""
    calls: list = []

    def spy(pack: dict) -> Target:
        calls.append(pack)
        return Target(long=False, stop_price=None, reason="flat")

    with pytest.raises(TypeError):
        prepare_v1(bad_pack, [], 7, spy)
    assert calls == []


# ---------------------------------------------------------------------------
# 6. The brief's forbidden import set: v1 must not pull venues, run, or
#    the evaluator into the IR.
# ---------------------------------------------------------------------------


def test_v1_module_does_not_import_venues_run_or_evaluate():
    """``krellbot.strategy_ir.v1`` stays a pure compile surface. The
    brief forbids importing ``krellbot.venues``, ``krellbot.run``, or
    ``krellbot.pack.evaluate`` — the compose step receives the
    evaluator as a callable argument."""
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
    layer. The v1 module is a pure compile surface and the package
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


def test_v1_module_does_not_open_files_or_touch_the_clock():
    """``prepare_v1`` and ``strip_editor`` are pure in-memory
    transforms. No ``open``, no ``pathlib.Path.read_*``, no
    ``os.environ``, no ``time``, no ``datetime``, no ``keyring``, no
    ``requests``. The compile step is synchronous, in-memory, and
    side-effect-free."""
    source = inspect.getsource(v1_mod)
    tree = ast.parse(source)
    forbidden_calls = {"open", "read_text", "read_bytes", "time", "datetime", "keyring"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in forbidden_calls:
            assert node.value.id not in forbidden_calls, f"v1 module calls {node.value.id}.{node.attr}"


# ---------------------------------------------------------------------------
# 7. The evaluate module is not edited by NS19d.
# ---------------------------------------------------------------------------


def test_evaluate_module_is_not_edited_by_ns19d():
    """The brief forbids editing ``src/krellbot/pack/evaluate.py``.
    The file's source today must remain untouched: ``prepare_v1``
    composes on top of the evaluator via a callable parameter, not
    by editing the evaluator."""
    src = inspect.getsource(evaluate_mod)
    assert "prepare_v1" not in src, (
        "evaluate.py must not know about prepare_v1; the compose step lives "
        "in krellbot.strategy_ir.v1 and is invoked by callers, not by the "
        "evaluator"
    )


def test_evaluate_module_signature_is_unchanged():
    """``evaluate.run(pack, candles)`` is the brief's pinned v1 entry
    point. NS19d adds a higher-level compose step but never reaches
    into the evaluator; ``run``'s signature stays ``(pack, candles)``."""
    sig = inspect.signature(evaluate_run)
    assert list(sig.parameters) == ["pack", "candles"]


# ---------------------------------------------------------------------------
# 8. Composition with the other NS19 leaves.
# ---------------------------------------------------------------------------


def test_prepare_v1_uses_strip_editor_for_the_pack_transform():
    """``prepare_v1`` is built on top of ``strip_editor`` (NS19c). The
    pack ``evaluate`` receives equals ``strip_editor(pack)`` exactly,
    not a hand-rolled copy."""
    captured: dict = {}

    def spy(pack: dict) -> Target:
        captured.update(pack)
        return Target(long=False, stop_price=None, reason="flat")

    pack = {
        "id": "x",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "layout": "tree",
        "x": 100,
        "y": -200,
        "editor": {"zoom": 1.5},
    }
    nodes = [{"id": "n1", "bar_index": 7}]
    prepare_v1(pack, nodes, 7, spy)
    assert captured == strip_editor(pack)


def test_prepare_v1_uses_check_availability_per_node():
    """``prepare_v1`` is built on top of ``check_availability``
    (NS19a). The refusal path goes through the same predicate the
    NS19a tests pin, so any future tweak to ``check_availability`` is
    observed by ``prepare_v1`` without further wiring."""
    nodes = [{"id": "n1", "bar_index": 6}]

    def must_not_run(pack: dict) -> Target:
        raise AssertionError("evaluate must not be called when a node is unavailable")

    with pytest.raises(FutureData):
        prepare_v1({"id": "x"}, nodes, 5, must_not_run)


def test_strip_editor_and_check_availability_remain_independent_of_prepare_v1():
    """``strip_editor`` (NS19c) and ``check_availability`` (NS19a)
    are the leaves ``prepare_v1`` is composed from. They must remain
    importable from their own modules so other code paths — paper,
    replay, ad-hoc tools — can still reach them directly without
    going through the compose step."""
    assert callable(strip_editor)
    assert callable(check_availability)
    assert hasattr(availability_mod, "FutureData")

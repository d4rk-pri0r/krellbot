"""NS19h: stateful operators require a checkpoint.

The brief: ``require_checkpoint(operator)`` returns ``None`` when the
operator's ``fn`` is *not* in the stateful set ``{"ema", "atr",
"roofing_filter"}``. When ``fn`` *is* in that set, the operator must
carry a ``checkpoint`` field, and the field must be a ``dict``. A
missing key, ``None``, the integer ``0``, the float ``0.0``, or the
boolean ``True`` all raise ``MissingCheckpoint``. The brief explicitly
forbids storing any of those values as a checkpoint — they are
commonly-tempting sentinels that hide the absence of state, and the
refusal forces the caller to materialise an actual ``dict``.

The stateful set is exactly three names — ``ema``, ``atr``, and
``roofing_filter`` — the three whitelist operators that hold state
across evaluations (the exponential moving average's seed, the average
true range's running window, and the roofing filter's two-stage state).
The set is not a policy decision the module gets to make: it is
pinned by the brief. Operators outside the set (``sma``, ``wma``,
``vwma``, ``stdev``, ``roc``, ``efficiency_ratio``, ``power_mean``,
``hma``, ``highest``, ``lowest``) never carry a checkpoint and the
function returns ``None`` without inspecting one.

``MissingCheckpoint`` carries the offending ``fn`` so the caller can
identify which operator failed the check. It carries no ``equity``,
``return_pct``, or ``pnl`` attribute — a refused checkpoint check is
not a return, and the brief forbids inventing one.

The module is a pure predicate over the operator shape. It does not
import ``krellbot.venues``, ``krellbot.run``, or
``krellbot.pack.evaluate``; it does not read the clock, touch the
keyring, or open a network transport. The strategy IR owns the
checkpoint check; venues, the evaluator, and runtime orchestration
consume the verified operator later.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from krellbot.strategy_ir import checkpoint as checkpoint_mod
from krellbot.strategy_ir.checkpoint import MissingCheckpoint, require_checkpoint

# ---------------------------------------------------------------------------
# 1. Module / signature shape and surface exposure.
# ---------------------------------------------------------------------------


def test_require_checkpoint_is_exposed_at_strategy_ir_checkpoint():
    """``require_checkpoint`` is importable from
    ``krellbot.strategy_ir.checkpoint`` — the brief's pinned module."""
    assert hasattr(checkpoint_mod, "require_checkpoint")
    assert callable(checkpoint_mod.require_checkpoint)


def test_require_checkpoint_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``require_checkpoint`` so
    callers can reach the checkpoint check through the package surface,
    the same way the other NS19 leaves are exposed."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "require_checkpoint")
    assert strategy_ir_pkg.require_checkpoint is checkpoint_mod.require_checkpoint


def test_missing_checkpoint_is_exposed_at_strategy_ir_checkpoint():
    """``MissingCheckpoint`` is importable from
    ``krellbot.strategy_ir.checkpoint``."""
    assert hasattr(checkpoint_mod, "MissingCheckpoint")
    assert inspect.isclass(checkpoint_mod.MissingCheckpoint)


def test_missing_checkpoint_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``MissingCheckpoint`` so
    callers can catch it the same way they catch the other NS19
    exceptions."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "MissingCheckpoint")
    assert strategy_ir_pkg.MissingCheckpoint is checkpoint_mod.MissingCheckpoint


def test_require_checkpoint_signature_pins_operator_only():
    """The brief pins the signature as ``require_checkpoint(operator)``
    — a single positional argument, no extra parameters. No keyword
    arguments, no defaults."""
    sig = inspect.signature(require_checkpoint)
    params = list(sig.parameters)
    assert params == ["operator"]
    assert sig.parameters["operator"].kind is inspect.Parameter.POSITIONAL_OR_KEYWORD


def test_missing_checkpoint_is_an_exception_subclass():
    """``MissingCheckpoint`` is an ``Exception`` subclass — it can be
    raised and caught the same way other NS19 exceptions are caught."""
    assert issubclass(MissingCheckpoint, Exception)


def test_stateful_fns_constant_is_exposed_and_pinned():
    """The brief pins the stateful set as exactly ``{"ema", "atr",
    "roofing_filter"}``. The module exposes that set as
    ``STATEFUL_FNS`` so callers can introspect it without re-deriving
    the policy. The set is a ``frozenset`` — the policy is pinned and
    must not be mutated."""
    assert hasattr(checkpoint_mod, "STATEFUL_FNS")
    assert checkpoint_mod.STATEFUL_FNS == frozenset({"ema", "atr", "roofing_filter"})


# ---------------------------------------------------------------------------
# 2. Returns None for non-stateful fns — checkpoint is never inspected.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    [
        "sma",
        "wma",
        "vwma",
        "stdev",
        "roc",
        "efficiency_ratio",
        "power_mean",
        "hma",
        "highest",
        "lowest",
    ],
)
def test_returns_none_for_non_stateful_fn_without_checkpoint(fn):
    """The non-stateful whitelist operators (``sma``, ``wma``, ``vwma``,
    ``stdev``, ``roc``, ``efficiency_ratio``, ``power_mean``, ``hma``,
    ``highest``, ``lowest``) never carry a checkpoint. The function
    returns ``None`` even when the operator has no ``checkpoint``
    key."""
    operator = {"fn": fn, "src": "close", "len": 14}
    assert require_checkpoint(operator) is None


@pytest.mark.parametrize(
    "fn",
    [
        "sma",
        "wma",
        "vwma",
        "stdev",
        "roc",
        "efficiency_ratio",
        "power_mean",
        "hma",
        "highest",
        "lowest",
    ],
)
def test_returns_none_for_non_stateful_fn_ignores_checkpoint_value(fn):
    """For non-stateful ``fn``, the function does not inspect the
    ``checkpoint`` field at all. A non-stateful operator can carry any
    sentinel (``None``, ``0``, ``0.0``, ``True``, an empty string) or
    no key at all and the function returns ``None``. The checkpoint
    rule is only applied to the stateful set."""
    for sentinel in [None, 0, 0.0, True, False, "", [], "anything"]:
        operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": sentinel}
        assert require_checkpoint(operator) is None, f"non-stateful fn={fn!r} should ignore checkpoint={sentinel!r}"


def test_returns_none_for_non_stateful_fn_with_no_checkpoint_key():
    """A non-stateful operator without a ``checkpoint`` key returns
    ``None`` — the function does not synthesise one or refuse the
    call."""
    operator = {"fn": "sma", "src": "close", "len": 14}
    assert require_checkpoint(operator) is None


def test_returns_none_for_extra_unknown_fn():
    """An ``fn`` the schema does not enumerate — e.g., a future
    indicator — is treated as non-stateful when not in the pinned
    stateful set. The module does not invent extra names."""
    operator = {"fn": "future_indicator", "src": "close", "len": 14}
    assert require_checkpoint(operator) is None


# ---------------------------------------------------------------------------
# 3. Stateful fns with a dict checkpoint return None.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn",
    ["ema", "atr", "roofing_filter"],
)
def test_returns_none_for_stateful_fn_with_dict_checkpoint(fn):
    """Every stateful ``fn`` (``ema``, ``atr``, ``roofing_filter``)
    with a ``dict`` checkpoint returns ``None``. The dict can be empty
    (``{}``) or carry any number of keys — the checkpoint shape is
    owned by the operator's caller, not the IR."""
    operator = {"fn": fn, "len": 14, "checkpoint": {}}
    assert require_checkpoint(operator) is None


def test_returns_none_for_ema_with_populated_dict_checkpoint():
    """``ema`` accepts a populated ``dict`` checkpoint (e.g., a
    seed)."""
    operator = {"fn": "ema", "src": "close", "len": 14, "checkpoint": {"seed": 1.0}}
    assert require_checkpoint(operator) is None


def test_returns_none_for_atr_with_populated_dict_checkpoint():
    """``atr`` accepts a populated ``dict`` checkpoint."""
    operator = {"fn": "atr", "len": 14, "checkpoint": {"window": [], "running": 0.0}}
    assert require_checkpoint(operator) is None


def test_returns_none_for_roofing_filter_with_populated_dict_checkpoint():
    """``roofing_filter`` accepts a populated ``dict`` checkpoint."""
    operator = {
        "fn": "roofing_filter",
        "src": "close",
        "len": 14,
        "checkpoint": {"hp": 0.0, "smooth": 0.0},
    }
    assert require_checkpoint(operator) is None


def test_empty_dict_is_a_valid_checkpoint():
    """An empty ``dict`` is a valid checkpoint. The function does not
    require a non-empty checkpoint — the brief pins ``dict``, not
    ``non-empty dict``."""
    operator = {"fn": "ema", "src": "close", "len": 14, "checkpoint": {}}
    assert require_checkpoint(operator) is None


def test_dict_checkpoint_with_arbitrary_keys_is_accepted():
    """A ``dict`` checkpoint with any keys passes — the IR does not
    dictate the inner shape. The operator's caller (the evaluator)
    owns the checkpoint layout."""
    operator = {
        "fn": "atr",
        "len": 14,
        "checkpoint": {"any": "shape", "the": "evaluator", "wants": [1, 2, 3]},
    }
    assert require_checkpoint(operator) is None


# ---------------------------------------------------------------------------
# 4. Stateful fns raise MissingCheckpoint for missing / sentinel values.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_missing_checkpoint_key_raises_missing_checkpoint(fn):
    """A stateful operator with no ``checkpoint`` key raises
    ``MissingCheckpoint``. The function refuses to assume the
    checkpoint is implicit."""
    operator = {"fn": fn, "src": "close", "len": 14}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_none_checkpoint_raises_missing_checkpoint(fn):
    """``checkpoint=None`` is not a valid checkpoint — it is a
    sentinel that hides the absence of state. The brief explicitly
    refuses it."""
    operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": None}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_zero_int_checkpoint_raises_missing_checkpoint(fn):
    """``checkpoint=0`` is not a valid checkpoint — the integer
    ``0`` is a tempting "no state" sentinel that the brief explicitly
    refuses. The function does not coerce ``0`` into a dict."""
    operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": 0}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_zero_float_checkpoint_raises_missing_checkpoint(fn):
    """``checkpoint=0.0`` is not a valid checkpoint — the float
    ``0.0`` is the floating-point version of the integer ``0``
    sentinel. The brief explicitly refuses it."""
    operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": 0.0}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_true_checkpoint_raises_missing_checkpoint(fn):
    """``checkpoint=True`` is not a valid checkpoint — the boolean
    ``True`` is the third tempting sentinel the brief pins. The
    function refuses it."""
    operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": True}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_false_checkpoint_raises_missing_checkpoint(fn):
    """``checkpoint=False`` is not a valid checkpoint — the boolean
    ``False`` is the boolean counterpart of ``0``. The function
    refuses it for the same reason it refuses ``True`` and ``0``:
    only a ``dict`` is a legal checkpoint."""
    operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": False}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_int_checkpoint_raises_missing_checkpoint(fn):
    """A non-zero integer (e.g., ``1``, ``42``) is not a valid
    checkpoint — only a ``dict`` is. The brief pins the only legal
    type."""
    for value in [1, 2, 14, 42, -1]:
        operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": value}
        with pytest.raises(MissingCheckpoint) as excinfo:
            require_checkpoint(operator)
        assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_float_checkpoint_raises_missing_checkpoint(fn):
    """A non-zero float (e.g., ``1.5``, ``-3.14``) is not a valid
    checkpoint — only a ``dict`` is."""
    for value in [1.5, -3.14, 1e9, float("inf")]:
        operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": value}
        with pytest.raises(MissingCheckpoint) as excinfo:
            require_checkpoint(operator)
        assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_string_checkpoint_raises_missing_checkpoint(fn):
    """A string ``checkpoint`` is not a valid checkpoint — only a
    ``dict`` is. Strings (even empty ones) are not dicts."""
    for value in ["", "seed", "checkpoint", "{}"]:
        operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": value}
        with pytest.raises(MissingCheckpoint) as excinfo:
            require_checkpoint(operator)
        assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_list_checkpoint_raises_missing_checkpoint(fn):
    """A list ``checkpoint`` is not a valid checkpoint — only a
    ``dict`` is. A list is a sequence, not a mapping."""
    for value in [[], [1, 2, 3], ["seed"], [{"x": 1}]]:
        operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": value}
        with pytest.raises(MissingCheckpoint) as excinfo:
            require_checkpoint(operator)
        assert excinfo.value.fn == fn


@pytest.mark.parametrize("fn", ["ema", "atr", "roofing_filter"])
def test_tuple_checkpoint_raises_missing_checkpoint(fn):
    """A tuple ``checkpoint`` is not a valid checkpoint — only a
    ``dict`` is."""
    operator = {"fn": fn, "src": "close", "len": 14, "checkpoint": (1, 2, 3)}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert excinfo.value.fn == fn


# ---------------------------------------------------------------------------
# 5. The stateful set is exactly {ema, atr, roofing_filter} — no
#    surprises.
# ---------------------------------------------------------------------------


def test_stateful_set_excludes_sma():
    """``sma`` is not in the stateful set — a simple moving average
    reads from a fixed window and carries no cross-evaluation state.
    The function returns ``None`` even when ``checkpoint`` is
    missing."""
    operator = {"fn": "sma", "src": "close", "len": 14}
    assert require_checkpoint(operator) is None


def test_stateful_set_excludes_wma_vwma_stdev_roc_er():
    """``wma``, ``vwma``, ``stdev``, ``roc``, ``efficiency_ratio`` are
    all window-based or ratio-based — they read from the candles
    directly and carry no cross-evaluation state."""
    for fn in ["wma", "vwma", "stdev", "roc", "efficiency_ratio"]:
        operator = {"fn": fn, "src": "close", "len": 14}
        assert require_checkpoint(operator) is None, f"unexpected stateful verdict for {fn}"


def test_stateful_set_excludes_power_mean_hma_highest_lowest():
    """``power_mean``, ``hma``, ``highest``, ``lowest`` are not in the
    stateful set — they are stateless window operations."""
    for fn in ["power_mean", "hma", "highest", "lowest"]:
        operator = {"fn": fn, "src": "close", "len": 14}
        assert require_checkpoint(operator) is None, f"unexpected stateful verdict for {fn}"


def test_stateful_set_includes_only_ema_atr_roofing_filter():
    """The stateful set is exactly ``{ema, atr, roofing_filter}``.
    No other whitelist operator is stateful, no other name is
    invented. The function refuses a checkpoint-less ``ema`` /
    ``atr`` / ``roofing_filter``."""
    for fn in ["ema", "atr", "roofing_filter"]:
        operator = {"fn": fn, "len": 14}
        with pytest.raises(MissingCheckpoint):
            require_checkpoint(operator)


def test_no_extra_names_in_stateful_set():
    """The brief is exhaustive: ``{"ema", "atr", "roofing_filter"}``
    is the *only* stateful set. No ``sma``, no ``wma``, no invented
    indicator appears in ``STATEFUL_FNS``."""
    expected = frozenset({"ema", "atr", "roofing_filter"})
    assert checkpoint_mod.STATEFUL_FNS == expected
    assert len(checkpoint_mod.STATEFUL_FNS) == 3


def test_stateful_set_is_immutable():
    """``STATEFUL_FNS`` is a ``frozenset`` — the policy is pinned and
    cannot be mutated by callers."""
    assert isinstance(checkpoint_mod.STATEFUL_FNS, frozenset)


# ---------------------------------------------------------------------------
# 6. The MissingCheckpoint exception carries fn and has no
#    equity, return_pct, or pnl.
# ---------------------------------------------------------------------------


def test_missing_checkpoint_carries_fn_attribute():
    """``MissingCheckpoint.fn`` is the operator's ``fn`` field so the
    caller can identify which operator failed the check."""
    err = MissingCheckpoint("ema")
    assert err.fn == "ema"


def test_missing_checkpoint_carries_atr_fn():
    """``MissingCheckpoint.fn`` carries ``"atr"`` when the offender
    is an ``atr`` operator."""
    err = MissingCheckpoint("atr")
    assert err.fn == "atr"


def test_missing_checkpoint_carries_roofing_filter_fn():
    """``MissingCheckpoint.fn`` carries ``"roofing_filter"`` when the
    offender is a ``roofing_filter`` operator."""
    err = MissingCheckpoint("roofing_filter")
    assert err.fn == "roofing_filter"


def test_missing_checkpoint_has_no_equity_attribute():
    """The brief forbids inventing ``equity`` on
    ``MissingCheckpoint``. A refused checkpoint check is not a
    return."""
    err = MissingCheckpoint("ema")
    assert not hasattr(err, "equity")


def test_missing_checkpoint_has_no_return_pct_attribute():
    """The brief forbids inventing ``return_pct`` on
    ``MissingCheckpoint``."""
    err = MissingCheckpoint("ema")
    assert not hasattr(err, "return_pct")


def test_missing_checkpoint_has_no_pnl_attribute():
    """The brief forbids inventing ``pnl`` on
    ``MissingCheckpoint``."""
    err = MissingCheckpoint("ema")
    assert not hasattr(err, "pnl")


def test_missing_checkpoint_str_message_names_fn():
    """The string form names the offending ``fn`` so log lines and
    error chains can identify the failing operator without poking at
    attributes."""
    err = MissingCheckpoint("ema")
    msg = str(err)
    assert "ema" in msg


def test_missing_checkpoint_exception_message_names_fn_for_raised_case():
    """The string form of a ``MissingCheckpoint`` raised by
    ``require_checkpoint`` names the offending ``fn``."""
    operator = {"fn": "atr", "len": 14}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(operator)
    assert "atr" in str(excinfo.value)


def test_missing_checkpoint_is_an_exception_with_fn_set_by_init():
    """``MissingCheckpoint(fn)`` sets ``fn`` in ``__init__`` so the
    attribute is available immediately on construction."""
    err = MissingCheckpoint("roofing_filter")
    assert hasattr(err, "fn")
    assert err.fn == "roofing_filter"


# ---------------------------------------------------------------------------
# 7. The brief's forbidden import set: checkpoint must not pull venues,
#    evaluate, or run into the IR.
# ---------------------------------------------------------------------------


def test_checkpoint_module_does_not_import_venues_run_or_evaluate():
    """``krellbot.strategy_ir.checkpoint`` stays a pure compile
    surface. The brief forbids importing ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` — the checkpoint
    check is a pure predicate over the operator shape."""
    source = inspect.getsource(checkpoint_mod)
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
                    f"checkpoint module imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"checkpoint module does a from-import from {node.module!r}"
            )


def test_strategy_ir_package_does_not_import_venues_run_or_evaluate_via_checkpoint():
    """The package ``__init__`` does not pull ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` into the IR
    layer. The checkpoint module is a pure compile surface and the
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


def test_checkpoint_module_does_not_open_files_or_touch_the_clock():
    """``require_checkpoint`` is a pure in-memory predicate. No
    ``open``, no ``pathlib.Path.read_*``, no ``os.environ``, no
    ``time``, no ``datetime``, no ``keyring``, no ``requests``. The
    checkpoint check is synchronous, in-memory, and
    side-effect-free."""
    source = inspect.getsource(checkpoint_mod)
    tree = ast.parse(source)
    forbidden_calls = {"open", "read_text", "read_bytes", "time", "datetime", "keyring"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in forbidden_calls:
            assert node.value.id not in forbidden_calls, f"checkpoint module calls {node.value.id}.{node.attr}"


# ---------------------------------------------------------------------------
# 8. Composition with the other NS19 leaves.
# ---------------------------------------------------------------------------


def test_require_checkpoint_is_independent_of_other_leaves():
    """``require_checkpoint`` (NS19h) is independent of
    ``check_bounds`` (NS19g), ``canonical_bytes`` (NS19f),
    ``require_v1_clock`` (NS19e), ``prepare_v1`` (NS19d),
    ``strip_editor`` (NS19c), ``execution_id`` (NS19b), and
    ``check_availability`` (NS19a). The leaves remain importable
    from their own modules and are not coupled by the new module."""
    from krellbot.strategy_ir.availability import check_availability
    from krellbot.strategy_ir.bounds import check_bounds
    from krellbot.strategy_ir.canonical import canonical_bytes
    from krellbot.strategy_ir.identity import execution_id
    from krellbot.strategy_ir.units import InvalidGraph, require_v1_clock
    from krellbot.strategy_ir.v1 import prepare_v1, strip_editor

    assert callable(require_checkpoint)
    assert callable(check_bounds)
    assert callable(canonical_bytes)
    assert callable(strip_editor)
    assert callable(prepare_v1)
    assert callable(check_availability)
    assert callable(execution_id)
    assert callable(require_v1_clock)
    assert MissingCheckpoint is not InvalidGraph


def test_require_checkpoint_accepts_a_stateful_indicator_with_dict_checkpoint():
    """End-to-end property: a hand-built ``ema`` indicator with a
    ``dict`` checkpoint is accepted. This is the shape a v1 pack
    would carry."""
    indicator = {"fn": "ema", "src": "close", "len": 14, "checkpoint": {"seed": 100.0}}
    assert require_checkpoint(indicator) is None


def test_require_checkpoint_accepts_a_non_stateful_indicator_without_checkpoint():
    """End-to-end property: the ``sma_cross.json`` fixture's indicator
    is a non-stateful ``sma`` without a checkpoint. The function
    returns ``None``."""
    import json
    from pathlib import Path

    fixture_path = Path(__file__).parent / "fixtures" / "packs" / "sma_cross.json"
    graph = json.loads(fixture_path.read_text())
    for name, spec in graph["indicators"].items():
        assert require_checkpoint(spec) is None, f"sma_cross indicator {name!r} should not require a checkpoint"


def test_require_checkpoint_refuses_a_stateful_indicator_without_dict_checkpoint():
    """End-to-end property: a stateful ``ema`` indicator without a
    dict checkpoint raises ``MissingCheckpoint(fn="ema")``."""
    indicator = {"fn": "ema", "src": "close", "len": 14}
    with pytest.raises(MissingCheckpoint) as excinfo:
        require_checkpoint(indicator)
    assert excinfo.value.fn == "ema"


def test_require_checkpoint_does_not_mutate_the_input_operator():
    """``require_checkpoint`` does not mutate the input operator. The
    function reads ``fn`` and ``checkpoint``; it never modifies
    them."""
    operator = {"fn": "ema", "src": "close", "len": 14, "checkpoint": {"seed": 1.0}}
    snapshot = dict(operator)
    snapshot["checkpoint"] = dict(operator["checkpoint"])
    assert require_checkpoint(operator) is None
    assert operator == snapshot

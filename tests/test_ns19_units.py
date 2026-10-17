"""NS19e: typed v1 clock — refuse a graph whose ``schema_version`` or
``timeframe`` is not the exact legal v1 value.

The brief: ``require_v1_clock(graph)`` returns ``None`` only when
``schema_version`` is the integer ``1`` AND ``timeframe`` is exactly
``"1h"``, ``"4h"``, or ``"1d"``. Anything else raises ``InvalidGraph``
carrying the offending ``field`` and ``value``. The exception carries no
``equity``, ``return_pct``, or ``pnl`` — a refused clock check is not a
return. The locked pack schema (``src/krellbot/pack/schema.json``) is
the source of truth for the allowed values; the module does not invent
extra timeframes.

A missing ``schema_version``, ``True``, ``1.0``, or ``"1"`` all raise.
The check uses ``type(value) is int``, not ``isinstance`` (which would
let ``True`` through, since ``bool`` is a subclass of ``int``) and not
``int(value)`` (which would coerce ``True``, ``1.0``, and ``"1"``).
A missing ``timeframe``, ``"1H"``, ``"1m"``, or the integer ``1`` also
raises. The module does not default a missing timeframe to ``"1h"``;
the schema requires ``timeframe`` and the IR clock check enforces
that.

The module is a pure predicate over the graph shape. It does not
import ``krellbot.venues``, ``krellbot.pack.evaluate``, or
``krellbot.run``. It does not read the clock, touch the keyring, or
open a network transport.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from krellbot.strategy_ir import units as units_mod
from krellbot.strategy_ir.units import InvalidGraph, require_v1_clock

# ---------------------------------------------------------------------------
# 1. require_v1_clock is exposed at the brief's pinned location.
# ---------------------------------------------------------------------------


def test_require_v1_clock_is_exposed_at_strategy_ir_units():
    """``require_v1_clock`` is importable from
    ``krellbot.strategy_ir.units`` — the brief's pinned module."""
    assert hasattr(units_mod, "require_v1_clock")
    assert callable(units_mod.require_v1_clock)


def test_require_v1_clock_is_exposed_via_the_strategy_ir_package():
    """The package ``__init__`` re-exports ``require_v1_clock`` so
    callers can reach the clock check through the package surface, the
    same way the other NS19 leaves are exposed."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "require_v1_clock")
    assert strategy_ir_pkg.require_v1_clock is units_mod.require_v1_clock


def test_invalid_graph_is_exposed_via_the_strategy_ir_package():
    """``InvalidGraph`` is re-exported through the package surface so
    callers can catch it the same way they catch the other NS19
    exceptions."""
    import krellbot.strategy_ir as strategy_ir_pkg

    assert hasattr(strategy_ir_pkg, "InvalidGraph")
    assert strategy_ir_pkg.InvalidGraph is units_mod.InvalidGraph


def test_require_v1_clock_signature_is_graph_only():
    """The brief pins the signature as ``require_v1_clock(graph)``.
    No extra positional or keyword parameters beyond the single
    input."""
    sig = inspect.signature(require_v1_clock)
    assert list(sig.parameters) == ["graph"]


# ---------------------------------------------------------------------------
# 2. Legal clock: schema_version=1 (int) and timeframe in {"1h","4h","1d"}
#    returns None.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("timeframe", ["1h", "4h", "1d"])
def test_returns_none_for_each_legal_timeframe(timeframe):
    """Every value the schema enumerates for ``timeframe`` is a legal
    v1 clock: ``1h``, ``4h``, ``1d``."""
    graph = {"schema_version": 1, "timeframe": timeframe}
    assert require_v1_clock(graph) is None


def test_returns_none_when_extra_keys_are_present():
    """Extra keys (indicators, entry, exit, risk, markets, label,
    version, layout, x, y, editor) do not change the verdict. The
    check only inspects ``schema_version`` and ``timeframe``."""
    graph = {
        "schema_version": 1,
        "timeframe": "1h",
        "id": "sma-cross",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "origin": "Backtest fixture.",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
        "layout": "tree",
        "x": 100,
        "y": -200,
        "editor": {"zoom": 1.5},
    }
    assert require_v1_clock(graph) is None


def test_returns_none_for_each_timeframe_independently_of_other_fields():
    """Sanity sweep: the verdict for ``timeframe`` does not depend on
    any other field of the graph. ``schema_version=1`` and a legal
    timeframe always returns ``None``."""
    for timeframe in ["1h", "4h", "1d"]:
        assert require_v1_clock({"schema_version": 1, "timeframe": timeframe}) is None
        assert require_v1_clock({"schema_version": 1, "timeframe": timeframe, "noise": [1, 2, 3]}) is None


# ---------------------------------------------------------------------------
# 3. schema_version checks: only the integer 1 is legal. Missing, True,
#    1.0, "1", and any other value raise.
# ---------------------------------------------------------------------------


def test_missing_schema_version_raises_invalid_graph():
    """A graph without a ``schema_version`` key is refused. The check
    does not default a missing version to ``1``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"timeframe": "1h"})
    assert excinfo.value.field == "schema_version"
    assert excinfo.value.value is None or "schema_version" in str(excinfo.value)


def test_missing_schema_version_field_is_schema_version():
    """The exception raised for a missing ``schema_version`` names
    ``schema_version`` as the offending field."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"timeframe": "1h"})
    assert excinfo.value.field == "schema_version"


def test_schema_version_true_raises_invalid_graph():
    """``True`` is rejected even though ``isinstance(True, int)`` is
    ``True`` in Python. ``bool`` is a subclass of ``int`` and the brief
    forbids letting that subclass relationship coerce the value. The
    check uses ``type(value) is int``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": True, "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"
    assert excinfo.value.value is True


def test_schema_version_false_raises_invalid_graph():
    """``False`` is also rejected for the same reason ``True`` is."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": False, "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"


def test_schema_version_one_point_zero_raises_invalid_graph():
    """``1.0`` is rejected even though it equals the integer ``1`` in
    numeric terms. The check refuses to coerce a float into an int."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1.0, "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"
    assert excinfo.value.value == 1.0


def test_schema_version_string_one_raises_invalid_graph():
    """``"1"`` is rejected even though ``int("1") == 1``. The check
    refuses to coerce a string into an int."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": "1", "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"
    assert excinfo.value.value == "1"


def test_schema_version_integer_two_raises_invalid_graph():
    """``2`` is rejected even though it is an int. The brief pins the
    only legal schema_version as the integer ``1``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 2, "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"
    assert excinfo.value.value == 2


def test_schema_version_zero_raises_invalid_graph():
    """``0`` is also rejected for the same reason."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 0, "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"


def test_schema_version_none_raises_invalid_graph():
    """``schema_version=None`` is rejected (it is present, just
    null)."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": None, "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"


def test_schema_version_list_raises_invalid_graph():
    """A list value for ``schema_version`` is rejected."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": [1], "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"


def test_schema_version_dict_raises_invalid_graph():
    """A dict value for ``schema_version`` is rejected."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": {"v": 1}, "timeframe": "1h"})
    assert excinfo.value.field == "schema_version"


def test_schema_version_check_does_not_use_isinstance():
    """Sanity check on the schema_version branch: ``True`` (a bool,
    which is a subclass of ``int``) must raise. If the implementation
    used ``isinstance(value, int)`` it would let ``True`` through.
    This test guards the contract by asserting the exact False
    condition the brief pins."""
    with pytest.raises(InvalidGraph):
        require_v1_clock({"schema_version": True, "timeframe": "1h"})


# ---------------------------------------------------------------------------
# 4. timeframe checks: only the strings "1h", "4h", "1d" are legal.
#    Missing, "1H", "1m", integer 1, and any other value raise.
# ---------------------------------------------------------------------------


def test_missing_timeframe_raises_invalid_graph():
    """A graph without a ``timeframe`` key is refused. The check does
    not default a missing timeframe to ``1h``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1})
    assert excinfo.value.field == "timeframe"


def test_missing_timeframe_field_is_timeframe():
    """The exception raised for a missing ``timeframe`` names
    ``timeframe`` as the offending field."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1})
    assert excinfo.value.field == "timeframe"


def test_timeframe_one_capital_H_raises_invalid_graph():
    """``"1H"`` is rejected — the legal values are case-sensitive."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": "1H"})
    assert excinfo.value.field == "timeframe"
    assert excinfo.value.value == "1H"


def test_timeframe_one_minute_raises_invalid_graph():
    """``"1m"`` is rejected because it is not in the schema's
    timeframe enum."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": "1m"})
    assert excinfo.value.field == "timeframe"
    assert excinfo.value.value == "1m"


def test_timeframe_integer_one_raises_invalid_graph():
    """The integer ``1`` is rejected even though ``str(1) == "1"``. The
    check refuses to coerce an int into a string."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": 1})
    assert excinfo.value.field == "timeframe"
    assert excinfo.value.value == 1


def test_timeframe_empty_string_raises_invalid_graph():
    """An empty string is rejected (not in the enum)."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": ""})
    assert excinfo.value.field == "timeframe"


def test_timeframe_none_raises_invalid_graph():
    """``timeframe=None`` is rejected (present but null)."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": None})
    assert excinfo.value.field == "timeframe"


def test_timeframe_other_duration_raises_invalid_graph():
    """A timeframe outside the v1 enum — ``"2h"``, ``"15m"``, ``"1w"``
    — is rejected."""
    for bad in ["2h", "15m", "1w", "30s", "5d", "12h"]:
        with pytest.raises(InvalidGraph) as excinfo:
            require_v1_clock({"schema_version": 1, "timeframe": bad})
        assert excinfo.value.field == "timeframe"


def test_timeframe_illegal_extra_hours_raises_invalid_graph():
    """``"24h"`` is rejected; the schema's enum is exactly ``"1h"``,
    ``"4h"``, ``"1d"``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": "24h"})
    assert excinfo.value.field == "timeframe"


def test_timeframe_check_does_not_invent_extra_values():
    """Sanity check on the timeframe branch: every value the schema
    forbids must raise. ``"1H"`` (case), ``"1m"`` (granularity), the
    integer ``1`` (type), and an empty string all raise."""
    for bad in ["1H", "1m", 1, ""]:
        with pytest.raises(InvalidGraph):
            require_v1_clock({"schema_version": 1, "timeframe": bad})


# ---------------------------------------------------------------------------
# 5. schema_version is checked before timeframe when both are bad. The
#    first failing field wins (it is the most informative reason).
# ---------------------------------------------------------------------------


def test_schema_version_is_reported_when_both_fields_are_bad():
    """When both ``schema_version`` and ``timeframe`` are illegal, the
    exception names ``schema_version`` first. The check orders
    ``schema_version`` ahead of ``timeframe`` because a wrong schema
    version is the more fundamental refusal."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 2, "timeframe": "1H"})
    assert excinfo.value.field == "schema_version"


def test_timeframe_is_reported_when_schema_version_is_legal():
    """When ``schema_version`` is legal but ``timeframe`` is not, the
    exception names ``timeframe``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": "1H"})
    assert excinfo.value.field == "timeframe"


# ---------------------------------------------------------------------------
# 6. The InvalidGraph exception carries field and value, and has no
#    equity, return_pct, or pnl attributes.
# ---------------------------------------------------------------------------


def test_invalid_graph_carries_the_offending_field():
    """``InvalidGraph.field`` is the name of the field that failed the
    check (``schema_version`` or ``timeframe``)."""
    err = InvalidGraph("schema_version", 1.0, "schema_version must be the integer 1")
    assert err.field == "schema_version"


def test_invalid_graph_carries_the_offending_value():
    """``InvalidGraph.value`` is the raw value that was supplied for
    that field — not a coerced, defaulted, or summarised form."""
    err = InvalidGraph("schema_version", 1.0, "schema_version must be the integer 1")
    assert err.value == 1.0


def test_invalid_graph_carries_true_verbatim():
    """When ``schema_version=True``, the exception's ``value``
    attribute is the boolean ``True``, not ``1``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": True, "timeframe": "1h"})
    assert excinfo.value.value is True


def test_invalid_graph_carries_one_point_zero_verbatim():
    """When ``schema_version=1.0``, the exception's ``value`` attribute
    is the float ``1.0``, not ``1``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1.0, "timeframe": "1h"})
    assert excinfo.value.value == 1.0
    assert isinstance(excinfo.value.value, float)


def test_invalid_graph_carries_string_one_verbatim():
    """When ``schema_version="1"``, the exception's ``value`` attribute
    is the string ``"1"``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": "1", "timeframe": "1h"})
    assert excinfo.value.value == "1"


def test_invalid_graph_carries_missing_schema_version_as_none():
    """When ``schema_version`` is missing, the exception's ``value``
    attribute is ``None``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"timeframe": "1h"})
    assert excinfo.value.field == "schema_version"
    assert excinfo.value.value is None


def test_invalid_graph_carries_one_H_verbatim():
    """When ``timeframe="1H"``, the exception's ``value`` attribute is
    the string ``"1H"``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": "1H"})
    assert excinfo.value.value == "1H"


def test_invalid_graph_carries_integer_timeframe_verbatim():
    """When ``timeframe=1``, the exception's ``value`` attribute is the
    integer ``1``, not ``"1"``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1, "timeframe": 1})
    assert excinfo.value.value == 1
    assert isinstance(excinfo.value.value, int) and not isinstance(excinfo.value.value, bool)


def test_invalid_graph_carries_missing_timeframe_as_none():
    """When ``timeframe`` is missing, the exception's ``value``
    attribute is ``None``."""
    with pytest.raises(InvalidGraph) as excinfo:
        require_v1_clock({"schema_version": 1})
    assert excinfo.value.field == "timeframe"
    assert excinfo.value.value is None


def test_invalid_graph_has_no_equity_attribute():
    """The brief forbids inventing ``equity`` on ``InvalidGraph``. A
    refused clock check is not a return."""
    err = InvalidGraph("schema_version", 2, "schema_version must be the integer 1")
    assert not hasattr(err, "equity")


def test_invalid_graph_has_no_return_pct_attribute():
    """The brief forbids inventing ``return_pct`` on ``InvalidGraph``."""
    err = InvalidGraph("schema_version", 2, "schema_version must be the integer 1")
    assert not hasattr(err, "return_pct")


def test_invalid_graph_has_no_pnl_attribute():
    """The brief forbids inventing ``pnl`` on ``InvalidGraph``."""
    err = InvalidGraph("schema_version", 2, "schema_version must be the integer 1")
    assert not hasattr(err, "pnl")


def test_invalid_graph_is_an_exception_subclass():
    """``InvalidGraph`` is an ``Exception`` subclass — it can be raised
    and caught the same way other NS19 exceptions are caught."""
    assert issubclass(InvalidGraph, Exception)


# ---------------------------------------------------------------------------
# 7. The brief's forbidden import set: units must not pull venues,
#    evaluate, or run into the IR.
# ---------------------------------------------------------------------------


def test_units_module_does_not_import_venues_run_or_evaluate():
    """``krellbot.strategy_ir.units`` stays a pure compile surface. The
    brief forbids importing ``krellbot.venues``,
    ``krellbot.pack.evaluate``, or ``krellbot.run`` — the clock check
    is a pure predicate over the graph shape."""
    source = inspect.getsource(units_mod)
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
                    f"units module imports {alias.name!r}"
                )
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not any(node.module == m or node.module.startswith(m + ".") for m in forbidden_modules), (
                f"units module does a from-import from {node.module!r}"
            )


def test_strategy_ir_package_does_not_import_venues_run_or_evaluate_via_units():
    """The package ``__init__`` does not pull ``krellbot.venues``,
    ``krellbot.run``, or ``krellbot.pack.evaluate`` into the IR layer.
    The units module is a pure compile surface and the package
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


def test_units_module_does_not_open_files_or_touch_the_clock():
    """``require_v1_clock`` is a pure in-memory predicate. No ``open``,
    no ``pathlib.Path.read_*``, no ``os.environ``, no ``time``, no
    ``datetime``, no ``keyring``, no ``requests``. The clock check is
    synchronous, in-memory, and side-effect-free."""
    source = inspect.getsource(units_mod)
    tree = ast.parse(source)
    forbidden_calls = {"open", "read_text", "read_bytes", "time", "datetime", "keyring"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in forbidden_calls:
            assert node.value.id not in forbidden_calls, f"units module calls {node.value.id}.{node.attr}"


# ---------------------------------------------------------------------------
# 8. Composition with the other NS19 leaves.
# ---------------------------------------------------------------------------


def test_require_v1_clock_is_independent_of_prepare_v1_and_check_availability():
    """``require_v1_clock`` (NS19e) is independent of ``prepare_v1``
    (NS19d) and ``check_availability`` (NS19a). The leaves remain
    importable from their own modules and are not coupled by the new
    module."""
    from krellbot.strategy_ir.availability import FutureData, check_availability
    from krellbot.strategy_ir.v1 import prepare_v1

    assert callable(check_availability)
    assert callable(prepare_v1)
    assert callable(require_v1_clock)
    assert FutureData is not InvalidGraph


def test_require_v1_clock_accepts_the_sma_cross_fixture_graph():
    """End-to-end property: the fixture pack ``sma_cross.json`` has
    ``schema_version=1`` and ``timeframe="1h"`` — both legal — so the
    clock check returns ``None``."""
    graph = {
        "schema_version": 1,
        "id": "sma-cross",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "origin": "Backtest fixture.",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    assert require_v1_clock(graph) is None

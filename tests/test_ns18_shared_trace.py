"""NS18b: replay and paper share one decision-trace builder.

The brief: one builder in `krellbot.domain.trace` is the only path that
emits the per-bar decision trace. `ResearchService._build_trace` (replay)
and `paper_decision_trace` (paper) both call that builder and return its
output. For one pack and one candle list, the two calls return equal
lists. A warmup condition outcome is the literal string ``"unknown"``,
never ``0``, ``0.0``, ``False``, or ``None``. The trace carries no
``fill_price`` and no ``venue_fill`` field; venue confirmation is the
adapter layer's concern, not this leaf.

The trace module imports `krellbot.pack.evaluate` (pure pack math) and
`krellbot.pack.model` (the `Candle` type). It does not import
`krellbot.venues`, `krellbot.run`, or anything that reads the OS
keyring or opens a network transport.
"""

from __future__ import annotations

import ast
import csv
import inspect
import json
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import application as application_pkg
from krellbot.application.research import (
    ResearchRequest,
    ResearchService,
)
from krellbot.domain import trace as trace_mod
from krellbot.domain.trace import paper_decision_trace, shared_decision_trace
from krellbot.pack.model import Candle

# ---------------------------------------------------------------------------
# Fixtures: a small pack + candle list runnable through `run_series`.
# ---------------------------------------------------------------------------

PACK_DICT = {
    "schema_version": 1,
    "id": "sma-cross",
    "version": "1.0.0",
    "label": "SMA cross",
    "author": "krellbot tests",
    "timeframe": "1h",
    "origin": "NS18b fixture.",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _synthetic_candles() -> list[Candle]:
    """8 1h bars: one cross above at bar 2, one cross below at bar 4.

    Bar 0 is in warmup (sma2 needs one previous close). Bar 2 closes
    above sma2 after a flat stretch; bar 4 closes below sma2. The rest
    are flat, so the trace covers every branch: warmup, entry, exit,
    and plain flat.
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
def synthetic_csv(tmp_path: Path) -> Path:
    """Write a small 1h CSV matching the synthetic candle shape."""
    path = tmp_path / "kraken_SUIUSD_1h.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_ms", "open", "high", "low", "close", "volume"])
        for c in _synthetic_candles():
            w.writerow([c.ts_ms, c.open, c.high, c.low, c.close, c.volume])
    return path


@pytest.fixture
def pack_path(tmp_path: Path) -> Path:
    p = tmp_path / "pack.json"
    p.write_text(json.dumps(PACK_DICT), encoding="utf-8")
    return p


@pytest.fixture
def pack_dict(pack_path: Path) -> dict:
    return json.loads(pack_path.read_text(encoding="utf-8"))


@pytest.fixture
def candles() -> list[Candle]:
    return _synthetic_candles()


# ---------------------------------------------------------------------------
# 1. shared_decision_trace exists at the brief's signature.
# ---------------------------------------------------------------------------


def test_shared_decision_trace_is_exposed():
    """The brief pins the symbol `shared_decision_trace` in
    `krellbot.domain.trace`. It must be importable from there."""
    assert hasattr(trace_mod, "shared_decision_trace")
    assert callable(trace_mod.shared_decision_trace)


def test_paper_decision_trace_is_exposed():
    """The brief pins the symbol `paper_decision_trace` in
    `krellbot.domain.trace`. It must be importable from there."""
    assert hasattr(trace_mod, "paper_decision_trace")
    assert callable(trace_mod.paper_decision_trace)


def test_shared_decision_trace_signature_is_pack_and_candles_only():
    """The brief pins the signature as `shared_decision_trace(pack, candles)`.
    No extra positional or keyword parameters beyond the two inputs."""
    sig = inspect.signature(shared_decision_trace)
    assert list(sig.parameters) == ["pack", "candles"]


def test_paper_decision_trace_signature_is_pack_and_candles_only():
    """Same brief pin for paper mode. The two functions share the
    signature."""
    sig = inspect.signature(paper_decision_trace)
    assert list(sig.parameters) == ["pack", "candles"]


# ---------------------------------------------------------------------------
# 2. Replay and paper return the same list for the same inputs.
# ---------------------------------------------------------------------------


def test_shared_and_paper_decision_trace_return_equal_lists(pack_dict: dict, candles: list[Candle]):
    """For one pack and one candle list, `shared_decision_trace` and
    `paper_decision_trace` return equal lists. Equality is exact, not
    element-wise tolerance: the lists are dicts, floats, and string
    sentinels and must compare with `==`."""
    a = shared_decision_trace(pack_dict, candles)
    b = paper_decision_trace(pack_dict, candles)
    assert a == b


def test_shared_and_paper_return_same_length(pack_dict: dict, candles: list[Candle]):
    """Both calls return one entry per candle. Length is the cheapest
    proxy for the equality."""
    assert len(shared_decision_trace(pack_dict, candles)) == len(candles)
    assert len(paper_decision_trace(pack_dict, candles)) == len(candles)


def test_paper_decision_trace_delegates_to_shared(monkeypatch, pack_dict: dict, candles: list[Candle]):
    """`paper_decision_trace` is the brief-mandated wrapper around the
    shared builder. Patch the shared builder to a sentinel and confirm
    the paper wrapper calls it and returns its output."""
    sentinel = [{"bar_ts": -1, "shared": True}]

    def fake_shared(p, c):
        assert p is pack_dict
        assert c is candles
        return sentinel

    monkeypatch.setattr(trace_mod, "shared_decision_trace", fake_shared)
    assert paper_decision_trace(pack_dict, candles) is sentinel


# ---------------------------------------------------------------------------
# 3. Existing trace keys stay. No fill_price, no venue_fill.
# ---------------------------------------------------------------------------


def test_shared_decision_trace_keeps_existing_keys(pack_dict: dict, candles: list[Candle]):
    """The brief pins the per-bar keys: `bar_ts`, `warmup`, `input`,
    `indicators`, `conditions`, `target`. Each entry must carry exactly
    these and nothing invented."""
    trace = shared_decision_trace(pack_dict, candles)
    expected = {"bar_ts", "warmup", "input", "indicators", "conditions", "target"}
    for entry in trace:
        assert set(entry.keys()) == expected


def test_paper_decision_trace_keeps_existing_keys(pack_dict: dict, candles: list[Candle]):
    """Paper mode emits the same keys."""
    trace = paper_decision_trace(pack_dict, candles)
    expected = {"bar_ts", "warmup", "input", "indicators", "conditions", "target"}
    for entry in trace:
        assert set(entry.keys()) == expected


@pytest.mark.parametrize("forbidden_field", ["fill_price", "venue_fill"])
def test_shared_decision_trace_has_no_fill_price_or_venue_fill(
    forbidden_field: str, pack_dict: dict, candles: list[Candle]
):
    """The brief forbids a `fill_price` or `venue_fill` field. The trace
    does not assert a modeled fill equals a venue fill."""
    trace = shared_decision_trace(pack_dict, candles)
    for entry in trace:
        assert forbidden_field not in entry


@pytest.mark.parametrize("forbidden_field", ["fill_price", "venue_fill"])
def test_paper_decision_trace_has_no_fill_price_or_venue_fill(
    forbidden_field: str, pack_dict: dict, candles: list[Candle]
):
    """Same brief pin for paper mode."""
    trace = paper_decision_trace(pack_dict, candles)
    for entry in trace:
        assert forbidden_field not in entry


# ---------------------------------------------------------------------------
# 4. The warmup condition outcome stays the literal string "unknown".
# ---------------------------------------------------------------------------


def test_shared_decision_trace_warmup_outcome_is_unknown_string(pack_dict: dict, candles: list[Candle]):
    """For every warmup bar, every condition outcome whose operands
    include `None` is the literal string `"unknown"`. The string is
    stored verbatim — the module does not coerce `"unknown"` to `0`,
    `0.0`, `None`, or `False`."""
    trace = shared_decision_trace(pack_dict, candles)
    # At least one entry must be a warmup entry (bar 0 — sma2 is not yet defined).
    warmup_entries = [t for t in trace if t["warmup"]]
    assert warmup_entries, trace
    unknown_seen = False
    for entry in warmup_entries:
        for cond in entry["conditions"]:
            outcome = cond["outcome"]
            # Strict string marker, not a bool, not a number, not None.
            assert outcome == "unknown" or outcome is True or outcome is False
            assert not isinstance(outcome, int)
            assert not isinstance(outcome, float)
            assert outcome is not None
            if outcome == "unknown":
                unknown_seen = True
    assert unknown_seen, "expected at least one 'unknown' outcome on a warmup bar"


def test_shared_decision_trace_unknown_is_not_zero_int(pack_dict: dict, candles: list[Candle]):
    """`"unknown"` must not be `0`. The brief forbids numeric coercion."""
    trace = shared_decision_trace(pack_dict, candles)
    for entry in trace:
        for cond in entry["conditions"]:
            outcome = cond["outcome"]
            if outcome == "unknown":
                assert outcome != 0
                assert outcome is not False


def test_shared_decision_trace_unknown_is_not_zero_float(pack_dict: dict, candles: list[Candle]):
    """`"unknown"` must not be `0.0`. The brief forbids float coercion."""
    trace = shared_decision_trace(pack_dict, candles)
    for entry in trace:
        for cond in entry["conditions"]:
            outcome = cond["outcome"]
            if outcome == "unknown":
                assert outcome != 0.0


def test_shared_decision_trace_unknown_is_not_none(pack_dict: dict, candles: list[Candle]):
    """`"unknown"` must not be `None`. The brief forbids null coercion."""
    trace = shared_decision_trace(pack_dict, candles)
    for entry in trace:
        for cond in entry["conditions"]:
            outcome = cond["outcome"]
            if outcome == "unknown":
                assert outcome is not None


def test_shared_decision_trace_unknown_is_str_instance(pack_dict: dict, candles: list[Candle]):
    """`"unknown"` is a `str`, not a numeric type that silently compares equal."""
    trace = shared_decision_trace(pack_dict, candles)
    for entry in trace:
        for cond in entry["conditions"]:
            outcome = cond["outcome"]
            if outcome == "unknown":
                assert isinstance(outcome, str)


def test_paper_decision_trace_preserves_unknown(pack_dict: dict, candles: list[Candle]):
    """The same warmup marker preservation holds for paper mode. The
    brief: one builder, one rule."""
    trace = paper_decision_trace(pack_dict, candles)
    warmup_entries = [t for t in trace if t["warmup"]]
    assert warmup_entries, trace
    for entry in warmup_entries:
        for cond in entry["conditions"]:
            outcome = cond["outcome"]
            if outcome == "unknown":
                assert isinstance(outcome, str)
                assert outcome != 0
                assert outcome != 0.0
                assert outcome is not None
                assert outcome is not False


# ---------------------------------------------------------------------------
# 5. Replay (ResearchService._build_trace) and paper share the builder.
# ---------------------------------------------------------------------------


def test_research_service_build_trace_equals_shared_decision_trace(pack_dict: dict, candles: list[Candle]):
    """`ResearchService._build_trace` is the replay entry point. Its
    output must equal `shared_decision_trace(pack, candles)` for the
    same inputs. The replay path must not diverge from paper mode."""
    svc = ResearchService(home=Path("/tmp/ns18b-shared-trace-home"))
    replay = svc._build_trace(pack_dict, candles)
    paper = paper_decision_trace(pack_dict, candles)
    shared = shared_decision_trace(pack_dict, candles)
    assert replay == shared
    assert replay == paper


def test_research_service_run_uses_shared_builder_for_trace(
    pack_path: Path, synthetic_csv: Path, tmp_path: Path, monkeypatch
):
    """End-to-end: running a research request produces a trace whose
    `trace` list equals the shared builder's output. Patch the shared
    builder and confirm the service picks it up (proving the service
    delegates rather than re-implementing)."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    svc = ResearchService(home=tmp_path)
    # First, baseline run.
    baseline = svc.run(ResearchRequest(pack_path=pack_path, dataset_csv=synthetic_csv, venue="kraken"))
    assert baseline.ok is True
    baseline_trace = baseline.detail["trace"]
    # Now patch the shared builder to a sentinel and confirm the service
    # produces the sentinel verbatim — proving it calls the shared builder.
    sentinel = [
        {
            "bar_ts": -1,
            "warmup": True,
            "input": {},
            "indicators": {},
            "conditions": [],
            "target": {"long": False, "stop_price": None, "reason": "warmup"},
        }
    ]
    monkeypatch.setattr(
        "krellbot.application.research.shared_decision_trace",
        lambda p, c: sentinel,
    )
    patched = svc.run(ResearchRequest(pack_path=pack_path, dataset_csv=synthetic_csv, venue="kraken"))
    assert patched.ok is True
    assert patched.detail["trace"] is sentinel
    # Sanity: baseline trace keys match the brief keys.
    expected = {"bar_ts", "warmup", "input", "indicators", "conditions", "target"}
    for entry in baseline_trace:
        assert set(entry.keys()) == expected


# ---------------------------------------------------------------------------
# 6. No venue imports, no run imports.
# ---------------------------------------------------------------------------


def test_shared_decision_trace_module_does_not_import_venues():
    """`krellbot.domain.trace` must not import `krellbot.venues`."""
    source = inspect.getsource(trace_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "venues" not in alias.name, f"trace module imports {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert "venues" not in (node.module or ""), f"trace module does a from-import from {(node.module)!r}"
            for alias in node.names:
                assert "venues" not in alias.name, f"trace module imports {alias.name!r} from {node.module!r}"


def test_shared_decision_trace_module_does_not_import_run():
    """`krellbot.domain.trace` must not import `krellbot.run`."""
    source = inspect.getsource(trace_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("krellbot.run"), f"trace module imports {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not (node.module or "").startswith("krellbot.run"), (
                f"trace module does a from-import from {(node.module)!r}"
            )


def test_application_research_does_not_define_a_parallel_builder():
    """The brief forbids replay keeping its own trace builder in
    parallel. After the move, `krellbot.application.research` must not
    still expose `_build_trace` as a method that builds the trace
    inline — it must call the shared builder. The method can stay as a
    thin shim, but its body must not duplicate `_condition_outcomes` /
    `_operand_value` / `_outcome_for` (those moved with the builder)."""
    src = inspect.getsource(application_pkg.research)
    # The helpers that walked the condition tree must have moved with
    # the builder. If they remain in research.py, replay could drift
    # from paper mode again.
    assert "def _condition_outcomes(" not in src
    assert "def _operand_value(" not in src
    assert "def _operand_token(" not in src
    assert "def _outcome_for(" not in src


# ---------------------------------------------------------------------------
# 7. Determinism: same inputs yield byte-identical output.
# ---------------------------------------------------------------------------


def test_shared_decision_trace_is_deterministic(pack_dict: dict, candles: list[Candle]):
    """Two calls with the same pack and candle list produce equal lists."""
    a = shared_decision_trace(pack_dict, candles)
    b = shared_decision_trace(pack_dict, candles)
    assert a == b


def test_paper_decision_trace_is_deterministic(pack_dict: dict, candles: list[Candle]):
    """Same for paper mode."""
    a = paper_decision_trace(pack_dict, candles)
    b = paper_decision_trace(pack_dict, candles)
    assert a == b

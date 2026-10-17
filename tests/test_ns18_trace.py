"""NS18a: decision trace keeps unknown as unknown.

`decision_trace(*, source_ts_ms, rule_value, intent)` returns a record
with exactly those three fields. `source_ts_ms` is stored as given.
When `rule_value` is the literal string `"unknown"`, the record stores
the string `"unknown"` — it does not coerce it to `0`, `0.0`, or `None`,
and it does not invent a `fill_price` or `venue_fill` field. There is
no helper in this module that returns true for modeled fills matching
venue fills.

The module does not import `krellbot.venues` or `krellbot.run`. Venue
knowledge stays in the adapter layer; run knowledge stays in the
tick / journal layer.
"""

from __future__ import annotations

import ast
import inspect
import os
import subprocess
import sys
from dataclasses import fields
from decimal import Decimal

import pytest

from krellbot.domain import trace as trace_mod
from krellbot.domain.trace import decision_trace

# ---------------------------------------------------------------------------
# 1. decision_trace signature: keyword-only, three-field record, no IO.
# ---------------------------------------------------------------------------


def test_decision_trace_returns_record_with_three_fields():
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="hold", intent="entry")
    assert hasattr(rec, "source_ts_ms")
    assert hasattr(rec, "rule_value")
    assert hasattr(rec, "intent")


def test_decision_trace_records_source_ts_ms_exactly():
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="hold", intent="entry")
    assert rec.source_ts_ms == 1_700_000_000_000


def test_decision_trace_source_ts_ms_zero_is_preserved():
    """`source_ts_ms=0` is a legal value (the source had no timestamp yet).
    The function does not coerce it away."""
    rec = decision_trace(source_ts_ms=0, rule_value="hold", intent="entry")
    assert rec.source_ts_ms == 0


def test_decision_trace_source_ts_ms_large_is_preserved():
    rec = decision_trace(source_ts_ms=2_500_000_000_000, rule_value="hold", intent="entry")
    assert rec.source_ts_ms == 2_500_000_000_000


def test_decision_trace_records_intent_exactly():
    rec = decision_trace(source_ts_ms=1, rule_value="hold", intent="entry")
    assert rec.intent == "entry"
    rec2 = decision_trace(source_ts_ms=1, rule_value="hold", intent="exit")
    assert rec2.intent == "exit"


def test_decision_trace_records_rule_value_exactly():
    """A numeric `rule_value` is stored exactly as passed. The function
    does not invent a fill price and does not coerce the value."""
    rec = decision_trace(source_ts_ms=1, rule_value=Decimal("30000.5"), intent="entry")
    assert rec.rule_value == Decimal("30000.5")


def test_decision_trace_arguments_are_keyword_only():
    """The brief pins the signature as keyword-only (`*,`). Positional
    arguments must not be accepted."""
    with pytest.raises(TypeError):
        decision_trace(1, "hold", "entry")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. unknown stays unknown — the brief's central guarantee.
# ---------------------------------------------------------------------------


def test_decision_trace_unknown_stays_unknown():
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent="entry")
    assert rec.rule_value == "unknown"


def test_decision_trace_unknown_is_not_zero_int():
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent="entry")
    assert rec.rule_value != 0


def test_decision_trace_unknown_is_not_zero_float():
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent="entry")
    assert rec.rule_value != 0.0


def test_decision_trace_unknown_is_not_none():
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent="entry")
    assert rec.rule_value is not None


def test_decision_trace_unknown_is_not_empty_string():
    """The brief forbids substituting `""` for the literal `"unknown"`.
    A caller passing the four-character string `"unknown"` must see
    those four characters in the record, not an empty value."""
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent="entry")
    assert rec.rule_value != ""


def test_decision_trace_unknown_is_str_instance():
    """The stored `"unknown"` is a string, not a number. The brief forbids
    the engine from quietly turning the missing-value marker into `0` or
    `0.0`."""
    rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent="entry")
    assert isinstance(rec.rule_value, str)


def test_decision_trace_unknown_preserved_for_every_intent():
    """`"unknown"` is preserved verbatim across every `intent` value.
    The engine never rewrites the missing-value marker for one intent
    but not another."""
    for intent in ("entry", "exit", "stop", "raise_stop", "ensure_stop"):
        rec = decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent=intent)
        assert rec.rule_value == "unknown", intent


def test_decision_trace_unknown_for_zero_source_ts_ms():
    """A missing `source_ts_ms` (caller passed `0`) does not change how
    `unknown` is preserved: the rule value is still `"unknown"`."""
    rec = decision_trace(source_ts_ms=0, rule_value="unknown", intent="entry")
    assert rec.rule_value == "unknown"
    assert rec.source_ts_ms == 0


def test_decision_trace_other_strings_are_preserved_verbatim():
    """The brief pins only the `"unknown"` case, but the implementation
    stores every rule value verbatim. Sanity-check that non-`unknown`
    strings are not mangled either."""
    rec = decision_trace(source_ts_ms=1, rule_value="hold", intent="entry")
    assert rec.rule_value == "hold"
    assert isinstance(rec.rule_value, str)


def test_decision_trace_numeric_rule_value_is_preserved_verbatim():
    """A real numeric `rule_value` is stored as a number, not as the
    string `"unknown"`."""
    rec = decision_trace(source_ts_ms=1, rule_value=30000.5, intent="entry")
    assert rec.rule_value == 30000.5
    assert rec.rule_value != "unknown"


# ---------------------------------------------------------------------------
# 3. The record has no fill_price and no venue_fill field.
# ---------------------------------------------------------------------------


def test_decision_trace_record_has_no_fill_price_field():
    """The brief forbids inventing `fill_price`. The record carries only
    `source_ts_ms`, `rule_value`, and `intent`."""
    rec = decision_trace(source_ts_ms=1, rule_value="hold", intent="entry")
    assert not hasattr(rec, "fill_price")


def test_decision_trace_record_has_no_venue_fill_field():
    """The brief forbids inventing `venue_fill`. The record carries only
    `source_ts_ms`, `rule_value`, and `intent`."""
    rec = decision_trace(source_ts_ms=1, rule_value="hold", intent="entry")
    assert not hasattr(rec, "venue_fill")


def test_decision_trace_record_keys_are_exactly_brief_fields():
    """The record exposes exactly the three brief fields and nothing
    invented. No `fill_price`, no `venue_fill`, no `modeled_px`,
    no `fee_bps`, no `bar_ts`, no venue field."""
    rec = decision_trace(source_ts_ms=1, rule_value="hold", intent="entry")
    forbidden = {"fill_price", "venue_fill", "modeled_px", "fee_bps", "bar_ts", "venue"}
    field_names = {f.name for f in fields(rec)}
    assert forbidden.isdisjoint(field_names)


@pytest.mark.parametrize("forbidden_field", ["fill_price", "venue_fill"])
def test_decision_trace_record_has_no_forbidden_field(forbidden_field: str):
    rec = decision_trace(source_ts_ms=1, rule_value="hold", intent="entry")
    assert forbidden_field not in {f.name for f in fields(rec)}


def test_decision_trace_record_unknown_value_keeps_no_fill_price():
    """The no-`fill_price` rule holds even when `rule_value` is the
    literal `"unknown"`. The engine does not pretend a venue fill."""
    rec = decision_trace(source_ts_ms=1, rule_value="unknown", intent="entry")
    assert not hasattr(rec, "fill_price")
    assert not hasattr(rec, "venue_fill")


# ---------------------------------------------------------------------------
# 4. The module does not add a helper that equates modeled and venue fills.
# ---------------------------------------------------------------------------


def test_decision_trace_module_does_not_expose_fills_equal_venue():
    """The brief explicitly forbids a `fills_equal_venue()` helper. The
    function name must not exist on the module."""
    assert not hasattr(trace_mod, "fills_equal_venue")


def test_decision_trace_module_does_not_expose_equal_fills():
    """No helper anywhere in the module returns true when a modeled fill
    matches a venue fill. Any such helper would be a forbidden lie."""
    for name in ("fills_equal_venue", "fills_match", "modeled_matches_venue", "equal_fills"):
        assert not hasattr(trace_mod, name), f"trace module must not expose {name!r}"


def test_decision_trace_module_reexports_decision_trace_and_record():
    """The public surface is the record class plus the factory."""
    assert hasattr(trace_mod, "decision_trace")
    assert hasattr(trace_mod, "DecisionTrace")


# ---------------------------------------------------------------------------
# 5. Isolation: no venue imports, no run imports.
# ---------------------------------------------------------------------------


def test_decision_trace_module_does_not_import_venues():
    """`krellbot.domain.trace` must not import `krellbot.venues`."""
    source = inspect.getsource(trace_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "venues" not in alias.name, f"krellbot.domain.trace imports {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert "venues" not in (node.module or ""), (
                f"krellbot.domain.trace does a from-import from {(node.module)!r}"
            )
            for alias in node.names:
                assert "venues" not in alias.name, f"krellbot.domain.trace imports {alias.name!r} from {node.module!r}"


def test_decision_trace_module_does_not_import_run():
    """`krellbot.domain.trace` must not import `krellbot.run`."""
    source = inspect.getsource(trace_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("krellbot.run"), f"krellbot.domain.trace imports {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            assert not (node.module or "").startswith("krellbot.run"), (
                f"krellbot.domain.trace does a from-import from {(node.module)!r}"
            )


def test_decision_trace_module_does_not_call_into_venues_or_run(monkeypatch):
    """Tripwire: any import of `krellbot.venues` or `krellbot.run` raises
    immediately. Reloads `trace` so the patched `__import__` runs against
    a fresh module object. Note: this test is the last one to touch
    `trace_mod`, because reloading it invalidates the locally-cached
    `DecisionTrace` reference imported at the top of this file."""
    import importlib

    real_import = __import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "krellbot.venues" or name.startswith("krellbot.venues."):
            raise AssertionError(
                f"krellbot.domain.trace must not import krellbot.venues (attempted import of {name!r})"
            )
        if name == "krellbot.run" or name.startswith("krellbot.run."):
            raise AssertionError(f"krellbot.domain.trace must not import krellbot.run (attempted import of {name!r})")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", guarded_import)
    importlib.reload(trace_mod)


def test_decision_trace_module_under_isolated_subprocess_has_no_venues_or_run_imports():
    """Run the module in a subprocess with `krellbot.venues` and
    `krellbot.run` import-blocked. The module must load and
    `decision_trace` must still return a record that preserves
    `unknown` verbatim."""
    env = dict(os.environ)
    env.pop("KRAKEN_API_KEY", None)
    env.pop("KRAKEN_API_SECRET", None)
    env.pop("COINBASE_API_KEY", None)
    env.pop("COINBASE_API_SECRET", None)
    env.pop("COINBASE_API_PASSPHRASE", None)
    env["KRELLBOT_HOME"] = "/tmp/var-folder-tmp-NS18a"
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    code = (
        "import builtins\n"
        "_real_import = builtins.__import__\n"
        "def _guard(name, globals=None, locals=None, fromlist=(), level=0):\n"
        "    if name == 'krellbot.venues' or name.startswith('krellbot.venues.'):\n"
        "        raise SystemExit('blocked: ' + name)\n"
        "    if name == 'krellbot.run' or name.startswith('krellbot.run.'):\n"
        "        raise SystemExit('blocked: ' + name)\n"
        "    return _real_import(name, globals, locals, fromlist, level)\n"
        "builtins.__import__ = _guard\n"
        "from krellbot.domain.trace import decision_trace\n"
        "rec = decision_trace(source_ts_ms=1, rule_value='unknown', intent='entry')\n"
        "assert rec.rule_value == 'unknown'\n"
        "assert rec.source_ts_ms == 1\n"
        "assert rec.intent == 'entry'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"isolated subprocess failed:\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    assert "OK" in result.stdout


# ---------------------------------------------------------------------------
# 6. Re-exports: the decision trace is reachable from krellbot.domain.
# ---------------------------------------------------------------------------


def test_domain_package_reexports_decision_trace():
    """`krellbot.domain.decision_trace` is the public factory; `DecisionTrace`
    is the record type."""
    import krellbot.domain as domain_mod

    assert hasattr(domain_mod, "decision_trace")
    assert hasattr(domain_mod, "DecisionTrace")


def test_decision_trace_callable_from_domain_package():
    """`krellbot.domain.decision_trace(...)` builds the same record as
    `krellbot.domain.trace.decision_trace(...)`."""
    from krellbot import domain as domain_mod

    rec = domain_mod.decision_trace(source_ts_ms=1_700_000_000_000, rule_value="unknown", intent="entry")
    assert rec.rule_value == "unknown"
    assert rec.source_ts_ms == 1_700_000_000_000
    assert rec.intent == "entry"
    assert hasattr(rec, "rule_value")
    assert hasattr(rec, "source_ts_ms")
    assert hasattr(rec, "intent")

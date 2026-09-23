"""Lint semantic checks beyond JSON schema.

Schema covers structure; this layer covers indicator-uniqueness, operand
resolution, lookback budget, and condition nesting depth.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot.pack import lint

FIX = Path(__file__).parent / "fixtures" / "packs"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def test_lint_rejects_lookback_601():
    pack = _load("valid.json")
    pack["indicators"]["sma20"]["len"] = 600
    errors = lint.check(pack)
    assert errors
    assert any("lookback" in e["message"] for e in errors)


def test_lint_rejects_unused_indicator():
    pack = _load("bad_unused_indicator.json")
    errors = lint.check(pack)
    assert errors
    assert any("unused" in e["message"].lower() or e["field"].startswith("indicators.") for e in errors)


def test_lint_rejects_undefined_indicator_operand():
    pack = _load("bad_undefined_operand.json")
    errors = lint.check(pack)
    assert errors
    assert any("entry" in e["field"] or "exit" in e["field"] for e in errors)


def test_lint_rejects_nested_depth_4():
    pack = _load("bad_nested_depth.json")
    errors = lint.check(pack)
    assert errors
    assert any("depth" in e["message"].lower() for e in errors)


def test_lint_accepts_depth_3():
    pack = _load("deep_ok.json")
    errors = lint.check(pack)
    assert errors == [], f"unexpected errors: {errors}"


def test_lint_accepts_legacy_pack():
    """A file with id+public_label and no schema_version is legacy: not runnable."""
    pack = _load("legacy.json")
    result = lint.check(pack)
    assert result == []
    assert lint.is_legacy(pack)


def test_lint_rejects_power_mean_p_zero():
    """power_mean with p=0 is forbidden (would be a geometric-mean-like edge case)."""
    pack = _load("bad_power_mean_p_zero.json")
    errors = lint.check(pack)
    assert errors
    assert any("p" in e["field"] for e in errors)

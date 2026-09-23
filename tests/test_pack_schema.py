"""Schema tests for krellbot.pack.

A valid DSL pack passes schema. Short side, unknown key, and bad lookback fail.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot.pack import lint

FIXTURES = Path(__file__).parent / "fixtures" / "packs"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_schema_accepts_valid_pack():
    pack = _load("valid.json")
    errors = lint.check(pack)
    assert errors == [], f"unexpected errors: {errors}"


def test_schema_rejects_short_side():
    """A top-level `short` key must fail schema because the DSL forbids shorts."""
    pack = _load("bad_short.json")
    errors = lint.check(pack)
    assert errors, "expected at least one error for `short` key"
    fields = [e["field"] for e in errors]
    assert any(f == "short" or f.startswith("short.") for f in fields), f"missing 'short' in {fields}"


def test_schema_rejects_unknown_key():
    pack = _load("bad_unknown.json")
    errors = lint.check(pack)
    assert errors, "expected at least one error for unknown key"
    fields = [e["field"] for e in errors]
    assert any(f == "leverage" or f.startswith("leverage.") for f in fields), f"missing 'leverage' in {fields}"


def test_schema_rejects_bad_id_pattern():
    pack = _load("bad_id.json")
    errors = lint.check(pack)
    assert errors
    fields = [e["field"] for e in errors]
    assert any(f == "id" for f in fields)


def test_schema_rejects_bad_pair_pattern():
    pack = _load("bad_pair.json")
    errors = lint.check(pack)
    assert errors
    fields = [e["field"] for e in errors]
    assert any(f.startswith("markets") for f in fields)


def test_schema_rejects_lookback_601():
    """An indicator with len 601 must be rejected by the lint pass."""
    pack = _load("bad_lookback_601.json")
    errors = lint.check(pack)
    assert errors, "expected at least one error for len > 600"
    fields = [e["field"] for e in errors]
    assert any("len" in f for f in fields), f"missing len field in {fields}"

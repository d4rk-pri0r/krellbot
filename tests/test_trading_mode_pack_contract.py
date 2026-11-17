"""Trading-mode pack contract: reserved ids, mode metadata, refusal rules."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from krellbot.pack import lint, modes

FIX = Path(__file__).parent / "fixtures" / "packs"


def _base_dsl() -> dict:
    import json

    return json.loads((FIX / "valid.json").read_text(encoding="utf-8"))


def _dca_pack() -> dict:
    pack = _base_dsl()
    pack["id"] = "mode-dca"
    pack["label"] = modes.MODE_LABELS["dca"]
    pack["origin"] = "Built-in DCA mode pack. Not live market performance."
    pack["mode"] = {"kind": "dca"}
    return pack


def _grid_pack() -> dict:
    pack = _base_dsl()
    pack["id"] = "mode-grid"
    pack["label"] = modes.MODE_LABELS["grid"]
    pack["origin"] = "Built-in grid mode pack. Long-only DSL; not a venue grid bot."
    pack["mode"] = {"kind": "grid", "levels": 5}
    return pack


def _rebalance_pack() -> dict:
    pack = _base_dsl()
    pack["id"] = "mode-rebalance"
    pack["label"] = modes.MODE_LABELS["rebalance"]
    pack["origin"] = "Built-in rebalance mode pack. Strategy-owned inventory only."
    pack["mode"] = {
        "kind": "rebalance",
        "threshold_pct": 5,
        "targets": [
            {"symbol": "BTC", "weight_pct": 60},
            {"symbol": "USD", "weight_pct": 40},
        ],
    }
    return pack


def test_docs_name_three_mode_ids():
    doc = Path("docs/trading-modes.md").read_text(encoding="utf-8")
    for mode_id in ("mode-dca", "mode-grid", "mode-rebalance"):
        assert mode_id in doc
    for kind in ("dca", "grid", "rebalance"):
        assert kind in doc
    pack_format = Path("docs/pack-format.md").read_text(encoding="utf-8")
    assert "trading-modes.md" in pack_format
    assert "`mode`" in pack_format or "mode" in pack_format


@pytest.mark.parametrize(
    "factory",
    [_dca_pack, _grid_pack, _rebalance_pack],
    ids=["dca", "grid", "rebalance"],
)
def test_valid_mode_packs_pass_lint(factory):
    pack = factory()
    errors = lint.check(pack)
    assert errors == [], f"unexpected errors: {errors}"


def test_ordinary_pack_without_mode_still_valid():
    pack = _base_dsl()
    assert "mode" not in pack
    assert lint.check(pack) == []


def test_reserved_mode_id_without_mode_is_refused():
    pack = _base_dsl()
    pack["id"] = "mode-dca"
    pack["origin"] = "missing mode object"
    errors = lint.check(pack)
    assert errors
    assert any(e["field"] == "mode" for e in errors)


def test_mode_pack_missing_origin_is_refused():
    pack = _dca_pack()
    del pack["origin"]
    errors = lint.check(pack)
    assert errors
    assert any(e["field"] == "origin" for e in errors)


def test_mode_pack_empty_origin_is_refused():
    pack = _dca_pack()
    pack["origin"] = "   "
    errors = lint.check(pack)
    assert errors
    assert any(e["field"] == "origin" for e in errors)


def test_mode_kind_id_mismatch_is_refused():
    pack = _dca_pack()
    pack["id"] = "mode-grid"
    errors = lint.check(pack)
    assert errors
    assert any(e["field"] == "id" for e in errors)


def test_grid_mode_missing_levels_is_refused():
    pack = _grid_pack()
    pack["mode"] = {"kind": "grid"}
    errors = lint.check(pack)
    assert errors
    assert any("levels" in e["field"] or "levels" in e["message"] for e in errors)


def test_rebalance_mode_missing_targets_is_refused():
    pack = _rebalance_pack()
    pack["mode"] = {"kind": "rebalance", "threshold_pct": 5}
    errors = lint.check(pack)
    assert errors
    assert any("targets" in e["field"] or "targets" in e["message"] for e in errors)


def test_rebalance_mode_missing_threshold_is_refused():
    pack = _rebalance_pack()
    pack["mode"] = {
        "kind": "rebalance",
        "targets": copy.deepcopy(pack["mode"]["targets"]),
    }
    errors = lint.check(pack)
    assert errors
    assert any("threshold" in e["field"] or "threshold" in e["message"] for e in errors)


def test_rebalance_weights_must_sum_to_100():
    pack = _rebalance_pack()
    pack["mode"]["targets"] = [
        {"symbol": "BTC", "weight_pct": 70},
        {"symbol": "USD", "weight_pct": 40},
    ]
    errors = lint.check(pack)
    assert errors
    assert any(e["field"] == "mode.targets" for e in errors)


def test_mode_constants_cover_three_kinds():
    assert set(modes.MODE_IDS) == modes.MODE_KINDS == {"dca", "grid", "rebalance"}
    assert modes.MODE_IDS["dca"] == "mode-dca"
    assert modes.MODE_IDS["grid"] == "mode-grid"
    assert modes.MODE_IDS["rebalance"] == "mode-rebalance"

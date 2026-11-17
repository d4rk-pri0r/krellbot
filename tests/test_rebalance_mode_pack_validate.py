"""Built-in rebalance mode pack validates; targets/threshold are pack fields."""

from __future__ import annotations

import copy
import json
from importlib import resources
from pathlib import Path

from krellbot.pack import lint, modes
from krellbot.release_policy import PAPER_ONLY_RELEASE

_MODES_DIR = resources.files("krellbot.packs").joinpath("modes")
_PACK_NAME = "mode-rebalance.json"


def _load_shipped() -> dict:
    raw = _MODES_DIR.joinpath(_PACK_NAME).read_text(encoding="utf-8")
    pack = json.loads(raw)
    assert isinstance(pack, dict)
    return pack


def test_shipped_rebalance_mode_pack_validates():
    pack = _load_shipped()
    assert pack["id"] == modes.MODE_IDS["rebalance"]
    assert pack["label"] == modes.MODE_LABELS["rebalance"]
    assert pack["mode"]["kind"] == "rebalance"
    errors = lint.check(pack)
    assert errors == [], f"unexpected errors: {errors}"


def test_rebalance_targets_and_threshold_are_pack_fields():
    pack = _load_shipped()
    mode = pack["mode"]
    assert isinstance(mode["threshold_pct"], (int, float))
    assert 0 < float(mode["threshold_pct"]) <= 100
    targets = mode["targets"]
    assert isinstance(targets, list) and targets
    weight_sum = 0.0
    for row in targets:
        assert isinstance(row["symbol"], str) and row["symbol"].strip()
        weight = float(row["weight_pct"])
        assert 0 < weight <= 100
        weight_sum += weight
    assert abs(weight_sum - 100.0) <= 0.01


def test_rebalance_origin_preserves_strategy_owned_inventory_note():
    pack = _load_shipped()
    origin = pack["origin"].lower()
    assert "strategy-owned" in origin
    assert "inventory" in origin


def test_rebalance_pack_lives_under_packs_modes():
    """Prefer pack-only ship path; not mixed into starter catalogue examples."""
    path = Path(str(_MODES_DIR.joinpath(_PACK_NAME)))
    assert path.is_file()
    assert "packs" in path.parts and "modes" in path.parts
    assert "examples" not in path.parts


def test_tampered_rebalance_missing_targets_is_refused():
    pack = _load_shipped()
    pack["mode"] = {"kind": "rebalance", "threshold_pct": copy.deepcopy(pack["mode"]["threshold_pct"])}
    errors = lint.check(pack)
    assert errors
    assert any("targets" in e["field"] or "targets" in e["message"] for e in errors)


def test_paper_only_release_stays_true():
    assert PAPER_ONLY_RELEASE is True

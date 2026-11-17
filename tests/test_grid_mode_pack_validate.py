"""Built-in grid mode pack validates; honesty vs a full exchange grid bot."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

from krellbot.pack import lint, modes

_MODES_PACKAGE = "krellbot.packs.modes"
_GRID_PACK_FILE = "mode-grid.json"
_REPO_GRID_PACK = Path(__file__).resolve().parents[1] / "src" / "krellbot" / "packs" / "modes" / _GRID_PACK_FILE


def _load_builtin_grid_pack() -> dict:
    raw = resources.files(_MODES_PACKAGE).joinpath(_GRID_PACK_FILE).read_text(encoding="utf-8")
    pack = json.loads(raw)
    assert isinstance(pack, dict)
    return pack


def test_builtin_grid_mode_pack_validates():
    pack = _load_builtin_grid_pack()
    assert pack["id"] == modes.MODE_IDS["grid"]
    assert pack["label"] == modes.MODE_LABELS["grid"]
    assert pack["mode"] == {"kind": "grid", "levels": 5}
    assert isinstance(pack.get("origin"), str) and pack["origin"].strip()
    errors = lint.check(pack)
    assert errors == [], f"unexpected errors: {errors}"


def test_builtin_grid_mode_pack_is_long_only_dsl():
    """Grid stays ordinary last-bar long/flat DSL — not a multi-order venue ladder."""
    pack = _load_builtin_grid_pack()
    assert pack["mode"]["kind"] == "grid"
    assert 2 <= int(pack["mode"]["levels"]) <= 50
    # Band edges live in indicators + entry/exit (highest/lowest), as documented.
    assert "band_high" in pack["indicators"]
    assert "band_low" in pack["indicators"]
    assert pack["indicators"]["band_high"]["fn"] == "highest"
    assert pack["indicators"]["band_low"]["fn"] == "lowest"
    assert "entry" in pack and "exit" in pack and "risk" in pack and "markets" in pack


def test_docs_state_grid_honesty_limits():
    doc = Path("docs/trading-modes.md").read_text(encoding="utf-8")
    lowered = doc.lower()
    assert "mode-grid" in doc
    assert "long-only" in lowered
    assert "full exchange grid" in lowered
    assert "no short" in lowered
    assert "no venue-native grid" in lowered
    assert "no hidden multi-order ladder" in lowered
    assert "krellbot.packs.modes" in doc or "packs/modes" in doc


def test_repo_and_package_grid_pack_match():
    """Shipped package resource matches the checkout modes path."""
    packaged = _load_builtin_grid_pack()
    on_disk = json.loads(_REPO_GRID_PACK.read_text(encoding="utf-8"))
    assert packaged == on_disk

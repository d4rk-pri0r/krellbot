"""Built-in trading-mode packs shipped as package data.

JSON files live under ``krellbot.packs.modes`` (``mode-<kind>.json``).
Loaders are read-only: they never write under ``KRELLBOT_HOME``, arm a
strategy, or start a scheduler. Interval and sizing stay explicit in the
pack JSON (``timeframe``, ``risk.max_account_pct``).
"""

from __future__ import annotations

import json
from importlib import resources

from krellbot.pack.modes import MODE_IDS, MODE_KINDS

_MODES_PACKAGE = "krellbot.packs.modes"


class ModePackError(RuntimeError):
    """Shipped mode pack is missing or inconsistent."""


def _filename_for(kind: str) -> str:
    return f"{MODE_IDS[kind]}.json"


def available_mode_kinds() -> list[str]:
    """Return kinds that have a shipped JSON file, MODE_IDS order."""
    root = resources.files(_MODES_PACKAGE)
    out: list[str] = []
    for kind in ("dca", "grid", "rebalance"):
        if kind not in MODE_KINDS:
            continue
        if root.joinpath(_filename_for(kind)).is_file():
            out.append(kind)
    return out


def load_mode_pack(kind: str) -> dict:
    """Load one built-in mode pack as a fresh dict.

    Raises ``KeyError`` for unknown kinds and ``ModePackError`` when the
    package data is missing or the pack id / mode.kind disagree.
    """
    if kind not in MODE_KINDS:
        raise KeyError(f"unknown mode kind: {kind!r}")
    filename = _filename_for(kind)
    path = resources.files(_MODES_PACKAGE).joinpath(filename)
    if not path.is_file():
        raise ModePackError(f"built-in mode pack {filename!r} is not shipped")
    pack = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(pack, dict):
        raise ModePackError(f"{filename!r} must be a JSON object")
    expected_id = MODE_IDS[kind]
    if pack.get("id") != expected_id:
        raise ModePackError(f"{filename!r} must have id {expected_id!r}")
    mode = pack.get("mode")
    if not isinstance(mode, dict) or mode.get("kind") != kind:
        raise ModePackError(f"{filename!r} must declare mode.kind {kind!r}")
    return pack

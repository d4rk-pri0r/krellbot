"""Pack DSL: readable JSON strategies the engine evaluates locally.

Public surface:
    * `check` / `is_legacy` / `lint_pack` - schema + semantic validation
    * `evaluate` is the submodule containing the pure `run` function
    * `indicators` - whitelist indicator math (float64)
    * `model` - Candle, Target dataclasses
"""

from __future__ import annotations

import json
from pathlib import Path

from . import evaluate, indicators
from .lint import check, is_legacy, lint_pack
from .model import Candle, Target

run = evaluate.run

__all__ = [
    "Candle",
    "Target",
    "check",
    "evaluate",
    "indicators",
    "is_legacy",
    "lint_pack",
    "load_pack",
    "run",
]


def load_pack(path: Path) -> tuple[str, dict]:
    """Load a pack JSON file. Returns ('dsl', dict) or ('legacy', dict).

    Raises FileNotFoundError or json.JSONDecodeError on IO/parse failure.
    Raises ValueError if the file looks like it tries to be DSL but is broken.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if is_legacy(data):
        return "legacy", data
    if "schema_version" in data:
        errors = check(data)
        if errors:
            msg = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
            raise ValueError(f"invalid DSL pack: {msg}")
        return "dsl", data
    return "unknown", data


def discover(home) -> list[tuple[Path, str, dict]]:
    """Return all (path, kind, data) tuples found in <home>/packs/ and
    <home>/packs/community/.

    `home` is the krellbot root (`paths.home()`), not the OS user home.
    Skips files that fail IO or JSON parsing. Skips non-dict roots. Does not
    validate DSL packs here - that is the lint command's job. Whether a pack
    is "community" is determined by its parent directory; callers check
    `krellbot.catalog.is_community(path, home)` to decide what to print.
    """
    out: list[tuple[Path, str, dict]] = []
    for sub in ("packs", "packs/community"):
        packs_dir = Path(home) / sub
        if not packs_dir.is_dir():
            continue
        for path in sorted(packs_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if is_legacy(data):
                kind = "legacy"
            elif "schema_version" in data:
                kind = "dsl"
            else:
                continue
            out.append((path, kind, data))
    return out

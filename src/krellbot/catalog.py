"""Pack discovery under `$KRELLBOT_HOME/packs/`.

The CLI's `arm` and `disarm` operate on a pack path or id. `catalog.discover`
returns every DSL pack file under `<home>/packs/` plus `<home>/packs/community/`.
Legacy packs (`id` + `public_label`, no `schema_version`) are intentionally
NOT armable and are excluded here.
"""

from __future__ import annotations

import json
from pathlib import Path

from krellbot.pack import lint as pack_lint


def discover(home: Path) -> list[Path]:
    """Return absolute paths to every runnable DSL pack file under home/packs/."""
    roots = [home / "packs", home / "packs" / "community"]
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if pack_lint.is_legacy(data):
                continue
            if "schema_version" not in data:
                continue
            out.append(path)
    return out


def is_community(path: Path, home: Path) -> bool:
    """True if the pack is installed under packs/community/."""
    try:
        path.resolve().relative_to((home / "packs" / "community").resolve())
        return True
    except ValueError:
        return False


def is_fixture(path: Path) -> bool:
    """True if the pack lives under the in-repo tests/fixtures/ tree."""
    parts = path.resolve().parts
    return "fixtures" in parts and "tests" in parts


def requires_license_for(path: Path, home: Path) -> bool:
    """True if the gate should apply to a pack installed at `path`.

    Community and fixture packs default to NOT requiring a license. The
    `arm_pack` call may override this with an explicit flag.
    """
    if is_community(path, home):
        return False
    return not is_fixture(path)


def load_pack_dict(path: Path) -> dict:
    """Read and parse a pack JSON file. Raises on bad JSON."""
    return json.loads(path.read_text(encoding="utf-8"))

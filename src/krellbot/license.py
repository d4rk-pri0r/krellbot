"""Offline license cache + entries-allowed gate.

The cache file lives at `$KRELLBOT_HOME/catalog/license-cache.json`. The
shape is `{status, period_end, grace_until}`. Status is one of `active`,
`past_due`, `lapsed`, `dead`. There is no HTTP here: the cache is written by
a separate (network-using) flow and read by `tick`. The gate is fail-closed:
a missing cache refuses entries. Exits are not gated.

The gate applies ONLY to packs whose armed record says `requires_license:
true`. Fixture and community packs do not require a license.
"""

from __future__ import annotations

import json
from pathlib import Path

_CACHE_FILENAME = "license-cache.json"


def cache_path(home: Path) -> Path:
    """Return the path to the license-cache.json file under <home>/catalog."""
    return Path(home) / "catalog" / _CACHE_FILENAME


def read_cache(home: Path) -> dict | None:
    """Return the parsed cache, or None if the file does not exist."""
    path = cache_path(home)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_cache(home: Path, *, status: str, period_end: int, grace_until: int) -> Path:
    """Write the license cache atomically. Returns the file path."""
    from krellbot import paths

    path = cache_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        {"status": status, "period_end": period_end, "grace_until": grace_until},
        sort_keys=True,
    )
    paths.atomic_write(path, body.encode("utf-8"))
    return path


def entries_allowed(cache: dict | None, *, now: int) -> bool:
    """True iff entries are allowed right now.

    Rule:
      * `cache is None` => False (fail-closed).
      * `status not in {"active", "past_due"}` => False.
      * `now > grace_until` => False.
      * else True.

    Exits are always allowed; this gate is entries only.
    """
    if not isinstance(cache, dict):
        return False
    status = cache.get("status")
    if status not in {"active", "past_due"}:
        return False
    try:
        grace_until = int(cache.get("grace_until", 0))
    except (TypeError, ValueError):
        return False
    return int(now) <= grace_until


def load(home: Path) -> dict | None:
    """Alias for `read_cache`. Kept for the module's public surface."""
    return read_cache(home)

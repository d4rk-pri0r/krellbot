"""Community packs: install + list.

A community pack is a DSL pack file under `<home>/packs/community/`. The
install command fetches the upstream index, locates the requested id, and
downloads the entry's URL. The URL is rejected unless the host is exactly
`raw.githubusercontent.com` and the path begins with
`/d4rk-pri0r/krellbot-community-packs/` so an entry cannot point at an
attacker-controlled host. The downloaded bytes are written verbatim so the
pack's `author` field is preserved unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from krellbot import paths as kb_paths

INDEX_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/index.json"
ALLOWED_HOST = "raw.githubusercontent.com"
ALLOWED_PATH_PREFIX = "/d4rk-pri0r/krellbot-community-packs/"


class Transport(Protocol):
    """HTTP-shaped transport for fetching community-pack bytes."""

    def get(self, url: str) -> bytes: ...


class ForeignUrlError(ValueError):
    """Raised when a community pack URL falls outside the allowed host/path."""


class IndexError_(ValueError):
    """Raised when the upstream index is malformed or the id is missing."""


def list_installed(home: Path) -> list[tuple[Path, dict]]:
    """Return (path, data) for every JSON file under <home>/packs/community/.

    Skips files that fail IO or JSON parsing, and non-dict roots. Order is
    sorted by path for stable CLI output.
    """
    out: list[tuple[Path, dict]] = []
    community_dir = Path(home) / "packs" / "community"
    if not community_dir.is_dir():
        return out
    for path in sorted(community_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            out.append((path, data))
    return out


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
        raise ForeignUrlError(f"refusing foreign url host: {parsed.netloc!r}")
    if not parsed.path.startswith(ALLOWED_PATH_PREFIX):
        raise ForeignUrlError(f"refusing foreign url path: {parsed.path!r}")


def install(
    pack_id: str,
    *,
    transport: Transport,
    home: Path | None = None,
) -> Path:
    """Install a community pack by id. Returns the file path written.

    Fetches `INDEX_URL`, locates the entry whose `id` matches, then downloads
    that entry's `url`. The URL must be on `raw.githubusercontent.com` and
    under `/d4rk-pri0r/krellbot-community-packs/`. Bytes are written verbatim
    so the pack's `author` field is preserved unchanged.
    """
    home = Path(home) if home is not None else kb_paths.home()
    index_body = transport.get(INDEX_URL)
    try:
        index = json.loads(index_body)
    except json.JSONDecodeError as exc:
        raise IndexError_(f"community index is not valid JSON: {exc}") from exc
    if isinstance(index, list):
        packs = index
    elif isinstance(index, dict):
        packs = index.get("packs")
    else:
        raise IndexError_("community index must be a list or an object")
    if not isinstance(packs, list):
        raise IndexError_("community index 'packs' must be a list")
    entry = next(
        (p for p in packs if isinstance(p, dict) and p.get("id") == pack_id),
        None,
    )
    if entry is None:
        raise IndexError_(f"community pack not found in index: {pack_id!r}")
    url = entry.get("url")
    if not isinstance(url, str) or not url:
        raise IndexError_(f"community pack {pack_id!r} has no url")
    _validate_url(url)
    body = transport.get(url)
    kb_paths.ensure_layout()
    community_dir = home / "packs" / "community"
    community_dir.mkdir(parents=True, exist_ok=True)
    target = community_dir / f"{pack_id}.json"
    kb_paths.atomic_write(target, body)
    return target

"""Community packs: install + list.

A community pack is a DSL pack file under `<home>/packs/community/`. The
install command fetches the upstream index, locates the requested id, and
downloads the entry's URL. The URL is rejected unless the host is exactly
`raw.githubusercontent.com` and the path begins with
`/d4rk-pri0r/krellbot-community-packs/` so an entry cannot point at an
attacker-controlled host.

The downloaded body is staged in a separate temp directory and only
renamed into the install directory after the atomic install helper
verifies it: bodies over `MAX_BODY_BYTES`, tar entries with traversal
names, and tar entries with symlinks that escape the install directory
are all refused with `InstallPayloadError` *before* the rename, so a
previous installed file (if any) is left unchanged. JSON bodies are
written verbatim so the pack's `author` field is preserved unchanged.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from krellbot import paths as kb_paths

INDEX_URL = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/index.json"
ALLOWED_HOST = "raw.githubusercontent.com"
ALLOWED_PATH_PREFIX = "/d4rk-pri0r/krellbot-community-packs/"

# Closed keys returned by the loopback community list/install API.
_INSTALLED_ROW_KEYS = ("id", "version", "label", "author", "origin")


class Transport(Protocol):
    """HTTP-shaped transport for fetching community-pack bytes."""

    def get(self, url: str) -> bytes: ...


class UrllibBytesTransport:
    """Production transport: HTTPS GET returning raw bytes (no JSON parse)."""

    def __init__(self, *, timeout: float = 20.0) -> None:
        self._timeout = timeout

    def get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"user-agent": "krellbot/0.1"})
        from krellbot.tls import urlopen

        with urlopen(req, timeout=self._timeout) as res:
            return res.read()


class ForeignUrlError(ValueError):
    """Raised when a community pack URL falls outside the allowed host/path."""


class IndexError_(ValueError):
    """Raised when the upstream index is malformed or the id is missing."""


class InstallPayloadError(ValueError):
    """Raised when a community pack body fails install-time safety checks.

    Covers archive traversal (a tar entry whose name escapes the
    staging directory), symlink escape (a tar entry whose link target
    resolves outside the install directory), and bodies over the
    install size limit (`MAX_BODY_BYTES`). The refusal is raised before
    the staged body is renamed into the install directory, so the
    previous installed file (if any) is left unchanged.
    """


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


def installed_rows(home: Path) -> list[dict]:
    """Closed-shape rows for the loopback community packs list API."""

    rows: list[dict] = []
    for _path, data in list_installed(home):
        row: dict = {}
        for key in _INSTALLED_ROW_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value:
                row[key] = value
        pack_id = row.get("id")
        if not isinstance(pack_id, str) or not pack_id:
            continue
        rows.append(row)
    return rows


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_HOST:
        raise ForeignUrlError(f"refusing foreign url host: {parsed.netloc!r}")
    if not parsed.path.startswith(ALLOWED_PATH_PREFIX):
        raise ForeignUrlError(f"refusing foreign url path: {parsed.path!r}")


def _parse_index_body(index_body: bytes) -> list[dict]:
    """Parse the upstream index into a list of dict entries."""

    try:
        index = json.loads(index_body)
    except UnicodeDecodeError as exc:
        raise IndexError_(f"community index is not valid UTF-8: {exc}") from exc
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
    return [p for p in packs if isinstance(p, dict)]


def fetch_index(*, transport: Transport) -> list[dict]:
    """Fetch and close the upstream community index for browse/install.

    Each row keeps only ``id``, ``url``, ``author``, and ``label`` when
    present as non-empty strings. ``id`` and ``url`` are required for a
    row to appear; foreign URLs are left in the row so install can refuse
    them with ``ForeignUrlError`` (browse does not pre-filter by allow-list).
    """

    packs = _parse_index_body(transport.get(INDEX_URL))
    rows: list[dict] = []
    for entry in packs:
        pack_id = entry.get("id")
        url = entry.get("url")
        if not isinstance(pack_id, str) or not pack_id:
            continue
        if not isinstance(url, str) or not url:
            continue
        row: dict = {"id": pack_id, "url": url}
        for key in ("author", "label"):
            value = entry.get(key)
            if isinstance(value, str) and value:
                row[key] = value
        rows.append(row)
    return rows


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

    Lookup uses the request id for equality only. After the body is fetched,
    FS ops use the index entry's own ``id`` after a CodeQL-recognized
    ``os.path.basename`` sanitizer (same pattern as catalogue install). A
    non-single-segment id is refused with ``InstallPayloadError`` before any
    destination write — after the allow-listed fetches, matching confinement
    tests that pin transport call order.
    """
    import os.path

    home = Path(home) if home is not None else kb_paths.home()
    packs = _parse_index_body(transport.get(INDEX_URL))
    entry = next(
        (p for p in packs if isinstance(p, dict) and p.get("id") == pack_id),
        None,
    )
    if entry is None:
        raise IndexError_(f"community pack not found in index: {pack_id!r}")
    # Use the index's own id for FS ops so the request string never reaches
    # path joins (CodeQL). Equality with the request id is required first.
    index_id = entry.get("id")
    if not isinstance(index_id, str) or index_id != pack_id:
        raise IndexError_(f"community pack not found in index: {pack_id!r}")
    url = entry.get("url")
    if not isinstance(url, str) or not url:
        raise IndexError_(f"community pack {pack_id!r} has no url")
    _validate_url(url)
    body = transport.get(url)
    # CodeQL-recognized sanitizer: basename strips directory components.
    # Refuse (do not strip-and-continue) when the index id is not already
    # a single path segment — same contract as atomic_install.
    safe_id = os.path.basename(index_id)
    windows_drive = len(safe_id) >= 2 and safe_id[1] == ":" and safe_id[0].isalpha()
    if (
        not safe_id
        or safe_id != index_id
        or os.path.basename(safe_id) != safe_id
        or "\x00" in index_id
        or "/" in index_id
        or "\\" in index_id
        or windows_drive
        or safe_id in {".", ".."}
    ):
        raise InstallPayloadError(f"community pack id is not a single path segment: {index_id!r}")
    kb_paths.ensure_layout()
    from krellbot.extensions import install as kb_extensions_install

    return kb_extensions_install.atomic_install(home=home, pack_id=safe_id, body=body)


def resolve_transport(transport: Transport | None) -> Transport:
    """Return ``transport`` or the production urllib bytes transport."""

    return transport if transport is not None else UrllibBytesTransport()


__all__ = [
    "ALLOWED_HOST",
    "ALLOWED_PATH_PREFIX",
    "INDEX_URL",
    "ForeignUrlError",
    "IndexError_",
    "InstallPayloadError",
    "Transport",
    "UrllibBytesTransport",
    "fetch_index",
    "install",
    "installed_rows",
    "list_installed",
    "resolve_transport",
]

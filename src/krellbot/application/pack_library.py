"""Pack library listing and update (application service).

``list_installed(home)`` returns every installed or known pack classified
into one of five lifecycle buckets by :mod:`krellbot.application.packs`.

``update_pack(home, pack_id, new_version)`` refuses when the deployed
record's ``revision_id`` differs from the installed record's
``revision_id``. A refusal is a typed exception (``UpdateRefused``)
carrying a stable ``code`` and the two revision ids; no byte on disk is
changed when the refusal fires.

``list_catalogue(home)`` returns the last verified signed catalogue
metadata (free + paid entries) from the local cache. ``refresh_catalogue``
fetches and verifies a fresh signed envelope through the license
activation transport before rewriting that cache.

``install_from_catalogue(home, pack_id)`` one-click installs a free
catalogue entry by writing a ``download_pending`` marker (with version
and permissions from the verified catalogue). Paid entries are refused
until activation redeem (M5.3) establishes entitlement. Already-local
packs return their existing classifier row without rewriting state.

``list_installed`` / ``update_pack`` / ``install_from_catalogue`` read
local metadata only; no network call is made. ``refresh_catalogue`` is
the network path and always takes an injectable transport in tests.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from krellbot import license as kb_license
from krellbot import paths as kb_paths
from krellbot.application import packs as app_packs

_EMPTY_CATALOGUE: dict[str, Any] = {
    "catalogue_version": "0",
    "packs": [],
}

# Closed pack id shape for path construction — no separators or traversal.
_SAFE_PACK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def _safe_pack_id_segment(pack_id: str) -> str:
    """Return a single path-segment pack id, or raise InstallRefused.

    Uses ``os.path.basename`` (CodeQL-recognized sanitizer) so directory
    components never reach a path expression, matching
    ``api.app._client_pack_basename``.
    """
    if not isinstance(pack_id, str) or not pack_id.strip():
        raise InstallRefused("invalid_request", "pack_id is required")
    raw = pack_id.strip()
    # CodeQL-recognized sanitizer: basename strips directory components.
    name = os.path.basename(raw)
    windows_drive = len(name) >= 2 and name[1] == ":" and name[0].isalpha()
    if (
        not name
        or name != raw
        or os.path.basename(name) != name
        or name in {".", ".."}
        or "/" in raw
        or "\\" in raw
        or "\x00" in raw
        or windows_drive
        or not _SAFE_PACK_ID.fullmatch(name)
    ):
        raise InstallRefused("invalid_request", "pack_id is required")
    return name


class InstallRefused(Exception):
    """``install_from_catalogue`` refused without changing any byte.

    The ``code`` attribute is one of:

      * ``"pack_not_found"`` — ``pack_id`` is absent from the verified
        catalogue cache.
      * ``"activation_required"`` — the entry is paid and local
        entitlement has not been established.
      * ``"invalid_request"`` — ``pack_id`` is missing or empty.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class UpdateRefused(Exception):
    """``update_pack`` refused the request without changing any byte.

    The ``code`` attribute is one of:

      * ``"deployed_revision_mismatch"`` — the deployed record's
        ``revision_id`` does not match the installed record's
        ``revision_id``. Carries ``deployed_revision_id`` and
        ``installed_revision_id`` attributes so the caller can
        render the rollback affordance deterministically.
      * ``"pack_not_found"`` — no installed pack file exists for the
        given ``pack_id``.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        deployed_revision_id: str | None = None,
        installed_revision_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.deployed_revision_id = deployed_revision_id
        self.installed_revision_id = installed_revision_id


def _read_one(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _find_installed_pack_path(home: Path, pack_id: str) -> Path | None:
    """Locate the on-disk installed pack file for ``pack_id``, or None."""
    if not isinstance(pack_id, str) or not pack_id:
        return None
    for root in (
        home / "packs",
        home / "packs" / "community",
        home / "packs" / "catalog",
    ):
        candidate = root / f"{pack_id}.json"
        if candidate.is_file():
            return candidate
    return None


def list_installed(home: Path) -> list[dict[str, Any]]:
    """Return every pack the pack library should render, classified by bucket.

    The list is the union of five closed buckets, evaluated by the
    classifier in :mod:`krellbot.application.packs`. Each row has the
    closed shape ``{bucket, pack_id, version, permissions,
    rollback_ref}``. The classifier performs the bucket assignment;
    this function only reads its result.

    No network call is made. The cached catalog at
    ``<home>/catalog/catalog.json`` is consulted when present and is
    the only source for ``purchased`` rows.
    """
    return app_packs.list_packs(Path(home))


def update_pack(home: Path, pack_id: str, new_version: str) -> Path:
    """Update an installed pack to ``new_version``.

    Refuses with :class:`UpdateRefused` when the deployed record's
    ``revision_id`` does not match the installed file's
    ``revision_id``. The refusal is typed (``code`` attribute) and the
    installed file is left unchanged on disk.

    Returns the absolute path to the rewritten pack file when the
    update succeeds. The file is rewritten atomically through
    :func:`krellbot.paths.atomic_write` so a crash mid-write never
    leaves a half-written pack file on disk.
    """
    home = Path(home)
    if not isinstance(pack_id, str) or not pack_id:
        raise UpdateRefused("pack_not_found", "pack_id is required")
    if not isinstance(new_version, str) or not new_version:
        raise UpdateRefused("invalid_request", "new_version is required")

    pack_path = _find_installed_pack_path(home, pack_id)
    if pack_path is None:
        raise UpdateRefused(
            "pack_not_found",
            f"pack file not found for {pack_id!r}",
        )

    installed = _read_one(pack_path)
    if installed is None:
        raise UpdateRefused(
            "pack_not_found",
            f"pack file unreadable for {pack_id!r}",
        )

    installed_rev = app_packs.installed_revision_id(installed)

    deployed = _read_one(home / "packs" / f"{pack_id}.deployed.json")
    if deployed is not None:
        deployed_rev = deployed.get("revision_id")
        if isinstance(deployed_rev, str) and deployed_rev != installed_rev:
            raise UpdateRefused(
                "deployed_revision_mismatch",
                (
                    f"refusing to update {pack_id!r}: deployed revision "
                    f"{deployed_rev[:12]}… differs from installed revision "
                    f"{installed_rev[:12]}…; re-deploy before updating"
                ),
                deployed_revision_id=deployed_rev,
                installed_revision_id=installed_rev,
            )

    if not isinstance(installed, dict):
        raise UpdateRefused(
            "pack_not_found",
            f"pack file for {pack_id!r} is not a JSON object",
        )
    installed["version"] = new_version
    payload = (json.dumps(installed, sort_keys=True) + "\n").encode("utf-8")
    kb_paths.atomic_write(pack_path, payload)
    return pack_path


def list_catalogue(home: Path) -> dict[str, Any]:
    """Return the cached verified signed catalogue, or an empty document.

    Reads ``<home>/catalog/catalogue.json`` only. No network call. A
    missing or unreadable cache returns
    ``{"catalogue_version": "0", "packs": []}`` so the browse surface can
    render an explicit empty state without inventing entries.
    """
    cached = kb_license.read_catalogue_cache(Path(home))
    if cached is None:
        return dict(_EMPTY_CATALOGUE)
    return cached


def _catalogue_entry(home: Path, pack_id: str) -> dict[str, Any] | None:
    document = list_catalogue(home)
    packs = document.get("packs")
    if not isinstance(packs, list):
        return None
    for entry in packs:
        if isinstance(entry, dict) and entry.get("id") == pack_id:
            return entry
    return None


def _row_dict(row: app_packs.PackRow) -> dict[str, Any]:
    return {
        "bucket": row.bucket,
        "pack_id": row.pack_id,
        "version": row.version,
        "permissions": list(row.permissions),
        "rollback_ref": row.rollback_ref,
    }


def install_from_catalogue(home: Path, pack_id: str) -> dict[str, Any]:
    """One-click install a free catalogue pack into the local library.

    Looks up ``pack_id`` in the verified catalogue cache only (no
    network). Free entries write a ``download_pending`` marker carrying
    the catalogue version/permissions so the library can show
    bucket+version immediately. Paid entries raise
    :class:`InstallRefused` with ``activation_required``. Unknown ids
    raise ``pack_not_found``. When the pack is already local (any
    classifier bucket), returns the existing row without rewriting.
    """
    home = Path(home)
    # Sanitize request id before catalogue lookup (no FS join on it).
    pack_id = _safe_pack_id_segment(pack_id)

    entry = _catalogue_entry(home, pack_id)
    if entry is None:
        raise InstallRefused(
            "pack_not_found",
            f"catalogue entry not found for {pack_id!r}",
        )
    tier = entry.get("tier")
    if tier == "paid":
        raise InstallRefused(
            "activation_required",
            f"paid pack {pack_id!r} requires activation redeem before install",
        )
    if tier != "free":
        raise InstallRefused(
            "pack_not_found",
            f"catalogue entry not installable for {pack_id!r}",
        )

    # Use the catalogue's own id (verified cache) for all FS ops so the
    # request string never reaches classify / path joins (CodeQL).
    catalog_id = entry.get("id")
    if not isinstance(catalog_id, str) or catalog_id != pack_id:
        raise InstallRefused("pack_not_found", "catalogue entry not found")
    safe_id = _safe_pack_id_segment(catalog_id)

    # Already-local check uses disk-listed rows only (ids from filenames),
    # never classify(user pack_id).
    for row in app_packs.list_packs(home):
        if row.get("pack_id") == safe_id and row.get("bucket") != app_packs.BUCKET_PURCHASED:
            return row

    packs_dir = (home / "packs").resolve()
    packs_dir.mkdir(parents=True, exist_ok=True)
    marker: dict[str, Any] = {
        "schema_version": "1",
        "pack_id": safe_id,
        "tier": "free",
    }
    version = entry.get("version")
    if isinstance(version, str) and version:
        marker["version"] = version
    permissions = entry.get("permissions")
    if isinstance(permissions, list) and all(isinstance(p, str) for p in permissions):
        marker["permissions"] = list(permissions)
    else:
        marker["permissions"] = []

    # Path is packs_dir + sanitized basename only (no user directories).
    filename = os.path.basename(f"{safe_id}.download_pending.json")
    target = (packs_dir / filename).resolve()
    if target.parent != packs_dir:
        raise InstallRefused("invalid_request", "pack_id is required")
    payload = (json.dumps(marker, sort_keys=True) + "\n").encode("utf-8")
    kb_paths.atomic_write(target, payload)

    # Classify with catalogue id only (not the raw request string).
    row = app_packs.classify(home, safe_id)
    if row is None:
        # Marker write succeeded; synthesise the closed row the UI expects.
        return {
            "bucket": app_packs.BUCKET_DOWNLOAD_PENDING,
            "pack_id": safe_id,
            "version": marker.get("version") if isinstance(marker.get("version"), str) else None,
            "permissions": list(marker["permissions"]),
            "rollback_ref": None,
        }
    return _row_dict(row)


def refresh_catalogue(
    home: Path,
    *,
    transport: Any = None,
    url: str | None = None,
) -> dict[str, Any]:
    """Fetch, verify, cache, and return signed catalogue metadata.

    Delegates to :func:`krellbot.application.license_activation.fetch_catalogue`.
    Tampered envelopes raise ``ValueError`` without rewriting the cache.
    """
    from krellbot.application.license_activation import fetch_catalogue

    return fetch_catalogue(Path(home), transport=transport, url=url)


__all__ = [
    "InstallRefused",
    "UpdateRefused",
    "install_from_catalogue",
    "list_catalogue",
    "list_installed",
    "refresh_catalogue",
    "update_pack",
]

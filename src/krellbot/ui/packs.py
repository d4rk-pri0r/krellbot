"""Pack listing and update for the dashboard.

Two public surfaces live here:

  * ``list_installed(home)`` — the production API for the pack library.
    Every pack the dashboard should render is classified into one of
    five lifecycle buckets (deployed, configured, installed,
    download_pending, purchased) by the application-layer classifier
    in :mod:`krellbot.application.packs`. The returned dict is closed:
    ``bucket``, ``pack_id``, ``version``, ``permissions``,
    ``rollback_ref``.

  * ``update_pack(home, pack_id, new_version)`` — refuses when the
    deployed record's ``revision_id`` differs from the installed
    record's ``revision_id``. A refusal is a typed exception
    (``UpdateRefused``) carrying a stable ``code`` and the two
    revision ids; no byte on disk is changed when the refusal fires.

The list is built from local metadata only — no network call, no
invention of performance numbers, no live-marketplace JS. The cached
catalog under ``<home>/catalog/catalog.json`` is read when present so
the dashboard can show purchased packs even when the workstation is
offline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from krellbot import paths as kb_paths
from krellbot.application import packs as app_packs
from krellbot.pack import lint as pack_lint


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


def _summarize(path: Path, data: dict) -> dict[str, Any]:
    """Return a closed, presentational summary of one pack file.

    Only local, declarative fields are exposed. No invented numbers,
    no fabricated performance figures, no equity-curve points. The
    ``runnable`` flag is False for legacy packs (id + public_label
    only, no ``schema_version``); this is the only field the arm
    affordance consults.
    """
    if pack_lint.is_legacy(data):
        return {
            "path": str(path),
            "id": str(data.get("id", "")),
            "public_label": str(data.get("public_label", "")),
            "schema_version": None,
            "runnable": False,
            "not_runnable_reason": "legacy pack; no schema_version",
            "markets": [],
            "timeframe": None,
            "label": str(data.get("public_label", "")),
            "version": None,
            "author": "",
        }
    schema_version = data.get("schema_version")
    pack_id = str(data.get("id", ""))
    label = str(data.get("label", ""))
    version = str(data.get("version", "")) or None
    author = str(data.get("author", ""))
    timeframe = data.get("timeframe") or None
    markets = data.get("markets") or []
    runnable = schema_version == 1
    return {
        "path": str(path),
        "id": pack_id,
        "public_label": label or pack_id,
        "schema_version": schema_version,
        "runnable": runnable,
        "not_runnable_reason": None if runnable else "schema_version is not 1",
        "markets": markets if isinstance(markets, list) else [],
        "timeframe": timeframe,
        "label": label,
        "version": version,
        "author": author,
    }


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
    """Return every pack the dashboard should render, classified by bucket.

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


def resolve_pack_path(home: Path, pack_id: str) -> Path | None:
    """Return the absolute path of the runnable pack with ``pack_id``, or None.

    Only runnable (schema_version 1) packs are resolved; a legacy
    pack that happens to share the id is ignored. The lookup walks
    ``packs/`` then ``packs/community/``; the first match wins.
    """
    if not isinstance(pack_id, str) or not pack_id:
        return None
    home = Path(home)
    for root in (home / "packs", home / "packs" / "community", home / "packs" / "catalog"):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            data = _read_one(path)
            if data is None:
                continue
            if pack_lint.is_legacy(data):
                continue
            if data.get("schema_version") != 1:
                continue
            if str(data.get("id", "")) == pack_id:
                return path
    return None


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


__all__ = [
    "UpdateRefused",
    "list_installed",
    "resolve_pack_path",
    "update_pack",
]

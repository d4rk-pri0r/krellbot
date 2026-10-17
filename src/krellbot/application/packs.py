"""Pack lifecycle classifier (application service).

The dashboard's pack library renders one row per pack with a closed
shape: ``bucket``, ``pack_id``, ``version``, ``permissions``, and
``rollback_ref``. ``bucket`` is one of five closed lifecycle states:

    deployed           - a deployed record exists for this pack id
    configured         - a configured record exists but no deployed one
    installed          - a pack file exists at <home>/packs/<id>.json
                         (or community/), but no configured or deployed
                         record
    download_pending   - a download-pending marker exists for this id
                         (no pack file on disk)
    purchased          - the cached catalog lists the id but no local
                         state exists yet

The classifier is the single source of truth for this mapping. The
dashboard's ``PackLibrary`` component renders the rows it returns; the
rollback affordance is gated on the presence of ``rollback_ref``.

Buckets are evaluated in priority order: ``deployed`` > ``configured``
> ``installed`` > ``download_pending`` > ``purchased``. The first match
wins, so a pack with a deployed record is reported as ``deployed`` even
if a configured record and an installed pack file also exist on disk.

No network call happens here. The classifier reads only the local
filesystem under ``<home>``. The catalog is read from
``<home>/catalog/catalog.json`` when present; the absence of that file
simply means no ``purchased`` rows are reported.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

BUCKET_DEPLOYED = "deployed"
BUCKET_CONFIGURED = "configured"
BUCKET_INSTALLED = "installed"
BUCKET_DOWNLOAD_PENDING = "download_pending"
BUCKET_PURCHASED = "purchased"

ALL_BUCKETS: tuple[str, ...] = (
    BUCKET_DEPLOYED,
    BUCKET_CONFIGURED,
    BUCKET_INSTALLED,
    BUCKET_DOWNLOAD_PENDING,
    BUCKET_PURCHASED,
)


def _canonical_json(pack: dict) -> bytes:
    """Canonical v1 JSON for revision-id derivation.

    Same scheme as ``krellbot.application.strategy``: sorted keys,
    ``(",", ":")`` separators, UTF-8. The classifier is intentionally
    consistent with the strategy draft service so a pack's deployed
    revision_id matches what the strategy store would have produced.
    """
    return json.dumps(pack, sort_keys=True, separators=(",", ":")).encode("utf-8")


def installed_revision_id(pack: dict) -> str:
    """sha256 of the canonical v1 JSON of an installed pack dict."""
    return hashlib.sha256(_canonical_json(pack)).hexdigest()


@dataclass(frozen=True)
class PackRow:
    """Closed-shape row returned to the dashboard.

    ``rollback_ref`` is non-None only for ``bucket == "deployed"`` packs
    that have a ``prior_revision_id`` in their deployed record. For
    every other bucket it is ``None``.
    """

    bucket: str
    pack_id: str
    version: str | None
    permissions: list[str]
    rollback_ref: dict | None


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _deployed_record(home: Path, pack_id: str) -> dict | None:
    return _read_json(home / "packs" / f"{pack_id}.deployed.json")


def _configured_record(home: Path, pack_id: str) -> dict | None:
    return _read_json(home / "packs" / f"{pack_id}.configured.json")


def _download_pending_marker(home: Path, pack_id: str) -> dict | None:
    return _read_json(home / "packs" / f"{pack_id}.download_pending.json")


def _installed_pack(home: Path, pack_id: str) -> dict | None:
    """Return the parsed pack dict from one of the installed roots, if any."""
    for root in (
        home / "packs",
        home / "packs" / "community",
        home / "packs" / "catalog",
    ):
        candidate = root / f"{pack_id}.json"
        if not candidate.is_file():
            continue
        data = _read_json(candidate)
        if data is None:
            continue
        return data
    return None


def _permissions_from(value: object) -> list[str]:
    """Coerce a permissions field to a list of strings.

    Defensive parsing only — the classifier never crashes on a bad
    shape, because the dashboard renders this field directly.
    """
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int, float, bool))]


def _rollback_ref_for(deployed: dict) -> dict | None:
    """Build a closed rollback_ref dict from a deployed record, or None.

    The dashboard renders the Rollback button only when this returns a
    dict. The shape is closed: it carries the prior revision id and
    the pack id, nothing else.
    """
    prior = deployed.get("prior_revision_id")
    if not isinstance(prior, str) or not prior:
        return None
    pack_id = deployed.get("pack_id")
    if not isinstance(pack_id, str) or not pack_id:
        return None
    return {
        "pack_id": pack_id,
        "prior_revision_id": prior,
    }


def _catalog_packs(home: Path) -> list[dict]:
    """Return the cached catalog's pack list, or [] when no cache exists."""
    catalog = _read_json(home / "catalog" / "catalog.json")
    if catalog is None:
        return []
    packs = catalog.get("packs")
    if not isinstance(packs, list):
        return []
    return [p for p in packs if isinstance(p, dict)]


def _row_from_deployed(home: Path, pack_id: str, deployed: dict) -> PackRow:
    pack = _installed_pack(home, pack_id)
    version = None
    if isinstance(deployed.get("version"), str):
        version = deployed["version"]
    if version is None and pack is not None and isinstance(pack.get("version"), str):
        version = pack["version"]
    permissions = _permissions_from(deployed.get("permissions"))
    if not permissions and pack is not None:
        permissions = _permissions_from(pack.get("permissions"))
    return PackRow(
        bucket=BUCKET_DEPLOYED,
        pack_id=pack_id,
        version=version,
        permissions=permissions,
        rollback_ref=_rollback_ref_for(deployed),
    )


def _row_from_configured(pack_id: str, configured: dict, pack: dict | None) -> PackRow:
    version = None
    if isinstance(pack, dict) and isinstance(pack.get("version"), str):
        version = pack["version"]
    permissions = _permissions_from(configured.get("permissions"))
    if not permissions and pack is not None:
        permissions = _permissions_from(pack.get("permissions"))
    return PackRow(
        bucket=BUCKET_CONFIGURED,
        pack_id=pack_id,
        version=version,
        permissions=permissions,
        rollback_ref=None,
    )


def _row_from_installed(pack_id: str, pack: dict) -> PackRow:
    version = pack.get("version") if isinstance(pack.get("version"), str) else None
    return PackRow(
        bucket=BUCKET_INSTALLED,
        pack_id=pack_id,
        version=version,
        permissions=_permissions_from(pack.get("permissions")),
        rollback_ref=None,
    )


def _row_from_purchased(entry: dict) -> PackRow | None:
    pack_id = entry.get("id")
    if not isinstance(pack_id, str) or not pack_id:
        return None
    version = entry.get("version") if isinstance(entry.get("version"), str) else None
    return PackRow(
        bucket=BUCKET_PURCHASED,
        pack_id=pack_id,
        version=version,
        permissions=_permissions_from(entry.get("permissions")),
        rollback_ref=None,
    )


def _row_from_download_pending(pack_id: str) -> PackRow:
    return PackRow(
        bucket=BUCKET_DOWNLOAD_PENDING,
        pack_id=pack_id,
        version=None,
        permissions=[],
        rollback_ref=None,
    )


def collect_pack_ids(home: Path) -> list[str]:
    """Return every pack id the classifier knows about, in stable order.

    The dashboard relies on a deterministic ordering so React keys stay
    stable across renders. Order is: ``deployed`` first, then
    ``configured``, then ``installed``, then ``download_pending``,
    then ``purchased``; within each bucket, sorted by id.
    """
    home = Path(home)
    catalog_packs = _catalog_packs(home)
    purchased_ids = sorted(
        {
            entry["id"]
            for entry in catalog_packs
            if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]
        }
    )

    installed: dict[str, dict] = {}
    for root in (
        home / "packs",
        home / "packs" / "community",
        home / "packs" / "catalog",
    ):
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            data = _read_json(path)
            if data is None:
                continue
            pack_id = data.get("id")
            if not isinstance(pack_id, str) or not pack_id:
                continue
            # First match wins (packs/ then community/ then catalog/),
            # mirroring the resolution order in the dashboard arm
            # affordance.
            installed.setdefault(pack_id, data)

    deployed_ids = sorted(pack_id for pack_id in installed if _deployed_record(home, pack_id) is not None)
    installed_ids = sorted(installed.keys())

    # ``download_pending`` ids are the download markers that do NOT have
    # an installed file on disk. A pending download for an installed
    # pack is meaningless (the pack is already there).
    pending_ids = sorted(
        candidate
        for candidate in (
            path.stem.removesuffix(".download_pending") for path in (home / "packs").glob("*.download_pending.json")
        )
        if candidate and candidate not in installed
    )

    # ``configured`` ids: installed pack with a configured record and
    # NO deployed record (deployed wins by priority).
    configured_ids = sorted(
        pack_id
        for pack_id in installed
        if pack_id not in deployed_ids and _configured_record(home, pack_id) is not None
    )

    # Strip ``installed_ids`` of any that are also configured or deployed,
    # because the priority order means they report the higher bucket.
    installed_only_ids = sorted(
        pack_id for pack_id in installed_ids if pack_id not in deployed_ids and pack_id not in configured_ids
    )

    purchased_only = sorted(pack_id for pack_id in purchased_ids if pack_id not in installed)

    return deployed_ids + configured_ids + installed_only_ids + pending_ids + purchased_only


def classify(home: Path, pack_id: str) -> PackRow | None:
    """Classify one pack id into a PackRow.

    Returns ``None`` only when the pack id is unknown to every state
    source. The dashboard treats ``None`` as "do not render this id".
    """
    home = Path(home)
    deployed = _deployed_record(home, pack_id)
    if deployed is not None:
        return _row_from_deployed(home, pack_id, deployed)

    pack = _installed_pack(home, pack_id)
    configured = _configured_record(home, pack_id)
    if configured is not None:
        return _row_from_configured(pack_id, configured, pack)

    if pack is not None:
        return _row_from_installed(pack_id, pack)

    if _download_pending_marker(home, pack_id) is not None:
        return _row_from_download_pending(pack_id)

    # Fall back to the cached catalog (purchased). A catalog entry is
    # the only state source that lives outside ``<home>/packs/``.
    for entry in _catalog_packs(home):
        if entry.get("id") == pack_id:
            return _row_from_purchased(entry)

    return None


def list_packs(home: Path) -> list[dict]:
    """Return every pack row the dashboard should render.

    Stable order: ``deployed`` → ``configured`` → ``installed`` →
    ``download_pending`` → ``purchased``; within each bucket by id.
    """
    out: list[dict] = []
    for pack_id in collect_pack_ids(home):
        row = classify(home, pack_id)
        if row is None:
            continue
        out.append(
            {
                "bucket": row.bucket,
                "pack_id": row.pack_id,
                "version": row.version,
                "permissions": list(row.permissions),
                "rollback_ref": row.rollback_ref,
            }
        )
    return out


__all__ = [
    "ALL_BUCKETS",
    "BUCKET_CONFIGURED",
    "BUCKET_DEPLOYED",
    "BUCKET_DOWNLOAD_PENDING",
    "BUCKET_INSTALLED",
    "BUCKET_PURCHASED",
    "PackRow",
    "classify",
    "collect_pack_ids",
    "installed_revision_id",
    "list_packs",
]

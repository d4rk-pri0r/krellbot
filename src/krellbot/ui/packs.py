"""Installed-pack listing for the dashboard.

The dashboard renders every pack file under ``<home>/packs/`` and
``<home>/packs/community/`` so the user can pick one to paper-arm. The
list is built from local metadata only — we never invent performance
numbers, equity curves, return percentages, or other backtested
fragments, and we never read the paid catalog directly into the view.

A legacy pack (id + public_label only, no ``schema_version``) is rendered
as ``runnable: false`` so the dashboard's arm affordance is hidden for
it. This is enforced in two places: ``list_installed`` returns
``runnable=False`` for legacy packs, and the per-pack arm route refuses
the request with 403 even if a stale UI sent the id.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from krellbot.pack import lint as pack_lint


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


def list_installed(home: Path) -> list[dict[str, Any]]:
    """Return a sorted summary of every pack file under ``<home>/packs/``.

    Legacy packs are included with ``runnable=False`` so the dashboard
    can render the "not runnable" badge — but the arm route refuses
    them anyway. Files that fail IO or JSON parsing are silently
    skipped: the dashboard is presentation-only and the CLI's
    ``lint`` command is the validation surface.
    """
    home = Path(home)
    roots = [home / "packs", home / "packs" / "community", home / "packs" / "catalog"]
    out: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            data = _read_one(path)
            if data is None:
                continue
            out.append(_summarize(path, data))
    return out


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


__all__ = ["list_installed", "resolve_pack_path"]

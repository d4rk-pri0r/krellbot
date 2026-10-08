"""Read-only ``GET /api/v1/operations`` body builder.

The view aggregates three read-only sources for the workstation:

  * ``live_gate.live_status`` — the closed-shape snapshot of the live
    authorization gate, kill switch, and promotion status.
  * The list of armed records from ``krellbot.config.load_config`` —
    projected to a closed shape that never carries ``cap``, ``stop``,
    ``starting_cash``, ``owned_qty``, ``pack_path``, ``pack_sha256``,
    or any balance / key material.
  * The deduped, severity-sorted alert list from
    ``krellbot.application.alerts.collect``.

Each deployment's ``promotion.code`` is what ``live_gate.check_promotion``
returns when run against that deployment, with ``revision_id`` fixed to
the literal ``"deployment"``. Promotion never succeeds; the field is the
typed refusal code so the UI can render the same message the API
returns when the operator clicks Promote.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from krellbot import config as kb_config
from krellbot.application import alerts, live_gate

SCHEMA_VERSION = "1"
PROMOTION_REVISION_ID = "deployment"

DEPLOYMENT_HISTORY_LIMIT = 50
_DEPLOYMENT_KIND = "deployment"
_DEPLOYMENT_REQUIRED_FIELDS = ("deployment_id", "venue", "pair", "state")
_CONFIG_SUBSET_KEYS = ("pack_id", "pack_version", "mode", "entries_paused")
_SCHEDULE_SUBSET_KEYS = ("timeframe", "interval", "next_run_at_ms", "last_run_at_ms")
_LAST_EXECUTION_SUMMARY_MAX = 240


def _deployment_projection(home: Path, *, env: Mapping[str, str] | None, now: int) -> list[dict]:
    """Project every armed record to a closed shape.

    ``mode`` is the stored mode, verbatim — a seeded live row stays
    ``"live"`` and is never rewritten into ``"paper"``.
    """

    config = kb_config.load_config(home)
    out: list[dict] = []
    for armed in config.armed:
        promo = live_gate.check_promotion(
            home,
            venue=armed.venue,
            pair=armed.pair,
            revision_id=PROMOTION_REVISION_ID,
            env=env,
            now=now,
        )
        out.append(
            {
                "venue": armed.venue,
                "pair": armed.pair,
                "pack_id": armed.pack_id,
                "pack_version": armed.pack_version,
                "mode": armed.mode,
                "entries_paused": bool(armed.entries_paused),
                "promotion": {
                    "available": False,
                    "code": promo.code,
                },
            }
        )
    return out


def operations_view(home: Path, *, env: Mapping[str, str] | None = None, now: int) -> dict:
    """Return the closed-shape operations view.

    The body never includes ``cap``, ``stop``, ``starting_cash``,
    ``owned_qty``, ``pack_path``, ``pack_sha256``, any balance, or any
    key material. ``promotion_available`` is always ``False``; the
    brief documents that promotion is owner-deferred in this build.
    """

    home = Path(home)
    return {
        "schema_version": SCHEMA_VERSION,
        "live": live_gate.live_status(home, env=env, now=now),
        "deployments": _deployment_projection(home, env=env, now=now),
        "alerts": [a.to_dict() for a in alerts.collect(home, now=now)],
    }


def _subset(raw: object, keys: tuple[str, ...]) -> dict:
    """Project ``raw`` onto a small whitelist of keys, string/bool typed."""

    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    for key in keys:
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = value
        elif isinstance(value, (int, float)):
            out[key] = value
        else:
            out[key] = str(value)
    return out


def _deployment_record_row(record: dict) -> dict | None:
    """Build one closed history row from a journal record, or None to skip.

    A row is emitted only for ``kind=deployment`` records whose detail
    carries every required identity field; anything else (a different
    kind, a truncated line, a missing field) is skipped rather than
    guessed. The row never carries ``cap``, ``stop``, ``starting_cash``,
    ``owned_qty``, ``pack_path``, ``pack_sha256``, balance, or key
    material.
    """

    if not isinstance(record, dict) or record.get("kind") != _DEPLOYMENT_KIND:
        return None
    detail = record.get("detail")
    if not isinstance(detail, dict):
        return None
    for field in _DEPLOYMENT_REQUIRED_FIELDS:
        value = detail.get(field)
        if not isinstance(value, str) or not value:
            return None
    try:
        created_at_ms = int(record.get("ts", 0) or 0) * 1000
    except (TypeError, ValueError):
        return None
    if created_at_ms <= 0:
        return None

    summary_raw = detail.get("last_execution_summary")
    summary = str(summary_raw)[:_LAST_EXECUTION_SUMMARY_MAX] if summary_raw is not None else ""

    return {
        "deployment_id": detail["deployment_id"],
        "venue": detail["venue"],
        "pair": detail["pair"],
        "created_at_ms": created_at_ms,
        "state": detail["state"],
        "config": _subset(detail.get("config"), _CONFIG_SUBSET_KEYS),
        "schedule": _subset(detail.get("schedule"), _SCHEDULE_SUBSET_KEYS),
        "last_execution_summary": summary,
    }


def list_deployment_records(home: Path) -> list[dict]:
    """Return the most recent deployment history rows, newest first.

    Walks the append-only journal under ``<home>/journal`` — the same
    per-month ``*.jsonl`` files ``krellbot.journal.append`` writes (and
    any ``deployments*.jsonl`` files a caller may keep there) — and
    projects every ``kind=deployment`` record onto the closed row shape
    above. Unparseable or incomplete lines are skipped, never raised.
    The result is capped at ``DEPLOYMENT_HISTORY_LIMIT`` rows. ``home``
    is read, never created or written.
    """

    journal_dir = Path(home) / "journal"
    if not journal_dir.is_dir():
        return []
    rows: list[dict] = []
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            row = _deployment_record_row(record)
            if row is not None:
                rows.append(row)
    rows.sort(key=lambda row: row["created_at_ms"], reverse=True)
    return rows[:DEPLOYMENT_HISTORY_LIMIT]


def get_deployment_record(home: Path, deployment_id: str) -> dict | None:
    """Return the newest closed row for ``deployment_id``, or None."""

    wanted = str(deployment_id)
    for row in list_deployment_records(home):
        if row["deployment_id"] == wanted:
            return row
    return None


__all__ = ["operations_view", "list_deployment_records", "get_deployment_record"]

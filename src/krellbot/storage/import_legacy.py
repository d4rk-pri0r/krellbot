"""Transactional ledger import + projection comparison for NS12.

The store is the new write path. The legacy journal keeps writing to JSONL
files until the cutover flips in a later leaf. This module is the
comparison view the doctor runs; it does not change the write path, does
not touch ``krellbot.venues``, and does not claim the journal has been
cut over.

The two responsibilities:

- ``import_legacy`` writes a batch of legacy records into the ledger in a
  single transaction. The optional ``writer`` callback is the only thing
  that touches the connection, so a test can inject a writer that raises
  ``OSError(errno.ENOSPC)`` mid-import and prove the rollback path.
- ``compare_legacy_projection`` reads the legacy journal directory and
  the store ledger and projects both down to a comparable shape. The
  result is one of ``"match"``, ``"mismatch"``, or ``"not_compared"``,
  the same vocabulary the doctor surfaces.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from krellbot.storage.database import OperationalStore

PROJECTION_MATCH = "match"
PROJECTION_MISMATCH = "mismatch"
PROJECTION_NOT_COMPARED = "not_compared"


# Where the operational store lives under the home directory. The doctor
# opens this exact path when comparing the legacy journal against the
# store ledger; a missing file at this path is one of the two ways
# `compare_legacy_projection` reports `not_compared`.
DEFAULT_STORE_FILENAME = "ops.sqlite"


def _default_writer(conn: sqlite3.Connection, record: dict) -> None:
    """Insert one record as a ledger row.

    ``kind`` becomes the ``kind`` column; the entire record is JSON-serialised
    into ``payload`` so a later projection has the same shape on both sides.
    """
    kind = str(record.get("kind", ""))
    payload = json.dumps(record, separators=(",", ":"), sort_keys=True)
    conn.execute(
        "INSERT INTO ledger (kind, payload) VALUES (?, ?)",
        (kind, payload),
    )


def import_legacy(
    store: OperationalStore,
    records: list[dict],
    writer: Callable[[sqlite3.Connection, dict], None] | None = None,
) -> None:
    """Write ``records`` to the ledger in a single transaction.

    The optional ``writer`` callback is the only thing that touches the
    connection. If it raises, the surrounding ``store.transaction()``
    context manager rolls back so the ledger and ``schema_migrations``
    are unchanged from before the call.
    """
    per_record = writer if writer is not None else _default_writer
    with store.transaction() as conn:
        for record in records:
            per_record(conn, record)


def _read_journal_records(home: Path) -> list[dict]:
    """Walk every ``*.jsonl`` under ``home/journal`` and parse one record per line."""
    journal_dir = home / "journal"
    if not journal_dir.is_dir():
        return []
    out: list[dict] = []
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
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _project_legacy(records: list[dict]) -> list[tuple[str, str]]:
    """Project a list of legacy journal records to ``(kind, payload)`` pairs."""
    return [
        (
            str(rec.get("kind", "")),
            json.dumps(rec, separators=(",", ":"), sort_keys=True),
        )
        for rec in records
    ]


def _project_ledger(rows: list[tuple[int, str, str]]) -> list[tuple[str, str]]:
    """Project store ledger rows to ``(kind, payload)`` pairs."""
    return [(kind, payload) for _id, kind, payload in rows]


def compare_legacy_projection(home: Path, store_path: Path | None = None) -> str:
    """Return ``"match"``, ``"mismatch"``, or ``"not_compared"``.

    Either side missing (no legacy journal records, no store file) yields
    ``"not_compared"`` rather than ``"match"``; the doctor relies on
    that distinction to avoid a false positive on a fresh home.
    """
    if store_path is None:
        store_path = home / DEFAULT_STORE_FILENAME
    journal_records = _read_journal_records(home)
    if not journal_records or not store_path.exists():
        return PROJECTION_NOT_COMPARED
    store = OperationalStore(store_path)
    ledger_rows = store.read_ledger()
    legacy_projection = _project_legacy(journal_records)
    ledger_projection = _project_ledger(ledger_rows)
    return PROJECTION_MATCH if legacy_projection == ledger_projection else PROJECTION_MISMATCH

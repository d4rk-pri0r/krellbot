"""Online sqlite backup, restore, and round-trip helpers for the operational store.

The backup uses ``sqlite3.Connection.backup`` so a writer holding a write
transaction cannot tear the copy. ``Connection.backup`` serialises the
source into the destination at a quiet snapshot point regardless of the
WAL state at the time of the call. A raw ``shutil.copy2`` of a live WAL
can lose rows the checkpoint has not flushed yet; ``Connection.backup``
does not.

``round_trip`` performs backup → restore → row comparison → projection
comparison so the doctor can declare ``backup_ok`` only when both pieces
agree. The projection check reuses ``import_legacy.compare_legacy_projection``
from NS12 — the store-vs-journal comparison is the same one that already
guards ``doctor.run``.

``notify_backup`` honours the telemetry consent gate. The disabled-by-default
case returns before touching the transport so a spy's ``post`` count stays
at zero; the enabled path posts a ``backup_completed`` event with the
install id. The eleven-key fill schema in ``telemetry.maybe_send`` does
not match backup events, so ``notify_backup`` posts directly through the
injected transport and relies on the same consent check.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol, TypedDict

from krellbot.storage import import_legacy
from krellbot.storage.database import OperationalStore

DEFAULT_BACKUP_FILENAME = "ops.sqlite.bak"


class BackupEvent(TypedDict, total=False):
    event: str
    install_id: str
    store_path: str
    backup_path: str


class BackupTransport(Protocol):
    def post(self, url: str, body: bytes, headers: dict) -> object: ...


def _open_backup(backup_path: Path) -> OperationalStore:
    """Open the backup file with a fresh OperationalStore."""
    return OperationalStore(backup_path)


def online_backup(store_path: Path, backup_path: Path) -> Path:
    """Copy the live store to ``backup_path`` using the sqlite backup API.

    A short-lived connection to the source is opened so the backup runs
    while the engine may still hold a writer lock; ``Connection.backup``
    pauses the destination write at a consistent snapshot point.
    """
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(store_path))
    try:
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return backup_path


def restore_backup(backup_path: Path) -> OperationalStore:
    """Open the backup copy with a fresh OperationalStore."""
    return _open_backup(backup_path)


def _read_source_rows(store_path: Path) -> list[tuple[int, str, str]]:
    store = OperationalStore(store_path)
    return store.read_ledger()


def _read_restored_rows(backup_path: Path) -> list[tuple[int, str, str]]:
    return _open_backup(backup_path).read_ledger()


def round_trip(store_path: Path) -> dict:
    """Run backup → restore → row comparison → projection comparison.

    Returns a dict with ``ok``, ``rows_match``, ``projection_status``,
    ``source_rows``, ``restored_rows``, ``backup_path``. ``ok`` is True
    iff ``rows_match`` is True and the NS12 projection comparison is not
    a mismatch (``"not_compared"`` is acceptable for a test home that
    did not set up a journal directory).
    """
    backup_path = store_path.with_name(store_path.name + ".bak")
    online_backup(store_path, backup_path)
    source = _read_source_rows(store_path)
    restored = _read_restored_rows(backup_path)
    rows_match = source == restored

    home = store_path.parent
    projection_status = import_legacy.compare_legacy_projection(home, store_path)

    return {
        "ok": rows_match and projection_status != import_legacy.PROJECTION_MISMATCH,
        "rows_match": rows_match,
        "projection_status": projection_status,
        "source_rows": source,
        "restored_rows": restored,
        "backup_path": str(backup_path),
    }


def notify_backup(
    home: Path,
    *,
    transport: BackupTransport | None = None,
    store_path: Path | None = None,
    backup_path: Path | None = None,
) -> None:
    """Post a backup-completed event when telemetry consent is on.

    Disabled consent (the default) is a no-op: the ``is_enabled`` gate
    returns before touching the transport so a spy's ``post`` count
    stays at zero. Backup events do not fit the eleven-key fill schema,
    so the consent check is mirrored from ``telemetry.maybe_send``
    rather than reusing it directly.
    """
    from krellbot import telemetry as kb_telemetry

    if not kb_telemetry.is_enabled(home):
        return
    if transport is None:
        return

    config_path = home / kb_telemetry.CONFIG_FILE
    install_id = ""
    if config_path.exists():
        try:
            install_id = str(json.loads(config_path.read_text(encoding="utf-8")).get("install_id") or "")
        except (OSError, json.JSONDecodeError):
            install_id = ""

    payload: BackupEvent = {
        "event": "backup_completed",
        "install_id": install_id,
        "store_path": str(store_path) if store_path is not None else "",
        "backup_path": str(backup_path) if backup_path is not None else "",
    }
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    headers = {"content-type": "application/json", "user-agent": "krellbot/0.1"}
    transport.post(kb_telemetry.DEFAULT_URL, body, headers)

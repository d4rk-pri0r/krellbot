"""SQLite operational store. Not a journal cutover."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class StoreBusy(RuntimeError):
    code = "store_busy"


class StoreCorrupt(RuntimeError):
    code = "store_corrupt"


class OperationalStore:
    """One writer. Migrations are idempotent. A failed transaction rolls back."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._write = threading.Lock()
        self._held = False
        self._local = threading.local()

    def connect(self) -> sqlite3.Connection:
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            return existing
        if self.path.exists() and self.path.read_bytes()[:16] not in {
            b"",
            b"SQLite format 3\x00",
        }:
            raise StoreCorrupt("database header is not sqlite")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, isolation_level=None, timeout=0.05, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        self._migrate(conn)
        self._local.conn = conn
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        current = int(row[0] or 0)
        if current < 1:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ledger (
                    id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
            conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")

    def transaction(self):
        return _Write(self)

    def read_ledger(self) -> list[tuple[int, str, str]]:
        conn = self.connect()
        rows = conn.execute("SELECT id, kind, payload FROM ledger ORDER BY id").fetchall()
        return [(int(row["id"]), str(row["kind"]), str(row["payload"])) for row in rows]


class _Write:
    def __init__(self, store: OperationalStore) -> None:
        self._store = store

    def __enter__(self) -> sqlite3.Connection:
        if not self._store._write.acquire(blocking=False):
            raise StoreBusy("another writer holds this store")
        self._store._held = True
        conn = self._store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as exc:
            self._store._held = False
            self._store._write.release()
            raise StoreBusy("another writer holds this store") from exc
        return conn

    def __exit__(self, exc_type, exc, tb) -> None:
        conn = self._store.connect()
        try:
            if exc_type is None:
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
        finally:
            self._store._held = False
            self._store._write.release()

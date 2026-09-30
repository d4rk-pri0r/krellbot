"""SQLite operational store. Not a journal cutover.

The store is the boundary between ``run.tick`` (and the Outbox) and the
underlying SQLite file. Every fault it sees becomes a typed
``StoreError`` subclass — ``StoreBusy``, ``StoreCorrupt``, or ``StoreFull``
— so callers can fail closed with a specific reason instead of catching
a raw ``sqlite3`` error or a generic ``RuntimeError``. Callers see the
typed error; nothing else.
"""

from __future__ import annotations

import errno
import sqlite3
import threading
from pathlib import Path


class StoreError(RuntimeError):
    """Base class for every OperationalStore fault.

    Subclasses keep their existing ``code`` so the audit/reason pipeline
    can switch on the typed error. A raw ``sqlite3`` error never escapes
    the store; the only way to see one is to ``OperationalStore.connect``
    inside a test that intentionally bypasses the wrapper.
    """

    code = "store_error"


class StoreBusy(StoreError):
    """Another writer holds the in-process lock or the SQLite lock."""

    code = "store_busy"


class StoreCorrupt(StoreError):
    """The store bytes are not a SQLite file or the schema is unreadable."""

    code = "store_corrupt"


class StoreFull(StoreError):
    """The store reported the disk/database is full."""

    code = "store_full"


def _classify_operational_error(exc: sqlite3.OperationalError) -> StoreError:
    """Map a single ``sqlite3.OperationalError`` to a typed ``StoreError``.

    The match is message-based: SQLite does not surface a typed code for
    "busy", "full", or "corrupt" in the Python DB-API; the same shape
    appears across CPython versions. Lowercased substring match keeps
    the call site resilient to language differences in the engine.
    """
    message = str(exc).lower()
    if "full" in message:
        return StoreFull(f"store full: {exc}")
    if "locked" in message or "busy" in message:
        return StoreBusy(f"store busy: {exc}")
    if "malformed" in message or "not a database" in message:
        return StoreCorrupt(f"store corrupt: {exc}")
    return StoreCorrupt(f"store corrupt: {exc}")


class OperationalStore:
    """One writer. Migrations are idempotent. A failed transaction rolls back.

    ``connect`` and ``transaction`` translate every fault into a typed
    ``StoreError``. The in-process lock is always released: a translation
    failure path still runs the ROLLBACK statement and clears
    ``_held``/``_write`` so a following ``transaction()`` succeeds.
    """

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
        try:
            conn = sqlite3.connect(self.path, isolation_level=None, timeout=0.05, check_same_thread=False)
        except (sqlite3.DatabaseError, OSError) as exc:
            raise StoreCorrupt(f"store open failed: {exc}") from exc
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA journal_mode=WAL")
            self._migrate(conn)
        except sqlite3.OperationalError as exc:
            raise _classify_operational_error(exc) from exc
        except sqlite3.DatabaseError as exc:
            raise StoreCorrupt(f"store schema unreadable: {exc}") from exc
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise StoreFull(f"store open failed: {exc}") from exc
            raise StoreCorrupt(f"store open failed: {exc}") from exc
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
        try:
            conn = self._store.connect()
        except (StoreError, OSError, sqlite3.DatabaseError):
            self._store._held = False
            self._store._write.release()
            raise
        try:
            conn.execute("BEGIN IMMEDIATE")
            return conn
        except sqlite3.OperationalError as exc:
            self._store._held = False
            self._store._write.release()
            raise _classify_operational_error(exc) from exc
        except sqlite3.DatabaseError as exc:
            self._store._held = False
            self._store._write.release()
            raise StoreCorrupt(f"store write failed: {exc}") from exc
        except OSError as exc:
            self._store._held = False
            self._store._write.release()
            if exc.errno == errno.ENOSPC:
                raise StoreFull(f"store write failed: {exc}") from exc
            raise StoreCorrupt(f"store write failed: {exc}") from exc

    def __exit__(self, exc_type, exc, tb) -> None:
        # ROLLBACK is attempted before raising, and the ROLLBACK's own
        # failure is suppressed. The in-process lock is always released.
        # Raw sqlite3 / OSError from BEGIN, statements inside the block,
        # or COMMIT becomes a typed StoreError chained from `exc`.
        translated: BaseException | None = None
        if exc_type is sqlite3.OperationalError:
            translated = _classify_operational_error(exc)
        elif exc_type is sqlite3.DatabaseError:
            translated = StoreCorrupt(f"store write failed: {exc}")
        elif exc_type is OSError:
            if exc.errno == errno.ENOSPC:
                translated = StoreFull(f"store write failed: {exc}")
            else:
                translated = StoreCorrupt(f"store write failed: {exc}")
        try:
            conn = self._store.connect()
            if translated is None and exc_type is None:
                try:
                    conn.execute("COMMIT")
                except sqlite3.OperationalError as commit_exc:
                    translated = _classify_operational_error(commit_exc)
                except sqlite3.DatabaseError as commit_exc:
                    translated = StoreCorrupt(f"store commit failed: {commit_exc}")
                except OSError as commit_exc:
                    if commit_exc.errno == errno.ENOSPC:
                        translated = StoreFull(f"store commit failed: {commit_exc}")
                    else:
                        translated = StoreCorrupt(f"store commit failed: {commit_exc}")
            elif exc_type is not None:
                try:
                    conn.execute("ROLLBACK")
                except (sqlite3.Error, OSError):
                    pass
        finally:
            self._store._held = False
            self._store._write.release()
        if translated is not None:
            raise translated from exc

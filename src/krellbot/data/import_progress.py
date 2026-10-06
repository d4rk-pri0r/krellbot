"""Durable local checkpoint for one Kraken OHLCVT archive import.

A `data import kraken-ohlcvt` run converts an arbitrary number of CSV records
before it can publish the cache. This module gives that one operation a
bounded, local, restartable progress record under
`<home>/import-progress/kraken-ohlcvt/<sha256(resolved archive path)>.sqlite3`
plus a persistent sibling `.lock` file, so a hard process exit mid-parse loses
at most the uncommitted tail instead of the whole conversion.

Boundaries, on purpose:

* The slot path hash is only a pending-operation lookup for one resolved
  source path. It is not data identity: identity is the streamed whole-archive
  SHA-256 plus the exact requested pair string, timeframe, ordered matching
  member descriptors, schema version and declared bounds stored in `meta`.
* A pending checkpoint that no longer matches is refused, never reset. An
  unreadable or inconsistent one is refused too. Refusals happen before any
  write, so the existing checkpoint, cache and dataset version bytes stay
  exactly as they were.
* Records are committed with their exact cursor position in one transaction
  every `CHECKPOINT_EVERY` accepted candles, at every matching-member boundary
  and at the final `parsed` boundary. Prices and volume stay exact decimal
  text; source position, not timestamp, is the uniqueness key.
* The slot lock is a nonblocking OS advisory lock on a file that is never
  unlinked; the kernel releases it when the owning process dies. It is not
  TickLock and does not participate in any global lock system.

This is stdlib `sqlite3` with a rollback journal (no WAL sidecar lifecycle) and
`synchronous=FULL`. It is a checkpoint, not a data manager: it does not dedupe
sources, fill gaps, or claim compressed random access, constant-memory sorting
or protection against a hostile concurrent filesystem.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA_VERSION = 1
CHECKPOINT_EVERY = 128
DEFAULT_MAX_RECORDS = 1_000_000
DEFAULT_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
_HASH_READ_BYTES = 1024 * 1024

_PROGRESS_ROOT = ("import-progress", "kraken-ohlcvt")
_META_KEYS = (
    "schema_version",
    "source_path",
    "source_sha256",
    "pair",
    "tf",
    "members_json",
    "max_records",
    "max_uncompressed_bytes",
    "checkpoint_every",
    "cursor_json",
)
_IDENTITY_KEYS = ("source_path", "source_sha256", "pair", "tf", "members_json")
_BOUND_KEYS = ("max_records", "max_uncompressed_bytes", "checkpoint_every")
_CURSOR_KEYS = ("next_member_index", "next_row_index", "records_seen", "candles_count", "phase")

_IS_WINDOWS = os.name == "nt"

# Validates a pending cursor against the actual selected source members while
# the checkpoint is still open read-only. It receives the read-only connection
# and the parsed cursor, and raises ImportProgressError on any inconsistency.
SourceAccounting = Callable[[sqlite3.Connection, Mapping[str, Any]], None]


class ImportProgressError(RuntimeError):
    """A pending import cannot be continued or started as asked; nothing was modified."""


def slot_paths(home: Path | str, source_path: Path | str) -> tuple[Path, Path]:
    """Return `(db_path, lock_path)` for one resolved archive path under `home`."""
    digest = hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()
    db = Path(home).joinpath(*_PROGRESS_ROOT) / f"{digest}.sqlite3"
    return db, db.with_name(db.name + ".lock")


def ensure_slot_dir(home: Path | str) -> Path:
    """Create the progress slot directory (mode 0700 on POSIX) and return it."""
    root = Path(home).joinpath(*_PROGRESS_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    if not _IS_WINDOWS:
        os.chmod(root.parent, 0o700)
        os.chmod(root, 0o700)
    return root


def file_sha256(path: Path | str) -> str:
    """Streamed hex SHA-256 of a file, reading at most 1 MiB at a time."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(_HASH_READ_BYTES)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def source_fingerprint(path: Path | str) -> tuple[int, int, int, int]:
    """Cheap identity of the file's current bytes: (dev, ino, size, mtime_ns)."""
    st = os.stat(path)
    return (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)


class SourceLock:
    """Nonblocking advisory lock on the persistent slot lock file.

    The lock file is created once and never unlinked; the OS releases the lock
    when the owning process dies, which is the recovery path after a hard exit.
    Contention raises `ImportProgressError` instead of waiting.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._fd: int | None = None

    def acquire(self) -> None:
        fd = os.open(str(self._path), os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
        try:
            if _IS_WINDOWS:
                import msvcrt

                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                except OSError as exc:
                    raise ImportProgressError(
                        f"another import of this archive is already in progress (lock {self._path})"
                    ) from exc
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as exc:
                    raise ImportProgressError(
                        f"another import of this archive is already in progress (lock {self._path})"
                    ) from exc
        except BaseException:
            os.close(fd)
            raise
        if not _IS_WINDOWS:
            os.chmod(self._path, 0o600)
        self._fd = fd

    def release(self) -> None:
        """Release and close. The lock file itself is never removed."""
        if self._fd is None:
            return
        fd = self._fd
        self._fd = None
        try:
            if _IS_WINDOWS:
                import msvcrt

                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            os.close(fd)

    def __enter__(self) -> "SourceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def _connect(db_path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=30.0)
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA synchronous=FULL")
    return con


_SQLITE_MAGIC = b"SQLite format 3\x00"


def _inspect_existing(
    path: Path,
    *,
    identity: Mapping[str, Any],
    bounds: Mapping[str, int],
    source_accounting: SourceAccounting | None = None,
) -> None:
    """Validate an existing checkpoint with a truly read-only connection.

    This runs before any writable open and before any journal-changing
    PRAGMA, so every refusal below leaves the checkpoint bytes exactly as
    they are. The journal mode is read from the file header first: opening a
    WAL checkpoint - even read-only - materializes `-wal`/`-shm` sidecars,
    and opening it writable would normalize the header back to the rollback
    journal before the refusal. A checkpoint whose header is not a sqlite
    database is refused without being opened at all.
    """
    try:
        with open(path, "rb") as fh:
            header = fh.read(100)
    except OSError as exc:
        raise ImportProgressError(f"checkpoint {path} cannot be read: {exc}") from exc
    if len(header) < 100 or not header.startswith(_SQLITE_MAGIC):
        raise ImportProgressError(f"checkpoint {path} is not a readable sqlite database")
    if header[18] != 1 or header[19] != 1:
        raise ImportProgressError(
            f"checkpoint {path} uses journal mode 'wal' (header write={header[18]}, "
            f"read={header[19]}), not the rollback journal; refusing without opening it"
        )
    con: sqlite3.Connection | None = None
    try:
        con = sqlite3.connect(f"{Path(path).absolute().as_uri()}?mode=ro", uri=True)
        _validate_existing(con, path, identity=identity, bounds=bounds, source_accounting=source_accounting)
    except ImportProgressError:
        raise
    except sqlite3.Error as exc:
        raise ImportProgressError(f"checkpoint {path} is unreadable: {exc}") from exc
    finally:
        if con is not None:
            con.close()


def _validate_existing(
    con: sqlite3.Connection,
    path: Path,
    *,
    identity: Mapping[str, Any],
    bounds: Mapping[str, int],
    source_accounting: SourceAccounting | None = None,
) -> None:
    """Refuse any checkpoint that does not match this import, reading only."""
    meta = _read_meta(con)
    if meta["schema_version"] != str(SCHEMA_VERSION):
        raise ImportProgressError(
            f"checkpoint schema version {meta['schema_version']!r} is not {SCHEMA_VERSION}"
        )
    for key in _IDENTITY_KEYS:
        if key == "members_json":
            if json.loads(meta[key]) != json.loads(_as_text(identity[key])):
                raise ImportProgressError(
                    f"checkpoint {key} no longer matches this source; refusing to reset pending progress"
                )
        elif meta[key] != _as_text(identity[key]):
            raise ImportProgressError(
                f"checkpoint {key} {meta[key]!r} does not match this import {_as_text(identity[key])!r}; "
                "refusing to reset pending progress"
            )
    for key in _BOUND_KEYS:
        if meta[key] != str(int(bounds[key])):
            raise ImportProgressError(
                f"checkpoint {key} {meta[key]!r} does not match the declared bound "
                f"{int(bounds[key])!r}; refusing to continue with different bounds"
            )
    cursor = _parse_cursor(meta["cursor_json"])
    member_count = len(json.loads(meta["members_json"]))
    if cursor["next_member_index"] > member_count:
        raise ImportProgressError(f"checkpoint cursor is past the {member_count} selected members")
    if cursor["phase"] == "parsed":
        if cursor["next_member_index"] != member_count:
            raise ImportProgressError("checkpoint claims parsed but members are still pending")
        if cursor["next_row_index"] != 0:
            raise ImportProgressError("checkpoint claims parsed but its cursor is inside a member")
    stored = int(con.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
    if stored != cursor["candles_count"]:
        raise ImportProgressError(
            f"checkpoint holds {stored} candles but its cursor claims {cursor['candles_count']}"
        )
    beyond = int(
        con.execute(
            "SELECT COUNT(*) FROM candles WHERE member_index > ? "
            "OR (member_index = ? AND row_index >= ?)",
            (
                cursor["next_member_index"],
                cursor["next_member_index"],
                cursor["next_row_index"],
            ),
        ).fetchone()[0]
    )
    if beyond:
        raise ImportProgressError(f"checkpoint holds {beyond} candles at or past its cursor position")
    if cursor["records_seen"] < cursor["candles_count"]:
        raise ImportProgressError("checkpoint cursor counts fewer records than candles")
    if cursor["next_member_index"] == 0 and cursor["records_seen"] != cursor["next_row_index"]:
        raise ImportProgressError(
            "checkpoint records_seen "
            f"{cursor['records_seen']} does not match its position {cursor['next_row_index']} "
            "in the first selected member"
        )
    in_current = int(
        con.execute(
            "SELECT COUNT(*) FROM candles WHERE member_index = ?", (cursor["next_member_index"],)
        ).fetchone()[0]
    )
    if in_current > cursor["next_row_index"]:
        raise ImportProgressError(
            f"checkpoint holds {in_current} candles inside member {cursor['next_member_index']} "
            f"but its cursor has only consumed {cursor['next_row_index']} records there"
        )
    if source_accounting is not None:
        # Last, and still read-only: tie the cursor and every stored candle
        # position to the actual selected source members, for ALL selected
        # member occurrences, in both the parsing and parsed phases.
        try:
            source_accounting(con, cursor)
        except ImportProgressError:
            raise
        except sqlite3.Error as exc:
            raise ImportProgressError(f"checkpoint {path} is unreadable: {exc}") from exc


def _read_meta(con: sqlite3.Connection) -> dict[str, str]:
    rows = con.execute("SELECT key, value FROM meta").fetchall()
    meta = {str(k): str(v) for k, v in rows}
    if set(meta) != set(_META_KEYS):
        raise ImportProgressError(
            f"checkpoint meta keys {sorted(meta)} do not match schema {SCHEMA_VERSION}"
        )
    return meta


def _parse_cursor(raw: str) -> dict[str, Any]:
    try:
        cursor = json.loads(raw)
    except ValueError as exc:
        raise ImportProgressError(f"checkpoint cursor_json is not valid JSON") from exc
    if not isinstance(cursor, dict) or set(cursor) != set(_CURSOR_KEYS):
        raise ImportProgressError(f"checkpoint cursor keys are not the declared set: {sorted(cursor)}")
    for key in ("next_member_index", "next_row_index", "records_seen", "candles_count"):
        value = cursor[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ImportProgressError(f"checkpoint cursor {key} is not a non-negative integer: {value!r}")
    if cursor["phase"] not in ("parsing", "parsed"):
        raise ImportProgressError(f"checkpoint cursor phase is unknown: {cursor['phase']!r}")
    return cursor


class ImportCheckpoint:
    """sqlite3-backed bounded progress for one archive import.

    `open_or_create` either validates an existing pending checkpoint against
    the caller's identity/bounds (refusing any mismatch before writing) or
    creates a fresh one. Rows are buffered and committed with their exact
    cursor position in a single transaction per `CHECKPOINT_EVERY` accepted
    candles, at member boundaries, and at the final `parsed` boundary.
    """

    def __init__(self, db_path: Path, con: sqlite3.Connection, checkpoint_every: int) -> None:
        self._path = Path(db_path)
        self._con = con
        self._checkpoint_every = checkpoint_every
        cursor = _parse_cursor(con.execute("SELECT value FROM meta WHERE key='cursor_json'").fetchone()[0])
        self._cursor = cursor
        self._records_seen = int(cursor["records_seen"])
        self._candles_count = int(cursor["candles_count"])
        self._pending: list[tuple[int, int, tuple[int, str, str, str, str, str]]] = []

    # -- construction ----------------------------------------------------

    @classmethod
    def open_or_create(
        cls,
        db_path: Path | str,
        *,
        identity: Mapping[str, Any],
        bounds: Mapping[str, int],
        source_accounting: SourceAccounting | None = None,
    ) -> "ImportCheckpoint":
        path = Path(db_path)
        if path.exists():
            return cls._open_existing(path, identity=identity, bounds=bounds, source_accounting=source_accounting)
        return cls._create(path, identity=identity, bounds=bounds)

    @classmethod
    def _create(cls, path: Path, *, identity: Mapping[str, Any], bounds: Mapping[str, int]) -> "ImportCheckpoint":
        con = _connect(path)
        try:
            con.execute("BEGIN IMMEDIATE")
            con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.execute(
                "CREATE TABLE candles ("
                "member_index INTEGER, row_index INTEGER, ts_ms INTEGER, "
                "open TEXT, high TEXT, low TEXT, close TEXT, volume TEXT, "
                "PRIMARY KEY (member_index, row_index))"
            )
            meta = {
                "schema_version": str(SCHEMA_VERSION),
                **{key: _as_text(identity[key]) for key in _IDENTITY_KEYS},
                **{key: str(int(bounds[key])) for key in _BOUND_KEYS},
                "cursor_json": json.dumps(
                    {
                        "next_member_index": 0,
                        "next_row_index": 0,
                        "records_seen": 0,
                        "candles_count": 0,
                        "phase": "parsing",
                    }
                ),
            }
            con.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)", sorted(meta.items())
            )
            con.execute("COMMIT")
        except BaseException:
            con.close()
            raise
        if not _IS_WINDOWS:
            os.chmod(path, 0o600)
        return cls(path, con, int(bounds["checkpoint_every"]))

    @classmethod
    def _open_existing(
        cls,
        path: Path,
        *,
        identity: Mapping[str, Any],
        bounds: Mapping[str, int],
        source_accounting: SourceAccounting | None = None,
    ) -> "ImportCheckpoint":
        # Inspect read-only first: every refusal must leave the checkpoint,
        # journal and sidecar bytes exactly as they were found. Only a
        # checkpoint that fully matches this import is opened for writing.
        _inspect_existing(path, identity=identity, bounds=bounds, source_accounting=source_accounting)
        try:
            con = _connect(path)
        except sqlite3.Error as exc:
            raise ImportProgressError(f"checkpoint {path} cannot be opened: {exc}") from exc
        return cls(path, con, int(bounds["checkpoint_every"]))

    # -- state ------------------------------------------------------------

    @property
    def phase(self) -> str:
        return str(self._cursor["phase"])

    @property
    def next_member_index(self) -> int:
        return int(self._cursor["next_member_index"])

    @property
    def next_row_index(self) -> int:
        return int(self._cursor["next_row_index"])

    @property
    def records_seen(self) -> int:
        return self._records_seen

    @property
    def candles_count(self) -> int:
        return self._candles_count

    # -- writing ----------------------------------------------------------

    def note_record(
        self,
        member_index: int,
        row_index: int,
        candle: tuple[int, str, str, str, str, str] | None,
    ) -> bool:
        """Account one consumed CSV record; commit when the buffer is full.

        `candle` is `(ts_ms, open, high, low, close, volume)` as exact decimal
        text, or `None` for a skipped (header/empty/non-numeric/wrong-width)
        record. Skipped records still advance the cursor and counts.
        """
        self._records_seen += 1
        if candle is not None:
            self._candles_count += 1
            self._pending.append((member_index, row_index, candle))
            if len(self._pending) >= self._checkpoint_every:
                self.commit(next_member_index=member_index, next_row_index=row_index + 1)
                return True
        return False

    def commit(self, *, next_member_index: int, next_row_index: int, phase: str = "parsing") -> None:
        """Commit buffered candles and the exact next-record cursor in ONE transaction."""
        cursor = {
            "next_member_index": int(next_member_index),
            "next_row_index": int(next_row_index),
            "records_seen": self._records_seen,
            "candles_count": self._candles_count,
            "phase": phase,
        }
        rows = [
            (member_index, row_index, c[0], c[1], c[2], c[3], c[4], c[5])
            for member_index, row_index, c in self._pending
        ]
        self._con.execute("BEGIN IMMEDIATE")
        try:
            if rows:
                self._con.executemany(
                    "INSERT INTO candles "
                    "(member_index, row_index, ts_ms, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            self._con.execute(
                "UPDATE meta SET value = ? WHERE key = 'cursor_json'", (json.dumps(cursor),)
            )
            self._con.execute("COMMIT")
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
        self._pending.clear()
        self._cursor = cursor

    def load_candles(self) -> list[tuple[int, str, str, str, str, str]]:
        """Committed candles in source order (member, then record position)."""
        rows = self._con.execute(
            "SELECT ts_ms, open, high, low, close, volume FROM candles "
            "ORDER BY member_index, row_index"
        ).fetchall()
        return [(int(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5])) for r in rows]

    # -- teardown ----------------------------------------------------------

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None  # type: ignore[assignment]

    def discard(self) -> None:
        """Remove the completed checkpoint (db + any journal sidecar).

        Called only after publication succeeded. The lock file is NOT removed:
        its inode outlives every single import.
        """
        self.close()
        for suffix in ("", "-journal", "-wal", "-shm"):
            candidate = self._path.with_name(self._path.name + suffix)
            try:
                candidate.unlink()
            except FileNotFoundError:
                pass


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else str(value)

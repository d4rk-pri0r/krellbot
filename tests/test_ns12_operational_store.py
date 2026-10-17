"""NS12 first leaf: one writer, migration, rollback. Not a journal cutover."""

from __future__ import annotations

import threading

import pytest

from krellbot.storage.database import OperationalStore, StoreBusy, StoreCorrupt


def test_migration_is_idempotent_and_a_failed_write_rolls_back(tmp_path) -> None:
    path = tmp_path / "ops.sqlite"
    store = OperationalStore(path)
    with store.transaction() as conn:
        conn.execute("INSERT INTO ledger (kind, payload) VALUES ('intent', 'a')")
    again = OperationalStore(path)
    assert again.read_ledger() == [(1, "intent", "a")]
    with pytest.raises(RuntimeError, match="boom"), again.transaction() as conn:
        conn.execute("INSERT INTO ledger (kind, payload) VALUES ('intent', 'b')")
        raise RuntimeError("boom")
    assert again.read_ledger() == [(1, "intent", "a")]


def test_second_writer_is_refused_while_the_lock_is_held(tmp_path) -> None:
    path = tmp_path / "ops.sqlite"
    holder = OperationalStore(path)
    other = OperationalStore(path)
    started = threading.Event()
    release = threading.Event()

    def hold() -> None:
        with holder.transaction():
            started.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=hold)
    thread.start()
    assert started.wait(timeout=2)
    with pytest.raises(StoreBusy), other.transaction():
        pass
    release.set()
    thread.join(timeout=2)
    assert other.connect().execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_corrupt_file_is_not_opened_as_a_store(tmp_path) -> None:
    path = tmp_path / "ops.sqlite"
    path.write_bytes(b"not a database!!")
    with pytest.raises(StoreCorrupt):
        OperationalStore(path).connect()

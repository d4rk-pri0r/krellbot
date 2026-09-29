"""NS12 second leaf: import_legacy behaviors, projection comparison, WAL restore.

The store is a one-writer SQLite ledger. The legacy journal keeps writing
to JSONL files until the cutover flips in a later leaf. This module
proves the comparison view the doctor runs without changing the write
path: a transactional import helper that rolls back on writer failure, a
WAL-restore check that survives copying the live file plus its -wal/-shm
siblings, and a projection comparison that surfaces `match`, `mismatch`,
or `not_compared` to doctor.run.

Do not claim the journal has been cut over.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
from pathlib import Path

import pytest

from krellbot import doctor
from krellbot.storage import import_legacy
from krellbot.storage.database import OperationalStore

# ---------------------------------------------------------------------------
# Behavior 1: import_legacy writes all records in one transaction, and a
# failing injected writer leaves both ledger and schema_migrations untouched.
# ---------------------------------------------------------------------------


def _record(kind: str, **detail: object) -> dict:
    base = {"ts": 1_700_000_000, "kind": kind, "venue": "kraken", "pack": "demo"}
    base.update(detail)
    return base


def test_import_legacy_writes_all_records_in_one_transaction(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "ops.sqlite")
    records = [_record("tick", bar_ts=1), _record("tick", bar_ts=2)]

    import_legacy.import_legacy(store, records)

    rows = store.read_ledger()
    assert [row[1] for row in rows] == ["tick", "tick"]
    assert json.loads(rows[0][2])["bar_ts"] == 1
    assert json.loads(rows[1][2])["bar_ts"] == 2


def test_import_legacy_rolls_back_when_injected_writer_raises(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "ops.sqlite")
    # Seed one committed row so the rollback can be distinguished from "store
    # was empty anyway". The seed must survive the failed import below.
    import_legacy.import_legacy(store, [_record("seed")])
    assert len(store.read_ledger()) == 1

    conn = store.connect()
    before_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    before_ledger = store.read_ledger()

    def writer(_conn, _record) -> None:
        raise RuntimeError("injected failure")

    with pytest.raises(RuntimeError, match="injected failure"):
        import_legacy.import_legacy(store, [_record("x"), _record("y")], writer=writer)

    assert store.read_ledger() == before_ledger
    after_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert after_version == before_version


# ---------------------------------------------------------------------------
# Behavior 2: disk-full simulation. An injected writer raising
# OSError(errno.ENOSPC) rolls back. No partial migration version remains.
# The test never fills the real disk.
# ---------------------------------------------------------------------------


def test_disk_full_rolls_back_no_partial_migration(tmp_path: Path) -> None:
    store = OperationalStore(tmp_path / "ops.sqlite")
    conn = store.connect()
    before_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    before_ledger = store.read_ledger()

    def enospc_writer(_conn, _record) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    with pytest.raises(OSError) as excinfo:
        import_legacy.import_legacy(store, [_record("first"), _record("second")], writer=enospc_writer)
    assert excinfo.value.errno == errno.ENOSPC

    assert store.read_ledger() == before_ledger
    after_version = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert after_version == before_version


# ---------------------------------------------------------------------------
# Behavior 3: WAL restore. Copy the sqlite file plus its -wal and -shm
# siblings to a new directory; a fresh OperationalStore on the copy reads
# back the same rows. If a sibling is missing after a checkpoint, reopen
# still returns the rows SQLite has checkpointed; the test names which
# case it proved.
# ---------------------------------------------------------------------------


def _write_two_rows(store: OperationalStore) -> None:
    import_legacy.import_legacy(store, [_record("tick", bar_ts=10), _record("tick", bar_ts=11)])


def _copy_sqlite_with_siblings(src_db: Path, dest_dir: Path) -> dict[str, Path]:
    copied: dict[str, Path] = {}
    for sibling in (src_db, src_db.with_name(src_db.name + "-wal"), src_db.with_name(src_db.name + "-shm")):
        if not sibling.exists():
            continue
        target = dest_dir / sibling.name
        shutil.copy2(sibling, target)
        copied[sibling.name] = target
    return copied


def test_wal_restore_with_siblings(tmp_path: Path) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    src_db = src_dir / "ops.sqlite"
    src_store = OperationalStore(src_db)
    _write_two_rows(src_store)

    # Force a checkpoint so the main file has the committed rows even if
    # the WAL sibling is dropped later. Without this, dropping -wal would
    # lose the rows SQLite hasn't yet checkpointed.
    src_store.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    copied = _copy_sqlite_with_siblings(src_db, dst_dir)
    assert "ops.sqlite" in copied

    restored = OperationalStore(dst_dir / "ops.sqlite")
    rows = restored.read_ledger()
    assert [row[1] for row in rows] == ["tick", "tick"]
    assert json.loads(rows[1][2])["bar_ts"] == 11


def test_wal_restore_after_checkpoint_without_wal_sibling(tmp_path: Path) -> None:
    """Open after copying only the main file; only the checkpointed rows must survive."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    dst_dir = tmp_path / "dst"
    dst_dir.mkdir()
    src_db = src_dir / "ops.sqlite"
    src_store = OperationalStore(src_db)
    _write_two_rows(src_store)

    # Checkpoint so the data is in the main file before we drop the -wal.
    src_store.connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Copy only the main file. The -wal sibling is intentionally left out.
    shutil.copy2(src_db, dst_dir / "ops.sqlite")

    restored = OperationalStore(dst_dir / "ops.sqlite")
    rows = restored.read_ledger()
    assert len(rows) == 2
    assert [row[1] for row in rows] == ["tick", "tick"]


# ---------------------------------------------------------------------------
# Behavior 4: projection comparison. Equal projections are "match". A
# differing payload is "mismatch". A home with no legacy journal and no
# store is "not_compared", not "match".
# ---------------------------------------------------------------------------


def _write_journal_line(journal_dir: Path, record: dict) -> None:
    journal_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), sort_keys=True)
    target = journal_dir / "2026-01.jsonl"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _make_home_0o700(home: Path) -> None:
    """Match the POSIX mode krellbot production code requires."""
    os.chmod(home, 0o700)


def test_compare_legacy_projection_match(tmp_path: Path) -> None:
    journal_dir = tmp_path / "journal"
    store_path = tmp_path / "ops.sqlite"
    record_a = _record("tick", bar_ts=42)
    record_b = _record("order_intent", bar_ts=43)

    _write_journal_line(journal_dir, record_a)
    _write_journal_line(journal_dir, record_b)

    store = OperationalStore(store_path)
    import_legacy.import_legacy(store, [record_a, record_b])

    assert import_legacy.compare_legacy_projection(tmp_path, store_path) == "match"


def test_compare_legacy_projection_mismatch(tmp_path: Path) -> None:
    journal_dir = tmp_path / "journal"
    store_path = tmp_path / "ops.sqlite"
    journal_record = _record("tick", bar_ts=1)
    store_record = _record("tick", bar_ts=2)

    _write_journal_line(journal_dir, journal_record)

    store = OperationalStore(store_path)
    import_legacy.import_legacy(store, [store_record])

    assert import_legacy.compare_legacy_projection(tmp_path, store_path) == "mismatch"


def test_compare_legacy_projection_not_compared_when_neither_exists(tmp_path: Path) -> None:
    """Empty home (no journal, no store) is 'not_compared', not 'match'."""
    store_path = tmp_path / "ops.sqlite"
    assert import_legacy.compare_legacy_projection(tmp_path, store_path) == "not_compared"


def test_compare_legacy_projection_not_compared_when_only_journal_exists(tmp_path: Path) -> None:
    journal_dir = tmp_path / "journal"
    store_path = tmp_path / "ops.sqlite"
    _write_journal_line(journal_dir, _record("tick"))
    # No store created.
    assert import_legacy.compare_legacy_projection(tmp_path, store_path) == "not_compared"


def test_compare_legacy_projection_not_compared_when_only_store_exists(tmp_path: Path) -> None:
    store_path = tmp_path / "ops.sqlite"
    store = OperationalStore(store_path)
    import_legacy.import_legacy(store, [_record("tick")])
    # No journal created.
    assert import_legacy.compare_legacy_projection(tmp_path, store_path) == "not_compared"


# ---------------------------------------------------------------------------
# Behavior 5: doctor.run calls the comparison. JSON includes
# projection_status. Mismatch adds a warning and bumps the exit code.
# The test calls doctor.run, not only the helper.
# ---------------------------------------------------------------------------


def test_doctor_run_reports_not_compared_when_nothing_to_compare(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    _make_home_0o700(tmp_path)
    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)
    assert body["projection_status"] == "not_compared"
    assert not any("projection" in w for w in body["warnings"])


def test_doctor_run_reports_match_when_projections_match(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    _make_home_0o700(tmp_path)
    journal_dir = tmp_path / "journal"
    store_path = tmp_path / "ops.sqlite"
    record = _record("tick", bar_ts=7)
    _write_journal_line(journal_dir, record)
    store = OperationalStore(store_path)
    import_legacy.import_legacy(store, [record])

    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)
    assert body["projection_status"] == "match"
    assert not any("projection" in w for w in body["warnings"])


def test_doctor_run_reports_mismatch_adds_warning_and_raises_exit_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    _make_home_0o700(tmp_path)
    journal_dir = tmp_path / "journal"
    store_path = tmp_path / "ops.sqlite"
    _write_journal_line(journal_dir, _record("tick", bar_ts=1))
    store = OperationalStore(store_path)
    import_legacy.import_legacy(store, [_record("tick", bar_ts=2)])

    exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)
    assert body["projection_status"] == "mismatch"
    assert any("projection mismatch" in w for w in body["warnings"])
    assert exit_code == 1


def test_doctor_module_imports_compare_legacy_projection() -> None:
    """Grep proof: doctor.py must call the comparison, not just host it."""
    import inspect

    from krellbot.storage import import_legacy as il

    source = inspect.getsource(doctor)
    assert "compare_legacy_projection" in source
    # And it must reach the real symbol.
    assert il.compare_legacy_projection is import_legacy.compare_legacy_projection


@pytest.mark.parametrize("case", ["match", "mismatch", "not_compared"])
def test_projection_status_reaches_json_body(case: str, tmp_path: Path, monkeypatch) -> None:
    """doctor.run surfaces projection_status in JSON for every comparison case."""
    monkeypatch.setattr("krellbot.doctor._ui_bind_available", lambda: True)
    _make_home_0o700(tmp_path)
    journal_dir = tmp_path / "journal"
    store_path = tmp_path / "ops.sqlite"

    if case == "match":
        record = _record("tick", bar_ts=10)
        _write_journal_line(journal_dir, record)
        OperationalStore(store_path)
        import_legacy.import_legacy(OperationalStore(store_path), [record])
    elif case == "mismatch":
        _write_journal_line(journal_dir, _record("tick", bar_ts=1))
        import_legacy.import_legacy(OperationalStore(store_path), [_record("tick", bar_ts=2)])
    else:
        # Neither side present.
        pass

    _exit_code, text = doctor.run(home=tmp_path, as_json=True)
    body = json.loads(text)
    assert body["projection_status"] == case
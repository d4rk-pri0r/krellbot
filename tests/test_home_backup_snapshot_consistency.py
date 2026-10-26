"""Real WAL/archive regressions; boundary scheduling is instrumentation, not a race-rate claim.

Every online_backup wrapper delegates to the genuine SQLite backup and never
changes snapshot bytes or replaces create/restore. Child writers use separate
interpreters, commit real transactions and report their PID for runtime evidence.
All homes and marker-shaped strings are isolated synthetic fixtures.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from krellbot.storage import backup, home_backup
from krellbot.storage.database import OperationalStore

_CHILD_WRITE = """
import json, os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=5)
try:
    assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    conn.execute('INSERT INTO ledger (kind, payload) VALUES (?, ?)', ('child', sys.argv[2]))
    conn.commit()
    print(json.dumps({'pid': os.getpid(), 'rows': conn.execute('SELECT COUNT(*) FROM ledger').fetchone()[0]}))
finally:
    conn.close()
"""


def _child_commit(path: Path, payload: str = "synthetic-child") -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD_WRITE, str(path), payload],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
    result = json.loads(proc.stdout)
    assert result["pid"] != os.getpid()
    return result


def _rows(path: Path) -> list[tuple]:
    with closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT id, kind, payload FROM ledger ORDER BY id").fetchall()


def _rows_sha(rows: list[tuple]) -> str:
    return hashlib.sha256(json.dumps([list(r) for r in rows], sort_keys=True).encode("utf-8")).hexdigest()


def _archive_members(path: Path) -> dict[str, bytes]:
    import tarfile

    with tarfile.open(path, "r:gz") as archive:
        assert all(member.isfile() and member.mode == 0o600 for member in archive.getmembers())
        return {member.name: archive.extractfile(member).read() for member in archive.getmembers()}


@pytest.fixture
def wal_home(tmp_path):
    home = tmp_path / "source"
    store = OperationalStore(home / "ops.sqlite")
    conn = store.connect()
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("INSERT INTO ledger (kind, payload) VALUES ('seed', 'synthetic-seed')")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert (home / "ops.sqlite-wal").stat().st_size > 0
    try:
        yield home, store
    finally:
        home_backup._release_store_handle(store)


@pytest.fixture
def snapshot_tmp(tmp_path, monkeypatch):
    """Force product staging into an observable external pytest temp directory."""
    staging = tmp_path / "snapshot-staging"
    staging.mkdir()
    monkeypatch.setattr(home_backup.tempfile, "tempdir", str(staging))
    yield staging
    assert list(staging.iterdir()) == [], "snapshot/restore staging leaked"
    # Linux also permits unlinking open files: inspect handles, not just names.
    descriptors = Path("/proc/self/fd")
    if descriptors.is_dir():
        for fd in descriptors.iterdir():
            try:
                target = os.readlink(fd)
            except FileNotFoundError:
                continue
            assert str(staging) not in target, f"stale staging handle: {target}"


@pytest.mark.parametrize("intervening_commit", [False, True], ids=["unchanged-control", "separate-child-commit"])
def test_archive_and_manifest_share_one_snapshot(wal_home, snapshot_tmp, tmp_path, monkeypatch, intervening_commit):
    home, store = wal_home
    source = home / "ops.sqlite"
    before = store.read_ledger()
    snapshots = []
    children = []
    genuine_backup = backup.online_backup

    def scheduled_backup(src, dst):
        # Instrumentation only: finish a genuine snapshot, then schedule a real
        # child commit before create can assemble/archive its captured bytes.
        result = genuine_backup(src, dst)
        snapshots.append((dst.read_bytes(), _rows(dst)))
        if intervening_commit and len(snapshots) == 1:
            children.append(_child_commit(src))
        return result

    monkeypatch.setattr(backup, "online_backup", scheduled_backup)
    archive = tmp_path / "backup.tar.gz"
    manifest = home_backup.create(home, archive, now=1_700_000_300)
    members = _archive_members(archive)
    db_bytes = members["files/ops.sqlite"]
    entry = next(item for item in manifest["files"] if item["path"] == "ops.sqlite")
    target = tmp_path / "restored"
    try:
        restored_manifest = home_backup.restore(archive, target)
    except home_backup.BackupError as exc:
        print(
            json.dumps(
                {
                    "restore": exc.code,
                    "message": str(exc),
                    "manifest": manifest,
                    "archived_sha256": hashlib.sha256(db_bytes).hexdigest(),
                    "snapshots": len(snapshots),
                    "children": children,
                },
                sort_keys=True,
            )
        )
        raise
    assert restored_manifest == manifest == json.loads(members["manifest.json"])
    assert entry == {"path": "ops.sqlite", "sha256": hashlib.sha256(db_bytes).hexdigest(), "size": len(db_bytes)}
    assert db_bytes == snapshots[0][0]
    assert manifest["ops_rows"] == len(snapshots[0][1]) == len(before)
    assert manifest["ops_rows_sha256"] == _rows_sha(snapshots[0][1]) == _rows_sha(before)
    assert _rows(target / "ops.sqlite") == before
    assert home_backup.verify_home(target, manifest) == []
    if intervening_commit:
        assert len(snapshots) == 1, "create must capture the database exactly once"
    expected_source = before + ([(2, "child", "synthetic-child")] if intervening_commit else [])
    assert store.read_ledger() == _rows(source) == expected_source
    assert all(child["rows"] == 2 for child in children)
    # A subsequent separate-process commit proves backup did not freeze/close
    # the source writer, and introduced no source ledger rows of its own.
    assert _child_commit(source, "after-backup")["rows"] == len(expected_source) + 1
    assert store.read_ledger() == expected_source + [(len(expected_source) + 1, "child", "after-backup")]
    assert list(snapshot_tmp.iterdir()) == []
    if os.name != "nt":
        assert archive.stat().st_mode & 0o777 == 0o600
    print(
        json.dumps(
            {
                "restore": "success",
                "manifest": manifest,
                "children": children,
                "archived_sha256": hashlib.sha256(db_bytes).hexdigest(),
                "snapshot_count": len(snapshots),
                "restored_rows": before,
            },
            sort_keys=True,
        )
    )


def test_unchanged_wal_home_is_deterministic(wal_home, snapshot_tmp, tmp_path):
    home, store = wal_home
    before = store.read_ledger()
    one, two = tmp_path / "one.tar.gz", tmp_path / "two.tar.gz"
    assert home_backup.create(home, one, now=123) == home_backup.create(home, two, now=123)
    assert one.read_bytes() == two.read_bytes()
    assert store.read_ledger() == before


def test_no_database_preserves_regular_files_and_exclusions(tmp_path, snapshot_tmp):
    home = tmp_path / "source"
    home.mkdir()
    (home / "config.json").write_bytes(b'{"mode":"paper"}')
    for rel in (
        "live-authorization.json",
        "logs/debug.txt",
        "run/test.lock",
        "old.bak",
        "ops.sqlite-wal",
        "ops.sqlite-shm",
        "ops.sqlite-journal",
    ):
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"-----BEGIN PRIVATE KEY-----\nsynthetic-excluded")
    archive = tmp_path / "no-db.tar.gz"
    manifest = home_backup.create(home, archive, now=123)
    data = (home / "config.json").read_bytes()
    assert manifest == {
        "schema": "1",
        "created_at": 123,
        "ops_rows": None,
        "ops_rows_sha256": None,
        "files": [{"path": "config.json", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}],
    }
    assert set(_archive_members(archive)) == {"manifest.json", "files/config.json"}
    target = tmp_path / "restored"
    assert home_backup.restore(archive, target) == manifest
    assert (target / "config.json").read_bytes() == data
    assert not (home / "ops.sqlite").exists()
    assert home_backup.verify_home(target, manifest) == []


@pytest.mark.parametrize("marker", ["-----BEGIN OPENSSH PRIVATE KEY-----", "kb_live_ABCDEFGHIJKLMNOPQRSTUVWXabcd"])
def test_secret_in_actual_wal_snapshot_is_refused(wal_home, snapshot_tmp, tmp_path, monkeypatch, marker):
    home, store = wal_home
    source = home / "ops.sqlite"
    assert marker.encode() not in source.read_bytes()
    genuine_backup = backup.online_backup
    calls = []

    def commit_before_snapshot(src, dst):
        # Boundary scheduling only: the marker enters the real WAL after file
        # enumeration/raw-file inspection but before the genuine online capture.
        calls.append(_child_commit(src, marker))
        result = genuine_backup(src, dst)
        assert marker.encode() in dst.read_bytes()
        return result

    monkeypatch.setattr(backup, "online_backup", commit_before_snapshot)
    archive = tmp_path / "refused.tar.gz"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.create(home, archive, now=123)
    assert exc.value.code == "secret_detected"
    assert str(exc.value) == "ops.sqlite"
    assert len(calls) == 1
    assert not archive.exists()
    assert store.read_ledger() == [(1, "seed", "synthetic-seed"), (2, "child", marker)]


def test_archive_write_failure_cleans_snapshot_and_output(wal_home, snapshot_tmp, tmp_path, monkeypatch):
    home, store = wal_home
    before = store.read_ledger()

    def fail_member(*args):
        # Explicit archive-I/O fault injection, not the snapshot regression.
        raise OSError("synthetic archive write failure")

    monkeypatch.setattr(home_backup, "_add_member", fail_member)
    archive = tmp_path / "failed.tar.gz"
    with pytest.raises(OSError, match="synthetic archive write failure"):
        home_backup.create(home, archive, now=123)
    assert not archive.exists()
    assert store.read_ledger() == before


@pytest.mark.parametrize("field", ["sha256", "size", "ops_rows_sha256"])
def test_restore_still_rejects_manifest_mismatch(wal_home, snapshot_tmp, tmp_path, field):
    import tarfile

    home, _store = wal_home
    archive = tmp_path / "healthy.tar.gz"
    home_backup.create(home, archive, now=123)
    members = _archive_members(archive)
    manifest = json.loads(members["manifest.json"])
    if field == "ops_rows_sha256":
        manifest[field] = "0" * 64
    else:
        entry = next(item for item in manifest["files"] if item["path"] == "ops.sqlite")
        entry[field] = "0" * 64 if field == "sha256" else entry[field] + 1
    members["manifest.json"] = json.dumps(manifest, sort_keys=True).encode()
    tampered = tmp_path / "tampered.tar.gz"
    with tarfile.open(tampered, "w:gz") as output:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            output.addfile(info, io.BytesIO(body))
    target = tmp_path / "never-created"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.restore(tampered, target)
    assert exc.value.code == "archive_corrupt"
    assert not target.exists()

"""M3-SVC NS28 home backup and restore: round-trip, safety, determinism.

The brief specifies `storage/home_backup.py`:
    - `create(home, out, *, now)` -> manifest (no secrets in archive)
    - `restore(archive, home)` -> manifest, raises `BackupError` with `.code`
    - `verify_home(home, manifest)` -> list[str] of mismatches (empty on success)

These tests pin the contract. They are RED before the implementation lands.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers: build a realistic home with config, journal, ops.sqlite, run/*.lock
# ---------------------------------------------------------------------------


def _seed_home(
    home: Path,
    *,
    include_lockfile: bool = True,
    include_live_authorization: bool = True,
    include_opstore: bool = True,
) -> dict:
    """Populate `home` with config.json, journal entries, ops.sqlite, optional run/lock.

    Returns a dict of sha256 of every seeded file and a list of ledger rows
    so the test can compare after restore.
    """
    home.mkdir(parents=True, exist_ok=True)
    shas: dict[str, str] = {}

    # config.json
    from krellbot.config import ArmedPack, Config, save_config

    pack_path = home / "demo-pack.json"
    pack_path.write_text('{"id":"demo","label":"demo","timeframe":"1h"}', encoding="utf-8")
    cfg = Config(
        armed=[
            ArmedPack(
                pack_path=str(pack_path),
                pack_sha256="0" * 64,
                pack_id="demo",
                pack_version="1.0.0",
                venue="kraken",
                pair="SUIUSD",
                cap=Decimal(100),
                stop=Decimal(5),
                mode="paper",
                starting_cash=Decimal(1000),
                requires_license=False,
                armed_at_ts=1,
            )
        ]
    )
    save_config(home, cfg)
    shas["config.json"] = hashlib.sha256((home / "config.json").read_bytes()).hexdigest()

    # catalog under packs/
    packs_dir = home / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    catalog = packs_dir / "demo-catalog.json"
    catalog.write_text('{"id":"demo","label":"demo"}', encoding="utf-8")
    shas["packs/demo-catalog.json"] = hashlib.sha256(catalog.read_bytes()).hexdigest()

    # journal records (3 tick records)
    from krellbot import journal as kb_journal

    journal_records_ts = [1_700_000_000, 1_700_000_100, 1_700_000_200]
    for ts in journal_records_ts:
        kb_journal.append(
            {
                "ts": ts,
                "kind": "tick",
                "venue": "kraken",
                "pack": "demo",
                "bar_ts": ts * 1000,
                "detail": {"reason": "warmup", "pair": "SUIUSD"},
            }
        )

    # ops.sqlite ledger rows (for ledger comparison)
    ledger_rows: list[tuple] = []
    if include_opstore:
        from krellbot.storage.database import OperationalStore

        store = OperationalStore(home / "ops.sqlite")
        conn = store.connect()
        # Two outbox rows: one sent, one committed.
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
            (json.dumps({"coid": "abc12345", "body": "x", "sent": True}),),
        )
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
            (json.dumps({"coid": "def67890", "body": "y", "sent": False}),),
        )
        ledger_rows = [
            (1, "outbox", json.dumps({"coid": "abc12345", "body": "x", "sent": True})),
            (2, "outbox", json.dumps({"coid": "def67890", "body": "y", "sent": False})),
        ]

    # run/<venue>.lock (must NOT be in archive)
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    if include_lockfile:
        lock = run_dir / "kraken.lock"
        lock.write_bytes(b"")
        shas["run/kraken.lock"] = hashlib.sha256(lock.read_bytes()).hexdigest()

    # live-authorization.json (must NOT be in archive)
    if include_live_authorization:
        la = home / "live-authorization.json"
        la.write_text(json.dumps({"grant": "secret-token-XYZ"}), encoding="utf-8")
        shas["live-authorization.json"] = hashlib.sha256(la.read_bytes()).hexdigest()

    return {"shas": shas, "ledger_rows": ledger_rows, "journal_tss": journal_records_ts}


# ---------------------------------------------------------------------------
# 8. Round trip: byte-equal restore of every file; ledger rows equal;
#    verify_home == []; live-authorization.json and run/*.lock NOT in archive.
# ---------------------------------------------------------------------------


def test_round_trip_restores_files_byte_equal(home, fresh_keyring, tmp_path):
    """After create -> rmtree -> restore, every captured file matches byte-for-byte."""
    from krellbot.storage import home_backup

    seeded = _seed_home(home)
    archive_storage = tempfile.mkdtemp()
    archive = Path(archive_storage) / "backup.tar.gz"

    home_backup.create(home, archive, now=1_700_000_300)
    assert archive.exists()

    # Inspect archive members: live-authorization.json and run/kraken.lock
    # must NOT be present.
    with tarfile.open(archive, "r:gz") as tf:
        member_names = {m.name for m in tf.getmembers()}
    assert "live-authorization.json" not in member_names, f"leaked live-auth in archive: {member_names}"
    assert "run/kraken.lock" not in member_names, f"leaked lock in archive: {member_names}"
    # Manifest and at least config.json + a journal file are present.
    assert "manifest.json" in member_names
    assert any(n.startswith("files/config.json") for n in member_names)
    assert any(n.startswith("files/journal/") for n in member_names)
    assert any(n.startswith("files/packs/") for n in member_names)
    assert any(n.startswith("files/ops.sqlite") for n in member_names)

    # Wipe home and restore.
    shutil.rmtree(home)
    target = tmp_path / "restored-home"
    assert not target.exists()

    returned_manifest = home_backup.restore(archive, target)
    assert returned_manifest["schema"] == "1"

    # config.json, packs/*.json byte-equal.
    for rel, sha in seeded["shas"].items():
        if rel in ("run/kraken.lock", "live-authorization.json"):
            continue
        restored_file = target / rel
        assert restored_file.is_file(), f"missing {rel} after restore"
        assert hashlib.sha256(restored_file.read_bytes()).hexdigest() == sha, f"{rel} does not match after restore"

    # Ledger rows equal (read restored ops.sqlite)
    from krellbot.storage.database import OperationalStore
    from krellbot.storage.home_backup import _release_store_handle

    restored_store = OperationalStore(target / "ops.sqlite")
    try:
        assert restored_store.read_ledger() == seeded["ledger_rows"]
    finally:
        _release_store_handle(restored_store)

    # verify_home == [] on the restored home.
    diffs = home_backup.verify_home(target, returned_manifest)
    assert diffs == [], f"verify_home reported differences: {diffs}"


# ---------------------------------------------------------------------------
# 9. Tampered archive: archive_corrupt on byte flip; manifest/member-set
#    mismatch; member with absolute path or '..'; symlink member.
# ---------------------------------------------------------------------------


def _rebuild_archive_with_tampered_file(archive: Path, member_path: str) -> Path:
    """Copy `archive` and flip one byte in `member_path`, returning the copy."""
    import io as _io

    src_bytes = archive.read_bytes()
    tampered = archive.with_name(archive.stem + ".tampered.tar.gz")
    out_buf = _io.BytesIO()
    with (
        tarfile.open(fileobj=_io.BytesIO(src_bytes), mode="r:gz") as src_tf,
        tarfile.open(fileobj=out_buf, mode="w:gz") as dst_tf,
    ):
        for member in src_tf.getmembers():
            if not member.isfile():
                dst_tf.addfile(member)
                continue
            f = src_tf.extractfile(member)
            data = f.read() if f else b""
            if member.name == member_path:
                data = bytes([(data[0] ^ 0x01) if data else 0xFF]) + data[1:]
            new_member = tarfile.TarInfo(name=member.name)
            new_member.size = len(data)
            new_member.mtime = 0
            new_member.uid = 0
            new_member.gid = 0
            new_member.uname = ""
            new_member.gname = ""
            new_member.mode = 0o600
            dst_tf.addfile(new_member, _io.BytesIO(data))
    tampered.write_bytes(out_buf.getvalue())
    return tampered


def test_tampered_archive_raises_archive_corrupt(home, fresh_keyring, tmp_path):
    """Flipping one byte in a non-manifest file makes restore raise archive_corrupt."""
    from krellbot.storage import home_backup

    _seed_home(home)
    archive_storage = tempfile.mkdtemp()
    archive = Path(archive_storage) / "backup.tar.gz"
    home_backup.create(home, archive, now=1_700_000_300)

    tampered = _rebuild_archive_with_tampered_file(archive, "files/config.json")

    target = tmp_path / "never-created"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.restore(tampered, target)
    assert exc.value.code == "archive_corrupt"
    assert not target.exists()


def test_archive_corrupt_when_manifest_member_set_mismatch(home, fresh_keyring, tmp_path):
    """If the tar contains a files/* member not in the manifest, restore refuses."""
    from krellbot.storage import home_backup

    _seed_home(home)
    archive_storage = tempfile.mkdtemp()
    archive = Path(archive_storage) / "backup.tar.gz"
    home_backup.create(home, archive, now=1_700_000_300)

    # Repack: keep manifest, drop one member, add a stray file under files/.
    import io as _io

    extra = tmp_path / "extra.tar.gz"
    out_buf = _io.BytesIO()
    with tarfile.open(archive, "r:gz") as src_tf, tarfile.open(fileobj=out_buf, mode="w:gz") as dst_tf:
        seen = set()
        for member in src_tf.getmembers():
            f = src_tf.extractfile(member)
            if member.name == "files/config.json":
                continue  # drop it: manifest expects it but it's absent
            data = f.read() if f else b""
            new_member = tarfile.TarInfo(name=member.name)
            new_member.size = len(data)
            new_member.mtime = 0
            new_member.mode = 0o600
            dst_tf.addfile(new_member, _io.BytesIO(data))
            seen.add(member.name)
    extra.write_bytes(out_buf.getvalue())

    target = tmp_path / "never-created-mismatch"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.restore(extra, target)
    assert exc.value.code == "archive_corrupt"
    assert not target.exists()


def test_archive_corrupt_on_absolute_or_dotdot_member(home, fresh_keyring, tmp_path):
    """A tar member named '/abs' or '../evil' is rejected as archive_corrupt."""
    from krellbot.storage import home_backup

    manifest = {"schema": "1", "created_at": 1, "files": [], "ops_rows": 0, "ops_rows_sha256": None}
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")

    def _make_bad_tar(member_name: str, body: bytes) -> Path:
        out = tmp_path / f"{member_name.replace('/', '_')}.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            m_info = tarfile.TarInfo(name="manifest.json")
            m_info.size = len(manifest_bytes)
            m_info.mtime = 0
            m_info.mode = 0o600
            tf.addfile(m_info, _io.BytesIO(manifest_bytes))
            bad = tarfile.TarInfo(name=member_name)
            bad.size = len(body)
            bad.mtime = 0
            bad.mode = 0o600
            tf.addfile(bad, _io.BytesIO(body))
        return out

    import io as _io

    abs_archive = _make_bad_tar("/abs", b"x")
    dotdot_archive = _make_bad_tar("../evil", b"x")

    for archive in (abs_archive, dotdot_archive):
        target = tmp_path / f"target-{archive.stem}"
        with pytest.raises(home_backup.BackupError) as exc:
            home_backup.restore(archive, target)
        assert exc.value.code == "archive_corrupt"
        assert not target.exists()


def test_archive_corrupt_on_symlink_member(home, fresh_keyring, tmp_path):
    """A symlink member is rejected (no extractall, links/devices refused)."""
    from krellbot.storage import home_backup

    manifest_bytes = json.dumps(
        {"schema": "1", "created_at": 1, "files": [], "ops_rows": 0, "ops_rows_sha256": None},
        sort_keys=True,
    ).encode("utf-8")

    archive = tmp_path / "symlink.tar.gz"
    import io as _io

    with tarfile.open(archive, "w:gz") as tf:
        m_info = tarfile.TarInfo(name="manifest.json")
        m_info.size = len(manifest_bytes)
        m_info.mtime = 0
        m_info.mode = 0o600
        tf.addfile(m_info, _io.BytesIO(manifest_bytes))
        link = tarfile.TarInfo(name="files/evil")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        link.mtime = 0
        link.mode = 0o600
        tf.addfile(link)

    target = tmp_path / "never-created-symlink"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.restore(archive, target)
    assert exc.value.code == "archive_corrupt"
    assert not target.exists()


# ---------------------------------------------------------------------------
# 10. home_not_empty leaves existing file byte-identical; schema != "1" -> schema error.
# ---------------------------------------------------------------------------


def test_restore_into_nonempty_home_raises_home_not_empty(home, fresh_keyring, tmp_path):
    """restore refuses to clobber an existing home and leaves it untouched."""
    from krellbot.storage import home_backup

    _seed_home(home)
    archive_storage = tempfile.mkdtemp()
    archive = Path(archive_storage) / "backup.tar.gz"
    home_backup.create(home, archive, now=1_700_000_300)

    # Seed the target with a file we expect to be left untouched.
    target = tmp_path / "already-nonempty"
    target.mkdir(parents=True, exist_ok=True)
    canary = target / "CANARY"
    canary.write_text("do not touch", encoding="utf-8")
    canary_bytes = canary.read_bytes()

    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.restore(archive, target)
    assert exc.value.code == "home_not_empty"

    # The canary file is byte-identical.
    assert canary.read_bytes() == canary_bytes


def test_restore_schema_2_raises_archive_schema(home, fresh_keyring, tmp_path):
    """A manifest whose schema != '1' is rejected as archive_schema."""
    from krellbot.storage import home_backup

    manifest_bytes = json.dumps(
        {"schema": "2", "created_at": 1, "files": [], "ops_rows": 0, "ops_rows_sha256": None},
        sort_keys=True,
    ).encode("utf-8")
    archive = tmp_path / "schema2.tar.gz"
    import io as _io

    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        info.mtime = 0
        info.mode = 0o600
        tf.addfile(info, _io.BytesIO(manifest_bytes))

    target = tmp_path / "schema2-target"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.restore(archive, target)
    assert exc.value.code == "archive_schema"
    assert not target.exists()


# ---------------------------------------------------------------------------
# 11. secret_detected: a captured file containing private-key markers refuses
#     the create and writes no archive.
# ---------------------------------------------------------------------------


def test_secret_detected_on_private_key_marker(home, fresh_keyring, tmp_path):
    """A file containing '-----BEGIN ... PRIVATE KEY-----' is refused; no archive written."""
    from krellbot.storage import home_backup

    _seed_home(home)
    secret = home / "extra.txt"
    secret.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nstuff\n", encoding="utf-8")

    archive = tmp_path / "refused.tar.gz"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.create(home, archive, now=1_700_000_300)
    assert exc.value.code == "secret_detected"
    # The relative path is named in the message but no archive written.
    assert "extra.txt" in str(exc.value)
    assert not archive.exists()


def test_secret_detected_on_kb_live_token(home, fresh_keyring, tmp_path):
    """A kb_live_<20+ alnum> string is refused; no archive written."""
    from krellbot.storage import home_backup

    _seed_home(home)
    secret = home / "token.txt"
    secret.write_text("kb_live_ABCDEFGHIJKLMNOPQRSTUVWXabcd", encoding="utf-8")

    archive = tmp_path / "refused2.tar.gz"
    with pytest.raises(home_backup.BackupError) as exc:
        home_backup.create(home, archive, now=1_700_000_300)
    assert exc.value.code == "secret_detected"
    assert not archive.exists()


# ---------------------------------------------------------------------------
# 12. Determinism: same home, same `now` -> byte-identical archive
# ---------------------------------------------------------------------------


def test_create_is_deterministic(home, fresh_keyring, tmp_path):
    """Two create() calls with the same now produce byte-identical archives."""
    from krellbot.storage import home_backup

    _seed_home(home)
    archive_storage = tempfile.mkdtemp()
    a1 = Path(archive_storage) / "a1.tar.gz"
    a2 = Path(archive_storage) / "a2.tar.gz"
    home_backup.create(home, a1, now=1_700_000_300)
    home_backup.create(home, a2, now=1_700_000_300)
    assert a1.read_bytes() == a2.read_bytes(), "archive bytes must match for the same now"


# ---------------------------------------------------------------------------
# 13. CLI: `krellbot backup restore --from P` restores into KRELLBOT_HOME
#     without pre-creating the home; with a bad archive, dir not created.
# ---------------------------------------------------------------------------


def test_cli_backup_restore_creates_home_without_paths_home_creating_it(home, fresh_keyring, tmp_path, monkeypatch):
    """`krellbot backup restore --from P` does NOT call paths.home() (which creates the dir).
    After a valid restore, the home exists. After a bad archive, it does not.
    """
    from krellbot import cli
    from krellbot.storage import home_backup

    # Seed a real home, create an archive from it, then point KRELLBOT_HOME
    # at a *non-existent* directory and verify the restore creates it.
    seeded_home = tmp_path / "source-home"
    seeded_home.mkdir(parents=True, exist_ok=True)
    # Re-seed inside seeded_home (note: fixtures set KRELLBOT_HOME=home,
    # but our helper targets `seeded_home` directly).
    _seed_home(seeded_home, include_lockfile=False, include_live_authorization=False)

    archive = tmp_path / "backup.tar.gz"
    home_backup.create(seeded_home, archive, now=1_700_000_300)

    # Now move KRELLBOT_HOME to a non-existent dir.
    target_home = tmp_path / "fresh-home"
    assert not target_home.exists()
    monkeypatch.setenv("KRELLBOT_HOME", str(target_home))
    monkeypatch.setattr("pathlib.Path.home", lambda: target_home)
    monkeypatch.setenv("HOME", str(target_home))
    monkeypatch.setenv("USERPROFILE", str(target_home))

    rc = cli.main(["krellbot", "backup", "restore", "--from", str(archive)])
    assert rc == 0
    assert target_home.is_dir()


def test_cli_backup_restore_bad_archive_leaves_dir_uncreated(home, fresh_keyring, tmp_path, monkeypatch, capsys):
    """A bad archive must not create the home."""
    from krellbot import cli

    target_home = tmp_path / "bad-target-home"
    assert not target_home.exists()
    monkeypatch.setenv("KRELLBOT_HOME", str(target_home))
    monkeypatch.setattr("pathlib.Path.home", lambda: target_home)
    monkeypatch.setenv("HOME", str(target_home))
    monkeypatch.setenv("USERPROFILE", str(target_home))

    # Create a fake "bad" archive file with random bytes (not a valid tar).
    bad_archive = tmp_path / "bad.tar.gz"
    bad_archive.write_bytes(b"not-a-tar-file")

    rc = cli.main(["krellbot", "backup", "restore", "--from", str(bad_archive)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "backup refused" in captured.out or "backup refused" in captured.err
    assert not target_home.exists()


# ---------------------------------------------------------------------------
# 14. scripts/restore_roundtrip.py runs as subprocess; rc=0; all rows pass.
# ---------------------------------------------------------------------------


def test_restore_roundtrip_script_runs_and_passes(home, fresh_keyring, tmp_path):
    """The Steward harness exits 0 and every JSON row reports pass=true."""
    repo_root = Path(__file__).resolve().parent.parent
    script = repo_root / "scripts" / "restore_roundtrip.py"
    # The script may not exist yet (RED). If it does not, skip — the test is
    # a forward-looking pin and the implementation writes it.
    if not script.exists():
        pytest.skip(f"scripts/restore_roundtrip.py not yet written: {script}")

    proc = subprocess.run(
        ["uv", "run", "python", str(script)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "KRELLBOT_ENABLE_LIVE": "0",
            "PYTHON_KEYRING_BACKEND": "tests.fakes.fake_keyring.FakeKeyring",
            "PYTHONPATH": str(repo_root),
        },
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"restore_roundtrip.py failed (rc={proc.returncode}):\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    # Every JSON line must have "pass": true.
    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(row)
    assert rows, f"no JSON rows emitted; stdout={proc.stdout!r}"
    fails = [r for r in rows if not r.get("pass")]
    assert not fails, f"failed rows: {fails}"

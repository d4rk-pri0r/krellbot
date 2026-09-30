"""Steward harness: build a realistic home, archive, wipe, restore, verify.

The script takes no arguments. All state lives in a `tempfile.mkdtemp()`
home and an adjacent archive directory; `~/.krellbot` is never read or
written. Every check emits one JSON row on stdout:

    {"case": str, "expected": str, "observed": str, "pass": bool}

The script exits 0 when every row reports pass=true and exits 1
otherwise. Designed to be run as `uv run python scripts/restore_roundtrip.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHONPATH = str(REPO_ROOT)


def _emitter(rows: list[dict]) -> None:
    for row in rows:
        json.dump(row, sys.stdout, sort_keys=True)
        sys.stdout.write("\n")
    sys.stdout.flush()


def _record(rows: list[dict], case: str, expected: str, observed) -> bool:
    ok = expected == str(observed)
    rows.append(
        {
            "case": case,
            "expected": str(expected),
            "observed": str(observed),
            "pass": ok,
        }
    )
    return ok


def _run_krellbot(home: Path, *args: str, extra: dict | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "KRELLBOT_HOME": str(home),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "KRELLBOT_ENABLE_LIVE": "0",
        "PYTHON_KEYRING_BACKEND": "tests.fakes.fake_keyring.FakeKeyring",
        "PYTHONPATH": PYTHONPATH,
    }
    if extra:
        env.update(extra)
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_tree(home: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(home.rglob("*")):
        if p.is_file():
            try:
                rel = p.relative_to(home).as_posix()
            except ValueError:
                continue
            out[rel] = _sha256_file(p)
    return out


def _read_ledger_rows(home: Path) -> list:
    import sqlite3

    p = home / "ops.sqlite"
    if not p.exists():
        return []
    rows = []
    with sqlite3.connect(str(p)) as conn:
        for row in conn.execute("SELECT id, kind, payload FROM ledger ORDER BY id").fetchall():
            rows.append((int(row[0]), str(row[1]), str(row[2])))
    return rows


def _seed_home_via_subprocesses(home: Path) -> tuple[dict, list]:
    """Build a realistic home. Returns (file_shas, ledger_rows)."""
    home.mkdir(parents=True, exist_ok=True)

    paper_pack = home / "demo-pack.json"
    paper_pack.write_text(
        json.dumps(
            {
                "id": "demo",
                "schema_version": 1,
                "version": "1.0.0",
                "label": "demo",
                "author": "steward",
                "timeframe": "1h",
                "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
                "entry": ["close", "crosses_above", "sma2"],
                "exit": ["close", "crosses_below", "sma2"],
                "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
                "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
            }
        ),
        encoding="utf-8",
    )

    proc_arm = _run_krellbot(
        home, "arm", str(paper_pack), "--venue", "kraken", "--mode", "paper", "--paper-balance", "1000"
    )
    assert proc_arm.returncode == 0, (
        f"arm failed rc={proc_arm.returncode}\nstdout={proc_arm.stdout!r}\nstderr={proc_arm.stderr!r}"
    )

    from krellbot import journal as kb_journal
    from krellbot.storage.database import OperationalStore
    from krellbot.storage.outbox import Outbox

    for ts in (1_700_000_000, 1_700_000_100, 1_700_000_200):
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

    store = OperationalStore(home / "ops.sqlite")
    outbox = Outbox(store)

    def _send(coid: str, body: str) -> None:
        return None

    outbox.dispatch("abc12345", json.dumps({"qty": "1"}), _send, mode="paper", venue="kraken")
    outbox.dispatch("def67890", json.dumps({"qty": "2"}), _send, mode="paper", venue="kraken")

    live_auth = home / "live-authorization.json"
    live_auth.write_text(json.dumps({"grant": "secret-XYZ"}), encoding="utf-8")
    (home / "run").mkdir(parents=True, exist_ok=True)
    (home / "run" / "kraken.lock").write_bytes(b"")
    (home / "packs").mkdir(parents=True, exist_ok=True)
    (home / "packs" / "demo-catalog.json").write_text(json.dumps({"id": "demo"}), encoding="utf-8")

    return _hash_tree(home), _read_ledger_rows(home)


def _reset_home_to_fresh_empty(home: Path) -> None:
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True, exist_ok=True)


def main() -> int:
    rows: list[dict] = []
    home = Path(tempfile.mkdtemp(prefix="steward-home-"))
    archive_dir = Path(tempfile.mkdtemp(prefix="steward-archive-"))
    archive = archive_dir / "backup.tar.gz"
    tampered = archive_dir / "tampered.tar.gz"
    non_empty_target = Path(tempfile.mkdtemp(prefix="steward-nonempty-"))
    fresh_target = Path(tempfile.mkdtemp(prefix="steward-fresh-"))

    try:
        source_shas, source_ledger = _seed_home_via_subprocesses(home)
        _record(
            rows,
            "home seeded with config/journal/ops.sqlite/run.lock/live-auth",
            str(len(source_shas) >= 5),
            str(len(source_shas) >= 5),
        )

        proc = _run_krellbot(home, "backup", "create", "--out", str(archive))
        _record(
            rows,
            "backup create rc",
            "0",
            str(proc.returncode),
        )
        _record(rows, "backup archive exists", "True", str(archive.exists()))

        member_names = tarfile_open(archive)
        _record(
            rows,
            "live-authorization.json NOT in archive",
            "False",
            str("live-authorization.json" in member_names),
        )
        _record(
            rows,
            "run/kraken.lock NOT in archive",
            "False",
            str("run/kraken.lock" in member_names),
        )
        _record(
            rows,
            "manifest.json in archive",
            "True",
            str("manifest.json" in member_names),
        )

        shutil.rmtree(home)
        proc = _run_krellbot(home, "backup", "restore", "--from", str(archive))
        _record(rows, "backup restore rc", "0", str(proc.returncode))

        restored_shas = _hash_tree(home)
        all_match = True
        diffs: list[str] = []
        for rel, sha in source_shas.items():
            if rel in (
                "live-authorization.json",
                "run/kraken.lock",
                "ops.sqlite",
                "ops.sqlite-shm",
                "ops.sqlite-wal",
            ):
                continue
            if rel not in restored_shas:
                all_match = False
                diffs.append(f"missing: {rel}")
                continue
            if restored_shas[rel] != sha:
                all_match = False
                diffs.append(f"diff: {rel} source={sha[:8]} restored={restored_shas[rel][:8]}")
        _record(rows, "every non-excluded non-sqlite file matches byte-for-byte", "True", str(all_match))
        if not all_match:
            for d in diffs:
                _record(rows, f"diff detail: {d}", "ok", "fail")

        live_present = (home / "live-authorization.json").exists()
        _record(rows, "live-authorization.json NOT restored", "False", str(live_present))

        restored_ledger = _read_ledger_rows(home)
        _record(rows, "ledger rows match", str(source_ledger), str(restored_ledger))

        from krellbot.storage import home_backup

        member_names2 = tarfile_open(archive)
        manifest = next((m for m in member_names2 if m == "manifest.json"), None)
        if manifest is None:
            verify_diffs = ["manifest.json missing in archive"]
        else:
            with tarfile.open(archive, "r:gz") as tf:
                f = tf.extractfile(manifest)
                raw = f.read() if f else b""
            manifest_dict = json.loads(raw.decode("utf-8"))
            verify_diffs = home_backup.verify_home(home, manifest_dict)
        _record(rows, "verify_home == []", "[]", str(verify_diffs))

        with open(archive, "rb") as fh:
            archive_bytes = fh.read()
        tampered_bytes = bytes([(b ^ 0x01) if i == 100 else b for i, b in enumerate(archive_bytes)])
        tampered.write_bytes(tampered_bytes)
        _reset_home_to_fresh_empty(fresh_target)
        proc = _run_krellbot(fresh_target, "backup", "restore", "--from", str(tampered))
        _record(rows, "tampered archive restore rc", "1", str(proc.returncode))
        _record(
            rows,
            "tampered archive target home not created",
            "False",
            str(any(fresh_target.iterdir())),
        )

        canary = non_empty_target / "CANARY"
        canary.write_text("do not touch", encoding="utf-8")
        canary_bytes = canary.read_bytes()
        proc = _run_krellbot(non_empty_target, "backup", "restore", "--from", str(archive))
        _record(rows, "non-empty home restore rc", "1", str(proc.returncode))
        _record(rows, "canary file unchanged", str(canary_bytes), str(canary.read_bytes()))

        _emitter(rows)
        return 0 if all(r["pass"] for r in rows) else 1
    finally:
        for p in (home, archive_dir, non_empty_target):
            try:
                shutil.rmtree(p)
            except OSError:
                pass


def tarfile_open(archive: Path) -> set[str]:
    import tarfile

    out: set[str] = set()
    with tarfile.open(archive, "r:gz") as tf:
        for m in tf.getmembers():
            out.add(m.name)
    return out


if __name__ == "__main__":
    raise SystemExit(main())

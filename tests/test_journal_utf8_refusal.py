"""Issue #340: invalid-UTF-8 journal bytes must not crash `krellbot journal`.

Real subprocess CLI tests against an isolated KRELLBOT_HOME, the fake
keyring backend, and live flags off. On the reporting revision a journal
``*.jsonl`` file containing invalid UTF-8 escaped ``_read_journal_records``
in ``krellbot/cli.py`` as a raw ``UnicodeDecodeError`` (exit 1, ~1.1KB
traceback) because only ``OSError`` was caught around the file read.

The fixed CLI skips undecodable lines exactly like torn JSON lines: valid
records in the same file and in other files still print and the exit code
stays 0. A wholly unreadable or wholly undecodable file contributes no
records. Every pre-existing behavior (healthy journal, torn JSON line,
chmod-000 file or directory, journal path as a plain file, --tail/--since/
--json flags, --json secret-field dropping) is pinned as a control.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

_BAD_LINE = b"\xff\xfe not utf-8: \x80\x81\n"


def _record_line(ts: int, note: str = "ok", **extra) -> bytes:
    detail = {"note": note}
    detail.update(extra)
    rec = {
        "ts": ts,
        "kind": "tick",
        "venue": "kraken",
        "pack": "p",
        "bar_ts": ts,
        "detail": detail,
    }
    return (json.dumps(rec) + "\n").encode("utf-8")


def _journal_dir(home: Path) -> Path:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    return journal_dir


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run `krellbot journal ...` in a subprocess with an isolated home."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["KRELLBOT_HOME"] = str(home)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_ENABLE_LIVE"] = "0"
    env["KRELLBOT_LIVE"] = "0"
    env["KRELLBOT_API_LIVE"] = "0"
    env["PYTHON_KEYRING_BACKEND"] = "tests.fakes.fake_keyring.FakeKeyring"
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "journal", *args],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=60,
    )


def _printed_records(proc: subprocess.CompletedProcess) -> list[dict]:
    return [
        json.loads(line)
        for line in proc.stdout.splitlines()
        if line.strip() and not line.strip().startswith("no journal")
    ]


def _permission_mode_enforced(home: Path) -> bool:
    """True when chmod 0o000 actually blocks reads for this process.

    Capability probe (plain assert-by-capability, no test markers): under
    uid 0 or on filesystems that ignore modes the 0000 file stays readable
    and the chmod-based controls assert the readable outcome instead.
    """
    probe = home / "mode-probe.jsonl"
    probe.write_bytes(b"{}\n")
    probe.chmod(0o000)
    try:
        probe.read_bytes()
    except OSError:
        return True
    finally:
        probe.unlink()
    return False


def test_invalid_utf8_lines_skipped_valid_records_in_same_file_print(tmp_path):
    """BASE-RED row: mixed valid/invalid UTF-8 in one file no longer exits 1."""
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-01.jsonl").write_bytes(
        _record_line(1_790_000_000, note="before") + _BAD_LINE + _record_line(1_790_000_002, note="after")
    )

    proc = _run_cli(home, "--tail", "20")

    assert proc.returncode == 0, proc.stderr
    assert "UnicodeDecodeError" not in proc.stderr
    assert "Traceback" not in proc.stderr
    notes = [r["detail"]["note"] for r in _printed_records(proc)]
    assert notes == ["before", "after"]


def test_wholly_invalid_file_alongside_healthy_file(tmp_path):
    """BASE-RED row: a wholly undecodable file contributes no records only."""
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-01.jsonl").write_bytes(_record_line(1_790_000_000, note="healthy"))
    journal_dir.joinpath("2026-02.jsonl").write_bytes(_BAD_LINE + b"\xc3\x28 more invalid\n" + b"\xff\xff\n")

    proc = _run_cli(home, "--tail", "20")

    assert proc.returncode == 0, proc.stderr
    assert "UnicodeDecodeError" not in proc.stderr
    notes = [r["detail"]["note"] for r in _printed_records(proc)]
    assert notes == ["healthy"]


def test_wholly_invalid_file_alone_reports_no_journal(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-02.jsonl").write_bytes(b"\xff\xfe\x80 bad\n")

    proc = _run_cli(home)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "no journal"


def test_healthy_journal_prints_records_rc0(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-01.jsonl").write_bytes(
        _record_line(1_790_000_000, note="one") + _record_line(1_790_000_001, note="two")
    )

    proc = _run_cli(home, "--tail", "20")

    assert proc.returncode == 0, proc.stderr
    notes = [r["detail"]["note"] for r in _printed_records(proc)]
    assert notes == ["one", "two"]


def test_torn_json_line_skipped_rc0(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-01.jsonl").write_bytes(
        _record_line(1_790_000_000, note="torn-ok")
        + b'{"ts": 1790000001, "kind": "tick", venue\n'
        + _record_line(1_790_000_002, note="after-torn")
    )

    proc = _run_cli(home, "--tail", "20")

    assert proc.returncode == 0, proc.stderr
    notes = [r["detail"]["note"] for r in _printed_records(proc)]
    assert notes == ["torn-ok", "after-torn"]


def test_chmod000_file_skipped_no_journal_when_alone(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    locked = journal_dir / "2026-01.jsonl"
    locked.write_bytes(_record_line(1_790_000_000, note="locked"))
    locked.chmod(0o000)

    proc = _run_cli(home)

    assert proc.returncode == 0, proc.stderr
    if _permission_mode_enforced(home):
        assert proc.stdout.strip() == "no journal"
    else:
        assert [r["detail"]["note"] for r in _printed_records(proc)] == ["locked"]


def test_chmod000_file_alongside_healthy_file(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    locked = journal_dir / "2026-01.jsonl"
    locked.write_bytes(_record_line(1_790_000_000, note="locked"))
    locked.chmod(0o000)
    journal_dir.joinpath("2026-02.jsonl").write_bytes(_record_line(1_790_000_001, note="healthy"))

    proc = _run_cli(home, "--tail", "20")

    assert proc.returncode == 0, proc.stderr
    notes = [r["detail"]["note"] for r in _printed_records(proc)]
    if _permission_mode_enforced(home):
        assert notes == ["healthy"]
    else:
        assert "healthy" in notes


def test_chmod000_journal_dir_rc0(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-01.jsonl").write_bytes(_record_line(1_790_000_000, note="inside"))
    journal_dir.chmod(0o000)
    try:
        proc = _run_cli(home)
    finally:
        journal_dir.chmod(0o700)

    assert proc.returncode == 0, proc.stderr
    if _permission_mode_enforced(home):
        assert proc.stdout.strip() == "no journal"
    else:
        assert [r["detail"]["note"] for r in _printed_records(proc)] == ["inside"]


def test_journal_path_as_plain_file_rc0(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "journal").write_text("not a directory\n", encoding="utf-8")

    proc = _run_cli(home)

    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "no journal"


def test_tail_flag_unchanged(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-01.jsonl").write_bytes(
        _record_line(1_790_000_000, note="first")
        + _record_line(1_790_000_001, note="second")
        + _record_line(1_790_000_002, note="third")
    )

    proc = _run_cli(home, "--tail", "2")

    assert proc.returncode == 0, proc.stderr
    notes = [r["detail"]["note"] for r in _printed_records(proc)]
    assert notes == ["second", "third"]


def test_since_flag_unchanged(tmp_path):
    now = int(time.time())
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    journal_dir.joinpath("2026-01.jsonl").write_bytes(
        _record_line(now - 3 * 3600, note="recent") + _record_line(now - 40 * 24 * 3600, note="ancient")
    )

    proc = _run_cli(home, "--since", "24h")

    assert proc.returncode == 0, proc.stderr
    notes = [r["detail"]["note"] for r in _printed_records(proc)]
    assert notes == ["recent"]


def test_json_flag_drops_secret_fields_unchanged(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    journal_dir = _journal_dir(home)
    rec = {
        "ts": 1_790_000_000,
        "kind": "tick",
        "venue": "kraken",
        "pack": "p",
        "bar_ts": 1_790_000_000,
        "license": "top-secret",
        "detail": {
            "note": "kept",
            "key": "kk",
            "secret": "ss",
            "license": "ll",
            "balance": "bb",
        },
    }
    journal_dir.joinpath("2026-01.jsonl").write_bytes((json.dumps(rec) + "\n").encode("utf-8") + _BAD_LINE)

    plain = _run_cli(home, "--tail", "20")
    assert plain.returncode == 0, plain.stderr
    raw = _printed_records(plain)
    assert len(raw) == 1
    assert raw[0]["detail"].get("key") == "kk"

    as_json = _run_cli(home, "--tail", "20", "--json")
    assert as_json.returncode == 0, as_json.stderr
    records = _printed_records(as_json)
    assert len(records) == 1
    detail = records[0]["detail"]
    assert detail == {"note": "kept"}
    assert "license" not in records[0]

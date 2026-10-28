"""Typed refusal for a missing/unreadable key file in `keys add` / `setup-kraken`.

Issue 331: ``krellbot keys add <venue> --file <path>`` and its alias
``krellbot setup-kraken <path>`` crashed with a raw ``FileNotFoundError`` /
``IsADirectoryError`` traceback and exit code 1 when the key file was missing
or unreadable. The admission edge now refuses with the same typed,
single-line stderr message and exit code 2 as the function's sibling
refusals (unknown venue, missing ``--file``, two-line file):
``No such file: <path>`` — and it refuses before any keyring write or
plaintext-ack write can happen.

The subprocess cases assert the real crash surface (process exit code and
stderr) with an isolated ``KRELLBOT_HOME``, the fake keyring backend, and all
live flags off; the in-process cases pin the negative invariants on refusal:
no keyring write and no plaintext-ack write.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the CLI in a subprocess with an isolated home and fake keyring.

    Strips inherited KRELLBOT_* values so a test cannot inherit or leak real
    credentials, forces the in-memory fake keyring (never a real OS backend),
    and keeps every live flag off.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["KRELLBOT_HOME"] = str(home)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_ENABLE_LIVE"] = "0"
    env["KRELLBOT_LIVE"] = "0"
    env["KRELLBOT_API_LIVE"] = "0"
    env["PYTHON_KEYRING_BACKEND"] = "tests.fakes.fake_keyring.FakeKeyring"
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )


def _write_keyfile(path: Path) -> None:
    path.write_text("FAKEKEY\nFAKESECRET\n", encoding="utf-8")


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    """Point KRELLBOT_HOME, HOME, USERPROFILE, and cli.STATE at tmp_path."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    import krellbot.cli as cli_mod

    cli_mod.STATE = tmp_path / ".krellbot" / "state.json"
    cli_mod.API_FILE = tmp_path / ".krellbot" / "api-base"
    return tmp_path


# --- Typed refusal: missing file (BASE RED: raw FileNotFoundError traceback, rc=1) ---


def test_keys_add_missing_file_is_typed_refusal(tmp_path):
    missing = tmp_path / "nonexistent" / "keys.csv"
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(missing))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"No such file: {missing}"
    assert "Stored" not in proc.stdout


def test_setup_kraken_missing_file_is_typed_refusal(tmp_path):
    missing = tmp_path / "nonexistent" / "keys.csv"
    proc = _run_cli(tmp_path, "setup-kraken", str(missing))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"No such file: {missing}"
    assert "Stored" not in proc.stdout


# --- Typed refusal: directory instead of file (BASE RED: raw IsADirectoryError traceback, rc=1) ---


def test_keys_add_directory_is_typed_refusal(tmp_path):
    adir = tmp_path / "adir"
    adir.mkdir()
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(adir))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"No such file: {adir}"
    assert "Stored" not in proc.stdout


def test_setup_kraken_directory_is_typed_refusal(tmp_path):
    adir = tmp_path / "adir"
    adir.mkdir()
    proc = _run_cli(tmp_path, "setup-kraken", str(adir))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"No such file: {adir}"
    assert "Stored" not in proc.stdout


def test_keys_add_unreadable_file_is_typed_refusal(isolated_home, fresh_keyring, capsys, monkeypatch):
    """PermissionError at the key-file read boundary is the same typed refusal.

    The CLI chmod-000 shape is uid-dependent (root ignores permission bits),
    so the unreadable-file edge is pinned in process at the exact file-read
    boundary cmd_keys_add uses: the read raises PermissionError, and the
    admission refuses with the same exit code 2 and one-line stderr message
    the CLI-level cases assert. It runs identically under any uid, root
    included, because no permission bit is ever relied upon.
    """
    import krellbot.cli as cli_mod

    keyfile = isolated_home / "keys.csv"
    _write_keyfile(keyfile)

    real_read_text = Path.read_text

    def unreadable_read_text(self, *args, **kwargs):
        if self == keyfile:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable_read_text)

    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(keyfile)])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"No such file: {keyfile}"
    assert "Stored" not in captured.out
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None
    assert not (isolated_home / "run" / "plaintext-ack").exists()


# --- Healthy two-line control stays byte-identical ---


def test_keys_add_healthy_two_line_file_still_stores(tmp_path):
    keyfile = tmp_path / "keys.csv"
    _write_keyfile(keyfile)
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(keyfile))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "Stored in fake keyring FakeKeyring. Not sent to krellbot.dev."
    assert proc.stderr == ""


def test_setup_kraken_healthy_two_line_file_still_stores(tmp_path):
    keyfile = tmp_path / "keys.csv"
    _write_keyfile(keyfile)
    proc = _run_cli(tmp_path, "setup-kraken", str(keyfile))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "Stored in fake keyring FakeKeyring. Not sent to krellbot.dev."
    assert proc.stderr == ""


# --- Sibling admission refusals stay unchanged ---


def test_keys_add_unknown_venue_still_refused_first(tmp_path):
    missing = tmp_path / "nonexistent" / "keys.csv"
    proc = _run_cli(tmp_path, "keys", "add", "ftx", "--file", str(missing))
    assert proc.returncode == 2
    assert proc.stderr.strip() == "Unknown venue: ftx"


def test_keys_add_missing_flag_still_refused(tmp_path):
    proc = _run_cli(tmp_path, "keys", "add", "kraken")
    assert proc.returncode == 2
    assert proc.stderr.strip() == "--file is required"


def test_keys_add_two_line_file_rule_still_refused(tmp_path):
    keyfile = tmp_path / "keys.csv"
    keyfile.write_text("FAKEKEY\n", encoding="utf-8")
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(keyfile))
    assert proc.returncode == 2
    assert proc.stderr.strip() == "Key file needs two lines: API key, then secret."


# --- Negative invariants on refusal: no keyring write, no plaintext-ack write ---


def test_refusal_writes_neither_keyring_nor_plaintext_ack(isolated_home, fresh_keyring, capsys):
    """A missing file with --i-understand-plaintext must not leave the ack behind."""
    import krellbot.cli as cli_mod

    missing = isolated_home / "nonexistent" / "keys.csv"
    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(missing), "--i-understand-plaintext"])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"No such file: {missing}"
    assert "Stored" not in captured.out
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None
    assert not (isolated_home / "run" / "plaintext-ack").exists()


def test_directory_refusal_writes_neither_keyring_nor_plaintext_ack(isolated_home, fresh_keyring, capsys):
    adir = isolated_home / "adir"
    adir.mkdir()
    import krellbot.cli as cli_mod

    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(adir), "--i-understand-plaintext"])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"No such file: {adir}"
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None
    assert not (isolated_home / "run" / "plaintext-ack").exists()

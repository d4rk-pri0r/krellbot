"""Typed refusal for a non-UTF-8 key file in `keys add` / `setup-kraken`.

Issue 346: ``krellbot keys add <venue> --file <path>`` and its alias
``krellbot setup-kraken <path>`` crashed with a raw ``UnicodeDecodeError``
traceback and exit code 1 when the key file contained bytes that are not
valid UTF-8 (for example a Latin-1/binary file saved over the intended
two-line UTF-8 key file). The read boundary now refuses with the same
typed, single-line stderr message and exit code 2 as the function's
sibling admission refusals (#331): ``Key file is not valid UTF-8: <path>``
— and it refuses before ``ensure_layout()``, so no keyring write and no
plaintext-ack write can happen.

The subprocess cases assert the real crash surface (process exit code and
stderr) with an isolated ``KRELLBOT_HOME``, the fake keyring backend, and
all live flags off; the in-process cases pin the negative invariants on
refusal: no keyring write, no plaintext-ack write, and no layout creation.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

INVALID_UTF8_KEYFILE = b"kraken-key\xff\xfe\nkraken-secret\n"


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the CLI in a subprocess with an isolated home and fake keyring.

    Strips inherited KRELLBOT_* values so a test cannot inherit or leak real
    credentials, forces the in-memory fake keyring (never a real OS backend),
    and keeps every live flag off. stderr is decoded with errors="replace"
    because the BASE crash surface is a traceback that may carry the raw
    undecodable bytes.
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
        errors="replace",
        cwd=str(REPO_ROOT),
        env=env,
        timeout=30,
    )


def _write_invalid_keyfile(path: Path) -> None:
    path.write_bytes(INVALID_UTF8_KEYFILE)


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


# --- Typed refusal: non-UTF-8 key file (BASE RED: raw UnicodeDecodeError traceback, rc=1) ---


def test_keys_add_invalid_utf8_is_typed_refusal(tmp_path):
    keyfile = tmp_path / "keys.csv"
    _write_invalid_keyfile(keyfile)
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(keyfile))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"Key file is not valid UTF-8: {keyfile}"
    assert "Traceback" not in proc.stderr
    assert "Stored" not in proc.stdout


def test_setup_kraken_invalid_utf8_is_typed_refusal(tmp_path):
    keyfile = tmp_path / "keys.csv"
    _write_invalid_keyfile(keyfile)
    proc = _run_cli(tmp_path, "setup-kraken", str(keyfile))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"Key file is not valid UTF-8: {keyfile}"
    assert "Traceback" not in proc.stderr
    assert "Stored" not in proc.stdout


def test_keys_add_invalid_utf8_secret_line_is_typed_refusal(tmp_path):
    """A decode error anywhere in the file (here: second line) is the same typed refusal."""
    keyfile = tmp_path / "keys.csv"
    keyfile.write_bytes(b"FAKEKEY\nFAKESECRET\xc3\x28\n")
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(keyfile))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"Key file is not valid UTF-8: {keyfile}"
    assert "Traceback" not in proc.stderr
    assert "Stored" not in proc.stdout


# --- Healthy two-line control stays byte-identical ---


def test_keys_add_healthy_two_line_file_still_stores(tmp_path):
    keyfile = tmp_path / "keys.csv"
    keyfile.write_text("FAKEKEY\nFAKESECRET\n", encoding="utf-8")
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(keyfile))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "Stored in fake keyring FakeKeyring. Not sent to krellbot.dev."
    assert proc.stderr == ""


def test_setup_kraken_healthy_two_line_file_still_stores(tmp_path):
    keyfile = tmp_path / "keys.csv"
    keyfile.write_text("FAKEKEY\nFAKESECRET\n", encoding="utf-8")
    proc = _run_cli(tmp_path, "setup-kraken", str(keyfile))
    assert proc.returncode == 0
    assert proc.stdout.strip() == "Stored in fake keyring FakeKeyring. Not sent to krellbot.dev."
    assert proc.stderr == ""


# --- Sibling admission refusals stay unchanged (byte-identical controls) ---


def test_keys_add_unknown_venue_still_refused_first(tmp_path):
    missing = tmp_path / "nonexistent" / "keys.csv"
    proc = _run_cli(tmp_path, "keys", "add", "bogusvenue", "--file", str(missing))
    assert proc.returncode == 2
    assert proc.stderr.strip() == "Unknown venue: bogusvenue"


def test_keys_add_missing_flag_still_refused(tmp_path):
    proc = _run_cli(tmp_path, "keys", "add", "kraken")
    assert proc.returncode == 2
    assert proc.stderr.strip() == "--file is required"


def test_keys_add_missing_file_still_typed_refusal(tmp_path):
    missing = tmp_path / "nonexistent" / "keys.csv"
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(missing))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"No such file: {missing}"


def test_setup_kraken_missing_file_still_typed_refusal(tmp_path):
    missing = tmp_path / "nonexistent" / "keys.csv"
    proc = _run_cli(tmp_path, "setup-kraken", str(missing))
    assert proc.returncode == 2
    assert proc.stderr.strip() == f"No such file: {missing}"


def test_keys_add_two_line_file_rule_still_refused(tmp_path):
    keyfile = tmp_path / "keys.csv"
    keyfile.write_text("FAKEKEY\n", encoding="utf-8")
    proc = _run_cli(tmp_path, "keys", "add", "kraken", "--file", str(keyfile))
    assert proc.returncode == 2
    assert proc.stderr.strip() == "Key file needs two lines: API key, then secret."


# --- Negative invariants on refusal: no keyring write, no plaintext-ack write, no layout ---


def test_utf8_refusal_writes_neither_keyring_nor_plaintext_ack(isolated_home, fresh_keyring, capsys):
    """A non-UTF-8 file with --i-understand-plaintext must not leave the ack behind."""
    import krellbot.cli as cli_mod

    keyfile = isolated_home / "keys.csv"
    _write_invalid_keyfile(keyfile)
    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(keyfile), "--i-understand-plaintext"])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"Key file is not valid UTF-8: {keyfile}"
    assert "Stored" not in captured.out
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None
    assert not (isolated_home / "run" / "plaintext-ack").exists()


def test_setup_kraken_utf8_refusal_writes_neither_keyring_nor_plaintext_ack(isolated_home, fresh_keyring, capsys):
    """The setup-kraken alias shares the refusal and its negative invariants."""
    import krellbot.cli as cli_mod

    keyfile = isolated_home / "keys.csv"
    _write_invalid_keyfile(keyfile)
    rc = cli_mod.main(["krellbot", "setup-kraken", str(keyfile)])
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"Key file is not valid UTF-8: {keyfile}"
    assert "Stored" not in captured.out
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None
    assert not (isolated_home / "run" / "plaintext-ack").exists()


def test_utf8_refusal_runs_before_ensure_layout(isolated_home, fresh_keyring, capsys):
    """The refusal happens before kb_paths.ensure_layout(), so the krellbot
    state tree is not created for an undecodable key file."""
    import krellbot.cli as cli_mod
    import krellbot.paths as kb_paths

    keyfile = isolated_home / "keys.csv"
    _write_invalid_keyfile(keyfile)

    def fail_layout():
        raise AssertionError("ensure_layout must not run for a non-UTF-8 key file")

    original_layout = kb_paths.ensure_layout
    kb_paths.ensure_layout = fail_layout
    try:
        rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(keyfile)])
    finally:
        kb_paths.ensure_layout = original_layout
    assert rc == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == f"Key file is not valid UTF-8: {keyfile}"

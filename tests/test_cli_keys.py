"""Tests for the keys-add command and the setup-kraken alias."""

import json
from pathlib import Path

import pytest


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


def _write_keyfile(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_keys_add_does_not_require_license(isolated_home, fresh_keyring, monkeypatch, capsys):
    import krellbot.cli as cli_mod

    keyfile = isolated_home / "k.txt"
    _write_keyfile(keyfile, "FAKEKEY", "FAKESECRET")

    called = {"urlopen": 0}

    def boom(*args, **kwargs):
        called["urlopen"] += 1
        raise AssertionError("network not allowed in keys add")

    monkeypatch.setattr("urllib.request.urlopen", boom)

    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(keyfile)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Not sent to krellbot.dev." in captured.out
    assert called["urlopen"] == 0
    assert fresh_keyring.get_password("krellbot:kraken", "key") == "FAKEKEY"
    assert fresh_keyring.get_password("krellbot:kraken", "secret") == "FAKESECRET"


def test_delete_file_zeros_then_unlinks(isolated_home, fresh_keyring, monkeypatch, capsys):
    """After --delete-file, the file is zeroed then unlinked."""
    import krellbot.cli as cli_mod

    keyfile = isolated_home / "k.txt"
    payload = "FAKEKEY\nFAKESECRET\n"
    keyfile.write_text(payload, encoding="utf-8")
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("network not allowed")),
    )

    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(keyfile), "--delete-file"])
    assert rc == 0
    assert not keyfile.exists()
    assert fresh_keyring.get_password("krellbot:kraken", "key") == "FAKEKEY"
    assert fresh_keyring.get_password("krellbot:kraken", "secret") == "FAKESECRET"


def test_store_failure_does_not_delete_file(isolated_home, fresh_keyring, monkeypatch, capsys):
    """Null backend + --delete-file: file remains, exit is non-zero."""
    import keyring as _keyring
    import keyring.backends.null as _null

    import krellbot.cli as cli_mod

    _keyring.set_keyring(_null.Keyring())
    keyfile = isolated_home / "k.txt"
    keyfile.write_text("FAKEKEY\nFAKESECRET\n", encoding="utf-8")

    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(keyfile), "--delete-file"])
    assert rc != 0
    assert keyfile.exists()
    assert "FAKEKEY" in keyfile.read_text(encoding="utf-8")


def test_legacy_state_keys_migrated_and_removed(isolated_home, fresh_keyring, monkeypatch, capsys):
    """`krellbot list` must migrate state.json's kraken_key/secret to the keyring and remove them from disk."""
    import krellbot.cli as cli_mod

    state_path = isolated_home / "state.json"
    state_path.write_text(
        json.dumps({"kraken_key": "FAKEKEY", "kraken_secret": "FAKESECRET", "license_key": "L"}),
        encoding="utf-8",
    )

    rc = cli_mod.main(["krellbot", "list"])
    assert rc == 0
    assert fresh_keyring.get_password("krellbot:kraken", "key") == "FAKEKEY"
    assert fresh_keyring.get_password("krellbot:kraken", "secret") == "FAKESECRET"
    on_disk = state_path.read_text(encoding="utf-8")
    assert "FAKESECRET" not in on_disk
    assert "kraken_key" not in on_disk
    assert "kraken_secret" not in on_disk
    assert "license_key" in on_disk


def test_keys_add_bad_file_lines_exits_2(isolated_home, fresh_keyring, monkeypatch, capsys):
    import krellbot.cli as cli_mod

    keyfile = isolated_home / "k.txt"
    keyfile.write_text("FAKEKEY\n", encoding="utf-8")

    rc = cli_mod.main(["krellbot", "keys", "add", "kraken", "--file", str(keyfile)])
    assert rc == 2
    captured = capsys.readouterr()
    assert "Key file needs two lines" in captured.err


def test_setup_kraken_alias_calls_keys_add(isolated_home, fresh_keyring, monkeypatch, capsys):
    import krellbot.cli as cli_mod

    keyfile = isolated_home / "k.txt"
    keyfile.write_text("FAKEKEY\nFAKESECRET\n", encoding="utf-8")

    rc = cli_mod.main(["krellbot", "setup-kraken", str(keyfile)])
    assert rc == 0
    assert fresh_keyring.get_password("krellbot:kraken", "key") == "FAKEKEY"
    assert fresh_keyring.get_password("krellbot:kraken", "secret") == "FAKESECRET"
    captured = capsys.readouterr()
    assert "krellbot setup <key>" not in captured.out

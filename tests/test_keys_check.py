"""`keys check` reads the stored credential and probes the venue. Exit codes
must follow the brief: 0 = trade-only, 1 = withdraw-capable or no key.

`cmd_keys_check` is called directly; we never go through `cli.py`.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    """Mirror the existing `isolated_home` pattern from test_cli_keys.py."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


def test_keys_check_kraken_trade_only_exits_zero(isolated_home, fresh_keyring, monkeypatch, capsys):
    """A trade-only Kraken key prints `trade on, withdraw off` and exits 0."""
    from krellbot import cli_keys
    from krellbot.venues.base import KeyPerms

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", "FAKESECRET")

    # Probe the same way cmd_keys_check does and return a trade-only result.
    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyPerms(can_trade=True, can_withdraw=False),
    )

    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trade on" in out
    assert "withdraw off" in out
    assert "FAKEKEY" not in capsys.readouterr().err
    assert "FAKESECRET" not in capsys.readouterr().err


def test_keys_check_kraken_withdraw_capable_exits_one(isolated_home, fresh_keyring, monkeypatch, capsys):
    """A key that returns a withdraw-capable `KeyPerms` must exit 1."""
    from krellbot import cli_keys
    from krellbot.venues.base import KeyPerms

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", "FAKESECRET")

    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyPerms(can_trade=True, can_withdraw=True),
    )

    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAKESECRET" not in captured.out
    assert "FAKESECRET" not in captured.err
    assert "FAKEKEY" not in captured.out
    assert "FAKEKEY" not in captured.err


def test_keys_check_no_stored_key_exits_one(isolated_home, fresh_keyring, capsys):
    """No key in storage → exit 1."""
    from krellbot import cli_keys

    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1


def test_keys_check_unknown_venue_exits_two(isolated_home, capsys):
    from krellbot import cli_keys

    rc = cli_keys.cmd_keys_check(["gemini"])
    assert rc == 2
    captured = capsys.readouterr()
    assert "usage" in captured.err

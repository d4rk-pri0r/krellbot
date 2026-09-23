"""Credential storage: env beats keyring beats a permission-checked file."""

import json
import os
import sys
from pathlib import Path

import pytest
from fakes.fake_keyring import FakeKeyring


def test_secrets_env_beats_keyring(fresh_keyring, tmp_path, monkeypatch):
    from krellbot import secrets

    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    fresh_keyring.set_password("krellbot:kraken", "key", "KEYRING_KEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", "KEYRING_SECRET")
    monkeypatch.setenv("KRELLBOT_KRAKEN_KEY", "ENV_KEY")
    monkeypatch.setenv("KRELLBOT_KRAKEN_SECRET", "ENV_SECRET")
    assert secrets.get("kraken") == ("ENV_KEY", "ENV_SECRET")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only mode check")
def test_secrets_file_refused_when_world_readable(fresh_keyring, tmp_path, monkeypatch):
    from krellbot import secrets

    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.delenv("KRELLBOT_KRAKEN_KEY", raising=False)
    monkeypatch.delenv("KRELLBOT_KRAKEN_SECRET", raising=False)
    keyfile = tmp_path / "k.txt"
    keyfile.write_text("FAKEKEY\nFAKESECRET\n", encoding="utf-8")
    os.chmod(keyfile, 0o644)
    monkeypatch.setenv("KRELLBOT_KRAKEN_KEYFILE", str(keyfile))
    with pytest.raises(PermissionError):
        secrets.get("kraken")


def test_partial_env_does_not_fall_through(fresh_keyring, tmp_path, monkeypatch):
    from krellbot import secrets

    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.delenv("KRELLBOT_KRAKEN_SECRET", raising=False)
    monkeypatch.setenv("KRELLBOT_KRAKEN_KEY", "ENV_KEY")
    with pytest.raises(ValueError) as ei:
        secrets.get("kraken")
    assert "must both be set" in str(ei.value)
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None


def test_null_backend_fails_loudly(fresh_keyring, tmp_path, monkeypatch):
    from krellbot import secrets

    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    import keyring as _keyring
    import keyring.backends.null as _null

    _keyring.set_keyring(_null.Keyring())
    with pytest.raises(RuntimeError) as ei:
        secrets.store("kraken", "FAKEKEY", "FAKESECRET")
    msg = str(ei.value)
    assert "FAKESECRET" not in msg
    assert "FAKEKEY" not in msg


def test_keyring_readback_mismatch_raises(fresh_keyring, tmp_path, monkeypatch):
    """A custom backend whose set_password is a no-op must surface as RuntimeError."""

    class NoopKeyring(FakeKeyring):
        def set_password(self, service, username, password):
            return None

    import keyring as _keyring

    _keyring.set_keyring(NoopKeyring())
    from krellbot import secrets

    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    with pytest.raises(RuntimeError) as ei:
        secrets.store("kraken", "FAKEKEY", "FAKESECRET")
    msg = str(ei.value)
    assert "FAKESECRET" not in msg
    assert "FAKEKEY" not in msg


def test_migrate_ignores_real_home_when_krellbot_home_set(fresh_keyring, tmp_path, monkeypatch):
    """KRELLBOT_HOME with no state.json must not read Path.home()/.krellbot."""
    from krellbot import secrets

    work = tmp_path / "work"
    realish = tmp_path / "realhome"
    work.mkdir()
    sentinel = realish / ".krellbot" / "state.json"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text(
        json.dumps({"kraken_key": "REALKEY", "kraken_secret": "REALSECRET", "license_key": "L"}),
        encoding="utf-8",
    )
    before = sentinel.read_bytes()
    monkeypatch.setenv("KRELLBOT_HOME", str(work))
    monkeypatch.setattr(Path, "home", lambda: realish)
    assert secrets.migrate_legacy() is False
    assert sentinel.read_bytes() == before
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None

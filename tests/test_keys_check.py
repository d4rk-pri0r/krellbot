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
    from krellbot.venues.base import KeyProbeOutcome, KeyProbeResult

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", "FAKESECRET")

    # Probe the same way cmd_keys_check does and return a trade-only result.
    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyProbeResult(
            outcome=KeyProbeOutcome.TRADE_ONLY,
            reason="trade on, withdraw off",
        ),
    )

    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trade on" in out
    assert "withdraw off" in out
    assert "FAKEKEY" not in capsys.readouterr().err
    assert "FAKESECRET" not in capsys.readouterr().err


def test_keys_check_kraken_withdraw_capable_exits_one(isolated_home, fresh_keyring, monkeypatch, capsys):
    """A key that returns a withdraw-capable `KeyProbeResult` must exit 1."""
    from krellbot import cli_keys
    from krellbot.venues.base import KeyProbeOutcome, KeyProbeResult

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", "FAKESECRET")

    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyProbeResult(
            outcome=KeyProbeOutcome.WITHDRAW_CAPABLE,
            reason="venue confirmed withdraw rights; refused",
        ),
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


# --- live `_probe` integration: end-to-end through the real KrakenVenue ---


# Real-shape base64 secret keeps the venue's HMAC sign path happy when we
# exercise the live venue in-process. The value is fake; only its shape
# matters.
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


def test_keys_check_kraken_trade_only_live_probe_returns_trade_only(isolated_home, fresh_keyring, capsys):
    """End-to-end: stored key, GetApiKeyInfo reports trade-only → trade-only."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys, secrets
    from krellbot.venues.base import KeyProbeOutcome

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    transport = FakeKrakenTransport(
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
            ]
        },
    )

    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.TRADE_ONLY
    assert result.is_trade_only is True


def test_keys_check_kraken_withdraw_capable_live_probe_returns_withdraw(isolated_home, fresh_keyring):
    """End-to-end: GetApiKeyInfo reports withdraw-funds → `_probe` reports `withdraw_capable`.

    `_probe` converts a typed `KeyProbeError` into a `KeyProbeResult`; the
    engine never sees `WithdrawCapableError` weaken.
    """
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys, secrets
    from krellbot.venues.base import KeyProbeOutcome

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    transport = FakeKrakenTransport(
        api_key_info={"permissions": ["query-funds", "withdraw-funds"]},
    )

    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.WITHDRAW_CAPABLE
    assert result.is_trade_only is False


def test_keys_check_kraken_read_only_live_probe_returns_trade_off(isolated_home, fresh_keyring):
    """End-to-end: read-only key cannot trade → `_probe` reports `trade_off`."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys, secrets
    from krellbot.venues.base import KeyProbeOutcome

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    transport = FakeKrakenTransport(
        api_key_info={"permissions": ["query-funds", "query-open-trades"]},
    )

    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.TRADE_OFF
    assert result.is_trade_only is False


def test_keys_check_kraken_end_to_end_trade_only_exits_zero(isolated_home, fresh_keyring, monkeypatch, capsys):
    """End-to-end CLI run with a real trade-only key: `cmd_keys_check` exits 0."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    transport = FakeKrakenTransport(
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
            ]
        },
    )

    real_probe = cli_keys._probe

    def monkeypatched_probe(venue, key, secret):
        return real_probe(venue, key, secret, transport=transport)

    monkeypatch.setattr(cli_keys, "_probe", monkeypatched_probe)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trade on" in out
    assert "withdraw off" in out


def test_keys_check_kraken_end_to_end_withdraw_capable_exits_one(isolated_home, fresh_keyring, monkeypatch, capsys):
    """End-to-end CLI run with a withdraw-capable key: `cmd_keys_check` exits 1."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys

    fresh_keyring.set_password("krellbot:kraken", "key", "FAKEKEY")
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)

    transport = FakeKrakenTransport(
        api_key_info={"permissions": ["query-funds", "withdraw-funds"]},
    )

    real_probe = cli_keys._probe

    def monkeypatched_probe(venue, key, secret):
        return real_probe(venue, key, secret, transport=transport)

    monkeypatch.setattr(cli_keys, "_probe", monkeypatched_probe)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1

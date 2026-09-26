"""Typed key-probe taxonomy for `krellbot keys check`.

The previous `_probe` swallowed every `WithdrawCapableError` into a single
`KeyPerms(can_trade=False, can_withdraw=True)`, so the CLI reported
"withdraw on or trade off" for invalid keys, shape errors, read-only
keys, and actually-withdraw-capable keys without distinguishing them.
These tests pin a small typed taxonomy:

- `KeyProbeResult.outcome` is one of:
    `trade_only` (canonical success, CLI exits 0)
    `withdraw_capable` (venue confirmed withdraw rights; refusal)
    `trade_off` (no required trade permission present; refusal)
    `invalid` (key cannot be verified: invalid / permission denied; refusal)
    `malformed` (venue response shape unknown; refusal)
    `unreachable` (network/transport failure; refusal)
- `KeyProbeResult.reason` is a short, secret-free string the CLI prints on
  stderr so the user can tell refusal reasons apart.
- `KeyProbeResult.is_trade_only_outcome` is the storage gate; only
  `outcome == "trade_only"` returns `True`. The instance property
  `result.is_trade_only` is the same gate on a result.

The probe never echoes the API key, secret, or any raw `apiKey` field
from the venue response on stderr.
"""

from __future__ import annotations

import pytest

from krellbot.venues.base import KeyProbeOutcome, KeyProbeResult

KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    """Mirror the `isolated_home` fixture used in `test_keys_check.py`.

    `krellbot.secrets` reads `KRELLBOT_HOME` and `HOME`; pointing them at
    `tmp_path` keeps the keyring's secrets from leaking across tests.
    """
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


# --- taxonomy shape ---------------------------------------------------------


def test_key_probe_result_trade_only_is_only_path_to_storage() -> None:
    """Only `trade_only` outcome is true through `is_trade_only_outcome`.

    A future wizard must refuse to store on anything else.
    """
    assert KeyProbeResult.is_trade_only_outcome(KeyProbeOutcome.TRADE_ONLY) is True
    for outcome in (
        KeyProbeOutcome.WITHDRAW_CAPABLE,
        KeyProbeOutcome.TRADE_OFF,
        KeyProbeOutcome.INVALID,
        KeyProbeOutcome.MALFORMED,
        KeyProbeOutcome.UNREACHABLE,
    ):
        assert KeyProbeResult.is_trade_only_outcome(outcome) is False, outcome


def test_key_probe_result_reason_is_secret_free() -> None:
    """Built-in reason strings must never contain key/secret material."""
    secret_text = "FAKESECRET-TO-NEVER-ECHO"
    sentinel = "REDACTED-APIKEY-DO-NOT-LOG"
    for outcome, reason in (
        (KeyProbeOutcome.WITHDRAW_CAPABLE, "venue confirmed withdraw rights"),
        (KeyProbeOutcome.TRADE_OFF, "missing required trade permission"),
        (KeyProbeOutcome.INVALID, "key cannot be verified (invalid or permission denied)"),
        (KeyProbeOutcome.MALFORMED, "venue response shape unknown"),
        (KeyProbeOutcome.UNREACHABLE, "transport unreachable; cannot verify"),
    ):
        result = KeyProbeResult(outcome=outcome, reason=reason)
        assert secret_text not in result.reason
        assert sentinel not in result.reason


# --- CLI integration via `_probe` (end-to-end through KrakenVenue) ---------


def _kraken_perm_transport(perms):  # type: ignore[no-untyped-def]
    from fakes.fake_kraken import FakeKrakenTransport

    return FakeKrakenTransport(api_key_info={"permissions": perms})


def _store(fresh_keyring, key: str = "FAKEKEY", secret: str = KRAKEN_TEST_SECRET_B64) -> None:
    fresh_keyring.set_password("krellbot:kraken", "key", key)
    fresh_keyring.set_password("krellbot:kraken", "secret", secret)


def test_probe_withdraw_capable_typed_as_withdraw_capable(isolated_home, fresh_keyring) -> None:
    """A key that venue confirms can withdraw → `withdraw_capable` outcome."""
    from krellbot import cli_keys, secrets

    _store(fresh_keyring)
    transport = _kraken_perm_transport(["query-funds", "withdraw-funds"])
    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.WITHDRAW_CAPABLE
    assert result.is_trade_only is False
    assert "FAKEKEY" not in result.reason
    assert "FAKESECRET" not in result.reason


def test_probe_invalid_key_typed_as_invalid_not_withdraw(isolated_home, fresh_keyring) -> None:
    """An invalid/permission-denied key → `invalid` outcome (NOT `withdraw_capable`).

    Previously this was indistinguishable from `withdraw_capable`. Now it
    has its own refusal reason so the user knows the key was unverifiable,
    not confirmed to withdraw.
    """
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys, secrets

    _store(fresh_keyring)
    # `api_key_info=None` on the fake → permission denied (`EAPI:Invalid key`)
    transport = FakeKrakenTransport(api_key_info=None)
    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.INVALID
    assert result.is_trade_only is False
    assert "FAKEKEY" not in result.reason
    assert "FAKESECRET" not in result.reason


def test_probe_malformed_response_typed_as_malformed(isolated_home, fresh_keyring) -> None:
    """A venue response with non-dict `result` → `malformed` outcome."""
    from krellbot import cli_keys, secrets

    _store(fresh_keyring)
    transport = _kraken_perm_transport([])
    # Reconfigure fake to return a non-dict result.
    transport._api_key_info = "not-a-dict"  # type: ignore[attr-defined]
    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.MALFORMED
    assert result.is_trade_only is False


def test_probe_read_only_key_typed_as_trade_off(isolated_home, fresh_keyring) -> None:
    """A read-only key (no `modify-trades`/`close-trades`) → `trade_off` outcome."""
    from krellbot import cli_keys, secrets

    _store(fresh_keyring)
    transport = _kraken_perm_transport(["query-funds", "query-open-trades", "query-closed-trades"])
    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.TRADE_OFF
    assert result.is_trade_only is False


def test_probe_trade_only_with_documented_extras_accepted(isolated_home, fresh_keyring) -> None:
    """A documented trade-only set with harmless read extras → `trade_only`."""
    from krellbot import cli_keys, secrets

    _store(fresh_keyring)
    transport = _kraken_perm_transport(
        [
            "query-funds",
            "query-open-trades",
            "query-closed-trades",
            "query-ledger",
            "export-data",
            "create-ws-token",
            "query-affiliate-participants",
            "modify-trades",
            "close-trades",
        ]
    )
    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.TRADE_ONLY
    assert result.is_trade_only is True


def test_probe_unknown_extra_permission_refused(isolated_home, fresh_keyring) -> None:
    """An unrecognized permission (e.g. `transfer-funds`) → refusal.

    Fails closed on unknown extras so a future Kraken-added permission
    cannot silently turn a verified-trade-only key into a partially
    trusted one.
    """
    from krellbot import cli_keys, secrets

    _store(fresh_keyring)
    transport = _kraken_perm_transport(
        [
            "query-funds",
            "query-open-trades",
            "modify-trades",
            "close-trades",
            "transfer-funds",  # not in the harmless-read extras whitelist
        ]
    )
    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome == KeyProbeOutcome.TRADE_OFF
    assert result.is_trade_only is False
    # Reason names the unknown permission so the reviewer can pinpoint it.
    assert "transfer-funds" in result.reason


# --- CLI surface: exit codes and reason printing (reviewer Q2) ------------


@pytest.mark.parametrize(
    "permissions",
    [
        ["query-funds", "withdraw-funds"],  # withdraw_capable
        ["query-funds", "query-open-trades"],  # trade_off (no modify/close)
    ],
)
def test_cmd_keys_check_refusal_prints_reason_on_stderr(
    isolated_home, fresh_keyring, monkeypatch, capsys, permissions
) -> None:
    """Refusal lines must include a reason the user can act on (Q2)."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys

    _store(fresh_keyring)
    transport = FakeKrakenTransport(api_key_info={"permissions": permissions})

    real_probe = cli_keys._probe

    def probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        return real_probe(*args, **kwargs, transport=transport)

    monkeypatch.setattr(cli_keys, "_probe", probe)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "FAKEKEY" not in err
    assert "FAKESECRET" not in err
    # No "withdraw on or trade off" ambiguity line.
    assert "withdraw on or trade off" not in err


def test_cmd_keys_check_invalid_key_says_invalid_not_network_required(
    isolated_home, fresh_keyring, monkeypatch, capsys
) -> None:
    """An invalid key must NOT be reported as 'network required'."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys

    _store(fresh_keyring)
    transport = FakeKrakenTransport(api_key_info=None)

    real_probe = cli_keys._probe

    def probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        return real_probe(*args, **kwargs, transport=transport)

    monkeypatch.setattr(cli_keys, "_probe", probe)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "network required" not in err
    assert "FAKEKEY" not in err
    assert "FAKESECRET" not in err


def test_cmd_keys_check_unreachable_does_use_network_required(
    isolated_home, fresh_keyring, monkeypatch, capsys
) -> None:
    """A real transport failure still surfaces as `unreachable` (refusal).

    The exact legacy wording ("network required") is preserved in the
    `unreachable` reason so any user scripts or CI gates grepping for
    the phrase still work.
    """
    from krellbot import cli_keys

    class _BoomTransport:
        def post(self, url, form, headers):  # type: ignore[no-untyped-def]
            raise OSError("dns failure")

        def get(self, url, headers=None):  # type: ignore[no-untyped-def]
            raise OSError("dns failure")

    _store(fresh_keyring)
    real_probe = cli_keys._probe

    def probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        return real_probe(*args, **kwargs, transport=_BoomTransport())

    monkeypatch.setattr(cli_keys, "_probe", probe)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "network required" in err
    assert "FAKEKEY" not in err
    assert "FAKESECRET" not in err


def test_cmd_keys_check_trade_only_keeps_canonical_line(isolated_home, fresh_keyring, monkeypatch, capsys) -> None:
    """The public success line 'trade on, withdraw off' is unchanged."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys

    _store(fresh_keyring)
    transport = FakeKrakenTransport(
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
            ]
        }
    )

    real_probe = cli_keys._probe

    def probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        return real_probe(*args, **kwargs, transport=transport)

    monkeypatch.setattr(cli_keys, "_probe", probe)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trade on, withdraw off" in out

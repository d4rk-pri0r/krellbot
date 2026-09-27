"""Round-2 regression tests for the arm-site diagnostic (review N1) and the
safe reason text used in `_probe` / `cmd_keys_check` (review N2).

Background
----------
Round 1 (commit ``3f081a6``) introduced a typed ``KeyProbeResult`` taxonomy
and routed the arm site through ``result.to_key_perms()``. The reviewer
flagged two follow-ups:

N1. ``to_key_perms()`` collapsed every refusal to
    ``(can_trade=False, can_withdraw=False)`` so ``arm_pack`` could not
    distinguish a confirmed ``withdraw_capable`` key (which should report
    ``"withdraw is on; trade-only keys refused"``) from a ``trade_off``
    or ``invalid`` key (which should report ``"trade is off"``).

N2. ``_reason_for(exc)`` returned ``str(exc).strip()`` verbatim, relying
    on convention + ``sanitize.register_secret`` to redact secrets. Any
    subclass that embeds credential material leaks it to stderr. We
    require fixed, safe per-outcome messages for ALL refusal paths so
    the helper does not depend on what the venue happens to put in the
    exception message.

These tests pin both behaviors with malicious permission tokens / typed
errors that would leak under the old code.
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes.fake_kraken import FakeKrakenTransport

from krellbot.venues.base import (
    KeyPerms,
    KeyProbeOutcome,
    KeyProbeResult,
)

KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="

# A clearly-malicious permission token that MUST NOT appear anywhere user-facing
# if the probe sees it: it could be a venue-supplied string with embedded
# credentials. The fix must refuse the key without echoing it.
MALICIOUS_PERMISSION_TOKEN = "FAKEKEY-DO-NOT-LOG-ME-99999"

# Sentinel strings used to simulate a leaky subclass that puts credentials
# in its exception message. These MUST NEVER reach the CLI stderr.
LEAKY_KEY_SENTINEL = "FAKEKEY-DO-NOT-LOG-ME"
LEAKY_SECRET_SENTINEL = "FAKESECRET-DO-NOT-LOG-ME"


# -----------------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------------


def _write_pack(home: Path, *, pack_id: str = "arm-r2", pair: str = "SUIUSD") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Arm R2",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _store(fresh_keyring) -> None:
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET_B64)


# =============================================================================
# N1: arm-site diagnostic specificity via to_key_perms()
# =============================================================================


def test_to_key_perms_withdraw_capable_signals_withdraw_on() -> None:
    """`to_key_perms()` must surface `can_withdraw=True` for `withdraw_capable`.

    Without this, `arm_pack` cannot distinguish a confirmed-withdraw key
    (which should report "withdraw is on; trade-only keys refused") from
    any other refusal. The reviewer ruling: arm-path diagnostic must
    retain the distinction.
    """
    result = KeyProbeResult(
        outcome=KeyProbeOutcome.WITHDRAW_CAPABLE,
        reason="venue confirmed withdraw rights; refused",
    )
    perms = result.to_key_perms()
    assert isinstance(perms, KeyPerms)
    assert perms.can_trade is False
    assert perms.can_withdraw is True, (
        "to_key_perms() must preserve `can_withdraw=True` for withdraw_capable "
        "so arm_pack reports the withdraw-on refusal, not 'trade is off'."
    )


def test_to_key_perms_trade_off_signals_neither() -> None:
    """`trade_off` outcome stays `(False, False)` — neither flag set."""
    result = KeyProbeResult(
        outcome=KeyProbeOutcome.TRADE_OFF,
        reason="no required trade permission; refused",
    )
    perms = result.to_key_perms()
    assert perms.can_trade is False
    assert perms.can_withdraw is False


def test_to_key_perms_invalid_signals_neither() -> None:
    """`invalid` outcome stays `(False, False)`."""
    result = KeyProbeResult(
        outcome=KeyProbeOutcome.INVALID,
        reason="key cannot be verified; refused",
    )
    perms = result.to_key_perms()
    assert perms.can_trade is False
    assert perms.can_withdraw is False


def test_to_key_perms_malformed_signals_neither() -> None:
    """`malformed` outcome stays `(False, False)`."""
    result = KeyProbeResult(
        outcome=KeyProbeOutcome.MALFORMED,
        reason="venue response shape unknown; refused",
    )
    perms = result.to_key_perms()
    assert perms.can_trade is False
    assert perms.can_withdraw is False


def test_to_key_perms_unreachable_signals_neither() -> None:
    """`unreachable` outcome stays `(False, False)`."""
    result = KeyProbeResult(
        outcome=KeyProbeOutcome.UNREACHABLE,
        reason="transport unreachable; cannot verify",
    )
    perms = result.to_key_perms()
    assert perms.can_trade is False
    assert perms.can_withdraw is False


def test_to_key_perms_trade_only_unchanged() -> None:
    """Public success path: `trade_only` keeps `can_trade=True, can_withdraw=False`."""
    result = KeyProbeResult(
        outcome=KeyProbeOutcome.TRADE_ONLY,
        reason="trade on, withdraw off",
    )
    perms = result.to_key_perms()
    assert perms.can_trade is True
    assert perms.can_withdraw is False


def test_arm_pack_reports_withdraw_on_for_withdraw_capable_key(home, fresh_keyring, monkeypatch, capsys) -> None:
    """End-to-end: a `withdraw_capable` probe makes `arm_pack` say 'withdraw is on'.

    This is the N1 regression — before the fix the arm site collapsed
    everything to 'trade is off'. The user's diagnostic must surface the
    actual reason the key was refused.
    """
    from krellbot import cli_keys
    from krellbot.cli import cmd_arm

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    _store(fresh_keyring)
    pack_path = _write_pack(home)

    # cli.py imports `from krellbot.cli_keys import _probe` inside `cmd_arm`,
    # so monkeypatching `cli_keys._probe` routes the arm site through our
    # typed result.
    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyProbeResult(
            outcome=KeyProbeOutcome.WITHDRAW_CAPABLE,
            reason="venue confirmed withdraw rights; refused",
        ),
    )

    rc = cmd_arm([str(pack_path), "--venue", "kraken", "--mode", "live"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "withdraw is on" in out, f"expected 'withdraw is on' in arm diagnostic, got: {out!r}"
    assert "trade is off" not in out, f"withdraw_capable must NOT collapse to 'trade is off'; got: {out!r}"


def test_arm_pack_reports_trade_off_for_trade_off_key(home, fresh_keyring, monkeypatch, capsys) -> None:
    """End-to-end: a `trade_off` probe makes `arm_pack` say 'trade is off'."""
    from krellbot import cli_keys
    from krellbot.cli import cmd_arm

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    _store(fresh_keyring)
    pack_path = _write_pack(home)

    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyProbeResult(
            outcome=KeyProbeOutcome.TRADE_OFF,
            reason="no required trade permission; refused",
        ),
    )

    rc = cmd_arm([str(pack_path), "--venue", "kraken", "--mode", "live"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "trade is off" in out
    assert "withdraw is on" not in out


def test_arm_pack_reports_trade_off_for_invalid_key(home, fresh_keyring, monkeypatch, capsys) -> None:
    """End-to-end: an `invalid` probe also says 'trade is off' (not 'withdraw is on')."""
    from krellbot import cli_keys
    from krellbot.cli import cmd_arm

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    _store(fresh_keyring)
    pack_path = _write_pack(home)

    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyProbeResult(
            outcome=KeyProbeOutcome.INVALID,
            reason="key cannot be verified; refused",
        ),
    )

    rc = cmd_arm([str(pack_path), "--venue", "kraken", "--mode", "live"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "trade is off" in out
    assert "withdraw is on" not in out


# =============================================================================
# N2: fixed safe per-outcome messages for ALL refusal paths
# =============================================================================


def test_reason_for_keyunverifiableerror_omits_leaky_message() -> None:
    """A `KeyUnverifiableError` whose message embeds fake credentials MUST NOT
    leak those credentials through `_reason_for`. The reason must be a
    fixed safe string keyed on the exception type, not the message body.
    """
    from krellbot.cli_keys import _reason_for
    from krellbot.venues.base import KeyUnverifiableError

    leaky = KeyUnverifiableError(
        f"GetApiKeyInfo denied; raw api_key={LEAKY_KEY_SENTINEL}; secret={LEAKY_SECRET_SENTINEL}"
    )
    reason = _reason_for(leaky)
    assert LEAKY_KEY_SENTINEL not in reason
    assert LEAKY_SECRET_SENTINEL not in reason


def test_reason_for_keymalformederror_omits_leaky_message() -> None:
    """A `KeyMalformedError` whose message embeds fake credentials MUST NOT leak."""
    from krellbot.cli_keys import _reason_for
    from krellbot.venues.base import KeyMalformedError

    leaky = KeyMalformedError(f"shape unknown; echoed api_key={LEAKY_KEY_SENTINEL}")
    reason = _reason_for(leaky)
    assert LEAKY_KEY_SENTINEL not in reason


def test_reason_for_keytradeofferror_omits_leaky_message() -> None:
    """A `KeyTradeOffError` whose message embeds fake credentials MUST NOT leak."""
    from krellbot.cli_keys import _reason_for
    from krellbot.venues.base import KeyTradeOffError

    leaky = KeyTradeOffError(f"missing required trade permissions; key={LEAKY_KEY_SENTINEL}")
    reason = _reason_for(leaky)
    assert LEAKY_KEY_SENTINEL not in reason


def test_reason_for_kraken_unknown_permission_error_omits_malicious_token() -> None:
    """A `KrakenKeyUnknownPermissionError` whose message includes a malicious
    permission token MUST NOT echo that token in the reason.
    """
    from krellbot.cli_keys import _reason_for
    from krellbot.venues.base import KrakenKeyUnknownPermissionError

    leaky = KrakenKeyUnknownPermissionError(f"grants unrecognized permissions: ['{MALICIOUS_PERMISSION_TOKEN}']")
    reason = _reason_for(leaky)
    assert MALICIOUS_PERMISSION_TOKEN not in reason, (
        f"unknown-permission reason must not echo the unrecognized token; got {reason!r}"
    )


def test_reason_for_arbitrary_typed_subclass_uses_safe_message() -> None:
    """An arbitrary typed subclass (not in the registered set) with credential
    material in its message MUST NOT leak. The reason must be a fixed safe
    string derived from the exception type, NOT the message body.
    """
    from krellbot.cli_keys import _reason_for
    from krellbot.venues.base import WithdrawCapableError

    class _VendorSpecificError(WithdrawCapableError):
        """A subclass a third-party venue adapter might add."""

    leaky = _VendorSpecificError(f"vendor: key={LEAKY_KEY_SENTINEL} secret={LEAKY_SECRET_SENTINEL}")
    reason = _reason_for(leaky)
    assert LEAKY_KEY_SENTINEL not in reason
    assert LEAKY_SECRET_SENTINEL not in reason


def test_probe_unknown_permission_does_not_echo_malicious_token(home, fresh_keyring) -> None:
    """A venue response carrying a malicious permission token MUST be refused
    WITHOUT echoing the token in `KeyProbeResult.reason`. This is the
    defense-in-depth test: even if the venue's exception message names
    the token, the CLI does not propagate it.
    """
    from krellbot import cli_keys, secrets

    _store(fresh_keyring)

    # Build a fake transport whose permission set contains the malicious token.
    transport = FakeKrakenTransport(
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
                MALICIOUS_PERMISSION_TOKEN,
            ]
        }
    )

    api_key, api_secret = secrets.get("kraken")
    result = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert result.outcome != KeyProbeOutcome.TRADE_ONLY
    assert MALICIOUS_PERMISSION_TOKEN not in result.reason, (
        f"unknown-permission refusal must not echo the unrecognized token; got reason {result.reason!r}"
    )


def test_cmd_keys_check_does_not_echo_malicious_permission_token(home, fresh_keyring, capsys) -> None:
    """A malicious permission token in the venue response MUST NOT reach
    the CLI stderr under any refusal outcome. The CLI stderr is the
    user-facing surface and the last line of defense.

    We let the real `_probe` run end-to-end against a fake transport
    whose permission set contains the malicious token. The Kraken venue
    raises a `KrakenKeyUnknownPermissionError` whose message names the
    token; `_probe` must translate that into a fixed safe reason that
    does NOT echo the token. We then drive `cmd_keys_check` against
    that already-safe result to confirm the CLI surface stays clean.
    """
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot import cli_keys, secrets

    _store(fresh_keyring)
    transport = FakeKrakenTransport(
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
                MALICIOUS_PERMISSION_TOKEN,
            ]
        }
    )
    api_key, api_secret = secrets.get("kraken")
    probe = cli_keys._probe("kraken", api_key, api_secret, transport=transport)
    assert MALICIOUS_PERMISSION_TOKEN not in probe.reason, (
        f"unknown-permission refusal must not echo the unrecognized token; got reason {probe.reason!r}"
    )
    assert probe.reason.strip(), "expected a non-empty refusal reason"

    # Drive the CLI surface with the safe typed result.
    original_probe = cli_keys._probe
    cli_keys._probe = lambda *_a, **_kw: probe
    try:
        rc = cli_keys.cmd_keys_check(["kraken"])
    finally:
        cli_keys._probe = original_probe
    assert rc == 1
    err = capsys.readouterr().err
    assert MALICIOUS_PERMISSION_TOKEN not in err


def test_cmd_keys_check_leaky_typed_exception_does_not_leak_to_stderr(home, fresh_keyring, monkeypatch, capsys) -> None:
    """If a future maintainer adds a typed subclass whose message embeds
    credentials, `_probe` must not propagate that to the CLI stderr.
    The fix decouples the printed reason from `str(exc)`.

    We patch the venue's `check_key` so it raises a leaky
    `KeyUnverifiableError`. The real `_probe` runs end-to-end; the helper
    must translate the typed exception into a safe fixed reason. We then
    drive `cmd_keys_check` against a `_probe` shim that returns that
    `KeyProbeResult` and assert the user-facing stderr is also safe.
    """
    from krellbot import cli_keys, secrets
    from krellbot.venues import kraken as kraken_mod
    from krellbot.venues.base import KeyUnverifiableError

    _store(fresh_keyring)

    real_check_key = kraken_mod.KrakenVenue.check_key

    def leaky_check_key(self):
        raise KeyUnverifiableError(f"GetApiKeyInfo denied; raw api_key={LEAKY_KEY_SENTINEL}")

    monkeypatch.setattr(kraken_mod.KrakenVenue, "check_key", leaky_check_key)
    api_key, api_secret = secrets.get("kraken")
    probe_result = cli_keys._probe("kraken", api_key, api_secret)
    assert LEAKY_KEY_SENTINEL not in probe_result.reason, (
        f"a leaky typed exception must not leak to KeyProbeResult.reason; got {probe_result.reason!r}"
    )
    # Sanity: the user still gets a useful refusal message (not blank).
    assert probe_result.reason.strip(), "expected a non-empty refusal reason"
    # Sanity: the leaky exception class is still surfaced via outcome.
    assert probe_result.outcome != "trade_only"

    # Now exercise the CLI surface: drive cmd_keys_check against a
    # `_probe` shim that returns the already-safe result.
    monkeypatch.setattr(cli_keys, "_probe", lambda *a, **kw: probe_result)
    # Restore the real check_key so any other call site isn't affected.
    monkeypatch.setattr(kraken_mod.KrakenVenue, "check_key", real_check_key)

    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1
    err = capsys.readouterr().err
    assert LEAKY_KEY_SENTINEL not in err
    assert err.strip(), "expected a non-empty refusal reason on stderr"


def test_probe_bare_withdraw_capable_error_does_not_leak_message(home, fresh_keyring) -> None:
    """A bare `WithdrawCapableError` raised by a future venue adapter MUST
    NOT propagate its message into the CLI's user-facing reason. The
    bare-class catch in `_probe` routes through `_reason_for`, which is
    keyed on the exception type and returns a fixed safe string.

    This is the defense-in-depth test for the legacy path where the
    bare-class branch used to do `_result(WITHDRAW_CAPABLE, str(exc))`.
    """
    from krellbot import cli_keys, secrets
    from krellbot.venues import kraken as kraken_mod
    from krellbot.venues.base import KeyProbeOutcome, WithdrawCapableError

    _store(fresh_keyring)

    def leaky_check_key(self):
        raise WithdrawCapableError(f"kraken key grants forbidden permissions; api_key={LEAKY_KEY_SENTINEL}")

    real = kraken_mod.KrakenVenue.check_key
    kraken_mod.KrakenVenue.check_key = leaky_check_key
    try:
        api_key, api_secret = secrets.get("kraken")
        result = cli_keys._probe("kraken", api_key, api_secret)
    finally:
        kraken_mod.KrakenVenue.check_key = real

    assert result.outcome == KeyProbeOutcome.WITHDRAW_CAPABLE
    assert LEAKY_KEY_SENTINEL not in result.reason, (
        f"bare WithdrawCapableError message must not leak to KeyProbeResult.reason; got {result.reason!r}"
    )
    assert result.reason.strip(), "expected a non-empty refusal reason"


# =============================================================================
# Public success output and prior taxonomy — must remain unchanged
# =============================================================================


def test_trade_only_outcome_keeps_canonical_success_line(home, fresh_keyring, monkeypatch, capsys) -> None:
    """The public success line 'trade on, withdraw off' MUST be unchanged."""
    from krellbot import cli_keys
    from krellbot.venues.base import KeyProbeResult

    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyProbeResult(
            outcome=KeyProbeOutcome.TRADE_ONLY,
            reason="trade on, withdraw off",
        ),
    )

    _store(fresh_keyring)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trade on" in out
    assert "withdraw off" in out


def test_unreachable_preserves_legacy_network_required_wording(home, fresh_keyring, monkeypatch, capsys) -> None:
    """The legacy 'network required' wording on `unreachable` is preserved
    so any user scripts grepping for it keep working.
    """
    from krellbot import cli_keys
    from krellbot.venues.base import KeyProbeResult

    monkeypatch.setattr(
        cli_keys,
        "_probe",
        lambda venue, key, secret: KeyProbeResult(
            outcome=KeyProbeOutcome.UNREACHABLE,
            reason="OSError; check skipped (network required)",
        ),
    )

    _store(fresh_keyring)
    rc = cli_keys.cmd_keys_check(["kraken"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "network required" in err


def test_unknown_outcome_is_refused_not_trade_only() -> None:
    """Any outcome outside the closed taxonomy is a refusal by construction.

    The storage gate (`is_trade_only_outcome`) is the single source of
    truth; tests pin that behavior to defend against a future maintainer
    accidentally widening the taxonomy without updating the gate.
    """
    from krellbot.venues.base import KeyProbeResult

    for outcome in (
        KeyProbeOutcome.WITHDRAW_CAPABLE,
        KeyProbeOutcome.TRADE_OFF,
        KeyProbeOutcome.INVALID,
        KeyProbeOutcome.MALFORMED,
        KeyProbeOutcome.UNREACHABLE,
    ):
        assert KeyProbeResult.is_trade_only_outcome(outcome) is False

    # Trade-only stays the only allowed path.
    assert KeyProbeResult.is_trade_only_outcome(KeyProbeOutcome.TRADE_ONLY) is True

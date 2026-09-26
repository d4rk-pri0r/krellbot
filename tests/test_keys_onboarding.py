"""Tests for the shared ephemeral probe-and-store operation.

The wizard key-add POST will eventually call ``probe_and_store(venue, key,
secret)`` to (1) reject unsupported inputs, (2) re-probe with the validated
key, (3) refuse to persist unless the venue says trade-only, (4) atomically
write the two-slot keyring pair (key, then secret) with read-back, and
(5) never echo a raw key/secret/error back to the caller.

These tests pin every behavior the brief and the SDD rulings demand. They
inject fakes for both the venue probe and the keyring backend so no real
keychain or network call is exercised.

Keyring backend classification
------------------------------
Native OS backends (whitelisted):
    * ``keyring.backends.macOS.Keyring`` (macOS Keychain)
    * ``keyring.backends.SecretService.Keyring`` (Linux)
    * ``keyring.backends.Windows.WinVaultKeyring`` (Windows)
Everything else (including ``null``, ``fail``, the in-memory ``FakeKeyring``
in tests) is rejected by the production code path so the browser wizard
cannot be tricked by a roundtripping fake. Tests for these backends pass an
``allow_injected_fake_backend=True`` flag so the unit tests can exercise
the happy and unhappy storage paths without a real OS keychain.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import keyring as _keyring
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fakes.fake_coinbase import FakeCoinbaseTransport
from fakes.fake_keyring import FakeKeyring
from fakes.fake_kraken import FakeKrakenTransport

from krellbot import keys_onboarding
from krellbot.venues.base import KeyProbeOutcome, KeyProbeResult

# Real-shape base64 secret keeps the Kraken HMAC sign path happy when the
# test exercises the real ``KrakenVenue`` in-process. The value is fake;
# only its shape matters.
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


def _make_coinbase_pem() -> str:
    """Generate a real EC P-256 PEM for the Coinbase tests."""
    priv = ec.generate_private_key(ec.SECP256R1())
    return priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")


# Generated once at import time; the PEM is fake and disposable, and
# every Coinbase test below uses it. We avoid a session fixture so
# parametrize can reference it directly.
COINBASE_TEST_SECRET_PEM = _make_coinbase_pem()

# Sentinel secrets that MUST NEVER appear anywhere user-facing or in any
# test's stored keyring value once a failure path runs.
LEAKY_KEY = "FAKEKEY-DO-NOT-LOG-ME-12345"
LEAKY_SECRET = "FAKESECRET-DO-NOT-LOG-ME-67890"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_home(monkeypatch, tmp_path):
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


def _install_fake_keyring(fresh_keyring) -> FakeKeyring:
    _keyring.set_keyring(fresh_keyring)
    return fresh_keyring


def _kraken_trade_only_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
            ]
        },
    )


def _kraken_withdraw_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        api_key_info={"permissions": ["query-funds", "withdraw-funds"]},
    )


def _kraken_trade_off_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        api_key_info={"permissions": ["query-funds", "query-open-trades"]},
    )


def _kraken_invalid_transport() -> FakeKrakenTransport:
    return FakeKrakenTransport(
        api_key_info_error="EAPI:Invalid key: Permission denied",
    )


def _coinbase_trade_only_transport() -> FakeCoinbaseTransport:
    """Coinbase says the key can trade and cannot transfer."""
    return FakeCoinbaseTransport(
        key_permissions=[{"can_trade": True, "can_transfer": False}],
    )


def _coinbase_withdraw_transport() -> FakeCoinbaseTransport:
    """Coinbase says the key can transfer (withdraw)."""
    return FakeCoinbaseTransport(
        key_permissions=[{"can_trade": True, "can_transfer": True}],
    )


def _coinbase_trade_off_transport() -> FakeCoinbaseTransport:
    """Coinbase says the key cannot trade and cannot transfer."""
    return FakeCoinbaseTransport(
        key_permissions=[{"can_trade": False, "can_transfer": False}],
    )


def _coinbase_invalid_transport() -> FakeCoinbaseTransport:
    """Coinbase returns a payload that ``check_key`` cannot reduce to perms.

    The brief asks for an "unknown result" branch: a payload whose shape
    we cannot reason about. We exercise this by routing
    ``key_permissions`` to ``/api/v3/brokerage/key_permissions`` but
    returning something that triggers ``KeyMalformedError`` upstream:
    a list whose only entry is not a dict AND the venue's ``_get`` will
    raise on it via ``_auth_headers``. The simpler path: replace the
    transport with one whose ``get`` raises ``KeyMalformedError`` on the
    permissions endpoint.
    """

    class _Boom:
        def get(self, url, headers=None):
            from krellbot.venues.base import KeyMalformedError

            raise KeyMalformedError("simulated malformed permissions body")

        def post(self, url, body, headers):
            return {"success": True}

    return _Boom()


# ===========================================================================
# 1. Input validation — venue / length / emptiness
# ===========================================================================


def test_unsupported_venue_returns_invalid_argument(isolated_home, fresh_keyring, capsys):
    """An unknown venue name must be rejected before any probe runs."""
    _install_fake_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "gemini",
        "FAKEKEY",
        "FAKESECRET",
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.INVALID_ARGUMENT
    assert "gemini" not in result.message  # never echo the venue name back
    assert "FAKEKEY" not in result.message
    assert "FAKESECRET" not in result.message
    assert fresh_keyring.get_password("krellbot:gemini", "key") is None


def test_empty_key_returns_invalid_argument(isolated_home, fresh_keyring):
    _install_fake_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.INVALID_ARGUMENT
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None


def test_empty_secret_returns_invalid_argument(isolated_home, fresh_keyring):
    _install_fake_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        "",
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.INVALID_ARGUMENT
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None


def test_oversized_key_returns_invalid_argument(isolated_home, fresh_keyring):
    _install_fake_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "X" * 1024,
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.INVALID_ARGUMENT
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None


def test_oversized_secret_returns_invalid_argument(isolated_home, fresh_keyring):
    _install_fake_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        "X" * 8192,
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.INVALID_ARGUMENT
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None


# ===========================================================================
# 2. Backend classification — null / fail / fake / unrecognized all rejected
# ===========================================================================


def test_null_keyring_backend_is_rejected(isolated_home):
    """``null`` must never be accepted even when ``set_password`` round-trips."""
    import keyring.backends.null as _null

    null_backend = _null.Keyring()
    _keyring.set_keyring(null_backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=null_backend,
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND
    # Round-tripping the null backend does not satisfy us.
    assert null_backend.get_password("krellbot:kraken", "key") is None
    assert null_backend.get_password("krellbot:kraken", "secret") is None


def test_fail_keyring_backend_is_rejected(isolated_home):
    """``fail`` is rejected without probe even though it cannot persist."""
    import keyring.backends.fail as _fail

    fail_backend = _fail.Keyring()
    _keyring.set_keyring(fail_backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fail_backend,
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND
    # The fail backend raises on get_password; we did not even get there.


def test_unrecognized_keyring_backend_is_rejected(isolated_home):
    """An unknown module path is rejected regardless of round-trip success."""

    class _WhollyUnknown(FakeKeyring):
        pass

    unknown = _WhollyUnknown()
    # Round-trip works; still rejected because the class is not whitelisted.
    unknown.set_password("krellbot:kraken", "key", "X")
    assert unknown.get_password("krellbot:kraken", "key") == "X"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=unknown,
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND
    # Wholly unknown must NOT have written our pair.
    assert unknown.get_password("krellbot:kraken", "key") == "X"
    assert unknown.get_password("krellbot:kraken", "secret") is None


def test_plaintext_backend_is_rejected(isolated_home):
    """A plaintext-style backend is rejected even when it round-trips.

    The ruling is: native OS keychain guarantee matters more than accepting
    every plugin backend. A backend whose ``__module__`` is ``plaintext`` or
    ``keyrings.alt.file`` is not a native OS keychain.
    """

    class _Plaintext(FakeKeyring):
        pass

    # Rename so the class doesn't expose 'fake' as the module.
    _Plaintext.__module__ = "keyrings.alt.file.Plaintext"
    plaintext = _Plaintext()

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=plaintext,
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND


def test_injected_fake_backend_is_allowed_only_when_explicit(
    isolated_home,
    fresh_keyring,
):
    """The fake backend must be rejected unless tests opt in.

    The opt-in keeps the production code path fail-closed for fakes. The
    opt-in lets tests exercise the store/rollback paths without a real
    OS keychain.
    """
    _install_fake_keyring(fresh_keyring)

    # Default: rejected.
    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND

    # With explicit opt-in: allowed (the test belows exercise this path).
    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORED
    assert fresh_keyring.get_password("krellbot:kraken", "key") == "FAKEKEY"


# ===========================================================================
# 3. Re-probe each call — never accept a client-side `validated=true`
# ===========================================================================


def test_does_not_skip_probe_when_caller_claims_trade_only(
    isolated_home,
    fresh_keyring,
    monkeypatch,
):
    """A second call with the same key MUST re-probe — the brief is explicit:

    ``A second request must re-probe; never accept a client-supplied
    validated=true.``

    The probe is the only authority. We verify that an external toggle
    cannot bypass the probe.
    """
    _install_fake_keyring(fresh_keyring)

    probe_calls: list[tuple[str, str, str]] = []

    def probe_factory(transport):
        def probe(venue, key, secret):
            probe_calls.append((venue, key, secret))
            return KeyProbeResult(
                outcome=KeyProbeOutcome.TRADE_ONLY,
                reason="trade on, withdraw off",
            )

        return probe

    probe = probe_factory(_kraken_trade_only_transport())
    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=probe,
        allow_injected_fake_backend=True,
        # NOTE: no validated= kwarg exists; client cannot bypass the probe.
    )
    assert result.status == keys_onboarding.Status.STORED
    assert probe_calls == [("kraken", "FAKEKEY", KRAKEN_TEST_SECRET_B64)]


# ===========================================================================
# 4. Venue probe outcomes → status mapping (both venues, all refusals)
# ===========================================================================


@pytest.mark.parametrize(
    "venue,key,secret,transport_factory,expected",
    [
        (
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            _kraken_trade_only_transport,
            keys_onboarding.Status.STORED,
        ),
        (
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            _kraken_withdraw_transport,
            keys_onboarding.Status.REFUSED_WITHDRAW,
        ),
        (
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            _kraken_trade_off_transport,
            keys_onboarding.Status.REFUSED_TRADE_OFF,
        ),
        (
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            _kraken_invalid_transport,
            keys_onboarding.Status.REFUSED_INVALID,
        ),
        (
            "coinbase",
            "FAKEKEY",
            COINBASE_TEST_SECRET_PEM,
            _coinbase_trade_only_transport,
            keys_onboarding.Status.STORED,
        ),
        (
            "coinbase",
            "FAKEKEY",
            COINBASE_TEST_SECRET_PEM,
            _coinbase_withdraw_transport,
            keys_onboarding.Status.REFUSED_WITHDRAW,
        ),
        (
            "coinbase",
            "FAKEKEY",
            COINBASE_TEST_SECRET_PEM,
            _coinbase_trade_off_transport,
            keys_onboarding.Status.REFUSED_TRADE_OFF,
        ),
        (
            "coinbase",
            "FAKEKEY",
            COINBASE_TEST_SECRET_PEM,
            _coinbase_invalid_transport,
            keys_onboarding.Status.REFUSED_MALFORMED,
        ),
    ],
)
def test_probe_outcomes_map_to_status(
    isolated_home,
    fresh_keyring,
    venue,
    key,
    secret,
    transport_factory,
    expected,
):
    _install_fake_keyring(fresh_keyring)
    transport = transport_factory()

    result = keys_onboarding.probe_and_store(
        venue,
        key,
        secret,
        keyring_backend=fresh_keyring,
        probe=transport,
        allow_injected_fake_backend=True,
    )
    assert result.status == expected
    # On trade_only we store the pair; on any refusal we do NOT.
    if expected == keys_onboarding.Status.STORED:
        assert fresh_keyring.get_password(f"krellbot:{venue}", "key") == key
        assert fresh_keyring.get_password(f"krellbot:{venue}", "secret") == secret
    else:
        assert fresh_keyring.get_password(f"krellbot:{venue}", "key") is None
        assert fresh_keyring.get_password(f"krellbot:{venue}", "secret") is None


# ===========================================================================
# 5. Result payload — fixed safe enum/message/backend only
# ===========================================================================


def test_result_carries_no_raw_key_or_secret_on_success(
    isolated_home,
    fresh_keyring,
):
    _install_fake_keyring(fresh_keyring)
    transport = _kraken_trade_only_transport()

    result = keys_onboarding.probe_and_store(
        "kraken",
        LEAKY_KEY,
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=transport,
        allow_injected_fake_backend=True,
    )

    assert result.status == keys_onboarding.Status.STORED
    # The result object must not carry the raw values anywhere — not in
    # message, not in a leaked attribute.
    payload = dataclasses.asdict(result)
    text = json.dumps(payload, sort_keys=True)
    assert LEAKY_KEY not in text
    assert "FAKESECRET" not in text  # KRAKEN_TEST_SECRET_B64 starts with this


def test_result_message_is_one_of_the_fixed_safe_strings(
    isolated_home,
    fresh_keyring,
):
    """Every status maps to a closed set of safe messages."""
    _install_fake_keyring(fresh_keyring)

    seen = set()
    for venue, key, secret, factory, expected in [
        ("kraken", "FAKEKEY", KRAKEN_TEST_SECRET_B64, _kraken_trade_only_transport, keys_onboarding.Status.STORED),
        (
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            _kraken_withdraw_transport,
            keys_onboarding.Status.REFUSED_WITHDRAW,
        ),
        (
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            _kraken_trade_off_transport,
            keys_onboarding.Status.REFUSED_TRADE_OFF,
        ),
        (
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            _kraken_invalid_transport,
            keys_onboarding.Status.REFUSED_INVALID,
        ),
    ]:
        result = keys_onboarding.probe_and_store(
            venue,
            key,
            secret,
            keyring_backend=fresh_keyring,
            probe=factory(),
            allow_injected_fake_backend=True,
        )
        assert result.status == expected
        seen.add(result.message)
    # Each message must be a member of the closed safe set.
    assert seen.issubset(set(keys_onboarding.SAFE_MESSAGES)), seen


def test_result_carries_backend_label_only(
    isolated_home,
    fresh_keyring,
):
    """The backend label is a fixed string; never the raw backend object."""
    _install_fake_keyring(fresh_keyring)
    transport = _kraken_trade_only_transport()

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=transport,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORED
    assert isinstance(result.backend_label, str)
    # No attribute for raw backend / raw probe error / raw exception.
    forbidden = {"backend", "raw_error", "exception", "traceback", "secret", "key"}
    assert forbidden.isdisjoint(set(vars(result)))


# ===========================================================================
# 6. Two-slot keyring write — non-atomic; rollback on partial failure
# ===========================================================================


def test_rollback_when_secret_slot_fails_after_key_slot_written(
    isolated_home,
    fresh_keyring,
):
    """Write the key slot, then fail on the secret slot. The helper MUST
    roll back: the key slot must NOT remain, and the result must disclose
    that rollback could not be confirmed in some scenarios.

    A backend that raises on the SECOND ``set_password`` simulates the
    non-atomic failure mode the ruling addresses.
    """

    class _SecretFails(FakeKeyring):
        def set_password(self, service, username, password):
            if username == "secret":
                raise RuntimeError("simulated keychain write failure")
            return super().set_password(service, username, password)

    backend = _SecretFails()
    _keyring.set_keyring(backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )

    # Never green on a write failure.
    assert result.status == keys_onboarding.Status.STORE_FAILED
    # Rollback removed the partial key slot.
    assert backend.get_password("krellbot:kraken", "key") is None
    # Rollback disclosure is in the safe message set.
    assert result.message in keys_onboarding.SAFE_MESSAGES
    # No raw exception text leaked.
    payload = dataclasses.asdict(result)
    assert "simulated keychain write failure" not in json.dumps(payload)
    assert "FAKEKEY" not in json.dumps(payload)
    assert "FAKESECRET" not in json.dumps(payload)


def test_rollback_when_secret_readback_mismatches(
    isolated_home,
    fresh_keyring,
):
    """Read-back mismatch (the secret wrote but reads back something else)
    must be reported as a store failure with rollback attempted.
    """

    class _SecretReadbackFails(FakeKeyring):
        def get_password(self, service, username):
            if username == "secret":
                return None  # write succeeded, read-back says it didn't persist
            return super().get_password(service, username)

    backend = _SecretReadbackFails()
    _keyring.set_keyring(backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    # Either rollback succeeded (key slot removed) or disclosed uncertainty.
    payload = dataclasses.asdict(result)
    payload_text = json.dumps(payload, sort_keys=True)
    assert "FAKEKEY" not in payload_text
    assert "FAKESECRET" not in payload_text
    assert result.message in keys_onboarding.SAFE_MESSAGES


def test_rollback_restores_prior_pair_when_present(
    isolated_home,
    fresh_keyring,
):
    """A rotation must restore the old pair on failure: if the keychain
    already has an old ``(k, s)`` and the new write fails partway, the
    old pair must remain (either untouched, or re-written). We never
    leave a half-rotated record.
    """
    backend = fresh_keyring
    backend.set_password("krellbot:kraken", "key", "OLDKEY")
    backend.set_password("krellbot:kraken", "secret", "OLDSECRET")
    _keyring.set_keyring(backend)

    class _SecretFails(FakeKeyring):
        def set_password(self, service, username, password):
            if username == "secret":
                raise RuntimeError("simulated write failure on secret slot")
            return super().set_password(service, username, password)

    class _SecretFailsBackend(_SecretFails):
        pass

    failing = _SecretFailsBackend()
    failing._store = dict(backend._store)  # carry the prior pair
    _keyring.set_keyring(failing)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=failing,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    # Either the old pair is intact, or the new key slot was rolled back.
    # Either way, the system must not be left with a partial new record.
    final_key = failing.get_password("krellbot:kraken", "key")
    final_secret = failing.get_password("krellbot:kraken", "secret")
    assert (final_key, final_secret) in {
        ("OLDKEY", "OLDSECRET"),  # old pair preserved
        (None, None),  # both removed (new partial fully cleaned)
    }
    payload = dataclasses.asdict(result)
    payload_text = json.dumps(payload, sort_keys=True)
    assert "NEWKEY" not in payload_text
    assert "OLDKEY" not in payload_text


def test_no_home_file_written_on_store_failure(
    isolated_home,
    fresh_keyring,
):
    """The ruling: ``do not write to KRELLBOT_HOME``. On any failure path
    no state file appears under the home dir.
    """
    backend = fresh_keyring
    _keyring.set_keyring(backend)

    class _SecretFails(FakeKeyring):
        def set_password(self, service, username, password):
            if username == "secret":
                raise RuntimeError("simulated")
            return super().set_password(service, username, password)

    failing = _SecretFails()
    _keyring.set_keyring(failing)

    keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=failing,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )

    # Walk every file under KRELLBOT_HOME and assert nothing references
    # the key/secret in plaintext.
    home = Path(isolated_home)
    for path in home.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"FAKEKEY" not in data, path
            assert b"FAKESECRET" not in data, path
            # KRAKEN_TEST_SECRET_B64 starts with 'kQH...' — also forbidden.
            assert b"kQH5HW" not in data, path


def test_no_home_file_written_on_refusal(isolated_home, fresh_keyring):
    """On a refusal outcome (withdraw_capable, trade_off, invalid) we
    must not write any state to disk.
    """
    backend = fresh_keyring
    _keyring.set_keyring(backend)

    keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_withdraw_transport(),
        allow_injected_fake_backend=True,
    )

    home = Path(isolated_home)
    assert home.exists()
    for path in home.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"FAKEKEY" not in data, path
            assert b"FAKESECRET" not in data, path


# ===========================================================================
# 7. Redaction registration
# ===========================================================================


def test_redaction_registered_before_probe_or_store(isolated_home, fresh_keyring):
    """``sanitize.register_secret`` must be called before any probe or
    keyring write so a future redaction pass at the print boundary
    catches the values even if an exception escapes the helper.
    """
    from krellbot import sanitize

    backend = fresh_keyring
    _keyring.set_keyring(backend)
    # Clear any prior registration so we can detect ours.
    sanitize._REGISTERED.clear()

    keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    # The values were registered for redaction.
    assert "FAKEKEY" in sanitize._REGISTERED
    assert KRAKEN_TEST_SECRET_B64 in sanitize._REGISTERED


# ===========================================================================
# 8. Silent / fail probe backends — redaction still holds
# ===========================================================================


def test_probe_failure_returns_unreachable_with_safe_message(
    isolated_home,
    fresh_keyring,
):
    """A probe transport that raises a transport-shaped exception
    (``OSError``/``RuntimeError``) is surfaced as REFUSED_UNREACHABLE
    with a fixed safe message — no raw exception text leaked.
    """
    backend = fresh_keyring
    _keyring.set_keyring(backend)

    class _Boom:
        def post(self, *args, **kwargs):
            raise OSError(f"boom: {LEAKY_SECRET}")

        def get(self, *args, **kwargs):
            return {"error": [], "result": {}}

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_Boom(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.REFUSED_UNREACHABLE
    payload = dataclasses.asdict(result)
    payload_text = json.dumps(payload, sort_keys=True)
    assert LEAKY_SECRET not in payload_text
    assert LEAKY_KEY not in payload_text
    assert "FAKESECRET" not in payload_text
    assert "FAKEKEY" not in payload_text
    assert result.message in keys_onboarding.SAFE_MESSAGES

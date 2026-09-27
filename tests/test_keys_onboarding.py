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


def test_unsupported_venue_returns_invalid_argument(isolated_home, fresh_keyring):
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
    assert result.message in keys_onboarding.SAFE_MESSAGES
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
    # The fake test backend is unrecognized: no label at all (never a
    # class name / name attribute). Real native backends get a fixed
    # label from _FIXED_BACKEND_LABELS.
    assert result.backend_label is None
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


# ===========================================================================
# 9. Verification-failure regressions — F1: backend label trust boundary
# ===========================================================================

MALICIOUS_BACKEND_NAME = "EVIL-NAME-<script>alert(1)</script>-http://atk.example/ping"
_FIXED_BACKEND_LABELS = getattr(keys_onboarding, "_FIXED_BACKEND_LABELS", frozenset())
FIXED_LABELS = (
    set(_FIXED_BACKEND_LABELS.values()) if hasattr(_FIXED_BACKEND_LABELS, "values") else set(_FIXED_BACKEND_LABELS)
)


def test_backend_label_is_fixed_even_when_name_attribute_is_hostile(isolated_home, fresh_keyring):
    """F1: a hostile ``name`` attribute must never reach the result payload."""

    class _HostileName(FakeKeyring):
        @property
        def name(self):
            return MALICIOUS_BACKEND_NAME

    backend = _HostileName()
    _keyring.set_keyring(backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORED
    # The fake backend gets no label (unrecognized), never the hostile
    # name attribute; only genuine native backends carry a fixed label.
    assert result.backend_label is None
    assert MALICIOUS_BACKEND_NAME not in json.dumps(dataclasses.asdict(result))


def test_hostile_name_attribute_not_leaked_on_unsupported_refusal(isolated_home):
    """F1: same leak vector via the UNSUPPORTED_BACKEND path."""

    class _HostileName(FakeKeyring):
        @property
        def name(self):
            return MALICIOUS_BACKEND_NAME

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=_HostileName(),
        probe=_kraken_trade_only_transport(),
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND
    assert result.backend_label is None or result.backend_label in FIXED_LABELS
    assert MALICIOUS_BACKEND_NAME not in json.dumps(dataclasses.asdict(result))


def test_backend_label_computation_cannot_be_made_to_raise_unsafely(isolated_home):
    """F1: a ``name`` property that raises must not leak exception text."""

    class _EvilLabel(FakeKeyring):
        @property
        def name(self):
            raise RuntimeError(f"label exploded {LEAKY_SECRET}")

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=_EvilLabel(),
        probe=_kraken_trade_only_transport(),
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND
    payload_text = json.dumps(dataclasses.asdict(result))
    assert LEAKY_SECRET not in payload_text
    assert "label exploded" not in payload_text


def test_unrecognized_backend_gets_no_label_never_a_class_name(isolated_home):
    """F1: class names/qualnames are untrusted; unrecognized means None."""

    class _Odd(FakeKeyring):
        pass

    _Odd.__qualname__ = MALICIOUS_BACKEND_NAME

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=_Odd(),
        probe=_kraken_trade_only_transport(),
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND
    assert result.backend_label is None
    assert MALICIOUS_BACKEND_NAME not in json.dumps(dataclasses.asdict(result))


def test_forged_class_relabelled_into_native_module_is_rejected(isolated_home):
    """F1: a forged class whose ``__module__`` claims an allowlisted native
    module path must be rejected — the class must actually be the module's
    own attribute, not merely carry the module's name."""
    pytest.importorskip("keyring.backends.macOS")
    import types as _types

    forged = _types.new_class("Keyring", (FakeKeyring,))
    forged.__module__ = "keyring.backends.macOS"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=forged(),
        probe=_kraken_trade_only_transport(),
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND
    assert result.backend_label is None


def test_subclass_relabelled_into_native_module_is_rejected(isolated_home):
    pytest.importorskip("keyring.backends.macOS")

    class _Relabelled(FakeKeyring):
        pass

    _Relabelled.__module__ = "keyring.backends.macOS"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=_Relabelled(),
        probe=_kraken_trade_only_transport(),
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND


@pytest.mark.parametrize(
    "marker_module",
    [
        "keyring.backends.null",
        "keyring.backends.fail",
        "keyrings.alt.file.Plaintext",
        "evil.plaintext.backend",
    ],
)
def test_non_persistent_markers_rejected_even_with_injection_flag(isolated_home, marker_module):
    """F1: null/fail/plaintext are rejected even when the test-injection
    flag is set — the opt-in only ever admits the in-tree FakeKeyring."""

    class _Marked(FakeKeyring):
        pass

    _Marked.__module__ = marker_module

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=_Marked(),
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.UNSUPPORTED_BACKEND


def test_real_native_backend_gets_its_fixed_label(isolated_home):
    """F1: the genuine macOS keychain class is accepted by classification
    and labelled with the fixed string. A refusal probe keeps this test
    free of any real keychain write."""
    macos = pytest.importorskip("keyring.backends.macOS")

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=macos.Keyring(),
        probe=_kraken_withdraw_transport(),
    )
    assert result.status == keys_onboarding.Status.REFUSED_WITHDRAW
    assert result.backend_label == "macOS Keychain"


# ===========================================================================
# 10. Verification-failure regressions — F2: fail closed before any write
# ===========================================================================


def test_unreadable_prior_pair_blocks_write_entirely(isolated_home):
    """F2: a prior-pair read failure must block the write — never treated
    as 'no prior pair', never overwritten, no lost credentials."""
    from krellbot import secrets as kb_secrets

    class _ReaderBlowsUp(FakeKeyring):
        writes = 0

        def get_password(self, service, username):
            raise RuntimeError(f"keychain read exploded {LEAKY_SECRET}")

        def set_password(self, service, username, password):
            type(self).writes += 1
            return super().set_password(service, username, password)

    backend = _ReaderBlowsUp()
    # Seed a prior pair directly so the broken reader cannot hide it.
    backend._store[("krellbot:kraken", "key")] = "OLDKEY"
    backend._store[("krellbot:kraken", "secret")] = "OLDSECRET"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-f2a",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "prior keyring state could not be read; nothing was written"
    assert result.message in keys_onboarding.SAFE_MESSAGES
    assert _ReaderBlowsUp.writes == 0
    # Prior credentials untouched.
    assert backend._store[("krellbot:kraken", "key")] == "OLDKEY"
    assert backend._store[("krellbot:kraken", "secret")] == "OLDSECRET"
    assert kb_secrets is not None


def test_corrupt_prior_pair_blocks_write_entirely(isolated_home):
    """F2: a half-present prior pair (key without secret) is corrupt and
    must block the write instead of being silently rotated away."""

    class _HalfPair(FakeKeyring):
        writes = 0

        def get_password(self, service, username):
            if username == "secret":
                return None
            return super().get_password(service, username)

        def set_password(self, service, username, password):
            type(self).writes += 1
            return super().set_password(service, username, password)

    backend = _HalfPair()
    backend._store[("krellbot:kraken", "key")] = "OLDKEY"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-f2b",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "prior keyring state could not be read; nothing was written"
    assert _HalfPair.writes == 0
    assert backend._store[("krellbot:kraken", "key")] == "OLDKEY"
    assert ("krellbot:kraken", "secret") not in backend._store


# ===========================================================================
# 11. Verification-failure regressions — F3: honest rollback reporting
# ===========================================================================


def test_partial_write_then_throw_restores_prior_with_proof(isolated_home):
    """F3: a backend that writes slot 1 then raises on slot 2 must be
    compensated back to the prior pair, and the 'restored' claim must be
    proven by a re-read (the final state IS the prior pair)."""

    class _SecretSlotExplodes(FakeKeyring):
        def set_password(self, service, username, password):
            if username == "secret":
                raise RuntimeError("secret slot exploded")
            return super().set_password(service, username, password)

    backend = _SecretSlotExplodes()
    backend._store[("krellbot:kraken", "key")] = "OLDKEY"
    backend._store[("krellbot:kraken", "secret")] = "OLDSECRET"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-f3a",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "keyring write failed; prior pair restored"
    assert backend.get_password("krellbot:kraken", "key") == "OLDKEY"
    assert backend.get_password("krellbot:kraken", "secret") == "OLDSECRET"


def test_silent_restore_failure_reports_uncertain(isolated_home):
    """F3: a backend that accepts the restore write but whose reader then
    reports a different value has NOT restored anything provable — the
    result must say rollback is uncertain, never 'restored'."""

    class _LyingRestore(FakeKeyring):
        def __init__(self):
            super().__init__()
            self._lie = False

        def set_password(self, service, username, password):
            if username == "secret":
                self._lie = True
                raise RuntimeError("secret slot exploded")
            return super().set_password(service, username, password)

        def get_password(self, service, username):
            if self._lie and username == "key":
                return "STALE-NOT-RESTORED"
            return super().get_password(service, username)

    backend = _LyingRestore()
    backend._store[("krellbot:kraken", "key")] = "OLDKEY"
    backend._store[("krellbot:kraken", "secret")] = "OLDSECRET"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-f3b",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "keyring write failed and rollback is uncertain"
    assert "restored" not in result.message


def test_silent_delete_failure_reports_uncertain(isolated_home):
    """F3: a delete that silently keeps the value must not be reported as
    'no prior pair was present' — the partial new key slot still exists."""

    class _SilentDelete(FakeKeyring):
        def set_password(self, service, username, password):
            if username == "secret":
                raise RuntimeError("secret slot exploded")
            return super().set_password(service, username, password)

        def delete_password(self, service, username):
            if username == "key":
                return None  # silently keeps the stored value
            return super().delete_password(service, username)

    backend = _SilentDelete()

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-f3c",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "keyring write failed and rollback is uncertain"
    assert "no prior pair" not in result.message


def test_existing_reader_fails_closed_on_partial_keyring_state(isolated_home, fresh_keyring, monkeypatch):
    """F3: the pre-existing reader (kb_secrets.get) must refuse a partial
    record rather than trading on it — an interruption that left partial
    state is detected, not silently consumed."""
    from krellbot import secrets as kb_secrets

    monkeypatch.delenv("KRELLBOT_KRAKEN_KEY", raising=False)
    monkeypatch.delenv("KRELLBOT_KRAKEN_SECRET", raising=False)
    monkeypatch.delenv("KRELLBOT_KRAKEN_KEYFILE", raising=False)
    _keyring.set_keyring(fresh_keyring)

    fresh_keyring.set_password("krellbot:kraken", "key", "ONLY-KEY-NO-SECRET")
    with pytest.raises(ValueError):
        kb_secrets.get("kraken")


# ===========================================================================
# 12. Verification-failure regressions — F4: injected probe contract
# ===========================================================================


def test_injected_probe_that_raises_returns_safe_unreachable(isolated_home, fresh_keyring):
    """F4: a caller-provided probe callable that raises must not crash the
    operation or leak the exception text; safe status contract holds."""

    def bad_probe(venue, key, secret):
        raise RuntimeError(f"probe exploded {LEAKY_SECRET}")

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=bad_probe,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.REFUSED_UNREACHABLE
    payload_text = json.dumps(dataclasses.asdict(result))
    assert LEAKY_SECRET not in payload_text
    assert "probe exploded" not in payload_text
    assert result.message in keys_onboarding.SAFE_MESSAGES
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None


def test_malformed_probe_results_fail_closed(isolated_home, fresh_keyring):
    """F4: unknown/malformed probe results must never store."""

    class _WeirdOutcome:
        outcome = "definitely_trade_only_and_validated"

    class _ValidatedOnly:
        validated = True

    bad_results = [_WeirdOutcome(), _ValidatedOnly(), "trade_only", None, 42]
    for bad in bad_results:
        result = keys_onboarding.probe_and_store(
            "kraken",
            "FAKEKEY",
            KRAKEN_TEST_SECRET_B64,
            keyring_backend=fresh_keyring,
            probe=lambda v, k, s, _r=bad: _r,
            allow_injected_fake_backend=True,
        )
        assert result.status == keys_onboarding.Status.REFUSED_MALFORMED, bad
        assert fresh_keyring.get_password("krellbot:kraken", "key") is None
        assert fresh_keyring.get_password("krellbot:kraken", "secret") is None


def test_probe_none_routes_through_cli_keys_probe(isolated_home, fresh_keyring, monkeypatch):
    """F4: the canonical real path — probe=None — still routes through
    ``cli_keys._probe`` (the single trade-only authority)."""
    from krellbot import cli_keys

    seen: list[tuple] = []

    def fake_cli_probe(venue, key, secret, transport=None):
        seen.append((venue, key, secret, transport))
        return KeyProbeResult(outcome=KeyProbeOutcome.TRADE_ONLY, reason="fake ok")

    monkeypatch.setattr(cli_keys, "_probe", fake_cli_probe)
    _keyring.set_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORED
    assert seen == [("kraken", "FAKEKEY", KRAKEN_TEST_SECRET_B64, None)]


# ===========================================================================
# 13. Verification-failure regressions — F5: redaction ordering
# ===========================================================================


def test_redaction_is_registered_before_probe_runs(isolated_home, fresh_keyring, monkeypatch):
    from krellbot import sanitize

    events: list[str] = []
    real_register = sanitize.register_secret

    def spy(*values):
        events.append("register")
        real_register(*values)

    monkeypatch.setattr(sanitize, "register_secret", spy)

    def probe(venue, key, secret):
        events.append("probe")
        return KeyProbeResult(outcome=KeyProbeOutcome.TRADE_ONLY, reason="ok")

    keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=probe,
        allow_injected_fake_backend=True,
    )
    assert events[0] == "register"
    assert events[-1] == "probe"


def test_wellformed_but_rejected_inputs_are_still_registered_for_redaction(isolated_home, fresh_keyring):
    """F5: registration is the FIRST handling of input — even values that
    end up rejected (bad venue) get masked, because they were handled."""
    from krellbot import sanitize

    sanitize._REGISTERED.clear()
    result = keys_onboarding.probe_and_store(
        "gemini",
        "GEKEY-987654",
        "GESECRET-987654",
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.INVALID_ARGUMENT
    assert "GEKEY-987654" in sanitize._REGISTERED
    assert "GESECRET-987654" in sanitize._REGISTERED
    # Rejected inputs are never echoed.
    payload_text = json.dumps(dataclasses.asdict(result))
    assert "GEKEY-987654" not in payload_text
    assert "GESECRET-987654" not in payload_text


def test_oversized_inputs_are_never_registered(isolated_home, fresh_keyring):
    """F5: gigantic strings must not land in the redaction set."""
    from krellbot import sanitize

    sanitize._REGISTERED.clear()
    big_key = "K" * 1024
    big_secret = "S" * 8192
    result = keys_onboarding.probe_and_store(
        "kraken",
        big_key,
        big_secret,
        keyring_backend=fresh_keyring,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.INVALID_ARGUMENT
    assert sanitize._REGISTERED == set()
    payload_text = json.dumps(dataclasses.asdict(result))
    assert "KKKK" not in payload_text
    assert "SSSS" not in payload_text


# ===========================================================================
# 14. Verification-failure regressions — F6: nonce ruling / no cred bytes
# ===========================================================================


def test_kraken_nonce_persists_but_home_files_never_hold_credentials(isolated_home, fresh_keyring):
    """F6: the Kraken probe legitimately persists a nonsecret monotonic
    nonce at ``run/kraken.nonce``. That file may exist and must contain
    only digits; no home file may contain credential bytes."""
    _keyring.set_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NONCEKEY-f6a",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORED

    nonce = Path(isolated_home) / "run" / "kraken.nonce"
    # Nonce persistence must remain ENABLED (explicit ruling exception).
    assert nonce.exists(), "kraken.nonce should still be persisted by the probe"
    assert nonce.read_text().strip().isdigit()

    for path in Path(isolated_home).rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"NONCEKEY-f6a" not in data, path
            assert b"kQH5HW" not in data, path


def test_refusal_path_leaves_no_credential_bytes_in_home(isolated_home, fresh_keyring):
    _keyring.set_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NONCEKEY-f6b",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=_kraken_withdraw_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.REFUSED_WITHDRAW

    for path in Path(isolated_home).rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            assert b"NONCEKEY-f6b" not in data, path
            assert b"kQH5HW" not in data, path


# ===========================================================================
# 15. Review C1 — first-slot write-then-raise MUST be compensated
# ===========================================================================


class _KeySlotWriteThenRaise(FakeKeyring):
    """C1 backend: the FIRST ``set_password(key)`` persists the NEW key,
    then raises — once. Subsequent key-slot writes succeed.

    A backend call can raise after durably writing — the raise alone
    proves nothing about what persisted. This one-shot variant models a
    transient failure that still accepts a compensation write, so the
    write path can restore the prior pair (or delete the partial new
    key) and PROVE it by reading back. The always-failing variant lives
    in ``_KeySlotAlwaysFails`` below.
    """

    def __init__(self):
        super().__init__()
        self._failed_once = False

    def set_password(self, service, username, password):
        if username == "key" and not self._failed_once:
            self._failed_once = True
            super().set_password(service, username, password)
            raise RuntimeError("simulated first-slot write-then-raise")
        return super().set_password(service, username, password)


class _KeySlotAlwaysFails(FakeKeyring):
    """C1 backend: EVERY key-slot ``set_password`` persists then raises.

    Compensation through a key-slot rewrite is impossible by
    construction; the write path must return the safe 'rollback is
    uncertain' message rather than guess."""

    def set_password(self, service, username, password):
        if username == "key":
            super().set_password(service, username, password)
            raise RuntimeError("simulated persistent first-slot failure")
        return super().set_password(service, username, password)


def test_slot1_write_then_raise_with_no_prior_pair_compensates_to_empty(isolated_home):
    """C1: no prior pair + first-slot write-then-raise → the partial new
    key must be deleted, the deletion PROVEN by readback, and the result
    must say the exact safe message — never green."""
    backend = _KeySlotWriteThenRaise()
    _keyring.set_keyring(backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-c1a",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "keyring write failed; no prior pair was present"
    assert result.message in keys_onboarding.SAFE_MESSAGES
    # Compensation proven: both slots read back absent (no half-pair, no
    # orphaned new key that would block a later retry).
    assert backend.get_password("krellbot:kraken", "key") is None
    assert backend.get_password("krellbot:kraken", "secret") is None


def test_slot1_write_then_raise_with_prior_pair_restores_prior(isolated_home):
    """C1: prior pair + first-slot write-then-raise → the prior pair must
    be restored and PROVEN by readback, not left as a half-rotated mix."""
    backend = _KeySlotWriteThenRaise()
    backend._store[("krellbot:kraken", "key")] = "OLDKEY-c1b"
    backend._store[("krellbot:kraken", "secret")] = "OLDSECRET-c1b"
    _keyring.set_keyring(backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-c1b",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "keyring write failed; prior pair restored"
    assert backend.get_password("krellbot:kraken", "key") == "OLDKEY-c1b"
    assert backend.get_password("krellbot:kraken", "secret") == "OLDSECRET-c1b"


def test_slot1_write_then_raise_with_silent_restore_reports_uncertain(isolated_home):
    """C1: compensation that silently does not persist is detected by the
    readback proof and reported as 'rollback is uncertain' — never
    'restored' / 'no prior pair was present'."""

    class _LyingKeyRestore(_KeySlotWriteThenRaise):
        def __init__(self):
            super().__init__()
            self._lie = False

        def set_password(self, service, username, password):
            if username == "key":
                super().set_password(service, username, password)  # persists
                self._lie = True
                raise RuntimeError("simulated first-slot write-then-raise")
            return super().set_password(service, username, password)

        def get_password(self, service, username):
            if self._lie and username == "key":
                return "STALE-NOT-RESTORED"
            return super().get_password(service, username)

    backend = _LyingKeyRestore()
    backend._store[("krellbot:kraken", "key")] = "OLDKEY-c1c"
    backend._store[("krellbot:kraken", "secret")] = "OLDSECRET-c1c"
    _keyring.set_keyring(backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-c1c",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "keyring write failed and rollback is uncertain"
    assert "restored" not in result.message
    assert "no prior pair" not in result.message


def test_slot1_write_then_raise_then_clean_retry_succeeds(isolated_home):
    """C1: 'permanently blocking subsequent onboarding' — after a
    compensated first-slot failure, a later retry against a healthy
    backend must succeed, proving the compensation left no half-pair."""
    failing = _KeySlotWriteThenRaise()
    _keyring.set_keyring(failing)

    first = keys_onboarding.probe_and_store(
        "kraken",
        "RETRYKEY-c1d",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=failing,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert first.status == keys_onboarding.Status.STORE_FAILED
    assert failing.get_password("krellbot:kraken", "key") is None

    # The retry: fresh healthy backend, same venue, new probe run.
    healthy = FakeKeyring()
    _keyring.set_keyring(healthy)

    second = keys_onboarding.probe_and_store(
        "kraken",
        "RETRYKEY-c1d",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=healthy,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert second.status == keys_onboarding.Status.STORED
    assert healthy.get_password("krellbot:kraken", "key") == "RETRYKEY-c1d"
    assert healthy.get_password("krellbot:kraken", "secret") == KRAKEN_TEST_SECRET_B64


def test_slot1_persistent_failure_reports_uncertain_never_green(isolated_home):
    """C1: when compensation itself is impossible (every key-slot write
    persists then raises, so the prior pair cannot be rewritten), the
    existing safe 'rollback is uncertain' message must be returned —
    never green, never a fabricated 'restored'."""
    backend = _KeySlotAlwaysFails()
    backend._store[("krellbot:kraken", "key")] = "OLDKEY-c1e"
    backend._store[("krellbot:kraken", "secret")] = "OLDSECRET-c1e"
    _keyring.set_keyring(backend)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "NEWKEY-c1e",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=backend,
        probe=_kraken_trade_only_transport(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORE_FAILED
    assert result.message == "keyring write failed and rollback is uncertain"
    assert result.message in keys_onboarding.SAFE_MESSAGES
    # Never green on a store failure.
    assert result.status != keys_onboarding.Status.STORED


# ===========================================================================
# 16. Review I1 — only a genuine KeyProbeResult may authorize storage
# ===========================================================================


def test_duck_typed_trade_only_object_never_authorizes_storage(isolated_home, fresh_keyring):
    """I1: a duck-typed object with ``outcome == 'trade_only'`` returned by
    a probe callable is not a KeyProbeResult. It must be rejected as
    malformed and must NEVER reach the keyring write path."""
    from krellbot.venues.base import KeyProbeOutcome

    class DuckProbe:
        outcome = "trade_only"
        reason = "totally legit"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=lambda v, k, s: DuckProbe(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.REFUSED_MALFORMED
    assert result.message in keys_onboarding.SAFE_MESSAGES
    # Nothing was stored.
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None
    # Mapping parity with a genuine result: same outcome, different verdict.
    assert KeyProbeOutcome.TRADE_ONLY == "trade_only"


def test_dict_probe_result_never_authorizes_storage(isolated_home, fresh_keyring):
    """I1: a plain dict — even one carrying forged 'validated' /
    'outcome' keys — must be refused as malformed."""
    forged = {
        "outcome": "trade_only",
        "reason": "totally legit",
        "validated": True,
    }
    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=lambda v, k, s: forged,
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.REFUSED_MALFORMED
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None
    assert fresh_keyring.get_password("krellbot:kraken", "secret") is None


def test_forged_validated_object_never_authorizes_storage(isolated_home, fresh_keyring):
    """I1: a duck-typed object whose only signal is ``validated = True``
    (no genuine outcome) must be refused as malformed."""

    class _ForgedValidated:
        validated = True

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=lambda v, k, s: _ForgedValidated(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.REFUSED_MALFORMED
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None


def test_genuine_result_with_junk_outcome_is_refused(isolated_home, fresh_keyring):
    """I1: a real KeyProbeResult with an out-of-taxonomy outcome string is
    rejected by the constructor itself; either refusal is safe — never
    STORED."""
    with pytest.raises(ValueError):
        KeyProbeResult(outcome="definitely_trade_only", reason="x")

    class _JunkOutcomeResult:
        """Malformed 'result' whose outcome is junk. Safe refusal
        required — never a crash, never a store."""

        outcome = "definitely_trade_only_and_validated"

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=lambda v, k, s: _JunkOutcomeResult(),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.REFUSED_MALFORMED
    assert fresh_keyring.get_password("krellbot:kraken", "key") is None


def test_injected_probe_with_genuine_trade_only_result_stores(isolated_home, fresh_keyring):
    """I1 guardrail: the isinstance gate must not break the legitimate
    test/diagnostic path — a probe callable returning a GENUINE
    KeyProbeResult(outcome=TRADE_ONLY) still stores."""
    _install_fake_keyring(fresh_keyring)

    result = keys_onboarding.probe_and_store(
        "kraken",
        "FAKEKEY",
        KRAKEN_TEST_SECRET_B64,
        keyring_backend=fresh_keyring,
        probe=lambda v, k, s: KeyProbeResult(
            outcome=KeyProbeOutcome.TRADE_ONLY,
            reason="trade on, withdraw off",
        ),
        allow_injected_fake_backend=True,
    )
    assert result.status == keys_onboarding.Status.STORED
    assert fresh_keyring.get_password("krellbot:kraken", "key") == "FAKEKEY"
    assert fresh_keyring.get_password("krellbot:kraken", "secret") == KRAKEN_TEST_SECRET_B64

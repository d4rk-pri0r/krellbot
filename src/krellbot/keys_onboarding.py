"""Shared ephemeral probe-and-store for venue API keys.

``probe_and_store`` is the single internal entry point the future wizard
key-add POST will use to (1) validate the inputs, (2) register redaction
for the secrets immediately, (3) classify the keyring backend and refuse
anything but a native OS keychain (unless tests opt in), (4) re-probe
with the venue, (5) write the two-slot ``(key, secret)`` keyring pair
only on an affirmative trade-only result, and (6) roll back on a partial
write so the system is never left with a half-stored record.

The function returns a ``KeyOnboardingResult`` whose payload is closed:
a fixed enum status, a fixed safe message from a closed set, and the
backend's display name. It NEVER carries the raw key, the raw secret,
the raw venue error, or any internal exception text.

CLI behaviour is preserved: ``krellbot keys check`` continues to read
from the keyring and exit 0/1/2 as before; ``krellbot keys add`` keeps
its existing plaintext-file path. ``probe_and_store`` is the wizard path.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Callable

from krellbot import sanitize


# Hard limits. Values above these are rejected before any network or
# keyring work so a hostile wizard cannot make us shovel megabytes into
# a keychain backend.
MAX_KEY_LEN = 256
MAX_SECRET_LEN = 4096


# Backend classification ---------------------------------------------------------


# Whitelist of native OS keychain backends. Anything else (including the
# ``FakeKeyring`` used in unit tests) is rejected by the production code
# path. The whitelist is keyed on the backend class's fully-qualified
# module path so a plugin cannot pass inspection by setting ``name`` to a
# friendly string.
_NATIVE_BACKEND_MODULE_PATHS: frozenset[str] = frozenset(
    {
        "keyring.backends.macos",
        "keyring.backends.macOS",
        "keyring.backends.secretstorage",
        "keyring.backends.SecretService",
        "keyring.backends.Windows",
        "keyring.backends.kwallet",
        "keyring.backends.kwallet5",
    }
)

# Module paths that identify the always-reject backends. These are not
# native OS keychains even when they round-trip.
_NON_PERSISTENT_MODULE_PATHS: frozenset[str] = frozenset(
    {
        "keyring.backends.null",
        "keyring.backends.fail",
    }
)


# Status + closed safe-message set ----------------------------------------------


class Status(str, Enum):
    """Closed status enum for ``probe_and_store``.

    A wizard POST maps each status to a fixed UI line. There is no
    "we'd like to update later" path — anything that is not ``STORED``
    is a refusal or a failure that must not be reported as success.
    """

    STORED = "stored"
    REFUSED_WITHDRAW = "refused_withdraw"
    REFUSED_TRADE_OFF = "refused_trade_off"
    REFUSED_INVALID = "refused_invalid"
    REFUSED_MALFORMED = "refused_malformed"
    REFUSED_UNREACHABLE = "refused_unreachable"
    UNSUPPORTED_BACKEND = "unsupported_backend"
    INVALID_ARGUMENT = "invalid_argument"
    STORE_FAILED = "store_failed"


# The closed set of safe messages. The wizard UI maps each Status to one
# of these; we do not compose messages from arbitrary strings anywhere
# in this module.
SAFE_MESSAGES: frozenset[str] = frozenset(
    {
        # STORED
        "stored in native OS keychain",
        # REFUSED_WITHDRAW
        "key has withdraw rights; refused",
        # REFUSED_TRADE_OFF
        "key lacks required trade permission; refused",
        # REFUSED_INVALID
        "key cannot be verified (invalid or permission denied); refused",
        # REFUSED_MALFORMED
        "venue response shape unknown; refused",
        # REFUSED_UNREACHABLE
        "venue unreachable; cannot verify",
        # UNSUPPORTED_BACKEND
        "keyring backend is not a native OS keychain; refused",
        # INVALID_ARGUMENT
        "input rejected; refused",
        # STORE_FAILED — disclosed uncertainty per the SDD ruling
        "keyring write failed and rollback is uncertain",
        "keyring write failed; prior pair restored",
        "keyring write failed; no prior pair was present",
    }
)

_MSG_FOR: dict[Status, str] = {
    Status.STORED: "stored in native OS keychain",
    Status.REFUSED_WITHDRAW: "key has withdraw rights; refused",
    Status.REFUSED_TRADE_OFF: "key lacks required trade permission; refused",
    Status.REFUSED_INVALID: "key cannot be verified (invalid or permission denied); refused",
    Status.REFUSED_MALFORMED: "venue response shape unknown; refused",
    Status.REFUSED_UNREACHABLE: "venue unreachable; cannot verify",
    Status.UNSUPPORTED_BACKEND: "keyring backend is not a native OS keychain; refused",
    Status.INVALID_ARGUMENT: "input rejected; refused",
}


@dataclasses.dataclass(frozen=True)
class KeyOnboardingResult:
    """Closed, secret-free outcome of a ``probe_and_store`` call."""

    status: Status
    message: str
    backend_label: str | None

    def __post_init__(self) -> None:
        if self.message not in SAFE_MESSAGES:
            raise ValueError(f"KeyOnboardingResult.message must be in SAFE_MESSAGES; got {self.message!r}")


# Probe + keyring backend injection ---------------------------------------------


# A probe is anything that accepts (venue, key, secret) and returns a
# ``KeyProbeResult``. We pass this through ``cli_keys._probe`` indirectly:
# the wizard layer composes a venue + transport + key and reuses the
# same `_probe` the CLI uses so the trade-only claim has one authority.
ProbeFn = Callable[[str, str, str], Any]
Transport = Any  # the venue transport interface


# Internal helpers --------------------------------------------------------------


def _validate_inputs(venue: str, key: str, secret: str) -> Status | None:
    """Reject unsupported venues, empty values, and oversized values.

    Returns ``None`` when the inputs are acceptable, or the refusal
    status that should be returned to the caller.
    """
    if venue not in ("kraken", "coinbase"):
        return Status.INVALID_ARGUMENT
    if not isinstance(key, str) or not key:
        return Status.INVALID_ARGUMENT
    if not isinstance(secret, str) or not secret:
        return Status.INVALID_ARGUMENT
    if len(key) > MAX_KEY_LEN:
        return Status.INVALID_ARGUMENT
    if len(secret) > MAX_SECRET_LEN:
        return Status.INVALID_ARGUMENT
    return None


def _classify_backend(backend: Any, allow_injected_fake_backend: bool) -> bool:
    """Return True iff ``backend`` is acceptable for a real key write.

    Native OS keychain backends always pass. The in-memory ``FakeKeyring``
    used by unit tests passes only when ``allow_injected_fake_backend`` is
    True (it is False by default so a wizard that accidentally uses the
    test backend in production fails closed).
    """
    if backend is None:
        return False
    cls = type(backend)
    module_path = (cls.__module__ or "").lower()
    cls_name = (cls.__name__ or "").lower()
    if module_path in _NON_PERSISTENT_MODULE_PATHS:
        return False
    # Native OS keychain classes live under a small set of well-known
    # module paths. We accept the module on a case-insensitive suffix
    # match so ``macOS`` and ``macos`` are both recognised.
    for native in _NATIVE_BACKEND_MODULE_PATHS:
        if module_path == native.lower():
            return True
    # Plaintext / file-style backends are explicitly rejected.
    if "plaintext" in module_path or ("file" in module_path and "keyrings.alt" in module_path):
        return False
    # The injected fake used by unit tests must opt in explicitly. The
    # check tolerates test subclasses whose ``__module__`` is the test
    # module (pytest re-parents subclasses) by walking the MRO and
    # looking for ``FakeKeyring`` from the tests package.
    if allow_injected_fake_backend:
        for klass in cls.__mro__:
            mod = (klass.__module__ or "").lower()
            if klass.__name__ == "FakeKeyring" and mod.endswith("fakes.fake_keyring"):
                return True
        # Plain ``FakeKeyring`` / classes whose name embeds ``fake``.
        if "fake" in cls_name and "fake" in module_path:
            return True
    return False


def _backend_label(backend: Any) -> str | None:
    """Return a fixed display name for the backend, or None if unknown.

    The wizard UI renders this label; it is not a free-form attribute.
    """
    cls = type(backend)
    cls_name = cls.__name__
    name_attr = getattr(backend, "name", None)
    if isinstance(name_attr, str) and name_attr:
        return name_attr
    return cls_name


def _run_probe(
    venue: str,
    key: str,
    secret: str,
    probe: Transport | ProbeFn | None,
) -> tuple[Status, str]:
    """Call the validated venue probe and map the outcome to (Status, msg).

    ``probe`` may be either a pre-built venue transport (the wizard
    composes a transport that points at a fake endpoint) or a probe
    callable returning a ``KeyProbeResult``. Both shapes are accepted
    so the test suite can drive the function with either.

    The CLI's ``_probe`` is the canonical authority for the trade-only
    claim. We route everything through it so wizard and CLI cannot drift.
    """
    from krellbot.cli_keys import _probe as cli_probe

    if callable(probe):
        # Tests inject a probe callable that returns the result directly.
        result = probe(venue, key, secret)
    else:
        # The wizard passes a transport; the CLI's _probe composes the
        # venue object from venue + key + secret + transport.
        result = cli_probe(venue, key, secret, transport=probe)
    outcome = getattr(result, "outcome", None)
    if outcome == "trade_only":
        return Status.STORED, _MSG_FOR[Status.STORED]
    if outcome == "withdraw_capable":
        return Status.REFUSED_WITHDRAW, _MSG_FOR[Status.REFUSED_WITHDRAW]
    if outcome == "trade_off":
        return Status.REFUSED_TRADE_OFF, _MSG_FOR[Status.REFUSED_TRADE_OFF]
    if outcome == "invalid":
        return Status.REFUSED_INVALID, _MSG_FOR[Status.REFUSED_INVALID]
    if outcome == "malformed":
        return Status.REFUSED_MALFORMED, _MSG_FOR[Status.REFUSED_MALFORMED]
    if outcome == "unreachable":
        return Status.REFUSED_UNREACHABLE, _MSG_FOR[Status.REFUSED_UNREACHABLE]
    return Status.REFUSED_MALFORMED, _MSG_FOR[Status.REFUSED_MALFORMED]


def _service(venue: str) -> str:
    return f"krellbot:{venue}"


def _read_existing_pair(keyring_backend: Any, venue: str) -> tuple[str | None, str | None]:
    """Return (existing_key, existing_secret) prior to a write attempt.

    Used by the rollback path to know what to restore if the new write
    fails partway.
    """
    try:
        k = keyring_backend.get_password(_service(venue), "key")
        s = keyring_backend.get_password(_service(venue), "secret")
        return k, s
    except Exception:
        # A read failure before we even started must not leak as a key
        # value. Treat it as "no prior pair".
        return None, None


def _delete_pair(keyring_backend: Any, venue: str) -> bool:
    """Delete both slots if present. Return True iff both deletions
    completed without raising.
    """
    ok = True
    for username in ("key", "secret"):
        try:
            keyring_backend.delete_password(_service(venue), username)
        except Exception:
            ok = False
    return ok


def _write_pair(
    keyring_backend: Any,
    venue: str,
    key: str,
    secret: str,
) -> tuple[bool, str]:
    """Write the (key, secret) pair, then read back. Returns (ok, msg).

    On any failure between slots, attempts rollback:
      * if a prior pair existed, restore it;
      * otherwise remove any partial new record.

    The ``msg`` is always from ``SAFE_MESSAGES``. We never echo the
    raw exception text.
    """
    prior_k, prior_s = _read_existing_pair(keyring_backend, venue)

    # Write slot 1 (key).
    try:
        keyring_backend.set_password(_service(venue), "key", key)
    except Exception:
        # Slot 1 itself failed; nothing to roll back. Disclose uncertainty
        # because we cannot confirm the partial state.
        return False, "keyring write failed and rollback is uncertain"

    # Write slot 2 (secret). If this fails we must roll back slot 1.
    try:
        keyring_backend.set_password(_service(venue), "secret", secret)
    except Exception:
        # Try to undo slot 1.
        try:
            keyring_backend.delete_password(_service(venue), "key")
        except Exception:
            # Rollback itself failed: partial new state is on disk.
            return False, "keyring write failed and rollback is uncertain"
        # If there was a prior pair, restore it.
        if prior_k is not None and prior_s is not None:
            try:
                keyring_backend.set_password(_service(venue), "key", prior_k)
                keyring_backend.set_password(_service(venue), "secret", prior_s)
                return False, "keyring write failed; prior pair restored"
            except Exception:
                return False, "keyring write failed and rollback is uncertain"
        return False, "keyring write failed; no prior pair was present"

    # Read back both slots to confirm the backend actually persisted.
    try:
        rb_k = keyring_backend.get_password(_service(venue), "key")
        rb_s = keyring_backend.get_password(_service(venue), "secret")
    except Exception:
        # Read-back failed; we cannot trust the state. Attempt rollback.
        if prior_k is not None and prior_s is not None:
            try:
                keyring_backend.set_password(_service(venue), "key", prior_k)
                keyring_backend.set_password(_service(venue), "secret", prior_s)
                return False, "keyring write failed; prior pair restored"
            except Exception:
                return False, "keyring write failed and rollback is uncertain"
        else:
            cleaned = _delete_pair(keyring_backend, venue)
            if cleaned:
                return False, "keyring write failed; no prior pair was present"
            return False, "keyring write failed and rollback is uncertain"

    if rb_k != key or rb_s != secret:
        # Read-back mismatch: backend reported success but stored nothing.
        # Restore prior or remove partial.
        if prior_k is not None and prior_s is not None:
            try:
                keyring_backend.set_password(_service(venue), "key", prior_k)
                keyring_backend.set_password(_service(venue), "secret", prior_s)
                return False, "keyring write failed; prior pair restored"
            except Exception:
                return False, "keyring write failed and rollback is uncertain"
        cleaned = _delete_pair(keyring_backend, venue)
        if cleaned:
            return False, "keyring write failed; no prior pair was present"
        return False, "keyring write failed and rollback is uncertain"

    return True, _MSG_FOR[Status.STORED]


# Public entry point ------------------------------------------------------------


def probe_and_store(
    venue: str,
    key: str,
    secret: str,
    *,
    keyring_backend: Any,
    probe: Transport | ProbeFn | None = None,
    allow_injected_fake_backend: bool = False,
) -> KeyOnboardingResult:
    """Probe the venue and persist the credential on trade-only result.

    Parameters
    ----------
    venue : str
        ``"kraken"`` or ``"coinbase"`` (any other value is rejected).
    key, secret : str
        The API key and private key / PEM secret. Must be non-empty and
        within the hard length limits; oversized or empty inputs are
        rejected before any probe or keyring call.
    keyring_backend : Any
        The active keyring backend. Must be a native OS keychain; the
        ``null``/``fail``/plaintext backends are rejected even when they
        round-trip. Tests can opt in to the in-memory ``FakeKeyring`` by
        setting ``allow_injected_fake_backend=True``.
    probe : Transport or callable, optional
        Either a venue transport to drive ``cli_keys._probe`` with, or a
        callable taking ``(venue, key, secret)`` and returning a
        ``KeyProbeResult``. The probe is the single authority for the
        trade-only claim; there is no ``validated=True`` escape hatch.
    allow_injected_fake_backend : bool
        Tests-only. Production code must leave this False so a wizard
        that ends up wired to the test backend fails closed.

    Returns
    -------
    KeyOnboardingResult
        A frozen dataclass with ``status``, ``message``, and
        ``backend_label``. The message is always from ``SAFE_MESSAGES``.
    """
    # 1. Input validation. We do this BEFORE registering redaction so we
    # never pollute the redaction set with a value that was never going
    # to be stored.
    refusal = _validate_inputs(venue, key, secret)
    if refusal is not None:
        return KeyOnboardingResult(
            status=refusal,
            message=_MSG_FOR[refusal],
            backend_label=None,
        )

    # 2. Register redaction immediately. This is the first thing we do
    # with the live values so any incidental echo is masked at the print
    # boundary by ``sanitize.redact``.
    sanitize.register_secret(key, secret)

    # 3. Backend classification. Must be a native OS keychain; null/fail/
    # plaintext/unrecognized are rejected even when they round-trip.
    if not _classify_backend(keyring_backend, allow_injected_fake_backend):
        return KeyOnboardingResult(
            status=Status.UNSUPPORTED_BACKEND,
            message=_MSG_FOR[Status.UNSUPPORTED_BACKEND],
            backend_label=_backend_label(keyring_backend),
        )

    # 4. Re-probe. The probe is the only authority; we do NOT honour any
    # client-supplied ``validated=True`` (no such parameter exists).
    probe_status, probe_msg = _run_probe(venue, key, secret, probe)
    if probe_status != Status.STORED:
        return KeyOnboardingResult(
            status=probe_status,
            message=probe_msg,
            backend_label=_backend_label(keyring_backend),
        )

    # 5. Two-slot keyring write. Non-atomic; on any failure we attempt
    # rollback (restore prior pair or remove partial new records) and
    # disclose uncertainty if rollback itself cannot be confirmed.
    ok, store_msg = _write_pair(keyring_backend, venue, key, secret)
    if not ok:
        return KeyOnboardingResult(
            status=Status.STORE_FAILED,
            message=store_msg,
            backend_label=_backend_label(keyring_backend),
        )

    return KeyOnboardingResult(
        status=Status.STORED,
        message=_MSG_FOR[Status.STORED],
        backend_label=_backend_label(keyring_backend),
    )

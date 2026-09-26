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
import sys
from collections.abc import Callable
from enum import Enum
from typing import Any

from krellbot import sanitize

# Hard limits. Values above these are rejected before any network or
# keyring work so a hostile wizard cannot make us shovel megabytes into
# a keychain backend. They also bound what may be registered for
# redaction (per argument), so gigantic strings never enter the
# redaction set.
MAX_KEY_LEN = 256
MAX_SECRET_LEN = 4096


# Backend classification ---------------------------------------------------------


# Whitelist of native OS keychain backend modules. Anything else (including
# the ``FakeKeyring`` used in unit tests) is rejected by the production code
# path. Acceptance is keyed on identity — the class must be an attribute of
# the allowlisted module — so a forged class or an attacker-defined subclass
# that merely sets ``__module__`` to an allowlisted path does not pass.
_NATIVE_BACKEND_MODULES: tuple[str, ...] = (
    "keyring.backends.macos",
    "keyring.backends.macOS",
    "keyring.backends.secretstorage",
    "keyring.backends.SecretService",
    "keyring.backends.Windows",
    "keyring.backends.kwallet",
    "keyring.backends.kwallet5",
)

# Fixed display labels for recognized native backends. Never derived from
# backend attributes (the ``name`` attribute and class names are untrusted
# and could carry attacker-controlled text into the wizard UI).
_FIXED_BACKEND_LABELS: dict[str, str] = {
    "keyring.backends.macos": "macOS Keychain",
    "keyring.backends.macOS": "macOS Keychain",
    "keyring.backends.secretstorage": "Secret Service (Linux)",
    "keyring.backends.SecretService": "Secret Service (Linux)",
    "keyring.backends.Windows": "Windows Credential Manager",
    "keyring.backends.kwallet": "KDE Wallet",
    "keyring.backends.kwallet5": "KDE Wallet",
}

# Module-path markers that identify always-reject backends regardless of
# any other signal. Substring-checked (case-insensitive) so a class
# relabelled into a marker module cannot dodge them; they apply even
# when the test-injection flag is set, because the opt-in only ever
# admits the in-tree fake from the tests package.
_REJECT_MODULE_MARKERS: tuple[str, ...] = (
    "null",
    "fail",
    "plaintext",
    "chainer",
)


class _KeyringFailureError(Exception):
    """Internal typed choke point: a keyring operation failed or its
    outcome could not be proven. Converted to a fixed safe result at the
    boundary; the original exception (which may embed untrusted text)
    never leaves this module."""


class _ProbeFailureError(Exception):
    """Internal typed choke point: an injected probe callable raised.
    Mapped to the safe REFUSED_UNREACHABLE result at the boundary; the
    probe's exception text never leaves this module."""


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
        "prior keyring state could not be read; nothing was written",
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


def _register_secret_guarded(*values: tuple[str, int]) -> None:
    """Register values for redaction, refusing to record gigantic strings.

    Each value carries its own store limit: an overlimit key (>256) or
    secret (>4096) is rejected input that will never be stored or
    echoed, so masking it is pointless — and a megabyte-sized value
    would otherwise live in the redaction set for the process lifetime
    and slow every redact() pass. Short values (<4 chars) are dropped by
    ``sanitize.register_secret`` itself.
    """
    for value, limit in values:
        if isinstance(value, str) and 4 <= len(value) <= limit:
            sanitize.register_secret(value)


def _native_module_for(cls: type) -> str | None:
    """Return the allowlisted native module a class genuinely belongs to.

    A class belongs to the module only if the module object actually
    holds that exact class as an attribute (``getattr(module,
    cls.__name__) is cls``). Merely carrying ``__module__ ==
    "keyring.backends.macOS"`` is not acceptance — a forged class or an
    attacker-defined subclass relabelled into the allowlisted namespace
    is rejected.
    """
    module_path = getattr(cls, "__module__", None)
    if not isinstance(module_path, str) or not module_path:
        return None
    if module_path not in _NATIVE_BACKEND_MODULES:
        return None
    module = sys.modules.get(module_path)
    if module is None:
        # Not imported: cannot prove membership; fail closed.
        return None
    return module_path if getattr(module, cls.__name__, None) is cls else None


def _classify_backend(backend: Any, allow_injected_fake_backend: bool) -> bool:
    """Return True iff ``backend`` is acceptable for a real key write.

    Native OS keychain classes (verified by identity against the
    allowlisted module) always pass. The in-memory ``FakeKeyring`` used
    by unit tests passes only when ``allow_injected_fake_backend`` is
    True. Marked modules (null/fail/plaintext/chainer) are rejected even
    when the flag is set: the opt-in only ever admits the in-tree fake
    from the tests package.
    """
    if backend is None:
        return False
    cls = type(backend)
    module_path = (getattr(cls, "__module__", "") or "").lower()
    # Always-reject markers, substring-checked (case-insensitive).
    for marker in _REJECT_MODULE_MARKERS:
        if marker in module_path:
            return False
    if _native_module_for(cls) is not None:
        return True
    # The injected fake used by unit tests must opt in explicitly. The
    # check walks the MRO and looks for ``FakeKeyring`` genuinely defined
    # in the tests fakes package (pytest re-parents subclasses into the
    # test module, so the defining module is checked via MRO).
    if allow_injected_fake_backend:
        for klass in cls.__mro__:
            mod = (klass.__module__ or "").lower()
            if klass.__name__ == "FakeKeyring" and mod.endswith("fakes.fake_keyring"):
                return True
    return False


def _backend_label(backend: Any) -> str | None:
    """Return a fixed display label for the backend, or None.

    The label is ONLY ever a fixed string from ``_FIXED_BACKEND_LABELS``
    (or None). It is never derived from the backend's ``name`` attribute,
    class name, qualname, or repr — those are untrusted and could carry
    attacker-controlled text into the wizard UI.
    """
    native = _native_module_for(type(backend))
    if native is None:
        return None
    return _FIXED_BACKEND_LABELS.get(native)


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
        # Test/diagnostic shape. An injected probe callable is untrusted:
        # it must not crash the operation nor leak its exception text.
        try:
            result = probe(venue, key, secret)
        except Exception as exc:
            raise _ProbeFailureError from exc
    else:
        # The canonical real path: the CLI's _probe is the single
        # authority for the trade-only claim.
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
    """Read the prior pair. Raises ``_KeyringFailureError`` when unreadable.

    A half-present prior pair (key without secret or vice versa) is
    corrupt and also raises: an unknown or corrupt prior state must
    block the write, never be treated as 'no prior pair', because
    rotation would otherwise overwrite credentials we could not see.
    """
    try:
        k = keyring_backend.get_password(_service(venue), "key")
        s = keyring_backend.get_password(_service(venue), "secret")
        if (k is None) != (s is None):
            raise ValueError("prior pair is corrupt (half present)")
        return k, s
    except _KeyringFailureError:
        raise
    except Exception as exc:
        raise _KeyringFailureError from exc


def _read_slot(keyring_backend: Any, venue: str, username: str) -> str | None:
    """Read one slot. Raises ``_KeyringFailureError`` when unreadable."""
    try:
        return keyring_backend.get_password(_service(venue), username)
    except _KeyringFailureError:
        raise
    except Exception as exc:
        raise _KeyringFailureError from exc


def _set_slot(keyring_backend: Any, venue: str, username: str, value: str) -> None:
    """Write one slot. Raises ``_KeyringFailureError`` on any failure."""
    try:
        keyring_backend.set_password(_service(venue), username, value)
    except _KeyringFailureError:
        raise
    except Exception as exc:
        raise _KeyringFailureError from exc


def _delete_slot(keyring_backend: Any, venue: str, username: str) -> None:
    """Delete one slot. Raises ``_KeyringFailureError`` on any failure."""
    try:
        keyring_backend.delete_password(_service(venue), username)
    except _KeyringFailureError:
        raise
    except Exception as exc:
        raise _KeyringFailureError from exc


def _compensate(
    keyring_backend: Any, venue: str, prior_k: str | None, prior_s: str | None, touched: tuple[str, ...]
) -> str:
    """Return the keyring to its prior state after a failed write.

    ``touched`` names the slots our write path actually modified; only
    those are rewritten directly. The FULL prior state (both slots) is
    then proven by a re-read, because a backend call that raised may
    still have partially persisted: if an untouched slot drifted, it is
    repaired too and the proof is repeated.

    Returns the safe message describing the provable outcome: prior
    pair restored, no prior pair present, or rollback-is-uncertain when
    the compensation failed, silently did not persist, or could not be
    re-read. A silent non-persist is detected by the re-read and
    reported as uncertain — never as a clean rollback.
    """

    def _restore(username: str, prior: str | None) -> None:
        if prior is not None:
            _set_slot(keyring_backend, venue, username, prior)
        else:
            _delete_slot(keyring_backend, venue, username)

    try:
        for username in touched:
            _restore(username, prior_k if username == "key" else prior_s)
        now_k = _read_slot(keyring_backend, venue, "key")
        now_s = _read_slot(keyring_backend, venue, "secret")
        if now_k != prior_k or now_s != prior_s:
            # An untouched slot drifted (a raising call that partially
            # wrote). Repair both slots and re-prove.
            _restore("key", prior_k)
            _restore("secret", prior_s)
            now_k = _read_slot(keyring_backend, venue, "key")
            now_s = _read_slot(keyring_backend, venue, "secret")
    except _KeyringFailureError:
        return "keyring write failed and rollback is uncertain"
    if now_k != prior_k or now_s != prior_s:
        return "keyring write failed and rollback is uncertain"
    if prior_k is not None:
        return "keyring write failed; prior pair restored"
    return "keyring write failed; no prior pair was present"


def _write_pair(
    keyring_backend: Any,
    venue: str,
    key: str,
    secret: str,
) -> tuple[bool, str]:
    """Write the (key, secret) pair, then read back. Returns (ok, msg).

    The two-slot write is NOT atomic. On any failure between slots we
    compensate: return the keyring to the prior state (restore the prior
    pair, or remove the partial new record). Every compensation claim is
    PROVEN by a re-read before it is reported — 'prior pair restored'
    means the keyring actually holds the prior pair again, and 'no prior
    pair was present' means both slots read back absent. A compensation
    that raises, silently does not persist, or cannot be re-read is
    reported as 'rollback is uncertain'.

    Compensation itself cannot be guaranteed (the backend may be failing
    generally): in that case partial state may remain and the result
    says so. The pre-existing reader (``secrets.get``) detects a
    half-present pair and fails closed rather than trading on it.
    """
    try:
        prior_k, prior_s = _read_existing_pair(keyring_backend, venue)
    except _KeyringFailureError:
        # Fail closed BEFORE any write: an unreadable or corrupt prior
        # state must never be rotated away as 'no prior pair'.
        return False, "prior keyring state could not be read; nothing was written"

    # Write slot 1 (key).
    try:
        _set_slot(keyring_backend, venue, "key", key)
    except _KeyringFailureError:
        # Slot 1 itself failed. We cannot know whether the backend wrote
        # anything, so disclose uncertainty rather than claim a clean state.
        return False, "keyring write failed and rollback is uncertain"

    # Write slot 2 (secret). Non-atomic: a failure here leaves the new
    # key slot (and possibly a half-overwritten secret slot) on disk
    # until compensated below.
    try:
        _set_slot(keyring_backend, venue, "secret", secret)
    except _KeyringFailureError:
        # Only slot 1 was modified by us; the proof inside _compensate
        # covers a secret slot that drifted anyway (write-then-raise).
        return False, _compensate(keyring_backend, venue, prior_k, prior_s, touched=("key",))

    # Read back both slots to confirm the backend actually persisted.
    try:
        rb_k = _read_slot(keyring_backend, venue, "key")
        rb_s = _read_slot(keyring_backend, venue, "secret")
    except _KeyringFailureError:
        # Unreadable after a reported-success write: treat as not
        # persisted and compensate; the compensation's own proof decides
        # the reported outcome.
        return False, _compensate(keyring_backend, venue, prior_k, prior_s, touched=("key", "secret"))
    if rb_k != key or rb_s != secret:
        # Read-back mismatch: the backend reported success but did not
        # persist what we wrote. Compensate to the prior state.
        return False, _compensate(keyring_backend, venue, prior_k, prior_s, touched=("key", "secret"))
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
    # 1. Register redaction as the FIRST handling of the credential
    #    input — before validation. Well-formed values that end up
    #    rejected (bad venue) were still handled and must be masked; the
    #    per-argument length gate keeps overlimit/gigantic strings out of
    #    the redaction set entirely. The venue name is not secret
    #    material and is deliberately not registered (it is legitimately
    #    echoed in CLI output).
    _register_secret_guarded(
        (key if isinstance(key, str) else "", MAX_KEY_LEN),
        (secret if isinstance(secret, str) else "", MAX_SECRET_LEN),
    )

    # 2. Validate. Rejected inputs are never echoed back to the caller.
    refusal = _validate_inputs(venue, key, secret)
    if refusal is not None:
        return KeyOnboardingResult(
            status=refusal,
            message=_MSG_FOR[refusal],
            backend_label=None,
        )

    # 3. Backend classification. Must be a native OS keychain; null/fail/
    #    plaintext/unrecognized are rejected even when they round-trip.
    if not _classify_backend(keyring_backend, allow_injected_fake_backend):
        return KeyOnboardingResult(
            status=Status.UNSUPPORTED_BACKEND,
            message=_MSG_FOR[Status.UNSUPPORTED_BACKEND],
            backend_label=_backend_label(keyring_backend),
        )

    # 4. Re-probe. The probe is the only authority; we do NOT honour any
    #    client-supplied ``validated=True`` (no such parameter exists).
    try:
        probe_status, probe_msg = _run_probe(venue, key, secret, probe)
    except _ProbeFailureError:
        # An injected probe callable raised: safe refusal, no raw text.
        return KeyOnboardingResult(
            status=Status.REFUSED_UNREACHABLE,
            message=_MSG_FOR[Status.REFUSED_UNREACHABLE],
            backend_label=_backend_label(keyring_backend),
        )
    if probe_status != Status.STORED:
        return KeyOnboardingResult(
            status=probe_status,
            message=probe_msg,
            backend_label=_backend_label(keyring_backend),
        )

    # 5. Two-slot keyring write. Non-atomic; on any failure we compensate
    #    (restore prior pair or remove partial new records) and prove the
    #    compensation by re-reading, disclosing uncertainty when the proof
    #    cannot be established.
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

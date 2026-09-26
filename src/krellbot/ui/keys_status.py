"""Durable key-verification status for the wizard.

The wizard status page renders "key present" and "trade-only verified at
<timestamp>". The timestamp is persisted here as a small JSON file under
$KRELLBOT_HOME — **no credentials, no key material, no raw venue error
text**. The file is what the GET handler reads; a fresh GET NEVER probes
the venue and NEVER reads the keyring secret bytes.

The set of fields is closed:

    {
        "version": 1,
        "kraken": {
            "stored": true|false,
            "verified_at": "<iso-8601 UTC>" | null,
            "last_status": "stored" | "refused_withdraw" | ... | "store_failed",
            "last_message": "<one of keys_onboarding.SAFE_MESSAGES>"
        },
        "coinbase": { ... same shape ... }
    }

``last_status`` and ``last_message`` are the closed enum/string set from
``keys_onboarding``. We never echo raw venue error text or exception
strings: any value coming from outside the closed set is dropped on
write. This is a presentation-only file; the live keyring (key + secret)
is the only authoritative credential store.
"""

from __future__ import annotations

import json
from json import JSONDecodeError
from pathlib import Path

_STATUS_FILENAME = "keys-onboarding-status.json"
_VENUES = ("kraken", "coinbase")
_VALID_STATUSES = frozenset(
    {
        "stored",
        "refused_withdraw",
        "refused_trade_off",
        "refused_invalid",
        "refused_malformed",
        "refused_unreachable",
        "unsupported_backend",
        "invalid_argument",
        "store_failed",
    }
)


def _status_path(home: Path) -> Path:
    return home / _STATUS_FILENAME


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string (Z suffix)."""
    import datetime as _dt

    # datetime.utcnow() is deprecated; use timezone-aware.
    now = _dt.datetime.now(_dt.timezone.utc)
    # Trim microseconds for stable rendering.
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_per_venue() -> dict[str, dict[str, object | None]]:
    return {
        v: {
            "stored": False,
            "verified_at": None,
            "last_status": None,
            "last_message": None,
        }
        for v in _VENUES
    }


def _read_raw(home: Path) -> dict[str, dict[str, object | None]]:
    """Return the raw on-disk status dict, or a blank one if missing/corrupt.

    Any read failure (missing file, unreadable, malformed JSON, wrong
    shape) is treated as 'no status recorded' — the wizard is idempotent,
    the file is not authoritative. The shape is fully validated: any
    unexpected keys or wrong-typed values are dropped so a stale file
    cannot inject fields into the bootstrap JSON.
    """
    path = _status_path(home)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return _empty_per_venue()
    try:
        data = json.loads(raw)
    except JSONDecodeError:
        return _empty_per_venue()
    if not isinstance(data, dict):
        return _empty_per_venue()
    out = _empty_per_venue()
    for venue in _VENUES:
        row = data.get(venue)
        if not isinstance(row, dict):
            continue
        stored = row.get("stored") is True
        verified_at = row.get("verified_at")
        if not isinstance(verified_at, str) or not verified_at:
            verified_at = None
        last_status = row.get("last_status")
        if last_status not in _VALID_STATUSES:
            last_status = None
        last_message = row.get("last_message")
        # The message is constrained to the closed safe-message set. We do
        # not import keys_onboarding here to keep this module import-light;
        # the wizard layer is the final consumer and asserts the closed set
        # at the boundary.
        if not isinstance(last_message, str) or not last_message:
            last_message = None
        out[venue] = {
            "stored": stored,
            "verified_at": verified_at,
            "last_status": last_status,
            "last_message": last_message,
        }
    return out


def read_status(home: Path) -> dict[str, dict[str, object | None]]:
    """Return the wizard status snapshot, sanitized to the closed shape.

    A fresh GET NEVER probes a venue and NEVER reads the keyring secret
    bytes. The 'stored' boolean is computed by keyring.get_password
    against the 'key' slot only (presence-only, no secret bytes are read
    out or echoed).
    """
    import keyring as _keyring
    import keyring.errors

    out = _read_raw(home)
    for venue in _VENUES:
        # Presence check — no secret bytes leave the keyring. The 'key'
        # slot's value (which IS a credential) is NEVER echoed into HTML,
        # JSON, or logs; we only check that it is non-None.
        try:
            present = _keyring.get_password(f"krellbot:{venue}", "key") is not None
        except (keyring.errors.KeyringError, OSError):  # defensive
            present = False
        out[venue]["stored"] = present
    return out


def record_outcome(home: Path, venue: str, *, status: str, message: str) -> None:
    """Record the outcome of one probe-and-store POST for ``venue``.

    Only ``status`` ∈ ``_VALID_STATUSES`` and ``message`` ∈
    ``keys_onboarding.SAFE_MESSAGES`` are accepted; anything else is
    dropped (the file is left untouched). On a STORED result, ``stored``
    is set to True and the durable timestamp is written. On any refusal,
    ``last_status``/``last_message`` reflect the closed message but
    ``stored`` is only flipped to True on STORED (and remains whatever
    the keyring presence check reports at read time).
    """
    from krellbot import keys_onboarding  # local import: avoid cycle at module load

    if venue not in _VENUES:
        return
    if status not in _VALID_STATUSES:
        return
    if message not in keys_onboarding.SAFE_MESSAGES:
        return
    snapshot = _read_raw(home)
    if venue not in snapshot:
        snapshot[venue] = {
            "stored": False,
            "verified_at": None,
            "last_status": None,
            "last_message": None,
        }
    row = snapshot[venue]
    row["last_status"] = status
    row["last_message"] = message
    if status == "stored":
        row["verified_at"] = _now_iso()
    payload = json.dumps({"version": 1, **snapshot}, separators=(",", ":")).encode("utf-8") + b"\n"
    _write_atomic(home, payload)


def _write_atomic(home: Path, payload: bytes) -> None:
    """Write the status file atomically. OSError propagates to caller."""
    from krellbot.paths import atomic_write

    atomic_write(_status_path(home), payload, mode=0o600)


__all__ = ["read_status", "record_outcome"]

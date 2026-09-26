"""Durable key-onboarding status for the wizard (presentation metadata only).

The wizard status page renders a HISTORICAL claim — "last stored through
wizard at <timestamp>; current key presence not checked" — derived solely
from this small JSON file under $KRELLBOT_HOME: **no credentials, no key
material, no raw venue error text**.

Reads make ZERO keyring calls: a GET never proves current keyring presence
(that would require reading a credential, which the brief forbids), and
never probes a venue. CLI-side removal or rotation of a key is therefore
NOT detectable here and is never implied otherwise.

The set of fields is closed:

    {
        "version": 1,
        "kraken": {
            "stored": true|false,            # diagnostic copy of the last outcome
            "verified_at": "<iso-8601 UTC>" | null,
            "last_status": "stored" | "refused_withdraw" | ... | "store_failed",
            "last_message": "<one of keys_onboarding.SAFE_MESSAGES>"
        },
        "coinbase": { ... same shape ... }
    }

Every field is validated at this read boundary against a closed set /
strict format:

* ``last_status`` ∈ the closed status enum;
* ``last_message`` ∈ ``keys_onboarding.SAFE_MESSAGES`` (a seeded or
  malformed file cannot place an arbitrary string into HTML or the
  bootstrap JSON);
* ``verified_at`` is a strictly-shaped, parseable, timezone-aware ISO-8601
  UTC timestamp (a forged attacker string is dropped, not rendered);
* the persisted ``stored`` flag is NEVER trusted as proof of anything —
  ``read_status`` re-derives the historical-stored claim from the binding
  of ``last_status == "stored"`` AND the closed STORED message AND a valid
  timestamp.

This file is a historical assertion, not authority: the live keyring
(key + secret) remains the only authoritative credential store, and this
module never reads it.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
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
# The closed STORED outcome binding: only this exact (status, message)
# pair, together with a strictly valid timestamp, yields the historical
# "last stored through wizard at …" claim.
_STORED_STATUS = "stored"
_STORED_MESSAGE = "stored in native OS keychain"

# Strict timestamp shape: exactly what _now_iso() writes — UTC, second
# precision, Z suffix. Anything else (offset forms, fractional seconds,
# attacker strings) is rejected rather than rendered.
_ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _status_path(home: Path) -> Path:
    return home / _STATUS_FILENAME


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string (Z suffix)."""
    # datetime.utcnow() is deprecated; use timezone-aware.
    now = _dt.datetime.now(_dt.timezone.utc)
    # Trim microseconds for stable rendering.
    return now.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> str | None:
    """Return ``value`` only if it is a strictly valid ISO-8601 UTC timestamp.

    A forged or malformed string returns None — it is never echoed to a
    renderer. Calendar validity (month/day/hour ranges) is checked by an
    actual parse, not just the shape regex.
    """
    if not isinstance(value, str) or not _ISO_UTC_RE.match(value):
        return None
    try:
        parsed = _dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return value


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
    """Return the sanitized on-disk status dict, or a blank one if missing/corrupt.

    Any read failure (missing file, unreadable, malformed JSON, wrong
    shape) is treated as 'no status recorded' — the wizard is idempotent,
    the file is not authoritative. The shape is fully validated at this
    boundary so a stale, malformed, or seeded file cannot inject fields
    into the bootstrap JSON:

    * unknown keys are dropped;
    * ``last_status`` must be inside the closed status enum;
    * ``last_message`` must be inside ``keys_onboarding.SAFE_MESSAGES``
      (C1: a type-check alone is not acceptance);
    * ``verified_at`` must pass the strict ISO-8601 UTC validation.

    The persisted ``stored`` flag is carried through verbatim ONLY as a
    diagnostic copy for ``record_outcome`` round-trips; ``read_status``
    never trusts it (see there).
    """
    from krellbot import keys_onboarding as _keys_onboarding

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
        verified_at = _parse_iso(row.get("verified_at"))
        last_status = row.get("last_status")
        if last_status not in _VALID_STATUSES:
            last_status = None
        last_message = row.get("last_message")
        # C1: enforced against the closed safe-message set AT THIS READ
        # BOUNDARY. A malformed, stale, or deliberately seeded status file
        # must not be able to place an arbitrary string (a credential
        # sentinel, a script payload) into a position the renderer or the
        # __KB_VIEW__ bootstrap would copy verbatim.
        if not isinstance(last_message, str) or last_message not in _keys_onboarding.SAFE_MESSAGES:
            last_message = None
        out[venue] = {
            "stored": stored,
            "verified_at": verified_at,
            "last_status": last_status,
            "last_message": last_message,
        }
    return out


def read_status(home: Path) -> dict[str, dict[str, object | None]]:
    """Return the wizard status snapshot — metadata only, ZERO keyring calls.

    A GET NEVER probes a venue and NEVER reads the keyring (I1: not even a
    ``get_password`` presence check — that would hand the API key itself
    to the process on every render). Presentation derives ONLY from the
    durable, nonsecret metadata in the status file.

    ``stored`` here is the HISTORICAL-stored claim, re-derived from the
    closed binding (``last_status == "stored"`` AND the STORED safe
    message AND a strictly valid timestamp). The persisted ``stored``
    flag is never trusted: absent or invalid metadata renders unknown /
    "not currently verified", never "no key stored" (which would wrongly
    imply current keyring absence was checked) and never a live
    "currently connected" claim.
    """
    out = _read_raw(home)
    for venue in _VENUES:
        row = out[venue]
        historically_stored = (
            row.get("last_status") == _STORED_STATUS
            and row.get("last_message") == _STORED_MESSAGE
            and isinstance(row.get("verified_at"), str)
        )
        row["stored"] = historically_stored
        if not historically_stored:
            # An unbound or partial row cannot support any stored claim.
            row["verified_at"] = None
    return out


def record_outcome(home: Path, venue: str, *, status: str, message: str) -> None:
    """Record the outcome of one probe-and-store POST for ``venue``.

    Only ``status`` ∈ the closed enum and ``message`` ∈
    ``keys_onboarding.SAFE_MESSAGES`` are accepted; anything else is
    dropped (the file is left untouched). On a STORED result the durable
    timestamp is written; on any refusal the row records the closed
    outcome without a stored claim. The written ``stored`` flag is a
    diagnostic copy of the outcome only — readers re-derive the claim via
    ``read_status`` and never trust this flag.
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
    row["stored"] = status == _STORED_STATUS
    if status == _STORED_STATUS:
        row["verified_at"] = _now_iso()
    payload = json.dumps({"version": 1, **snapshot}, separators=(",", ":")).encode("utf-8") + b"\n"
    _write_atomic(home, payload)


def _write_atomic(home: Path, payload: bytes) -> None:
    """Write the status file atomically. OSError propagates to caller."""
    from krellbot.paths import atomic_write

    atomic_write(_status_path(home), payload, mode=0o600)


__all__ = ["read_status", "record_outcome"]

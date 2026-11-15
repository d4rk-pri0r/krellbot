"""Operator-owned live authorization gate and kill switch.

This release (v0.9.6) is paper-only. ``check_live_send`` therefore refuses
before it reads any operator state: no environment variable, authorization
file, kill-switch release, or stored key can enable a live send. The
policy lives in :mod:`krellbot.release_policy` and is temporary; an
owner-approved code/release change is the only way to re-enable live.

When live is re-enabled, order paths require THREE things, all of them true:

1. ``KRELLBOT_ENABLE_LIVE`` is exactly the string ``"1"``.
2. The operator-written authorization record under
   ``<home>/live-authorization.json`` names the exact ``(venue, pair)`` and
   has not yet expired.
3. The kill switch file under ``<home>/run/kill-switch.json`` is not
   engaged.

This module is the ONLY place that reads or writes the authorization
record. The workstation grants and revokes it through
:func:`grant_authorization` / :func:`revoke_authorization` behind a typed
``LIVE`` confirmation. Promotion to live is owner-deferred in this build,
so ``check_promotion`` always refuses with ``CODE_PROMOTION_DEFERRED`` even
when the rest of the gate would let the send through.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from krellbot import release_policy
from krellbot.paths import atomic_write

SCHEMA_VERSION = "1"
AUTH_FILE = "live-authorization.json"
KILL_FILE = "kill-switch.json"
CONFIRMATION_TEXT = "LIVE"
MAX_GRANT_TTL_SECONDS = 7 * 24 * 60 * 60  # seven days

CODE_OK = "ok"
CODE_KILL_SWITCH = "kill_switch_engaged"
CODE_LIVE_DISABLED = "live_disabled"
CODE_LIVE_NOT_AUTHORIZED = "live_not_authorized"
CODE_PROMOTION_DEFERRED = "live_promotion_owner_deferred"
CODE_PAPER_ONLY_RELEASE = release_policy.CODE_PAPER_ONLY_RELEASE
CODE_BAD_INPUT = "bad_input"
CODE_CONFIRMATION_REQUIRED = "confirmation_required"
CODE_AUTHORIZED = "live_authorized"
CODE_REVOKED = "live_authorization_revoked"


@dataclass(frozen=True)
class LiveGateResult:
    """Outcome of a single gate check."""

    code: str
    ok: bool
    message: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "code": self.code,
            "ok": self.ok,
            "message": self.message,
        }


@dataclass(frozen=True)
class KillState:
    """In-memory shape of the kill switch file."""

    engaged: bool
    reason: str | None
    engaged_at: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "engaged": self.engaged,
            "reason": self.reason,
            "engaged_at": self.engaged_at,
        }


@dataclass(frozen=True)
class AuthorizationState:
    """Closed-shape snapshot of the operator live authorization record."""

    active: bool
    expires_at: int | None
    grants: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "active": self.active,
            "expires_at": self.expires_at,
            "grants": [{"venue": v, "pair": p} for v, p in self.grants],
        }


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def auth_path(home: Path) -> Path:
    """Path to the operator-owned authorization record."""
    return Path(home) / AUTH_FILE


def kill_path(home: Path) -> Path:
    """Path to the kill switch file."""
    return Path(home) / "run" / KILL_FILE


# ---------------------------------------------------------------------------
# Time and env shims so check_* can be exercised without globals
# ---------------------------------------------------------------------------


def _resolve_now(now: int | None) -> int:
    return int(time.time()) if now is None else now


def _resolve_env(env: Mapping[str, str] | None, key: str) -> str | None:
    if env is None:
        return os.environ.get(key)
    return env.get(key)


# ---------------------------------------------------------------------------
# Authorization record (product reads and writes via this module only)
# ---------------------------------------------------------------------------


def _parse_authorization_payload(data: object, *, now: int) -> AuthorizationState | None:
    """Return an active authorization state, or ``None`` when inactive/invalid."""
    if type(data) is not dict:
        return None
    if data.get("schema_version") != "1":
        return None
    if data.get("granted_by") != "operator":
        return None
    expires_at = data.get("expires_at")
    if type(expires_at) is not int or expires_at <= now:
        return None
    grants_raw = data.get("grants")
    if type(grants_raw) is not list:
        return None
    result: list[tuple[str, str]] = []
    for entry in grants_raw:
        if type(entry) is not dict:
            continue
        venue = entry.get("venue")
        pair = entry.get("pair")
        if type(venue) is not str or not venue:
            continue
        if type(pair) is not str or not pair:
            continue
        result.append((venue, pair))
    if not result:
        return None
    return AuthorizationState(True, expires_at, tuple(result))


def read_authorization(home: Path, *, now: int) -> list[tuple[str, str]]:
    """Return the operator grants that are currently in force.

    Returns ``[]`` (never raises) when the file is missing, unreadable, not
    UTF-8, not JSON, or fails any of the schema checks below. The result
    list contains only entries whose ``venue`` and ``pair`` are both
    non-empty ``str`` instances (exact ``type(x) is str``).
    """
    state = authorization_state(home, now=now)
    return list(state.grants)


def authorization_state(home: Path, *, now: int) -> AuthorizationState:
    """Return the closed-shape authorization snapshot (never raises)."""
    path = auth_path(home)
    try:
        raw = path.read_bytes()
    except OSError:
        return AuthorizationState(False, None, ())
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return AuthorizationState(False, None, ())
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return AuthorizationState(False, None, ())
    parsed = _parse_authorization_payload(data, now=now)
    if parsed is None:
        return AuthorizationState(False, None, ())
    return parsed


def _validate_confirmation(confirmation: object) -> LiveGateResult | None:
    if type(confirmation) is not str or confirmation.strip() != CONFIRMATION_TEXT:
        return _refusal(
            CODE_CONFIRMATION_REQUIRED,
            f"type {CONFIRMATION_TEXT} to confirm live authorization",
        )
    return None


def _validate_venue_pair(venue: object, pair: object) -> tuple[str, str] | LiveGateResult:
    if type(venue) is not str or not venue.strip():
        return _refusal(CODE_BAD_INPUT, "venue must be a non-empty string")
    if type(pair) is not str or not pair.strip():
        return _refusal(CODE_BAD_INPUT, "pair must be a non-empty string")
    return venue.strip(), pair.strip()


def _validate_expires_at(expires_at: object, *, now: int) -> int | LiveGateResult:
    if type(expires_at) is not int:
        return _refusal(CODE_BAD_INPUT, "expires_at must be an int unix timestamp")
    if expires_at <= now:
        return _refusal(CODE_BAD_INPUT, "expires_at must be in the future")
    if expires_at - now > MAX_GRANT_TTL_SECONDS:
        return _refusal(
            CODE_BAD_INPUT,
            f"expires_at must be within {MAX_GRANT_TTL_SECONDS} seconds from now",
        )
    return expires_at


def grant_authorization(
    home: Path,
    *,
    venue: str,
    pair: str,
    expires_at: int,
    confirmation: str,
    now: int,
) -> LiveGateResult:
    """Write a single-venue/pair operator authorization behind typed confirmation.

    While ``PAPER_ONLY_RELEASE`` is active the grant is refused and the file
    is left untouched. A successful grant replaces any previous record.
    """
    if release_policy.paper_only_release_active():
        return _refusal(CODE_PAPER_ONLY_RELEASE, release_policy.paper_only_message())
    confirm_refusal = _validate_confirmation(confirmation)
    if confirm_refusal is not None:
        return confirm_refusal
    venue_pair = _validate_venue_pair(venue, pair)
    if isinstance(venue_pair, LiveGateResult):
        return venue_pair
    clean_venue, clean_pair = venue_pair
    clean_expires = _validate_expires_at(expires_at, now=now)
    if isinstance(clean_expires, LiveGateResult):
        return clean_expires

    payload = {
        "schema_version": "1",
        "granted_by": "operator",
        "expires_at": clean_expires,
        "grants": [{"venue": clean_venue, "pair": clean_pair}],
    }
    path = auth_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(
        path,
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        mode=0o600,
    )
    return LiveGateResult(
        CODE_AUTHORIZED,
        True,
        f"live authorization granted for {clean_venue} {clean_pair}",
    )


def revoke_authorization(home: Path, *, now: int | None = None) -> LiveGateResult:
    """Remove the operator authorization record if present.

    While ``PAPER_ONLY_RELEASE`` is active revocation is refused so the
    Operations panel stays read-only for the paper-only release. ``now`` is
    accepted for call-site symmetry and unused.
    """
    del now
    if release_policy.paper_only_release_active():
        return _refusal(CODE_PAPER_ONLY_RELEASE, release_policy.paper_only_message())
    path = auth_path(home)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return LiveGateResult(CODE_REVOKED, True, "live authorization revoked")


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def kill_state(home: Path) -> KillState:
    """Read the kill switch file. Fail closed if it is unreadable or malformed."""
    path = kill_path(home)
    if not path.exists():
        return KillState(False, None, None)
    try:
        raw = path.read_bytes()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return KillState(True, "kill switch file unreadable", None)
    if type(data) is not dict:
        return KillState(True, "kill switch file unreadable", None)
    engaged = data.get("engaged")
    reason = data.get("reason")
    engaged_at = data.get("engaged_at")
    if engaged is not True:
        return KillState(True, "kill switch file unreadable", None)
    if type(reason) is not str:
        return KillState(True, "kill switch file unreadable", None)
    if type(engaged_at) is not int:
        return KillState(True, "kill switch file unreadable", None)
    return KillState(True, reason, engaged_at)


def _validate_engage_reason(reason: object) -> str:
    if type(reason) is not str:
        raise ValueError("reason must be a string")
    if len(reason) < 1 or len(reason) > 200:
        raise ValueError("reason must be 1..200 characters")
    if "\n" in reason or "\r" in reason:
        raise ValueError("reason must not contain newline characters")
    return reason


def _validate_engage_now(now: object) -> int:
    if type(now) is not int:
        raise ValueError("now must be an int")
    return now


def engage_kill(home: Path, *, reason: str, now: int) -> KillState:
    """Write the kill switch file and return the new state."""
    clean_reason = _validate_engage_reason(reason)
    clean_now = _validate_engage_now(now)
    path = kill_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {"engaged": True, "reason": clean_reason, "engaged_at": clean_now},
        sort_keys=True,
        separators=(",", ":"),
    )
    atomic_write(path, payload.encode("utf-8"), mode=0o600)
    return KillState(True, clean_reason, clean_now)


def release_kill(home: Path) -> KillState:
    """Remove the kill switch file if present and return the released state."""
    path = kill_path(home)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return KillState(False, None, None)


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------


def _refusal(code: str, message: str) -> LiveGateResult:
    return LiveGateResult(code=code, ok=False, message=message)


def check_live_send(
    home: Path,
    *,
    venue: str,
    pair: str,
    env: Mapping[str, str] | None = None,
    now: int | None = None,
) -> LiveGateResult:
    """Authorize (or refuse) a single live send."""
    if release_policy.paper_only_release_active():
        return _refusal(CODE_PAPER_ONLY_RELEASE, release_policy.paper_only_message())
    if kill_state(home).engaged:
        return _refusal(CODE_KILL_SWITCH, "kill switch engaged; live send refused")
    if _resolve_env(env, "KRELLBOT_ENABLE_LIVE") != "1":
        return _refusal(CODE_LIVE_DISABLED, "KRELLBOT_ENABLE_LIVE is not '1'; live send refused")
    grants = read_authorization(home, now=_resolve_now(now))
    if (venue, pair) not in grants:
        return _refusal(
            CODE_LIVE_NOT_AUTHORIZED,
            "live send not authorized for venue/pair",
        )
    return LiveGateResult(CODE_OK, True, "live send authorized")


def check_promotion(
    home: Path,
    *,
    venue: str,
    pair: str,
    revision_id: str,
    env: Mapping[str, str] | None = None,
    now: int | None = None,
) -> LiveGateResult:
    """Authorize (or refuse) promotion of a revision to live.

    Even when the underlying ``check_live_send`` would let a send through,
    promotion is owner-deferred in this build and always refuses with
    ``CODE_PROMOTION_DEFERRED``.
    """
    if type(revision_id) is not str or not revision_id:
        return _refusal(CODE_LIVE_NOT_AUTHORIZED, "revision_id is required")
    send_result = check_live_send(home, venue=venue, pair=pair, env=env, now=now)
    if not send_result.ok:
        return send_result
    return _refusal(CODE_PROMOTION_DEFERRED, "live promotion is owner-deferred in this build")


def live_status(
    home: Path,
    *,
    env: Mapping[str, str] | None = None,
    now: int | None = None,
) -> dict[str, object]:
    """Return a read-only snapshot of every gate input for the UI."""
    grants = sorted(read_authorization(home, now=_resolve_now(now)))
    paper_only = release_policy.paper_only_release_active()
    return {
        "schema_version": SCHEMA_VERSION,
        "live_enabled": (not paper_only) and _resolve_env(env, "KRELLBOT_ENABLE_LIVE") == "1",
        "release_policy": "paper_only" if paper_only else "live_allowed",
        "release_policy_code": CODE_PAPER_ONLY_RELEASE if paper_only else CODE_OK,
        "authorized": [{"venue": v, "pair": p} for v, p in grants],
        "kill_switch": kill_state(home).to_dict(),
        "promotion_available": False,
        "promotion_code": CODE_PROMOTION_DEFERRED,
    }

"""Operator-owned live authorization gate and kill switch.

Live order paths require THREE things, all of them true:

1. ``KRELLBOT_ENABLE_LIVE`` is exactly the string ``"1"``.
2. The operator-written authorization record under
   ``<home>/live-authorization.json`` names the exact ``(venue, pair)`` and
   has not yet expired.
3. The kill switch file under ``<home>/run/kill-switch.json`` is not
   engaged.

This module is the ONLY place that reads the authorization record, and it
never writes it. Promotion to live is owner-deferred in this build, so
``check_promotion`` always refuses with ``CODE_PROMOTION_DEFERRED`` even
when the rest of the gate would let the send through.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from krellbot.paths import atomic_write

SCHEMA_VERSION = "1"
AUTH_FILE = "live-authorization.json"
KILL_FILE = "kill-switch.json"

CODE_OK = "ok"
CODE_KILL_SWITCH = "kill_switch_engaged"
CODE_LIVE_DISABLED = "live_disabled"
CODE_LIVE_NOT_AUTHORIZED = "live_not_authorized"
CODE_PROMOTION_DEFERRED = "live_promotion_owner_deferred"


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
# Authorization record (product only reads)
# ---------------------------------------------------------------------------


def read_authorization(home: Path, *, now: int) -> list[tuple[str, str]]:
    """Return the operator grants that are currently in force.

    Returns ``[]`` (never raises) when the file is missing, unreadable, not
    UTF-8, not JSON, or fails any of the schema checks below. The result
    list contains only entries whose ``venue`` and ``pair`` are both
    non-empty ``str`` instances (exact ``type(x) is str``).
    """
    path = auth_path(home)
    try:
        raw = path.read_bytes()
    except OSError:
        return []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if type(data) is not dict:
        return []
    if data.get("schema_version") != "1":
        return []
    if data.get("granted_by") != "operator":
        return []
    expires_at = data.get("expires_at")
    if type(expires_at) is not int or expires_at <= now:
        return []
    grants = data.get("grants")
    if type(grants) is not list:
        return []
    result: list[tuple[str, str]] = []
    for entry in grants:
        if type(entry) is not dict:
            continue
        venue = entry.get("venue")
        pair = entry.get("pair")
        if type(venue) is not str or not venue:
            continue
        if type(pair) is not str or not pair:
            continue
        result.append((venue, pair))
    return result


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
    return {
        "schema_version": SCHEMA_VERSION,
        "live_enabled": _resolve_env(env, "KRELLBOT_ENABLE_LIVE") == "1",
        "authorized": [{"venue": v, "pair": p} for v, p in grants],
        "kill_switch": kill_state(home).to_dict(),
        "promotion_available": False,
        "promotion_code": CODE_PROMOTION_DEFERRED,
    }

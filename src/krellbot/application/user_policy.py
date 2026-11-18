"""Operator-owned user policy file under ``$KRELLBOT_HOME``.

The policy is a closed JSON schema the operator controls. MCP and the
workstation consult it before paper-arm, live, or key-export actions.
Hard product boundaries still apply: MCP never live-arms or reads keys,
and ``PAPER_ONLY_RELEASE`` still blocks live regardless of this file.

Missing file → safe defaults (allow paper-arm, allow live at the policy
layer, deny key export). Live remains blocked by ``PAPER_ONLY_RELEASE``
and the MCP hard refuse until the operator writes an explicit policy.
Malformed file → fail closed (deny all three). Writes go through
:func:`save_policy` and append a journal audit record. Enforce seams
call :func:`ensure_allowed`, which journals a refuse row with a reason
code when denied; :func:`check` stays silent for probes.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from krellbot.paths import atomic_write

SCHEMA_VERSION = "1"
POLICY_FILENAME = "user-policy.json"

ACTION_PAPER_ARM = "paper_arm"
ACTION_LIVE = "live"
ACTION_KEY_EXPORT = "key_export"

ACTIONS: tuple[str, ...] = (ACTION_PAPER_ARM, ACTION_LIVE, ACTION_KEY_EXPORT)

CODE_OK = "ok"
CODE_POLICY_DENIED = "user_policy_denied"
CODE_POLICY_INVALID = "user_policy_invalid"
CODE_POLICY_UPDATED = "user_policy_updated"
CODE_BAD_INPUT = "user_policy_bad_input"

MESSAGE_DENY_PAPER_ARM = "user policy denies paper-arm"
MESSAGE_DENY_LIVE = "user policy denies live"
MESSAGE_DENY_KEY_EXPORT = "user policy denies key export"
MESSAGE_INVALID = "user policy file is invalid; fail closed"
MESSAGE_UPDATED = "user policy updated"

_IS_WINDOWS = sys.platform == "win32"

_DENY_MESSAGES: dict[str, str] = {
    ACTION_PAPER_ARM: MESSAGE_DENY_PAPER_ARM,
    ACTION_LIVE: MESSAGE_DENY_LIVE,
    ACTION_KEY_EXPORT: MESSAGE_DENY_KEY_EXPORT,
}


@dataclass(frozen=True)
class UserPolicy:
    """Closed operator policy snapshot."""

    schema_version: str
    allow_paper_arm: bool
    allow_live: bool
    allow_key_export: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "allow_paper_arm": self.allow_paper_arm,
            "allow_live": self.allow_live,
            "allow_key_export": self.allow_key_export,
        }

    def allows(self, action: str) -> bool:
        if action == ACTION_PAPER_ARM:
            return self.allow_paper_arm
        if action == ACTION_LIVE:
            return self.allow_live
        if action == ACTION_KEY_EXPORT:
            return self.allow_key_export
        return False


# Safe defaults when the operator has not written a file yet.
# ``allow_live`` defaults True at this layer so release-policy / MCP hard
# gates remain the sole live blockers until the operator writes a file;
# a written ``allow_live: false`` is still enforced.
DEFAULT_POLICY = UserPolicy(
    schema_version=SCHEMA_VERSION,
    allow_paper_arm=True,
    allow_live=True,
    allow_key_export=False,
)

# Fail-closed snapshot when the on-disk file is present but unusable.
_INVALID_POLICY = UserPolicy(
    schema_version=SCHEMA_VERSION,
    allow_paper_arm=False,
    allow_live=False,
    allow_key_export=False,
)


@dataclass(frozen=True)
class PolicyDecision:
    """Outcome of a single policy check or save."""

    code: str
    ok: bool
    message: str
    action: str | None = None
    policy: UserPolicy | None = None

    def to_dict(self) -> dict[str, object]:
        body: dict[str, object] = {
            "schema_version": SCHEMA_VERSION,
            "code": self.code,
            "ok": self.ok,
            "message": self.message,
            "effect": "refused" if not self.ok else "unchanged",
        }
        if self.action is not None:
            body["action"] = self.action
        if self.policy is not None:
            body["policy"] = self.policy.to_dict()
        return body


def policy_path(home: Path) -> Path:
    """Return the path to the operator-owned user policy JSON."""
    return Path(home) / POLICY_FILENAME


def _parse_bool(raw: object) -> bool | None:
    if type(raw) is bool:
        return raw
    return None


def _parse_payload(data: object) -> UserPolicy | None:
    if not isinstance(data, dict):
        return None
    version = data.get("schema_version")
    if version not in (1, "1", SCHEMA_VERSION):
        return None
    paper = _parse_bool(data.get("allow_paper_arm"))
    live = _parse_bool(data.get("allow_live"))
    keys = _parse_bool(data.get("allow_key_export"))
    if paper is None or live is None or keys is None:
        return None
    return UserPolicy(
        schema_version=SCHEMA_VERSION,
        allow_paper_arm=paper,
        allow_live=live,
        allow_key_export=keys,
    )


@dataclass(frozen=True)
class _LoadResult:
    policy: UserPolicy
    invalid: bool


def _load(home: Path) -> _LoadResult:
    path = policy_path(home)
    if not path.exists():
        return _LoadResult(DEFAULT_POLICY, False)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _LoadResult(_INVALID_POLICY, True)
    parsed = _parse_payload(raw)
    if parsed is None:
        return _LoadResult(_INVALID_POLICY, True)
    return _LoadResult(parsed, False)


def load_policy(home: Path) -> UserPolicy:
    """Load the operator policy, or return defaults / fail-closed.

    Missing file → :data:`DEFAULT_POLICY`. Unreadable or malformed file →
    deny all three actions (fail closed).
    """
    return _load(home).policy


def check(home: Path, action: str) -> PolicyDecision:
    """Return whether ``action`` is allowed under the operator policy."""
    if action not in ACTIONS:
        return PolicyDecision(
            CODE_BAD_INPUT,
            False,
            f"unknown policy action: {action}",
            action=action,
        )
    loaded = _load(home)
    if loaded.invalid:
        return PolicyDecision(
            CODE_POLICY_INVALID,
            False,
            MESSAGE_INVALID,
            action=action,
            policy=loaded.policy,
        )
    if loaded.policy.allows(action):
        return PolicyDecision(
            CODE_OK,
            True,
            "allowed",
            action=action,
            policy=loaded.policy,
        )
    return PolicyDecision(
        CODE_POLICY_DENIED,
        False,
        _DENY_MESSAGES[action],
        action=action,
        policy=loaded.policy,
    )


def ensure_allowed(
    home: Path,
    action: str,
    *,
    clock: Any | None = None,
) -> PolicyDecision:
    """Enforce ``action`` and journal a refuse row when denied.

    Call this at seams that actually attempt the action (paper-arm, live
    arm, key export). Probes and agent ``policy_check`` should use
    :func:`check` so they do not flood the journal.
    """
    decision = check(home, action)
    if not decision.ok:
        now = int((clock or time.time)())
        _append_policy_refuse(
            home,
            ts=now,
            action=action,
            code=decision.code,
            message=decision.message,
        )
    return decision


def save_policy(
    home: Path,
    policy: UserPolicy | dict[str, Any],
    *,
    clock: Any | None = None,
) -> PolicyDecision:
    """Persist the operator policy and append a journal audit record.

    No-op writes (byte-identical payload) still return ok but do not
    append a second audit row.
    """
    home = Path(home)
    if isinstance(policy, UserPolicy):
        parsed = policy
    else:
        parsed = _parse_payload(policy)
        if parsed is None:
            return PolicyDecision(CODE_BAD_INPUT, False, "invalid user policy payload")

    # Policy cannot loosen hard product invariants via this API — callers
    # may set allow_live / allow_key_export True for a future release, but
    # MCP / PAPER_ONLY_RELEASE still refuse those surfaces today.
    before = load_policy(home)
    # When the file was missing, before is DEFAULT; still audit the write.
    path = policy_path(home)
    home.mkdir(parents=True, exist_ok=True)
    payload = parsed.to_dict()
    encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    previous_bytes: bytes | None
    if path.exists():
        try:
            previous_bytes = path.read_bytes()
        except OSError:
            previous_bytes = None
    else:
        previous_bytes = None

    atomic_write(path, encoded, mode=0o600)

    changed = previous_bytes != encoded
    if changed:
        now = int((clock or time.time)())
        _append_policy_audit(
            home,
            ts=now,
            before=before.to_dict(),
            after=parsed.to_dict(),
        )

    return PolicyDecision(
        CODE_POLICY_UPDATED if changed else CODE_OK,
        True,
        MESSAGE_UPDATED if changed else "user policy unchanged",
        policy=parsed,
    )


def _append_user_policy_record(home: Path, *, ts: int, detail: dict[str, object]) -> None:
    """Append a ``kind=user_policy`` journal row under ``home/journal``.

    Uses an explicit home (not process ``KRELLBOT_HOME``) so tests and
    multi-home callers audit the correct tree. Failures are swallowed so
    a read-only journal cannot block a successful policy write or refuse.
    """
    record = {
        "ts": int(ts),
        "kind": "user_policy",
        "venue": "-",
        "pack": "-",
        "bar_ts": 0,
        "detail": detail,
    }
    journal_dir = Path(home) / "journal"
    try:
        journal_dir.mkdir(parents=True, exist_ok=True)
        if not _IS_WINDOWS:
            os.chmod(journal_dir, 0o700)
        import datetime

        utc_ts = datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc)
        file_path = journal_dir / f"{utc_ts:%Y-%m}.jsonl"
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
        fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(fd, "a", encoding="utf-8", newline="\n", closefd=False) as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fd)
        finally:
            os.close(fd)
        if not _IS_WINDOWS:
            os.chmod(file_path, 0o600)
    except OSError:
        return


def _append_policy_audit(
    home: Path,
    *,
    ts: int,
    before: dict[str, object],
    after: dict[str, object],
) -> None:
    """Append a policy-change audit row under ``home/journal``."""
    _append_user_policy_record(
        home,
        ts=ts,
        detail={
            "event": "changed",
            "before": before,
            "after": after,
        },
    )


def _append_policy_refuse(
    home: Path,
    *,
    ts: int,
    action: str,
    code: str,
    message: str,
) -> None:
    """Append a policy-refuse receipt under ``home/journal``."""
    _append_user_policy_record(
        home,
        ts=ts,
        detail={
            "event": "refused",
            "reason": code,
            "code": code,
            "action": action,
            "message": message,
        },
    )


__all__ = [
    "ACTIONS",
    "ACTION_KEY_EXPORT",
    "ACTION_LIVE",
    "ACTION_PAPER_ARM",
    "CODE_BAD_INPUT",
    "CODE_OK",
    "CODE_POLICY_DENIED",
    "CODE_POLICY_INVALID",
    "CODE_POLICY_UPDATED",
    "DEFAULT_POLICY",
    "MESSAGE_DENY_KEY_EXPORT",
    "MESSAGE_DENY_LIVE",
    "MESSAGE_DENY_PAPER_ARM",
    "MESSAGE_INVALID",
    "MESSAGE_UPDATED",
    "POLICY_FILENAME",
    "SCHEMA_VERSION",
    "PolicyDecision",
    "UserPolicy",
    "check",
    "ensure_allowed",
    "load_policy",
    "policy_path",
    "save_policy",
]

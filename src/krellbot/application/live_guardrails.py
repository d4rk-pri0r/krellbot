"""Live guardrails surface — active rails before arm + journaled refusals.

Deploy/Operations shows these rails before ``live.arm``:

* stop required
* max account pct (> 0)
* kill switch
* grant expiry
* paper-only rail when ``PAPER_ONLY_RELEASE`` is set

Refusals are journaled with closed reason codes under
``detail.reason == "live_refused"`` so Operations alerts can surface them.
This module never places an order and does not mutate gate files.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from krellbot import journal as kb_journal
from krellbot import release_policy
from krellbot.application import live_gate

SCHEMA_VERSION = "1"

CODE_STOP_REQUIRED = "stop_required"
CODE_MAX_ACCOUNT_PCT = "max_account_pct_required"
CODE_KILL_SWITCH = live_gate.CODE_KILL_SWITCH
CODE_GRANT_EXPIRED = "grant_expired"
CODE_LIVE_NOT_AUTHORIZED = live_gate.CODE_LIVE_NOT_AUTHORIZED
CODE_PAPER_ONLY = release_policy.CODE_PAPER_ONLY_RELEASE

REASON_LIVE_REFUSED = "live_refused"
SOURCE = "live_guardrails"


@dataclass(frozen=True)
class PackRiskView:
    """Secret-free pack risk slice used by the guardrails surface."""

    pack_id: str
    stop_present: bool
    stop_ok: bool
    max_account_pct: Decimal | None
    max_account_pct_ok: bool

    def to_dict(self) -> dict[str, object]:
        pct: object
        if self.max_account_pct is None:
            pct = None
        else:
            # Keep JSON friendly (int when whole, else str).
            if self.max_account_pct == self.max_account_pct.to_integral_value():
                pct = int(self.max_account_pct)
            else:
                pct = str(self.max_account_pct)
        return {
            "pack_id": self.pack_id,
            "stop_present": self.stop_present,
            "stop_ok": self.stop_ok,
            "max_account_pct": pct,
            "max_account_pct_ok": self.max_account_pct_ok,
        }


@dataclass(frozen=True)
class GuardrailRail:
    """One named rail with whether it currently blocks live arm."""

    id: str
    active: bool
    blocking: bool
    code: str | None
    message: str
    detail: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "active": self.active,
            "blocking": self.blocking,
            "code": self.code,
            "message": self.message,
            "detail": dict(self.detail),
        }


@dataclass(frozen=True)
class GuardrailsSnapshot:
    """Closed-shape snapshot for Deploy preflight UI + API."""

    venue: str
    pair: str | None
    pack: PackRiskView | None
    rails: tuple[GuardrailRail, ...]
    blocking_codes: tuple[str, ...]
    ok: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": SCHEMA_VERSION,
            "venue": self.venue,
            "pair": self.pair,
            "pack": None if self.pack is None else self.pack.to_dict(),
            "rails": [rail.to_dict() for rail in self.rails],
            "blocking_codes": list(self.blocking_codes),
            "ok": self.ok,
            "code": "ok" if self.ok else (self.blocking_codes[0] if self.blocking_codes else "refused"),
            "effect": "unchanged" if self.ok else "refused",
            "message": (
                "live guardrails clear" if self.ok else f"live guardrails blocking: {', '.join(self.blocking_codes)}"
            ),
        }


def _resolve_now(now: int | None) -> int:
    return int(time.time()) if now is None else now


def inspect_pack_risk(pack_data: object) -> PackRiskView | None:
    """Return pack risk view, or ``None`` when ``pack_data`` is not a mapping."""
    if type(pack_data) is not dict:
        return None
    pack_id_raw = pack_data.get("id")
    pack_id = pack_id_raw if isinstance(pack_id_raw, str) and pack_id_raw else "-"
    risk = pack_data.get("risk")
    risk_row = risk if type(risk) is dict else {}
    stop_block = risk_row.get("stop")
    stop_present = type(stop_block) is dict and bool(stop_block)
    stop_ok = False
    if type(stop_block) is dict:
        stop_type = stop_block.get("type")
        try:
            if stop_type == "pct":
                stop_ok = Decimal(str(stop_block.get("pct", "0"))) > Decimal(0)
            elif stop_type == "atr":
                stop_ok = Decimal(str(stop_block.get("mult", "0"))) > Decimal(0)
            else:
                stop_ok = False
        except (InvalidOperation, TypeError, ValueError):
            stop_ok = False

    pct_raw = risk_row.get("max_account_pct")
    max_pct: Decimal | None
    max_ok: bool
    try:
        if pct_raw is None:
            max_pct = None
            max_ok = False
        else:
            max_pct = Decimal(str(pct_raw))
            max_ok = max_pct > Decimal(0)
    except (InvalidOperation, TypeError, ValueError):
        max_pct = None
        max_ok = False

    return PackRiskView(
        pack_id=pack_id,
        stop_present=stop_present,
        stop_ok=stop_ok,
        max_account_pct=max_pct,
        max_account_pct_ok=max_ok,
    )


def pair_from_pack(pack_data: object, venue: str) -> str | None:
    """Return the pack market pair for ``venue``, or ``None``."""
    if type(pack_data) is not dict:
        return None
    markets = pack_data.get("markets")
    if type(markets) is not list:
        return None
    for entry in markets:
        if type(entry) is not dict:
            continue
        if entry.get("venue") != venue:
            continue
        pair = entry.get("pair")
        if isinstance(pair, str) and pair:
            return pair
    return None


def _read_grant_expiry(home: Path, *, now: int) -> tuple[bool, bool, int | None]:
    """Return ``(present, expired, expires_at)`` for the auth file.

    Distinguishes a missing grant from an expired one without mutating
    :mod:`krellbot.application.live_gate` parse rules.
    """
    path = live_gate.auth_path(home)
    try:
        raw = path.read_bytes()
    except OSError:
        return False, False, None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return False, False, None
    if type(data) is not dict:
        return False, False, None
    expires_at = data.get("expires_at")
    if type(expires_at) is not int:
        return False, False, None
    if expires_at <= now:
        return True, True, expires_at
    state = live_gate.authorization_state(home, now=now)
    if not state.active:
        return True, True, expires_at
    return True, False, expires_at


def snapshot(
    home: Path,
    *,
    venue: str = "kraken",
    pack_data: object | None = None,
    now: int | None = None,
) -> GuardrailsSnapshot:
    """Build the active-guardrails snapshot for Deploy preflight."""
    clean_venue = venue.strip().lower() if isinstance(venue, str) else "kraken"
    if not clean_venue:
        clean_venue = "kraken"
    stamp = _resolve_now(now)
    pack = inspect_pack_risk(pack_data) if pack_data is not None else None
    pair = pair_from_pack(pack_data, clean_venue) if pack_data is not None else None

    rails: list[GuardrailRail] = []

    paper_only = release_policy.paper_only_release_active()
    rails.append(
        GuardrailRail(
            id="paper_only_rail",
            active=paper_only,
            blocking=paper_only,
            code=CODE_PAPER_ONLY if paper_only else None,
            message=(
                release_policy.paper_only_message() if paper_only else "paper-only rail is not set for this release"
            ),
            detail={"release_policy": "paper_only" if paper_only else "live_allowed"},
        )
    )

    kill = live_gate.kill_state(home)
    rails.append(
        GuardrailRail(
            id="kill_switch",
            active=True,
            blocking=kill.engaged,
            code=CODE_KILL_SWITCH if kill.engaged else None,
            message=(f"kill switch engaged: {kill.reason}" if kill.engaged else "kill switch clear"),
            detail=kill.to_dict(),
        )
    )

    present, expired, expires_at = _read_grant_expiry(home, now=stamp)
    auth = live_gate.authorization_state(home, now=stamp)
    if not present:
        grant_blocking = True
        grant_code = CODE_LIVE_NOT_AUTHORIZED
        grant_message = "no live grant on file"
    elif expired:
        grant_blocking = True
        grant_code = CODE_GRANT_EXPIRED
        grant_message = "live grant expired"
    else:
        grant_blocking = False
        grant_code = None
        grant_message = "live grant active"
    rails.append(
        GuardrailRail(
            id="grant_expiry",
            active=True,
            blocking=grant_blocking,
            code=grant_code,
            message=grant_message,
            detail={
                "present": present,
                "expired": expired,
                "expires_at": expires_at,
                "active": auth.active,
                "grants": [{"venue": v, "pair": p} for v, p in auth.grants],
            },
        )
    )

    # Stop + max account pct rails are always required for live arm.
    if pack is None:
        rails.append(
            GuardrailRail(
                id="stop_required",
                active=True,
                blocking=False,
                code=None,
                message="live arm requires a pack stop (provide revision to check)",
                detail={"checked": False},
            )
        )
        rails.append(
            GuardrailRail(
                id="max_account_pct",
                active=True,
                blocking=False,
                code=None,
                message="live arm requires max_account_pct > 0 (provide revision to check)",
                detail={"checked": False},
            )
        )
    else:
        rails.append(
            GuardrailRail(
                id="stop_required",
                active=True,
                blocking=not pack.stop_ok,
                code=CODE_STOP_REQUIRED if not pack.stop_ok else None,
                message=("pack stop present and positive" if pack.stop_ok else "live arm requires a stop"),
                detail={
                    "checked": True,
                    "stop_present": pack.stop_present,
                    "stop_ok": pack.stop_ok,
                },
            )
        )
        rails.append(
            GuardrailRail(
                id="max_account_pct",
                active=True,
                blocking=not pack.max_account_pct_ok,
                code=CODE_MAX_ACCOUNT_PCT if not pack.max_account_pct_ok else None,
                message=(
                    f"max_account_pct={pack.max_account_pct}"
                    if pack.max_account_pct_ok
                    else "live arm requires max_account_pct > 0"
                ),
                detail={
                    "checked": True,
                    "max_account_pct": (
                        None
                        if pack.max_account_pct is None
                        else (
                            int(pack.max_account_pct)
                            if pack.max_account_pct == pack.max_account_pct.to_integral_value()
                            else str(pack.max_account_pct)
                        )
                    ),
                    "max_account_pct_ok": pack.max_account_pct_ok,
                },
            )
        )

    blocking = tuple(rail.code for rail in rails if rail.blocking and rail.code)
    return GuardrailsSnapshot(
        venue=clean_venue,
        pair=pair,
        pack=pack,
        rails=tuple(rails),
        blocking_codes=blocking,
        ok=len(blocking) == 0,
    )


def journal_refusal(
    home: Path,
    *,
    venue: str,
    pack_id: str,
    pair: str | None,
    code: str,
    message: str,
    now: int | None = None,
) -> None:
    """Append one ``live_refused`` journal record; never raises to callers.

    ``home`` is accepted for call-site clarity; ``krellbot.journal.append``
    writes under ``KRELLBOT_HOME`` / ``paths.home()`` (tests set both).
    """
    del home  # journal.append resolves via paths.home() / KRELLBOT_HOME
    stamp = _resolve_now(now)
    record = {
        "ts": stamp,
        "kind": "tick",
        "venue": venue,
        "pack": pack_id,
        "bar_ts": 0,
        "detail": {
            "reason": REASON_LIVE_REFUSED,
            "code": code,
            "pair": pair,
            "source": SOURCE,
            "message": message,
        },
    }
    try:
        kb_journal.append(record)
    except (OSError, ValueError, TypeError):
        pass


def journal_blocking_refusals(
    home: Path,
    snap: GuardrailsSnapshot,
    *,
    now: int | None = None,
) -> list[str]:
    """Journal each blocking rail once; return the codes written."""
    stamp = _resolve_now(now)
    pack_id = snap.pack.pack_id if snap.pack is not None else "-"
    written: list[str] = []
    for rail in snap.rails:
        if not rail.blocking or rail.code is None:
            continue
        journal_refusal(
            home,
            venue=snap.venue,
            pack_id=pack_id,
            pair=snap.pair,
            code=rail.code,
            message=rail.message,
            now=stamp,
        )
        written.append(rail.code)
    return written


def evaluate(
    home: Path,
    *,
    venue: str = "kraken",
    pack_data: object | None = None,
    journal: bool = True,
    now: int | None = None,
) -> dict[str, Any]:
    """Snapshot rails, optionally journal refusals, return API body."""
    stamp = _resolve_now(now)
    snap = snapshot(home, venue=venue, pack_data=pack_data, now=stamp)
    body = snap.to_dict()
    if journal and not snap.ok:
        body["journaled_codes"] = journal_blocking_refusals(home, snap, now=stamp)
    else:
        body["journaled_codes"] = []
    return body

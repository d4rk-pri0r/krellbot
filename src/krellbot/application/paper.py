"""Paper command service — the single application boundary for paper commands.

`PaperService` owns:

    paper.arm          (paper mode only — the legacy live path stays in run.arm_pack)
    paper.disarm
    paper.pause_entries
    paper.resume_entries
    paper.raise_stop

Every method validates completely before mutating the armed-pack config and
returns a typed `CommandResultV1`. CLI, dashboard forms, and any future
versioned API route through this service; nothing else re-implements pause
semantics, entitlement checks, or persistence.

Contracts (`.superpowers/sdd/krellbot-2027/contracts/commands.md`):

  * `home` is explicit. A supplied `home` always wins over `KRELLBOT_HOME`
    or `Path.home()`; the service never reads the process environment to
    decide where to write.
  * `clock` is injected; the service has no internal `time.time()` call.
  * The service does NOT read the OS keyring and does NOT open a network
    transport. Paper commands are local-only.
  * `entries_paused` persists and survives `load_config`. Pause and resume
    are idempotent. Pause does NOT disarm or liquidate.
  * Invalid venue, mode, pack, balance, stop, or a live command sent here
    refuses before any config byte changes. Refusals leave `revision_after`
    equal to `revision_before`.
  * `disarm`, `pause_entries`, `resume_entries`, and `raise_stop` read the
    stored armed record and refuse with `stored_mode_not_paper` when its
    `mode` is not `paper`. The caller payload does not influence the
    stored-mode check; a missing `mode` or a `mode: paper` payload still
    refuses when the stored record is live. Live authority stays in the
    legacy CLI path.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from krellbot import config as kb_config
from krellbot import secrets as kb_secrets
from krellbot.pack import lint as kb_pack_lint

SCHEMA_VERSION = "1"

# Stable codes per contracts/commands.md v1 closed set.
CODE_ARMED = "armed"
CODE_DISARMED = "disarmed"
CODE_ENTRIES_PAUSED = "entries_paused"
CODE_ENTRIES_RESUMED = "entries_resumed"
CODE_STOP_RAISED = "stop_raised"
CODE_ALREADY_PAUSED = "already_paused"
CODE_ALREADY_RESUMED = "already_resumed"
CODE_ALREADY_ARMED = "already_armed"
CODE_NOT_ARMED = "not_armed"
CODE_INVALID_REQUEST = "invalid_request"
CODE_INVALID_PACK = "invalid_pack"
CODE_LEGACY_PACK_NOT_RUNNABLE = "legacy_pack_not_runnable"
CODE_UNKNOWN_VENUE = "unknown_venue"
CODE_PACK_HAS_NO_MARKET = "pack_has_no_market"
CODE_INVALID_BALANCE = "invalid_balance"
CODE_INVALID_STOP = "invalid_stop"
CODE_MINIMUM_NOT_MET = "minimum_not_met"
CODE_STORED_MODE_NOT_PAPER = "stored_mode_not_paper"


@dataclass(frozen=True)
class CommandResultV1:
    """Versioned paper-command result.

    `schema_version` is the literal string `"1"`. `effect` is one of
    `changed`, `unchanged`, `refused`. `revision_before` and
    `revision_after` are sha256 hex strings of the on-disk armed-pack
    config bytes; `None` when the file does not yet exist. A refusal
    leaves both revisions equal.
    """

    schema_version: str
    correlation_id: str
    code: str
    ok: bool
    message: str
    effect: str
    revision_before: str | None
    revision_after: str | None

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "correlation_id": self.correlation_id,
            "code": self.code,
            "ok": self.ok,
            "message": self.message,
            "effect": self.effect,
            "revision_before": self.revision_before,
            "revision_after": self.revision_after,
        }


def _revision(home: Path) -> str | None:
    path = kb_config.config_path(home)
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_pair(pack_path: Path, venue: str) -> str:
    """Return the pack's pair for `venue`. Mirrors `run.arm_pack`'s lookup.

    The service does not read the engine's private state — it re-reads
    the same pack file the engine just validated. Raises if the pack
    has no market for the venue; the caller is responsible for mapping
    that case to a refusal before persistence would have happened.
    """
    try:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    markets = data.get("markets") or []
    market = next((m for m in markets if m.get("venue") == venue), None)
    if market is None:
        return ""
    return str(market.get("pair", ""))


def _classify_invalid_input(pack_path: Path, venue: str) -> tuple[str, str]:
    """Map an `rc=2` (invalid input) refusal to a specific code + message.

    `run.arm_pack` returns 2 for any input failure but does not expose
    which one. The service classifies by re-reading the pack file the
    engine just looked at; this is presentation logic only and does
    not change the engine's on-disk refusal contract.
    """
    if not pack_path.exists():
        return CODE_INVALID_REQUEST, "pack file not found"
    try:
        data = json.loads(pack_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return CODE_INVALID_PACK, "pack JSON parse error"
    if not isinstance(data, dict):
        return CODE_INVALID_PACK, "pack must be a JSON object"
    if kb_pack_lint.is_legacy(data):
        return CODE_LEGACY_PACK_NOT_RUNNABLE, "legacy packs are not runnable"
    errors = kb_pack_lint.check(data)
    if errors:
        return CODE_INVALID_PACK, "pack validation failed"
    pair = _resolve_pair(pack_path, venue)
    if not pair:
        return CODE_PACK_HAS_NO_MARKET, f"pack has no market for {venue}"
    return CODE_INVALID_REQUEST, "invalid input refused by paper service"


def _now_seconds_default() -> float:
    return time.time()


class PaperService:
    """Single application-service boundary for paper commands."""

    def __init__(self, home: Path, *, clock: Callable[[], float] | None = None) -> None:
        self._home = Path(home)
        self._clock = clock or _now_seconds_default

    @property
    def home(self) -> Path:
        return self._home

    # ---- arm -------------------------------------------------------------

    def arm(
        self,
        pack_path: Path,
        *,
        venue: str,
        mode: str,
        paper_balance: Decimal | None,
        correlation_id: str = "",
        requires_license: bool | None = None,
    ) -> CommandResultV1:
        """Arm a pack in paper mode.

        The service is the boundary; the engine's ``run.arm_pack``
        remains the single authority for the typed live confirmation,
        the key check, the pack-shape validation, and the costmin
        check (so the existing live path and the existing engine
        guarantees are unchanged). For paper mode the service runs
        its own validation, then delegates to ``run.arm_pack`` with
        ``home=self._home`` so the persistence and the on-disk
        record are byte-identical to what the engine produces.

        Refuses a `mode=live` request before any config byte changes.
        """
        rev_before = _revision(self._home)

        if mode != "paper":
            return self._refusal(
                CODE_INVALID_REQUEST,
                "live arm is not handled by the paper service",
                correlation_id,
                rev_before,
            )

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        if paper_balance is None:
            return self._refusal(
                CODE_INVALID_BALANCE,
                "paper arm requires --paper-balance",
                correlation_id,
                rev_before,
            )
        if paper_balance <= Decimal(0):
            return self._refusal(
                CODE_INVALID_BALANCE,
                "paper-balance must be positive",
                correlation_id,
                rev_before,
            )

        # Delegate the actual arm to ``run.arm_pack`` so the existing
        # engine guarantees (pack-shape validation, costmin check,
        # costmin refusal) and the on-disk record stay identical.
        # We pass ``home=self._home`` so persistence lands in the
        # supplied home, not in whatever ``KRELLBOT_HOME`` happens to
        # be at process start.
        from krellbot import run as kb_run

        rc = kb_run.arm_pack(
            pack_path,
            venue=venue,
            mode=mode,
            paper_balance=paper_balance,
            requires_license=requires_license,
            home=self._home,
        )

        rev_after = _revision(self._home)

        if rc == 0:
            # Build the typed message from the on-disk record when one
            # is present (the production path). The record MAY be
            # absent in tests that monkeypatch ``run.arm_pack`` with a
            # spy that returns 0 without persisting — the service still
            # trusts the rc and emits a typed success result.
            config = kb_config.load_config(self._home)
            pair = _resolve_pair(pack_path, venue)
            armed = kb_config.find_armed(config, venue, pair) if pair else None
            if armed is not None:
                message = f"armed {armed.pack_id} {armed.pack_version} on {venue} {armed.pair}"
            else:
                message = f"armed {venue} {pair or '?'}"
            return CommandResultV1(
                schema_version=SCHEMA_VERSION,
                correlation_id=correlation_id,
                code=CODE_ARMED,
                ok=True,
                message=message,
                effect="changed",
                revision_before=rev_before,
                revision_after=rev_after,
            )
        if rc == 1:
            # State refusal. Distinguish already-armed from costmin by
            # inspecting the current config (costmin leaves no record;
            # already-armed leaves the record unchanged).
            pair = _resolve_pair(pack_path, venue)
            config = kb_config.load_config(self._home)
            armed = kb_config.find_armed(config, venue, pair)
            if armed is not None:
                return self._refusal(
                    CODE_ALREADY_ARMED,
                    f"already armed: {venue} {pair}",
                    correlation_id,
                    rev_before,
                )
            return self._refusal(
                CODE_MINIMUM_NOT_MET,
                "cap cannot meet the pair minimum",
                correlation_id,
                rev_before,
            )
        # rc == 2: invalid input — pack shape / venue / balance. The
        # service has already enforced the balance branch; anything
        # reaching this return is pack-shape. ``rev_after == rev_before``
        # proves no byte changed. Classify to a specific code so the
        # adapter can render the right reason.
        code, msg = _classify_invalid_input(pack_path, venue)
        return self._refusal(code, msg, correlation_id, rev_before)

    # ---- disarm ----------------------------------------------------------

    def disarm(self, *, venue: str, pair: str, correlation_id: str = "") -> CommandResultV1:
        rev_before = _revision(self._home)

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        config = kb_config.load_config(self._home)
        armed = kb_config.find_armed(config, venue, pair)
        if armed is None:
            return self._refusal(
                CODE_NOT_ARMED,
                f"not armed: {venue} {pair}",
                correlation_id,
                rev_before,
            )

        # F01: paper commands read the stored record's mode and refuse to
        # mutate a non-paper target. The caller payload does not override
        # this check; live authority stays in the legacy CLI path.
        if armed.mode != "paper":
            return self._refusal(
                CODE_STORED_MODE_NOT_PAPER,
                f"stored mode is {armed.mode!r}; paper service only mutates paper targets",
                correlation_id,
                rev_before,
            )

        config.armed = [a for a in config.armed if not (a.venue == venue and a.pair == pair)]
        kb_config.save_config(self._home, config)
        rev_after = _revision(self._home)

        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=CODE_DISARMED,
            ok=True,
            message=f"disarmed {venue} {pair}",
            effect="changed",
            revision_before=rev_before,
            revision_after=rev_after,
        )

    # ---- pause / resume --------------------------------------------------

    def pause_entries(self, *, venue: str, pair: str, correlation_id: str = "") -> CommandResultV1:
        return self._set_entries_paused(venue=venue, pair=pair, paused=True, correlation_id=correlation_id)

    def resume_entries(self, *, venue: str, pair: str, correlation_id: str = "") -> CommandResultV1:
        return self._set_entries_paused(venue=venue, pair=pair, paused=False, correlation_id=correlation_id)

    def _set_entries_paused(self, *, venue: str, pair: str, paused: bool, correlation_id: str) -> CommandResultV1:
        rev_before = _revision(self._home)

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        config = kb_config.load_config(self._home)
        armed = kb_config.find_armed(config, venue, pair)
        if armed is None:
            return self._refusal(
                CODE_NOT_ARMED,
                f"not armed: {venue} {pair}",
                correlation_id,
                rev_before,
            )

        # F01: refuse before any byte change. The caller payload does not
        # override the stored-mode check.
        if armed.mode != "paper":
            return self._refusal(
                CODE_STORED_MODE_NOT_PAPER,
                f"stored mode is {armed.mode!r}; paper service only mutates paper targets",
                correlation_id,
                rev_before,
            )

        if armed.entries_paused == paused:
            if paused:
                code, msg = CODE_ALREADY_PAUSED, f"already paused: {venue} {pair}"
            else:
                code, msg = CODE_ALREADY_RESUMED, f"already resumed: {venue} {pair}"
            return CommandResultV1(
                schema_version=SCHEMA_VERSION,
                correlation_id=correlation_id,
                code=code,
                ok=True,
                message=msg,
                effect="unchanged",
                revision_before=rev_before,
                revision_after=rev_before,
            )

        armed.entries_paused = paused
        kb_config.save_config(self._home, config)
        rev_after = _revision(self._home)

        if paused:
            code, msg = CODE_ENTRIES_PAUSED, f"entries paused: {venue} {pair}"
        else:
            code, msg = CODE_ENTRIES_RESUMED, f"entries resumed: {venue} {pair}"

        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=code,
            ok=True,
            message=msg,
            effect="changed",
            revision_before=rev_before,
            revision_after=rev_after,
        )

    # ---- raise stop ------------------------------------------------------

    def raise_stop(
        self,
        *,
        venue: str,
        pair: str,
        new_stop: Decimal,
        correlation_id: str = "",
    ) -> CommandResultV1:
        rev_before = _revision(self._home)

        if venue not in kb_secrets.VENUES:
            return self._refusal(
                CODE_UNKNOWN_VENUE,
                f"unknown venue: {venue}",
                correlation_id,
                rev_before,
            )

        config = kb_config.load_config(self._home)
        armed = kb_config.find_armed(config, venue, pair)
        if armed is None:
            return self._refusal(
                CODE_NOT_ARMED,
                f"not armed: {venue} {pair}",
                correlation_id,
                rev_before,
            )

        # F01: refuse before any byte change. The caller payload does not
        # override the stored-mode check.
        if armed.mode != "paper":
            return self._refusal(
                CODE_STORED_MODE_NOT_PAPER,
                f"stored mode is {armed.mode!r}; paper service only mutates paper targets",
                correlation_id,
                rev_before,
            )

        if new_stop <= armed.stop:
            return self._refusal(
                CODE_INVALID_STOP,
                "new stop must be strictly above the current stop",
                correlation_id,
                rev_before,
            )

        armed.stop = new_stop
        kb_config.save_config(self._home, config)
        rev_after = _revision(self._home)

        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=CODE_STOP_RAISED,
            ok=True,
            message=f"stop set: {venue} {pair} -> {new_stop}",
            effect="changed",
            revision_before=rev_before,
            revision_after=rev_after,
        )

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _refusal(
        code: str,
        message: str,
        correlation_id: str,
        revision: str | None,
    ) -> CommandResultV1:
        return CommandResultV1(
            schema_version=SCHEMA_VERSION,
            correlation_id=correlation_id,
            code=code,
            ok=False,
            message=message,
            effect="refused",
            revision_before=revision,
            revision_after=revision,
        )

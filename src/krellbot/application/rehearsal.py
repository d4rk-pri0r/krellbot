"""Synthetic paper rehearsal — a bounded, candle-driven simulated run.

``RehearsalService`` is the single application boundary for the built-in
SYNTHETIC PAPER example. It exists so a fresh local app has one explicit,
honest rehearsal: a fixed synthetic OHLCV series shipped as a package
resource is fed — bar by bar, through the REAL engine (``krellbot.run.tick``)
and the REAL ``PaperVenue`` — until the sample pack's own rules produce an
entry fill, an owned position, and an exit fill. No HTTP, no key, no
account, no live transport is touched anywhere in this path.

Honesty rules that shape this module:

* The label is fixed: ``'Synthetic paper rehearsal — simulated data, not
  market-performance evidence'``. It is carried by every status projection
  and by the shipped resources themselves.
* Nothing here is a canned success response. Status is computed from the
  durable venue/journal/state bytes the engine just wrote; commands
  either advance the run by real evaluation or refuse.
* The sample is FIXED for this bounded POC: one pack, one 50-bar series,
  one venue/pair. No configuration surface is added.

Isolation rules:

* All rehearsal state lives under ``<home>/rehearsal`` — a self-contained
  mini ``KRELLBOT_HOME`` (config.json, ops.sqlite, run/, journal/). The
  user's own ``config.json``, paper venue state, outbox, and journal are
  never read or written by a rehearsal step.
* ``run.tick``'s journal sink resolves the journal directory through the
  process ``KRELLBOT_HOME`` (``paths.ensure_layout()``), not through the
  ``home`` parameter. To keep every engine write inside the rehearsal
  root, engine calls run under a scoped ``KRELLBOT_HOME`` override that
  is restored in ``finally``. The service is sync; the window is bounded
  to one tick.

Lifecycle (state machine persisted in ``<home>/rehearsal/state.json``):

    idle --start--> running --pause--> paused --resume--> running
    running/paused --exit--> exited        any --stop--> stopped (terminal)

* ``start``/``resume`` advance exactly one bar (one real engine tick).
* ``pause`` persists ``entries_paused`` on the rehearsal armed record so
  the engine's existing suppression logic blocks entries while stops,
  exits, and repairs stay operative; ``resume`` clears it.
* ``exit`` advances bars until the pack's OWN exit rule closes the
  position (a legitimate owned exit through the engine), bounded by the
  series end.
* ``stop`` is terminal: the stopped marker persists and every later
  lifecycle command — including ``stop`` itself — refuses with
  ``already_stopped``; no further evaluation happens.
* Repeated/pending actions never duplicate evaluations or fills: the
  cursor advances only inside a successful engine step, and the engine's
  own journal/coid dedup still applies underneath.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal
from functools import wraps
from importlib import resources
from pathlib import Path
from threading import RLock

from krellbot import config as kb_config
from krellbot import journal as kb_journal
from krellbot import paths as kb_paths
from krellbot import run as kb_run
from krellbot.pack.model import Candle
from krellbot.venues import paper as kb_paper_venue
from krellbot.venues.paper import PaperVenue

SCHEMA_VERSION = "1"
REHEARSAL_LABEL = "Synthetic paper rehearsal — simulated data, not market-performance evidence"
SAMPLE_NOTE = (
    "Synthetic hourly candles generated for the built-in paper rehearsal example. "
    "Simulated data, not market-performance evidence; no exchange feed was read to "
    "produce these bars."
)
STATE_FILENAME = "state.json"
REHEARSAL_DIRNAME = "rehearsal"

SAMPLE_VENUE = "kraken"
SAMPLE_PAIR = "SUIUSD"
SAMPLE_PACK_ID = "rehearsal-sma-cross"
SAMPLE_BALANCE = Decimal(10000)
RECENT_FILLS_LIMIT = 20
DRIVER_CADENCE_SECONDS = 1.0

# Commands, projections and driving share one process-wide critical section.
# The API invokes these synchronously on its event loop, never in a worker
# thread: no other API handler can observe the scoped engine environment.
_OPERATIONS_LOCK = RLock()


def _serialized(method):
    @wraps(method)
    def call(*args, **kwargs):
        with _OPERATIONS_LOCK:
            return method(*args, **kwargs)

    return call


STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_EXITED = "exited"
STATUS_STOPPED = "stopped"

CODE_STARTED = "started"
CODE_PAUSED = "paused"
CODE_RESUMED = "resumed"
CODE_EXITED = "exited"
CODE_STOPPED = "stopped"
CODE_ALREADY_STARTED = "already_started"
CODE_ALREADY_PAUSED = "already_paused"
CODE_ALREADY_STOPPED = "already_stopped"
CODE_NOT_RUNNING = "not_running"
CODE_NOT_PAUSED = "not_paused"
CODE_NO_OPEN_POSITION = "no_open_position"
CODE_EXIT_BOUNDARY = "exit_boundary_reached"
CODE_UNKNOWN_COMMAND = "unknown_command"
CODE_INVALID_REQUEST = "invalid_request"
CODE_STATE_UNAVAILABLE = "state_unavailable"

COMMANDS = (
    "rehearsal.start",
    "rehearsal.pause",
    "rehearsal.resume",
    "rehearsal.exit",
    "rehearsal.stop",
)


# ---- package resources ----------------------------------------------------


def _read_resource(name: str) -> str:
    return resources.files("krellbot.application.rehearsal_resources").joinpath(name).read_text(encoding="utf-8")


def load_sample_pack() -> dict:
    """Return the shipped synthetic rehearsal pack dict (package resource)."""
    return json.loads(_read_resource("rehearsal_pack.json"))


def load_sample_candles() -> list[Candle]:
    """Return the shipped synthetic OHLCV series as ``Candle`` objects."""
    doc = json.loads(_read_resource("candles.json"))
    return [Candle.from_dict(bar) for bar in doc["candles"]]


# ---- rehearsal state ------------------------------------------------------


@dataclass(frozen=True)
class _RehearsalState:
    status: str
    cursor: int

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "status": self.status, "cursor": int(self.cursor)}


def _state_path(rehearsal_home: Path) -> Path:
    return rehearsal_home / STATE_FILENAME


def _read_state(rehearsal_home: Path) -> _RehearsalState:
    path = _state_path(rehearsal_home)
    if not path.exists():
        return _RehearsalState(status=STATUS_IDLE, cursor=0)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _RehearsalState(status=STATUS_IDLE, cursor=0)
    status = raw.get("status") if isinstance(raw, dict) else None
    cursor = raw.get("cursor") if isinstance(raw, dict) else None
    if status not in {STATUS_IDLE, STATUS_RUNNING, STATUS_PAUSED, STATUS_EXITED, STATUS_STOPPED}:
        status = STATUS_IDLE
    if not isinstance(cursor, int) or cursor < 0:
        cursor = 0
    return _RehearsalState(status=status, cursor=cursor)


def _write_state(rehearsal_home: Path, state: _RehearsalState) -> None:
    rehearsal_home.mkdir(parents=True, exist_ok=True)
    kb_paths.atomic_write(
        _state_path(rehearsal_home),
        (json.dumps(state.to_dict(), sort_keys=True) + "\n").encode("utf-8"),
    )


# ---- service --------------------------------------------------------------


class RehearsalService:
    """Drive the built-in synthetic paper rehearsal under ``home``."""

    def __init__(self, home: Path) -> None:
        self._home = Path(home)
        self._rehearsal_home = self._home / REHEARSAL_DIRNAME

    @property
    def home(self) -> Path:
        return self._home

    @property
    def rehearsal_home(self) -> Path:
        return self._rehearsal_home

    # ---- public API ------------------------------------------------------

    @_serialized
    def status_dict(self) -> dict:
        """Return the closed plain-JSON rehearsal projection.

        Computed from durable state: the cursor/control file, the venue
        state file, and the armed record — never a canned body.
        """
        state = _read_state(self._rehearsal_home)
        candles = load_sample_candles()
        venue = self._build_venue()
        # snapshot() is an execution operation: it applies stops and writes.
        # Project the loaded durable truth without invoking that operation.
        snap = kb_paper_venue._to_truth(venue._state)
        balances = {asset: format(qty, "f") for asset, qty in venue.balances().items()}
        if not balances:
            # Idle run, venue not seeded yet: project the configured start
            # so the shell can render what the rehearsal will begin from.
            balances = {"USD": format(SAMPLE_BALANCE, "f")}
        qty = venue.owned_qty(SAMPLE_PAIR)
        resting = venue.resting_stop(SAMPLE_PAIR)
        fills = [
            {
                "id": str(fill.coid),
                "coid": str(fill.coid),
                "pair": str(fill.pair),
                "side": str(fill.side),
                "qty": format(fill.qty, "f"),
                "price": format(fill.price, "f"),
                "ts_ms": int(fill.ts_ms),
            }
            for fill in snap.recent_fills[-RECENT_FILLS_LIMIT:]
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "label": REHEARSAL_LABEL,
            "status": state.status,
            "cursor": int(state.cursor),
            "total_bars": len(candles),
            "driver_cadence_seconds": DRIVER_CADENCE_SECONDS,
            "balances": balances,
            "position": {"pair": SAMPLE_PAIR, "qty": format(qty, "f")},
            "resting_stop": (format(resting, "f") if resting is not None else None),
            "recent_fills": fills,
            "entries_paused": self._entries_paused(),
        }

    @_serialized
    def handle(self, command: str, payload: dict | None = None) -> dict:
        """Run one rehearsal lifecycle command. Returns the closed result
        envelope: ``schema_version``/``code``/``ok``/``message``/``effect``
        plus the full state readback under ``rehearsal``."""
        payload = payload if payload is not None else {}
        if not isinstance(payload, dict) or payload:
            return self._refusal(CODE_INVALID_REQUEST, "rehearsal payload must be an empty object")
        if command not in COMMANDS:
            return self._refusal(CODE_UNKNOWN_COMMAND, f"unknown command {command}")

        state = _read_state(self._rehearsal_home)

        if state.status == STATUS_STOPPED:
            return self._refusal(CODE_ALREADY_STOPPED, "rehearsal already stopped")

        if command == "rehearsal.start":
            return self._start(state)
        if command == "rehearsal.pause":
            return self._pause(state)
        if command == "rehearsal.resume":
            return self._resume(state)
        if command == "rehearsal.exit":
            return self._exit(state)
        return self._stop(state)

    # ---- lifecycle -------------------------------------------------------

    def _start(self, state: _RehearsalState) -> dict:
        if state.status != STATUS_IDLE:
            return self._refusal(CODE_ALREADY_STARTED, f"rehearsal already {state.status}")
        if not self._seed():
            return self._refusal(CODE_STATE_UNAVAILABLE, "rehearsal seed failed")
        _write_state(self._rehearsal_home, _RehearsalState(status=STATUS_RUNNING, cursor=0))
        stepped = self._step()
        return self._result(
            CODE_STARTED,
            True,
            "rehearsal started on the synthetic sample",
            "changed" if stepped else "unchanged",
        )

    def _pause(self, state: _RehearsalState) -> dict:
        if state.status == STATUS_PAUSED:
            return self._refusal(CODE_ALREADY_PAUSED, "rehearsal already paused")
        if state.status not in {STATUS_RUNNING, STATUS_EXITED}:
            return self._refusal(CODE_NOT_RUNNING, f"cannot pause from {state.status}")
        changed = self._set_entries_paused(True)
        _write_state(self._rehearsal_home, _RehearsalState(status=STATUS_PAUSED, cursor=state.cursor))
        return self._result(
            CODE_PAUSED,
            True,
            "rehearsal paused: entries suppressed, protection on",
            "changed" if changed else "unchanged",
        )

    def _resume(self, state: _RehearsalState) -> dict:
        if state.status != STATUS_PAUSED:
            return self._refusal(CODE_NOT_PAUSED, f"cannot resume from {state.status}")
        changed = self._set_entries_paused(False)
        _write_state(self._rehearsal_home, _RehearsalState(status=STATUS_RUNNING, cursor=state.cursor))
        stepped = self._step()
        return self._result(
            CODE_RESUMED,
            True,
            "rehearsal resumed",
            "changed" if (stepped or changed) else "unchanged",
        )

    def _exit(self, state: _RehearsalState) -> dict:
        if state.status not in {STATUS_RUNNING, STATUS_PAUSED}:
            return self._refusal(CODE_NO_OPEN_POSITION, f"cannot exit from {state.status}")
        candles = load_sample_candles()
        if self._build_venue().owned_qty(SAMPLE_PAIR) <= 0:
            return self._refusal(CODE_NO_OPEN_POSITION, "no open rehearsal position to exit")
        cursor = state.cursor
        status = STATUS_PAUSED if state.status == STATUS_PAUSED else STATUS_RUNNING
        if status == STATUS_PAUSED:
            # Exiting while paused is the protective path: un-pause entries
            # suppression for the drive so the engine's own exit rule can
            # act, exactly as a protective exit outranks an entry hold.
            self._set_entries_paused(False)
            status = STATUS_RUNNING
        while self._build_venue().owned_qty(SAMPLE_PAIR) > 0:
            if cursor >= len(candles) - 1:
                _write_state(self._rehearsal_home, _RehearsalState(status=STATUS_RUNNING, cursor=cursor))
                return self._refusal(
                    CODE_EXIT_BOUNDARY,
                    "synthetic series ended before the pack's exit rule fired",
                )
            cursor = self._advance_once(cursor)
        self._set_entries_paused(True)
        _write_state(self._rehearsal_home, _RehearsalState(status=STATUS_EXITED, cursor=cursor))
        return self._result(CODE_EXITED, True, "rehearsal position exited by the pack's own rule", "changed")

    def _stop(self, state: _RehearsalState) -> dict:
        _write_state(self._rehearsal_home, _RehearsalState(status=STATUS_STOPPED, cursor=state.cursor))
        return self._result(CODE_STOPPED, True, "rehearsal stopped: no further evaluations", "changed")

    # ---- engine plumbing -------------------------------------------------

    @_serialized
    def drive(self) -> bool:
        """Advance the running rehearsal by one bar (real engine tick).

        Public stepping primitive: the app's background auto-drive calls
        this on a timer while the run is ``running``; tests call it
        directly. Returns True when a bar was consumed. Refuses — without
        evaluating anything — when the run is not running, is stopped, or
        has reached the end of the bounded series.
        """
        state = _read_state(self._rehearsal_home)
        if state.status != STATUS_RUNNING:
            return False
        candles = load_sample_candles()
        if state.cursor >= len(candles) - 1:
            return False
        had_position = self._build_venue().owned_qty(SAMPLE_PAIR) > 0
        cursor = self._advance_once(state.cursor)
        if had_position and self._build_venue().owned_qty(SAMPLE_PAIR) == 0:
            self._set_entries_paused(True)
            _write_state(self._rehearsal_home, _RehearsalState(status=STATUS_EXITED, cursor=cursor))
        return True

    def _seed(self) -> bool:
        """Materialize the isolated rehearsal home: the shipped pack bytes
        under ``<rehearsal>/packs/`` and the armed record via the real
        ``run.arm_pack``. Idempotent — an existing armed record wins."""
        try:
            self._rehearsal_home.mkdir(parents=True, exist_ok=True)
            pack_bytes = json.dumps(load_sample_pack(), sort_keys=True).encode("utf-8")
            pack_path = self._rehearsal_home / "packs" / "rehearsal-pack.json"
            pack_path.parent.mkdir(parents=True, exist_ok=True)
            if not pack_path.exists():
                kb_paths.atomic_write(pack_path, pack_bytes)
            with self._engine_env():
                config = kb_config.load_config(self._rehearsal_home)
                if kb_config.find_armed(config, SAMPLE_VENUE, SAMPLE_PAIR) is None:
                    rc = kb_run.arm_pack(
                        pack_path,
                        venue=SAMPLE_VENUE,
                        mode="paper",
                        paper_balance=SAMPLE_BALANCE,
                        requires_license=False,
                        home=self._rehearsal_home,
                    )
                    if rc != 0:
                        return False
            return True
        except (OSError, ValueError):
            return False

    def _step(self) -> bool:
        """Advance exactly one bar through the real engine. Returns False
        when the boundary refuses the advance."""
        state = _read_state(self._rehearsal_home)
        candles = load_sample_candles()
        if state.cursor >= len(candles) - 1:
            return False
        cursor = self._advance_once(state.cursor)
        return cursor > state.cursor

    def _advance_once(self, cursor: int) -> int:
        """Run one real tick over ``candles[: cursor + 2]``.

        The SAME cursor-bounded prefix is handed to the evaluator and the
        PaperVenue (the venue's reader), so no fill or stop can be priced
        from a bar beyond the cursor.
        """
        candles = load_sample_candles()[: cursor + 2]
        with self._engine_env():
            venue = PaperVenue(
                SAMPLE_VENUE,
                rules_provider=kb_paper_venue.default_rules,
                candle_reader=lambda _venue, _pair: list(candles),
                home=self._rehearsal_home,
                starting_cash=SAMPLE_BALANCE,
                clock=lambda: candles[-1].ts_ms / 1000,
            )
            rc = kb_run.tick(
                venue=SAMPLE_VENUE,
                venue_obj=venue,
                reader=lambda _venue, _pair: list(candles),
                journal_sink=kb_journal.append,
                clock=lambda: candles[-1].ts_ms / 1000,
                home=self._rehearsal_home,
            )
            if rc != 0:
                raise RuntimeError(f"rehearsal engine refused tick: {rc}")
        state = _read_state(self._rehearsal_home)
        new_cursor = cursor + 1
        _write_state(self._rehearsal_home, _RehearsalState(status=state.status, cursor=new_cursor))
        return new_cursor

    def _build_venue(self) -> PaperVenue:
        """Load durable venue truth over only the consumed candle prefix."""
        state = _read_state(self._rehearsal_home)
        candles = load_sample_candles()[: state.cursor + 1]

        def reader(_venue: str, _pair: str) -> list[Candle]:
            return list(candles)

        return PaperVenue(
            SAMPLE_VENUE,
            rules_provider=kb_paper_venue.default_rules,
            candle_reader=reader,
            home=self._rehearsal_home,
        )

    def _entries_paused(self) -> bool:
        config = kb_config.load_config(self._rehearsal_home)
        armed = kb_config.find_armed(config, SAMPLE_VENUE, SAMPLE_PAIR)
        return bool(armed.entries_paused) if armed is not None else False

    def _set_entries_paused(self, paused: bool) -> bool:
        with self._engine_env():
            config = kb_config.load_config(self._rehearsal_home)
            armed = kb_config.find_armed(config, SAMPLE_VENUE, SAMPLE_PAIR)
            if armed is None:
                return False
            if armed.entries_paused == paused:
                return False
            armed.entries_paused = paused
            kb_config.save_config(self._rehearsal_home, config)
        return True

    @contextlib.contextmanager
    def _engine_env(self) -> Iterator[None]:
        """Scope ``KRELLBOT_HOME`` to the rehearsal root for engine calls.

        ``run.tick``'s default journal sink and ``arm_pack``'s layout call
        resolve the home through the process environment. Restored in
        ``finally``; the window covers only synchronous engine work.
        """
        previous = os.environ.get("KRELLBOT_HOME")
        os.environ["KRELLBOT_HOME"] = str(self._rehearsal_home)
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop("KRELLBOT_HOME", None)
            else:
                os.environ["KRELLBOT_HOME"] = previous

    # ---- result envelopes -------------------------------------------------

    def _result(self, code: str, ok: bool, message: str, effect: str) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "code": code,
            "ok": ok,
            "message": message,
            "effect": effect,
            "rehearsal": self.status_dict(),
        }

    def _refusal(self, code: str, message: str) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "code": code,
            "ok": False,
            "message": message,
            "effect": "refused",
            "rehearsal": self.status_dict(),
        }


# ---- module API -----------------------------------------------------------


def rehearsal_service_for(home: Path) -> RehearsalService:
    """Build the rehearsal service bound to ``home`` (app wiring helper)."""
    return RehearsalService(home=home)

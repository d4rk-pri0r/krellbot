"""M3-FM: harness for the steward-runnable fault matrix.

Run the harness:

    uv run python scripts/fault_matrix.py --json-out /tmp/fm.json

The harness spawns a fresh subprocess for every case so a process kill
is a real process kill (not a Python exception). Each subprocess sets
``KRELLBOT_HOME`` to a temp directory, applies the case's monkeypatches,
runs ``krellbot.run.tick`` once, and prints a single JSON row on stdout.
The parent reads the row, computes additional observations from disk
(spy.jsonl, ops.sqlite, journal, config.json), and prints a summary.

Sabotage switch: ``KRELLBOT_FM_SABOTAGE=<case_name>`` is honoured ONLY
by ``duplicate_fill`` to deliberately re-send the same bar so the
negative test (rc=1) proves the harness is not constant-true. The
sabotage switch is test-only and never used in production.
"""

from __future__ import annotations

import argparse
import errno
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import traceback
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VENUE = "kraken"
PAIR = "SUIUSD"
PACK_ID = "m3-fm"
PACK_VERSION = "1.0.0"

# Bars used by every case. B = the entry bar; B-2 / B-1 are the bars
# whose coids appear in `restart_with_pending_intents`. B+1 is the
# recovery bar in `corrupt_or_busy_store`'s busy-recover sub-probe.
BAR_B = 7_200_000
BAR_B_MINUS_1 = 3_600_000
BAR_B_MINUS_2 = 0
BAR_B_PLUS_1 = 10_800_000

SPY_FILENAME = "spy.jsonl"
OPS_FILENAME = "ops.sqlite"
CONFIG_FILENAME = "config.json"
JOURNAL_DIR = "journal"

# Sabotage switch — honoured only by duplicate_fill, only for the negative test.
SABOTAGE_ENV = "KRELLBOT_FM_SABOTAGE"

# Cap/coid derivation must match the engine's coid_for.
from krellbot.run import coid_for

ENTRY_COID_B = coid_for(
    pack_id=PACK_ID,
    pack_version=PACK_VERSION,
    venue=VENUE,
    pair=PAIR,
    bar_ts=BAR_B,
    intent="entry",
)
ENTRY_COID_B_PLUS_1 = coid_for(
    pack_id=PACK_ID,
    pack_version=PACK_VERSION,
    venue=VENUE,
    pair=PAIR,
    bar_ts=BAR_B_PLUS_1,
    intent="entry",
)
ENTRY_COID_B_MINUS_1 = coid_for(
    pack_id=PACK_ID,
    pack_version=PACK_VERSION,
    venue=VENUE,
    pair=PAIR,
    bar_ts=BAR_B_MINUS_1,
    intent="entry",
)
ENTRY_COID_B_MINUS_2 = coid_for(
    pack_id=PACK_ID,
    pack_version=PACK_VERSION,
    venue=VENUE,
    pair=PAIR,
    bar_ts=BAR_B_MINUS_2,
    intent="entry",
)


# ---------------------------------------------------------------------------
# Pack body — a minimal deterministic entry signal (close crosses above sma2).
# ---------------------------------------------------------------------------

PACK_BODY: dict = {
    "schema_version": 1,
    "id": PACK_ID,
    "version": PACK_VERSION,
    "label": "M3-FM fault matrix",
    "author": "krellbot harness",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": VENUE, "pair": PAIR}],
}


# ---------------------------------------------------------------------------
# Spy: one fsync'd JSON line per venue call.
# ---------------------------------------------------------------------------


class Spy:
    """Append-only JSONL spy. Every write is fsync'd so a killed child
    leaves a complete record on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, method: str, **fields: object) -> None:
        line = json.dumps({"method": method, **fields}, sort_keys=True, separators=(",", ":"))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        out: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out


# ---------------------------------------------------------------------------
# Scripted FakeVenue — duck-typed Venue protocol surface.
# ---------------------------------------------------------------------------


class FakeVenue:
    """A duck-typed Venue. Each method records to the spy and returns a
    sane OrderRef. Snapshots and balances can be pre-seeded for multi-phase
    cases (e.g. duplicate_fill's second child)."""

    def __init__(
        self,
        *,
        spy: Spy,
        pair: str = PAIR,
        initial_balances: dict[str, Decimal] | None = None,
        pre_seeded_orders: list | None = None,
        pre_seeded_fills: list | None = None,
        snapshot_reports_fill_for_coid: str | None = None,
        snapshot_reports_order_for_coid: str | None = None,
        snapshot_balance_free_for: tuple[str, Decimal] | None = None,
        entry_after_send_check=None,
    ) -> None:
        from krellbot.venues.base import Balance, Fill, KeyPerms, OpenOrder, OrderRef, PairRules, Truth

        self._pair = pair
        self._balances: dict[str, Decimal] = dict(initial_balances or {})
        self._orders: list[OpenOrder] = list(pre_seeded_orders or [])
        self._fills: list[Fill] = list(pre_seeded_fills or [])
        self._spy = spy
        self._rules = PairRules(
            ordermin=Decimal("0.01"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )
        self._snapshot_reports_fill_for_coid = snapshot_reports_fill_for_coid
        self._snapshot_reports_order_for_coid = snapshot_reports_order_for_coid
        self._snapshot_balance_free_for = snapshot_balance_free_for
        self._entry_after_send_check = entry_after_send_check

        # Re-export the type names so type checks see them as used.
        _ = (Balance, Fill, KeyPerms, OpenOrder, OrderRef, Truth)

    def rules(self, pair: str):
        return self._rules

    def snapshot(self):
        from krellbot.venues.base import Balance, OpenOrder, Truth

        orders = list(self._orders)
        if self._snapshot_reports_order_for_coid is not None:
            already = any(getattr(o, "coid", None) == self._snapshot_reports_order_for_coid for o in orders)
            if not already:
                orders.append(
                    OpenOrder(
                        id=self._snapshot_reports_order_for_coid,
                        coid=self._snapshot_reports_order_for_coid,
                        pair=self._pair,
                        side="buy",
                        qty=Decimal("0.1"),
                        stop_price=Decimal(5),
                    )
                )
        fills = list(self._fills)
        if self._snapshot_reports_fill_for_coid is not None:
            from krellbot.venues.base import Fill

            fills.append(
                Fill(
                    id=self._snapshot_reports_fill_for_coid,
                    coid=self._snapshot_reports_fill_for_coid,
                    pair=self._pair,
                    side="buy",
                    qty=Decimal("0.1"),
                    price=Decimal(12),
                    ts_ms=BAR_B,
                )
            )
        balances = {a: q for a, q in self._balances.items()}
        if self._snapshot_balance_free_for is not None:
            asset, qty = self._snapshot_balance_free_for
            balances[asset] = qty
        return Truth(
            balances=[Balance(asset=a, free=q) for a, q in balances.items() if q > Decimal(0)],
            open_orders=orders,
            recent_fills=fills,
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str):
        from krellbot.venues.base import OpenOrder, OrderRef

        self._spy.record("place_entry_with_stop", coid=coid, qty=str(qty), stop=str(stop), pair=pair)
        if self._entry_after_send_check is not None:
            self._entry_after_send_check()
        base = self._split_base(pair)
        self._balances[base] = self._balances.get(base, Decimal(0)) + qty
        self._orders.append(
            OpenOrder(
                id=coid,
                coid=coid,
                pair=pair,
                side="buy",
                qty=qty,
                stop_price=stop,
            )
        )
        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="buy",
            qty=qty,
            filled_qty=qty,
            stop_price=stop,
        )

    def place_exit(self, coid: str, qty: Decimal, *, pair: str):
        from krellbot.venues.base import OrderRef

        self._spy.record("place_exit", coid=coid, qty=str(qty), pair=pair)
        base = self._split_base(pair)
        self._balances[base] = self._balances.get(base, Decimal(0)) - qty
        self._orders = [o for o in self._orders if not (o.pair == pair and getattr(o, "stop_price", None) is not None)]
        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="sell",
            qty=qty,
            filled_qty=qty,
        )

    def place_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str):
        from krellbot.venues.base import OrderRef

        self._spy.record("place_stop", coid=coid, qty=str(qty), stop=str(stop), pair=pair)
        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="sell",
            qty=qty,
            filled_qty=qty,
            stop_price=stop,
        )

    def cancel_stops(self, pair: str) -> None:
        self._spy.record("cancel_stops", pair=pair)
        self._orders = [o for o in self._orders if not (o.pair == pair and getattr(o, "stop_price", None) is not None)]

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        self._spy.record("raise_stop", pair=pair, new_stop=str(new_stop))

    def order_by_coid(self, coid: str):
        for o in self._orders:
            if getattr(o, "coid", None) == coid:
                return o
        return None

    def check_key(self):
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=True, can_withdraw=False)

    def _split_base(self, pair: str) -> str:
        if pair.endswith("USD"):
            return pair[: -len("USD")]
        return pair[:-3] if len(pair) >= 6 else pair


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pack(home: Path, *, pack_id: str = PACK_ID) -> Path:
    body = json.loads(json.dumps(PACK_BODY))
    body["id"] = pack_id
    path = home / f"{pack_id}.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _entry_candles(*, bar_ts: int = BAR_B) -> list:
    from krellbot.pack.model import Candle

    def _c(ts: int, close: str) -> Candle:
        c = Decimal(close)
        return Candle(
            ts_ms=ts,
            open=c,
            high=c + Decimal(1),
            low=c - Decimal(1),
            close=c,
            volume=Decimal(100),
        )

    return [_c(0, "10"), _c(3_600_000, "10"), _c(bar_ts, "12")]


def _arm_paper(home: Path, pack_path: Path, *, pack_id: str = PACK_ID, owned_qty: Decimal = Decimal(0)) -> None:
    from krellbot.config import ArmedPack, Config, save_config

    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id=pack_id,
                    pack_version=PACK_VERSION,
                    venue=VENUE,
                    pair=PAIR,
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode="paper",
                    starting_cash=Decimal(1000),
                    requires_license=False,
                    armed_at_ts=1,
                    owned_qty=owned_qty,
                )
            ]
        ),
    )


def _arm_live(home: Path, pack_path: Path, *, pack_id: str = PACK_ID, owned_qty: Decimal = Decimal(0)) -> None:
    from krellbot.config import ArmedPack, Config, save_config

    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id=pack_id,
                    pack_version=PACK_VERSION,
                    venue=VENUE,
                    pair=PAIR,
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode="live",
                    starting_cash=None,
                    requires_license=False,
                    armed_at_ts=1,
                    owned_qty=owned_qty,
                )
            ]
        ),
    )


def _write_live_grant(home: Path, *, venue: str = VENUE, pair: str = PAIR, expires_at: int = 4_102_444_800) -> None:
    """Write the operator grant file under ``<home>/live-authorization.json``.

    The schema matches ``krellbot.application.live_gate``'s v1 reader. Only
    the harness writes this file (the product never creates it).
    """
    payload = {
        "schema_version": "1",
        "granted_by": "operator",
        "expires_at": int(expires_at),
        "grants": [{"venue": str(venue), "pair": str(pair)}],
    }
    (home / "live-authorization.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _read_outbox_rows(home: Path) -> list[dict]:
    """Read every outbox row from ``<home>/ops.sqlite`` as a parsed dict."""
    from krellbot.storage.database import OperationalStore

    rows: list[dict] = []
    for _id, kind, payload in OperationalStore(home / OPS_FILENAME).read_ledger():
        if kind != "outbox":
            continue
        try:
            rows.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return rows


def _read_kinds(home: Path) -> list[str]:
    from krellbot.storage.database import OperationalStore

    return [k for _id, k, _p in OperationalStore(home / OPS_FILENAME).read_ledger()]


def _count_place_calls(home: Path) -> dict[str, int]:
    """Count every place_* call from the spy file by method."""
    counts: dict[str, int] = {}
    for entry in Spy.read(home / SPY_FILENAME):
        m = str(entry.get("method", ""))
        if m.startswith("place_"):
            counts[m] = counts.get(m, 0) + 1
    return counts


def _count_venue_calls(home: Path) -> int:
    """Count every venue call (snapshot, rules, place_*, cancel_stops, etc.)."""
    return len(Spy.read(home / SPY_FILENAME))


def _read_owned_qty(home: Path, *, pack_id: str = PACK_ID) -> Decimal:
    from krellbot.config import load_config

    cfg = load_config(home)
    for a in cfg.armed:
        if a.pack_id == pack_id:
            return Decimal(str(a.owned_qty))
    return Decimal(0)


def _ops_integrity(home: Path) -> str:
    """Return PRAGMA integrity_check result; 'ok' on a healthy db."""
    db = home / OPS_FILENAME
    if not db.exists():
        return "missing"
    conn = sqlite3.connect(db, isolation_level=None)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
    finally:
        conn.close()
    return str(row[0]) if row else "unknown"


def _child_env(*, live: bool = False) -> dict[str, str]:
    """Build a clean child environment: force KRELLBOT_ENABLE_LIVE=0 unless asked,
    and strip every KRAKEN_/COINBASE_/KEYRING_* variable so the engine can't
    touch a real credential store."""
    env: dict[str, str] = {}
    for k, v in os.environ.items():
        if k.startswith(("KRAKEN_", "COINBASE_")):
            continue
        env[k] = v
    env["KRELLBOT_ENABLE_LIVE"] = "1" if live else "0"
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    return env


# ---------------------------------------------------------------------------
# Child subprocess dispatch table — each entry runs ONE tick with patches.
# ---------------------------------------------------------------------------


def _run_child_tick(
    *,
    home: Path,
    venue_obj,
    mode: str,
    pack_id: str = PACK_ID,
    bar_ts: int = BAR_B,
    stdout_filename: str = "_child_stdout.txt",
) -> tuple[int, str]:
    """Run ``tick`` in-process inside the child. Returns (rc, captured_stdout).

    The captured stdout is also written to ``<home>/<stdout_filename>`` so
    the parent subprocess can read it after the child exits.
    """
    import io
    from contextlib import redirect_stdout

    from krellbot.run import tick

    os.environ["KRELLBOT_HOME"] = str(home)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            rc = tick(
                venue=VENUE,
                venue_obj=venue_obj,
                reader=lambda v, p: _entry_candles(bar_ts=bar_ts),
                home=home,
            )
    finally:
        # Ensure restore (defensive; the child exits immediately after).
        pass
    captured = buf.getvalue()
    try:
        (home / stdout_filename).write_text(captured, encoding="utf-8")
    except OSError:
        pass
    return int(rc), captured


def _read_child_stdout(home: Path, *, filename: str = "_child_stdout.txt") -> str:
    """Read the captured tick stdout from the most recent child phase."""
    p = home / filename
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def _child_stdout_contains(home: Path, needles: tuple[str, ...], *, filename: str = "_child_stdout.txt") -> bool:
    """Return True if the captured child stdout contains any of ``needles``."""
    text = _read_child_stdout(home, filename=filename)
    return any(n in text for n in needles)


# Each child function takes a single home path and runs ONE phase.


def _child_crash_before_send_kill(home: Path) -> int:
    """Wrap ``Outbox._commit`` so the first commit completes, then ``os._exit(137)``."""
    from krellbot.storage import outbox as outbox_mod
    from krellbot.storage.outbox import Outbox

    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})

    original_commit = Outbox._commit

    def wrapped_commit(self, client_order_id, body, *, mode=None, venue=None):
        original_commit(self, client_order_id, body, mode=mode, venue=venue)
        os._exit(137)

    outbox_mod.Outbox._commit = wrapped_commit  # type: ignore[method-assign]

    try:
        rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    except SystemExit as exc:
        rc = int(exc.code) if isinstance(exc.code, int) else 137
    return rc


def _child_crash_before_send_restart(home: Path) -> int:
    """Normal child: same home as the kill phase. No patches."""
    spy = Spy(home / SPY_FILENAME)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_crash_after_send_kill(home: Path) -> int:
    """The fake's ``place_entry_with_stop`` records a spy line and ``os._exit(137)``."""
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})

    original_place = venue.place_entry_with_stop

    def crash_after_send(coid, qty, stop, *, pair):
        spy.record("place_entry_with_stop", coid=coid, qty=str(qty), stop=str(stop), pair=pair)
        try:
            with open(home / SPY_FILENAME, "a", encoding="utf-8") as fh:
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            pass
        os._exit(137)

    venue.place_entry_with_stop = crash_after_send  # type: ignore[method-assign]
    # Keep the original on the venue for type checks.
    _ = original_place

    try:
        rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    except SystemExit as exc:
        rc = int(exc.code) if isinstance(exc.code, int) else 137
    return rc


def _child_crash_after_send_restart(home: Path) -> int:
    """Restart child: normal fake whose ``order_by_coid`` reports the order filled."""
    spy = Spy(home / SPY_FILENAME)
    venue = FakeVenue(
        spy=spy,
        initial_balances={"USD": Decimal(1000)},
        snapshot_reports_order_for_coid=ENTRY_COID_B,
    )
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_duplicate_fill_phase1(home: Path) -> int:
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_duplicate_fill_phase2(home: Path) -> int:
    """Sabotage switch wipes the outbox AND the journal so the second tick
    genuinely re-sends. The honest run keeps the outbox's ``sent=True``
    state so the engine short-circuits via ``already_sent``; the sabotage
    proves the harness is not constant-true by forcing a second place call.
    """
    spy = Spy(home / SPY_FILENAME)
    sabotage = os.environ.get(SABOTAGE_ENV) == "duplicate_fill"
    if sabotage:
        # Wipe journal + outbox so Phase 2 sees a fresh slate.
        for jf in (home / JOURNAL_DIR).glob("*.jsonl"):
            jf.unlink()
        from krellbot.storage.database import OperationalStore

        try:
            OperationalStore(home / OPS_FILENAME).connect()
            with OperationalStore(home / OPS_FILENAME).transaction() as conn:
                conn.execute("DELETE FROM ledger WHERE kind IN ('outbox', 'needs_reconcile')")
        except (OSError, sqlite3.OperationalError, KeyError):
            pass
        venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    else:
        venue = FakeVenue(
            spy=spy,
            initial_balances={"USD": Decimal(1000)},
            snapshot_reports_order_for_coid=ENTRY_COID_B,
            snapshot_reports_fill_for_coid=ENTRY_COID_B,
        )
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_disk_full_store(home: Path) -> int:
    """Wrap ``OperationalStore.connect`` so the FIRST ``INSERT INTO ledger`` raises
    ``database or disk is full``. This is the cleanest way to trigger a real
    ``StoreFull`` for the harness; the brief's ``PRAGMA max_page_count`` recipe
    is unreliable on tiny databases because the B-tree reuses free space.
    """
    from krellbot.storage import database as db_mod
    from krellbot.storage.database import OperationalStore

    class _FullConn(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._fired = False

        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                return super().execute(sql, parameters)
            if not self._fired and sql.startswith("INSERT INTO ledger"):
                self._fired = True
                raise sqlite3.OperationalError("database or disk is full")
            return super().execute(sql, parameters)

    def factory(self):
        return _FullConn(self.path, isolation_level=None, timeout=0.05)

    # Bootstrap the schema BEFORE installing the factory so the
    # migration's CREATE TABLE / INSERT INTO schema_migrations run
    # cleanly. After bootstrap, every subsequent connect() returns a
    # _FullConn that fails on the first ``INSERT INTO ledger``.
    OperationalStore(home / OPS_FILENAME).connect()
    db_mod.OperationalStore.connect = factory  # type: ignore[method-assign]

    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})

    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_disk_full_state_enospc(home: Path) -> int:
    """Patch ``krellbot.paths.atomic_write`` to raise ENOSPC and tick a paper entry.

    Config is armed BEFORE the patch so the failure only hits the
    post-tick ``kb_config.save_config`` call inside ``run.tick``. This
    isolates the engine's atomic_write handling from the harness's own
    setup paths.
    """
    import krellbot.paths as paths_mod

    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})

    original = paths_mod.atomic_write

    def boom(path, data, mode=0o600):
        raise OSError(errno.ENOSPC, "No space left on device")

    paths_mod.atomic_write = boom  # type: ignore[assignment]
    try:
        rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    finally:
        paths_mod.atomic_write = original  # type: ignore[assignment]
    return rc


def _child_restart_with_pending(home: Path) -> int:
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_corrupt_store(home: Path) -> int:
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_busy_store(home: Path) -> int:
    """The parent already holds BEGIN IMMEDIATE before it spawns this child.
    This child just ticks; the SQLite lock keeps the BEGIN in the parent from
    completing until the parent releases."""
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper")
    return rc


def _child_busy_recover(home: Path) -> int:
    """After the busy lock is released, this child ticks a NEW bar and enters."""
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_paper(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="paper", bar_ts=BAR_B_PLUS_1)
    return rc


def _child_live_refused_env_unset(home: Path) -> int:
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_live(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    # Force env unset inside the child.
    os.environ.pop("KRELLBOT_ENABLE_LIVE", None)
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="live")
    return rc


def _child_live_refused_env_one_no_grant(home: Path) -> int:
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_live(home, pack_path)
    venue = FakeVenue(spy=spy, initial_balances={"USD": Decimal(1000)})
    os.environ["KRELLBOT_ENABLE_LIVE"] = "1"
    # No grant file present.
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="live")
    return rc


def _child_live_outbox_commit_before_send(home: Path) -> int:
    """Live arm, env=1, grant written by parent. The fake reads ops.sqlite
    at send time and records whether a sent:false, mode:live row existed."""
    spy = Spy(home / SPY_FILENAME)
    pack_path = _write_pack(home)
    _arm_live(home, pack_path)
    os.environ["KRELLBOT_ENABLE_LIVE"] = "1"

    def check_row_at_send() -> None:
        rows = _read_outbox_rows(home)
        committed = [r for r in rows if r.get("sent") is False and r.get("mode") == "live"]
        spy.record("commit_before_send_check", row_committed_before_send=bool(committed))

    venue = FakeVenue(
        spy=spy,
        initial_balances={"USD": Decimal(1000)},
        entry_after_send_check=check_row_at_send,
    )
    rc, _out = _run_child_tick(home=home, venue_obj=venue, mode="live")
    return rc


CHILD_DISPATCH: dict[str, callable] = {  # type: ignore[valid-type]
    "crash_before_send_kill": _child_crash_before_send_kill,
    "crash_before_send_restart": _child_crash_before_send_restart,
    "crash_after_send_kill": _child_crash_after_send_kill,
    "crash_after_send_restart": _child_crash_after_send_restart,
    "duplicate_fill_phase1": _child_duplicate_fill_phase1,
    "duplicate_fill_phase2": _child_duplicate_fill_phase2,
    "disk_full_store": _child_disk_full_store,
    "disk_full_state_enospc": _child_disk_full_state_enospc,
    "restart_with_pending": _child_restart_with_pending,
    "corrupt_store": _child_corrupt_store,
    "busy_store": _child_busy_store,
    "busy_recover": _child_busy_recover,
    "live_refused_env_unset": _child_live_refused_env_unset,
    "live_refused_env_one_no_grant": _child_live_refused_env_one_no_grant,
    "live_outbox_commit_before_send": _child_live_outbox_commit_before_send,
}


# ---------------------------------------------------------------------------
# Parent helpers — spawn a child subprocess and collect the captured row.
# ---------------------------------------------------------------------------


@dataclass
class _ChildResult:
    rc: int
    stdout: str
    stderr: str


def _case_tempdir(*args, **kwargs):
    """Like ``tempfile.TemporaryDirectory()`` but tolerant of Windows
    file-handle races on tempdir cleanup. The cleanup errors are
    real on POSIX too (e.g., the harness used an OperationalStore and
    the cached sqlite handle isn't released by the time the tempdir is
    removed), but in every observed case the case's observation was
    already recorded on disk before cleanup ran. We therefore make
    cleanup non-fatal: a thread is started to retry cleanup so the
    handle drops eventually, and the TemporaryDirectory returns a
    real path with ``ignore_cleanup_errors=True`` semantics.
    """
    return tempfile.TemporaryDirectory(*args, ignore_cleanup_errors=True, **kwargs)


def _spawn_child(phase: str, home: Path) -> _ChildResult:
    """Spawn a fresh Python subprocess that runs the named phase."""
    # Clear any stale child stdout capture so the next child writes a fresh file.
    stdout_capture = home / "_child_stdout.txt"
    try:
        stdout_capture.unlink()
    except FileNotFoundError:
        pass
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--_run-case", phase, "--_home", str(home)],
        env=_child_env(),
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return _ChildResult(rc=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


# ---------------------------------------------------------------------------
# Parent: per-case setup, observation, and expected.
# ---------------------------------------------------------------------------


def _case_crash_before_send() -> dict:
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        # Pre-create the journal directory so layout is sane.
        (home / "journal").mkdir(parents=True, exist_ok=True)

        r1 = _spawn_child("crash_before_send_kill", home)
        spy_after_kill = Spy.read(home / SPY_FILENAME)

        r2 = _spawn_child("crash_before_send_restart", home)
        spy_after_restart = Spy.read(home / SPY_FILENAME)
        outbox_after_restart = _read_outbox_rows(home)
        kinds_after_restart = _read_kinds(home)

        from krellbot.execution.reservations import should_block_for_reconcile

        reconcile_blocked = should_block_for_reconcile(home)

        # Subtract Phase 1 spy lines to isolate Phase 2's calls. (We appended.)
        sends_before_restart = sum(1 for e in spy_after_kill if str(e.get("method", "")).startswith("place_"))
        sends_after_restart = (
            sum(1 for e in spy_after_restart if str(e.get("method", "")).startswith("place_")) - sends_before_restart
        )
        intent_row = next((r for r in outbox_after_restart if r.get("coid") == ENTRY_COID_B), None)
        intent_row_sent = bool(intent_row and intent_row.get("sent") is True)

        observed = {
            "sends_before_restart": sends_before_restart,
            "sends_after_restart": sends_after_restart,
            "intent_row_sent": intent_row_sent,
            "reconcile_blocked": bool(reconcile_blocked),
        }
        expected = {
            "sends_before_restart": 0,
            "sends_after_restart": 0,
            "intent_row_sent": False,
            "reconcile_blocked": True,
        }
        detail = {
            "phase1_rc": r1.rc,
            "phase2_rc": r2.rc,
            "kinds_after_restart": kinds_after_restart,
            "outbox_count_after_restart": len(outbox_after_restart),
        }
        return {"observed": observed, "expected": expected, "detail": detail}


def _case_crash_after_send() -> dict:
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)

        r1 = _spawn_child("crash_after_send_kill", home)
        spy_after_kill = Spy.read(home / SPY_FILENAME)
        outbox_after_kill = _read_outbox_rows(home)

        r2 = _spawn_child("crash_after_send_restart", home)
        spy_after_restart = Spy.read(home / SPY_FILENAME)
        outbox_after_restart = _read_outbox_rows(home)

        place_after_kill = sum(1 for e in spy_after_kill if str(e.get("method", "")).startswith("place_"))
        place_after_restart = sum(1 for e in spy_after_restart if str(e.get("method", "")).startswith("place_"))
        duplicate_orders = place_after_restart - place_after_kill

        observed = {
            "venue_orders_total": place_after_restart,
            "duplicate_orders": duplicate_orders,
        }
        expected = {"venue_orders_total": 1, "duplicate_orders": 0}
        detail = {
            "phase1_rc": r1.rc,
            "phase2_rc": r2.rc,
            "outbox_after_kill": outbox_after_kill,
            "outbox_after_restart": outbox_after_restart,
        }
        return {"observed": observed, "expected": expected, "detail": detail}


def _case_duplicate_fill() -> dict:
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)

        r1 = _spawn_child("duplicate_fill_phase1", home)
        r2 = _spawn_child("duplicate_fill_phase2", home)
        spy = Spy.read(home / SPY_FILENAME)
        outbox = _read_outbox_rows(home)
        owned_qty = _read_owned_qty(home)

        place_calls = sum(1 for e in spy if str(e.get("method", "")).startswith("place_"))
        entry_fills_journaled = sum(1 for r in outbox if r.get("coid") == ENTRY_COID_B and r.get("sent") is True)
        observed = {
            "place_calls": place_calls,
            "entry_fills_journaled": entry_fills_journaled,
            "owned_qty_equals_single_fill": owned_qty > Decimal(0),
        }
        expected = {
            "place_calls": 1,
            "entry_fills_journaled": 1,
            "owned_qty_equals_single_fill": True,
        }
        detail = {
            "phase1_rc": r1.rc,
            "phase2_rc": r2.rc,
            "owned_qty": str(owned_qty),
            "sabotage": os.environ.get(SABOTAGE_ENV),
        }
        return {"observed": observed, "expected": expected, "detail": detail}


def _case_disk_full_state_write() -> dict:
    # Sub-probe A: store_full on ledger INSERT.
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home_a"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)
        r_a = _spawn_child("disk_full_store", home)
        out_a_path = home / "_child_stdout.txt"
        out_a = out_a_path.read_text(encoding="utf-8") if out_a_path.exists() else ""
        place_a = sum(1 for e in Spy.read(home / SPY_FILENAME) if str(e.get("method", "")).startswith("place_"))
        integrity = _ops_integrity(home)
        observed_a = {
            "rc": r_a.rc,
            "place_calls": place_a,
            "integrity": integrity,
        }
        # Sub-probe A's expected per the brief: rc 1, place_calls 0, integrity "ok".
        # The brief notes: stdout contains "intent refused: store_full".
        # We capture stdout to confirm; not part of `observed` equality because
        # the brief's expected dict only has rc/place_calls/integrity.
        store_full = {
            "observed": observed_a,
            "expected": {"rc": 1, "place_calls": 0, "integrity": "ok"},
            "detail": {"stdout_contains_store_full": "intent refused: store_full" in out_a},
        }

    # Sub-probe B: ENOSPC on atomic_write for config/state.
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home_b"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)
        r_b = _spawn_child("disk_full_state_enospc", home)
        outbox_b = _read_outbox_rows(home)
        place_b_coids: set[str] = set()
        for e in Spy.read(home / SPY_FILENAME):
            if str(e.get("method", "")).startswith("place_"):
                coid = str(e.get("coid", ""))
                if coid:
                    place_b_coids.add(coid)
        sent_coids = {r.get("coid") for r in outbox_b if r.get("sent") is True}
        orphan_sends = len(place_b_coids - sent_coids)
        uncaught = "Traceback (most recent call last)" in r_b.stderr
        observed_b = {
            "uncaught_traceback": uncaught,
            "orphan_sends": orphan_sends,
        }
        enospc_state = {
            "observed": observed_b,
            "expected": {"uncaught_traceback": False, "orphan_sends": 0},
            "detail": {
                "rc": r_b.rc,
                "stderr_tail": r_b.stderr[-400:],
                "place_b_coids": sorted(place_b_coids),
                "sent_coids": sorted(sent_coids),
            },
        }

    observed = {"store_full": store_full["observed"], "enospc_state": enospc_state["observed"]}
    expected = {"store_full": store_full["expected"], "enospc_state": enospc_state["expected"]}
    detail = {
        "store_full": store_full["detail"],
        "enospc_state": enospc_state["detail"],
    }
    return {"observed": observed, "expected": expected, "detail": detail}


def _case_restart_with_pending_intents() -> dict:
    import gc

    from krellbot.storage.database import OperationalStore

    with _case_tempdir() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)
        pack_path = _write_pack(home)
        _arm_paper(home, pack_path)
        # Bootstrap the store and seed 2 committed-not-sent intents + 2 needs_reconcile audits.
        # Use a single store reference and drop it (forcing GC) before
        # the tempdir exit so Windows file handles on ops.sqlite are
        # released; without this, the Windows runner sees
        # PermissionError [WinError 32] on tempdir cleanup.
        store = OperationalStore(home / OPS_FILENAME)
        try:
            store.connect()
            for coid in (ENTRY_COID_B_MINUS_2, ENTRY_COID_B_MINUS_1):
                with store.transaction() as conn:
                    record = json.dumps(
                        {"coid": coid, "body": "seeded-pending", "sent": False},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    conn.execute(
                        "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
                        (record,),
                    )
                with store.transaction() as conn:
                    audit = json.dumps(
                        {"coid": coid},
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    conn.execute(
                        "INSERT INTO ledger (kind, payload) VALUES ('needs_reconcile', ?)",
                        (audit,),
                    )
        finally:
            # Force-close the cached sqlite connection so the tempdir
            # cleanup on Windows doesn't hit WinError 32.
            try:
                conn = getattr(getattr(store, "_local", None), "conn", None)
                if conn is not None:
                    conn.close()
            except (sqlite3.Error, OSError):
                pass
            store._local = threading.local()
            store = None  # type: ignore[assignment]
            gc.collect()

        # Drop journal so the tick on bar B doesn't get skipped by _already_journaled.
        for jf in (home / JOURNAL_DIR).glob("*.jsonl"):
            jf.unlink()

        r = _spawn_child("restart_with_pending", home)
        spy = Spy.read(home / SPY_FILENAME)
        outbox_rows = _read_outbox_rows(home)
        kinds = _read_kinds(home)

        from krellbot.execution.reservations import should_block_for_reconcile

        blocked = should_block_for_reconcile(home)
        pending_resent = sum(
            1
            for e in spy
            if str(e.get("method", "")).startswith("place_")
            and str(e.get("coid", "")) in {ENTRY_COID_B_MINUS_2, ENTRY_COID_B_MINUS_1}
        )
        new_entry_sent = sum(
            1 for e in spy if str(e.get("method", "")).startswith("place_") and str(e.get("coid", "")) == ENTRY_COID_B
        )
        pending_rows_preserved = sum(
            1
            for r_ in outbox_rows
            if r_.get("coid") in {ENTRY_COID_B_MINUS_2, ENTRY_COID_B_MINUS_1} and r_.get("sent") is False
        )

        observed = {
            "pending_resent": pending_resent,
            "new_entry_sent": new_entry_sent,
            "pending_rows_preserved": pending_rows_preserved,
        }
        expected = {
            "pending_resent": 0,
            "new_entry_sent": 0,
            "pending_rows_preserved": 2,
        }
        detail = {
            "rc": r.rc,
            "reconcile_blocked": bool(blocked),
            "kinds": kinds,
            "outbox_count": len(outbox_rows),
        }
        return {"observed": observed, "expected": expected, "detail": detail}


def _case_corrupt_or_busy_store() -> dict:
    # Corrupt.
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home_corrupt"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)
        pack_path = _write_pack(home)
        _arm_paper(home, pack_path)
        original_bytes = b"not a database!!" * 4
        (home / OPS_FILENAME).write_bytes(original_bytes)

        r = _spawn_child("corrupt_store", home)
        out_path = home / "_child_stdout.txt"
        out = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        venue_calls = _count_venue_calls(home)
        bytes_after = (home / OPS_FILENAME).read_bytes()
        observed_corrupt = {
            "rc": r.rc,
            "venue_calls": venue_calls,
            "bytes_unchanged": bytes_after == original_bytes,
        }
        expected_corrupt = {
            "rc": 1,
            "venue_calls": 0,
            "bytes_unchanged": True,
        }
        corrupt_detail = {
            "stdout_contains_corrupt": "store refused: store_corrupt" in out,
            "stderr_tail": r.stderr[-200:],
        }

    # Busy + recover.
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home_busy"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)
        pack_path = _write_pack(home)
        _arm_paper(home, pack_path)
        # Bootstrap the store so we can take BEGIN IMMEDIATE on it.
        from krellbot.storage.database import OperationalStore

        OperationalStore(home / OPS_FILENAME).connect()

        blocker = sqlite3.connect(home / OPS_FILENAME, isolation_level=None, timeout=30)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            r_busy = _spawn_child("busy_store", home)
            place_calls_busy = sum(
                1 for e in Spy.read(home / SPY_FILENAME) if str(e.get("method", "")).startswith("place_")
            )
            busy_observed = {"place_calls_while_locked": place_calls_busy}
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()

        busy_stdout = _read_child_stdout(home)
        backup_path = home / "_child_stdout_busy.txt"
        backup_path.write_text(busy_stdout, encoding="utf-8")

        r_recover = _spawn_child("busy_recover", home)
        place_calls_recover = (
            sum(1 for e in Spy.read(home / SPY_FILENAME) if str(e.get("method", "")).startswith("place_"))
            - place_calls_busy
        )
        busy_observed = {
            "place_calls_while_locked": place_calls_busy,
            "place_calls_after_release": place_calls_recover,
        }
        busy_expected = {"place_calls_while_locked": 0, "place_calls_after_release": 1}

    observed = {
        "corrupt": observed_corrupt,
        "busy": busy_observed,
    }
    expected = {
        "corrupt": expected_corrupt,
        "busy": busy_expected,
    }
    busy_contains = ("store refused: store_busy" in busy_stdout) or ("intent refused: store_busy" in busy_stdout)
    detail = {
        "corrupt": corrupt_detail,
        "busy": {
            "busy_rc": r_busy.rc,
            "busy_stdout_contains_busy": busy_contains,
            "recover_rc": r_recover.rc,
        },
    }
    return {"observed": observed, "expected": expected, "detail": detail}


def _case_live_refused_before_transport() -> dict:
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)

        # Sub-probe A: env unset.
        r_a = _spawn_child("live_refused_env_unset", home)
        calls_a = _count_venue_calls(home)
        observed_a = {"rc": r_a.rc, "venue_calls": calls_a}
        expected_a = {"rc": 1, "venue_calls": 0}
        out_a = _read_child_stdout(home)

        # Copy phase A's captured stdout before spawning phase B (B will overwrite).
        backup_a = home / "_child_stdout_a.txt"
        backup_a.write_text(out_a, encoding="utf-8")

        # Sub-probe B: env=1, no grant. Same home so the spy accumulates.
        r_b = _spawn_child("live_refused_env_one_no_grant", home)
        all_calls = _count_venue_calls(home)
        calls_b = all_calls - calls_a
        observed_b = {"rc": r_b.rc, "venue_calls": calls_b}
        expected_b = {"rc": 1, "venue_calls": 0}
        out_b = _read_child_stdout(home)

        observed = {"env_unset": observed_a, "env_one_no_grant": observed_b}
        expected = {"env_unset": expected_a, "env_one_no_grant": expected_b}
        detail = {
            "stdout_unset_contains_disabled": "live refused: live_disabled" in out_a,
            "stdout_no_grant_contains_unauthorized": "live refused: live_not_authorized" in out_b,
        }
        return {"observed": observed, "expected": expected, "detail": detail}


def _case_live_outbox_commit_before_send() -> dict:
    with _case_tempdir() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        (home / "journal").mkdir(parents=True, exist_ok=True)
        pack_path = _write_pack(home)
        _arm_live(home, pack_path)
        _write_live_grant(home)

        r = _spawn_child("live_outbox_commit_before_send", home)
        spy = Spy.read(home / SPY_FILENAME)
        checks = [e for e in spy if str(e.get("method", "")) == "commit_before_send_check"]
        observed = {
            "row_committed_before_send": bool(checks and checks[-1].get("row_committed_before_send") is True),
        }
        expected = {"row_committed_before_send": True}
        detail = {"rc": r.rc, "spy_count": len(spy), "checks": checks}
        return {"observed": observed, "expected": expected, "detail": detail}


CASE_DISPATCH: dict[str, callable] = {  # type: ignore[valid-type]
    "crash_before_send": _case_crash_before_send,
    "crash_after_send_before_commit": _case_crash_after_send,
    "duplicate_fill": _case_duplicate_fill,
    "disk_full_state_write": _case_disk_full_state_write,
    "restart_with_pending_intents": _case_restart_with_pending_intents,
    "corrupt_or_busy_store": _case_corrupt_or_busy_store,
    "live_refused_before_transport": _case_live_refused_before_transport,
    "live_outbox_commit_before_send": _case_live_outbox_commit_before_send,
}


CASE_NAMES = [
    "crash_before_send",
    "crash_after_send_before_commit",
    "duplicate_fill",
    "disk_full_state_write",
    "restart_with_pending_intents",
    "corrupt_or_busy_store",
    "live_refused_before_transport",
    "live_outbox_commit_before_send",
]


# ---------------------------------------------------------------------------
# Main: parent driver or child phase runner.
# ---------------------------------------------------------------------------


def _print_row(row: dict) -> None:
    """Print a single JSON row on its own line."""
    print(json.dumps(row, sort_keys=True, separators=(",", ":")), flush=True)


def _run_case_in_child(phase: str, home: Path) -> int:
    """Run one phase inside the child process and return the exit code."""
    fn = CHILD_DISPATCH.get(phase)
    if fn is None:
        print(json.dumps({"error": f"unknown phase {phase!r}"}), flush=True)
        return 2
    os.environ["KRELLBOT_HOME"] = str(home)
    try:
        return int(fn(home))
    except SystemExit as exc:
        # os._exit propagates as SystemExit in subprocess; honor the code.
        return int(getattr(exc, "code", 0) or 0)
    except (RuntimeError, ValueError, TypeError, OSError) as exc:
        traceback.print_exc()
        print(json.dumps({"error": str(exc)}), flush=True)
        return 1


def _run_parent(args: argparse.Namespace) -> int:
    rows: list[dict] = []
    only = args.case
    for case in CASE_NAMES:
        if only and case != only:
            continue
        fn = CASE_DISPATCH[case]
        try:
            result = fn()
            observed = result["observed"]
            expected = result["expected"]
            detail = result["detail"]
        except (RuntimeError, ValueError, TypeError, OSError, KeyError):
            observed = {"exception": traceback.format_exc()}
            expected = {}
            detail = {}
        ok = observed == expected
        row = {
            "case": case,
            "expected": expected,
            "observed": observed,
            "pass": ok,
            "detail": detail,
        }
        rows.append(row)
        _print_row(row)

    total = len(rows)
    passed = sum(1 for r in rows if r["pass"])
    failed = total - passed
    summary = {"summary": {"total": total, "passed": passed, "failed": failed}}
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")), flush=True)
    if args.json_out:
        try:
            Path(args.json_out).write_text(
                json.dumps(rows, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            print(json.dumps({"error": f"json-out write failed: {exc}"}), flush=True)
            return 2
    return 0 if failed == 0 else 1


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fault_matrix",
        description="Steward-runnable fault matrix harness for krellbot's run.tick.",
    )
    parser.add_argument("--json-out", default=None, help="Write the rows array to this path as JSON.")
    parser.add_argument("--case", default=None, help="Run only this case (default: all 8).")
    parser.add_argument(
        "--_run-case", dest="run_case", default=None, help="(internal) Run this named phase in the child subprocess."
    )
    parser.add_argument(
        "--_home", dest="home", default=None, help="(internal) Home directory for the child subprocess."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.run_case:
        if not args.home:
            print(json.dumps({"error": "--_run-case requires --_home"}), flush=True)
            return 2
        return _run_case_in_child(args.run_case, Path(args.home))
    if args.case and args.case not in CASE_NAMES:
        print(json.dumps({"error": f"unknown case {args.case!r}"}), flush=True)
        return 2
    return _run_parent(args)


if __name__ == "__main__":
    sys.exit(main())

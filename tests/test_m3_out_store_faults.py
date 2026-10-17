"""M3-OUT C: store faults are typed and fail closed.

Coverage:

  test_corrupt_store_refuses_paper_tick_with_zero_venue_calls
  test_corrupt_store_refuses_live_tick_with_zero_venue_calls
  test_busy_store_paper_entry_has_intent_refused_and_no_place
  test_busy_store_recovers_on_next_bar
  test_full_store_paper_entry_has_intent_refused_store_full
  test_write_classifies_known_operational_errors
  test_write_classifies_oserror_enospc
  test_write_releases_lock_after_translate
  test_store_error_subclass_relationships_and_codes
"""

from __future__ import annotations

import errno
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.live_grant import write_grant

from krellbot.config import ArmedPack, Config, save_config
from krellbot.pack.model import Candle
from krellbot.storage.database import OperationalStore as Store
from krellbot.storage.database import (
    StoreBusy,
    StoreCorrupt,
    StoreError,
    StoreFull,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


_PACK_BODY = {
    "schema_version": 1,
    "id": "m3-out-store",
    "version": "1.0.0",
    "label": "M3-OUT store faults",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _write_pack(home: Path, pack_id: str) -> Path:
    body = json.loads(json.dumps(_PACK_BODY))
    body["id"] = pack_id
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path, *, pack_id: str) -> None:
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id=pack_id,
                    pack_version="1.0.0",
                    venue="kraken",
                    pair="SUIUSD",
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode="paper",
                    starting_cash=Decimal(1000),
                    requires_license=False,
                    armed_at_ts=1,
                )
            ]
        ),
    )


def _arm_live(home: Path, pack_path: Path, *, pack_id: str) -> None:
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id=pack_id,
                    pack_version="1.0.0",
                    venue="kraken",
                    pair="SUIUSD",
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode="live",
                    starting_cash=None,
                    requires_license=False,
                    armed_at_ts=1,
                )
            ]
        ),
    )


class _FakeVenue:
    def __init__(self, *, balances: dict[str, Decimal] | None = None) -> None:
        self._balances: dict[str, Decimal] = dict(balances or {"USD": Decimal(1000)})
        self.place_calls: list[str] = []

    def rules(self, pair: str):
        from krellbot.venues.base import PairRules

        return PairRules(
            ordermin=Decimal("0.01"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )

    def snapshot(self):
        from krellbot.venues.base import Balance, Truth

        return Truth(
            balances=[Balance(asset=a, free=q) for a, q in self._balances.items() if q > Decimal(0)],
            open_orders=[],
            recent_fills=[],
        )

    def place_entry_with_stop(self, coid, qty, stop, *, pair):
        self.place_calls.append(f"entry:{coid}")

        from krellbot.venues.base import OrderRef

        return OrderRef(id=coid, coid=coid, pair=pair, side="buy", qty=qty, filled_qty=qty, stop_price=stop)

    def place_exit(self, coid, qty, *, pair):
        self.place_calls.append(f"exit:{coid}")

        from krellbot.venues.base import OrderRef

        return OrderRef(id=coid, coid=coid, pair=pair, side="sell", qty=qty, filled_qty=qty)

    def place_stop(self, coid, qty, stop, *, pair):
        self.place_calls.append(f"stop:{coid}")

        from krellbot.venues.base import OrderRef

        return OrderRef(id=coid, coid=coid, pair=pair, side="sell", qty=qty, filled_qty=qty, stop_price=stop)

    def cancel_stops(self, pair):
        self.place_calls.append("cancel_stops")

    def raise_stop(self, pair, new_stop):
        self.place_calls.append("raise_stop")

    def order_by_coid(self, coid):
        return None

    def check_key(self):
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=True, can_withdraw=False)


def _candle(ts_ms: int, close: str) -> Candle:
    c = Decimal(close)
    return Candle(
        ts_ms=ts_ms,
        open=c,
        high=c + Decimal(1),
        low=c - Decimal(1),
        close=c,
        volume=Decimal(100),
    )


def _entry_signal_candles() -> list[Candle]:
    return [_candle(0, "10"), _candle(3_600_000, "10"), _candle(7_200_000, "12")]


# ---------------------------------------------------------------------------
# Test 12: corrupt store — both paper and live ticks refuse with zero calls.
# ---------------------------------------------------------------------------


def test_corrupt_store_refuses_paper_tick_with_zero_venue_calls(home, monkeypatch, capsys):
    """ops.sqlite holds garbage; paper tick returns 1, prints store refused,
    and makes zero venue calls; file bytes are unchanged.
    """
    from krellbot.run import tick

    pack_id = "m3-store-corrupt-paper"
    pack_path = _write_pack(home, pack_id)
    _arm_paper(home, pack_path, pack_id=pack_id)
    db_path = home / "ops.sqlite"
    original_bytes = b"not a database!!" * 4
    db_path.write_bytes(original_bytes)
    venue = _FakeVenue()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    out = capsys.readouterr().out
    assert rc == 1, rc
    assert "store refused: store_corrupt" in out, out
    assert venue.place_calls == [], venue.place_calls
    assert db_path.read_bytes() == original_bytes


def test_corrupt_store_refuses_live_tick_with_zero_venue_calls(home, monkeypatch, capsys):
    """ops.sqlite holds garbage; live tick (grant+env) returns 1 with zero calls."""
    from krellbot.run import tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair="SUIUSD")
    pack_id = "m3-store-corrupt-live"
    pack_path = _write_pack(home, pack_id)
    _arm_live(home, pack_path, pack_id=pack_id)
    db_path = home / "ops.sqlite"
    original_bytes = b"not a database!!" * 4
    db_path.write_bytes(original_bytes)
    venue = _FakeVenue()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    out = capsys.readouterr().out
    assert rc == 1, rc
    assert "store refused: store_corrupt" in out, out
    assert venue.place_calls == [], venue.place_calls
    assert db_path.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# Test 13: busy store — intent_refused, no place, recovers next bar.
# ---------------------------------------------------------------------------


def test_busy_store_paper_entry_has_intent_refused_and_no_place(home, monkeypatch, capsys):
    """Another sqlite3 connection holds BEGIN IMMEDIATE on ops.sqlite while a
    paper tick with an entry signal runs. No place call; tick detail has
    intent_refused: 'store_busy'; tick returns 1.
    """
    from krellbot.run import tick

    pack_id = "m3-store-busy"
    pack_path = _write_pack(home, pack_id)
    _arm_paper(home, pack_path, pack_id=pack_id)
    blocker = sqlite3.connect(home / "ops.sqlite", isolation_level=None, timeout=30)
    blocker.execute("BEGIN IMMEDIATE")

    try:
        venue = _FakeVenue()
        rc = tick(
            venue="kraken",
            venue_obj=venue,
            reader=lambda v, p: _entry_signal_candles(),
            home=home,
        )
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    assert rc == 1, rc
    assert venue.place_calls == [], venue.place_calls

    journal_dir = home / "journal"
    seen = False
    for jf in sorted(journal_dir.glob("*.jsonl")):
        for line in jf.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                d.get("kind") == "tick"
                and d.get("pack") == pack_id
                and d.get("detail", {}).get("intent_refused") == "store_busy"
            ):
                seen = True
    assert seen, "intent_refused=store_busy must appear in the tick detail"


def test_busy_store_recovers_on_next_bar(home, monkeypatch):
    """After the busy lock is released, a second tick on a NEW bar enters normally."""
    from krellbot.run import tick

    pack_id = "m3-store-busy-recover"
    pack_path = _write_pack(home, pack_id)
    _arm_paper(home, pack_path, pack_id=pack_id)
    blocker = sqlite3.connect(home / "ops.sqlite", isolation_level=None, timeout=30)
    blocker.execute("BEGIN IMMEDIATE")

    try:
        venue = _FakeVenue()
        rc_busy = tick(
            venue="kraken",
            venue_obj=venue,
            reader=lambda v, p: _entry_signal_candles(),
            home=home,
        )
        assert rc_busy == 1
    finally:
        blocker.execute("ROLLBACK")
        blocker.close()

    venue2 = _FakeVenue()
    rc_ok = tick(
        venue="kraken",
        venue_obj=venue2,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    assert rc_ok == 0, rc_ok
    assert any(c.startswith("entry:") for c in venue2.place_calls), venue2.place_calls


# ---------------------------------------------------------------------------
# Test 14: full store — intent_refused=store_full, _Write maps errors.
# ---------------------------------------------------------------------------


def test_full_store_paper_entry_has_intent_refused_store_full(home, monkeypatch, capsys):
    """A SQLite FULL on the ledger INSERT.

    The brief's recipe (``PRAGMA max_page_count``) is unreliable on small
    databases because the B-tree reuses free space. We patch
    ``OperationalStore.connect`` with a wrapper that returns a
    ``sqlite3.Connection`` subclass whose ``execute`` injects
    ``database or disk is full`` after the BEGIN goes through, so the
    next INSERT raises the exact message the brief lists.
    """
    from krellbot.run import tick
    from krellbot.storage import database as db_mod

    pack_id = "m3-store-full"
    pack_path = _write_pack(home, pack_id)
    _arm_paper(home, pack_path, pack_id=pack_id)
    bootstrap = Store(home / "ops.sqlite")
    bootstrap.connect()
    del bootstrap

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

    monkeypatch.setattr(db_mod.OperationalStore, "connect", factory)

    venue = _FakeVenue()
    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )

    assert rc == 1, rc
    assert venue.place_calls == [], venue.place_calls

    journal_dir = home / "journal"
    seen = False
    for jf in sorted(journal_dir.glob("*.jsonl")):
        for line in jf.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                d.get("kind") == "tick"
                and d.get("pack") == pack_id
                and d.get("detail", {}).get("intent_refused") == "store_full"
            ):
                seen = True
    assert seen, "intent_refused=store_full must appear in the tick detail"


def test_write_classifies_known_operational_errors(home, monkeypatch) -> None:
    """_Write maps sqlite3.OperationalError messages to the right StoreError.

    The mapping lives in two places: ``_Write.__enter__`` (BEGIN IMMEDIATE)
    and ``_Write.__exit__`` (COMMIT). Both branches go through the same
    classifier; a custom Connection subclass overrides ``execute`` so the
    first BEGIN goes through and any later statement raises.
    """
    from krellbot.storage import database as db_mod

    class _RaisingConn(sqlite3.Connection):
        """A sqlite3.Connection subclass that injects a custom error after BEGIN."""

        def __init__(self, *args, exc_to_raise=None, **kwargs):
            super().__init__(*args, **kwargs)
            self._exc_to_raise = exc_to_raise

        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                return super().execute(sql, parameters)
            if self._exc_to_raise is not None:
                exc = self._exc_to_raise
                self._exc_to_raise = None
                raise exc
            return super().execute(sql, parameters)

    for msg, expected_cls in [
        ("database or disk is full", StoreFull),
        ("database is locked", StoreBusy),
        ("database disk image is malformed", StoreCorrupt),
    ]:
        path = home / f"write-cls-{msg.split()[1]}.sqlite"
        captured_msg = msg

        def _factory(*args, kwargs_msg=captured_msg, **kwargs):
            return _RaisingConn(*args, **kwargs, exc_to_raise=sqlite3.OperationalError(kwargs_msg))

        original_connect = sqlite3.connect
        monkeypatch.setattr(sqlite3, "connect", _factory)
        try:
            store = db_mod.OperationalStore(path)
            with pytest.raises(expected_cls), store.transaction():
                store.connect().execute("INSERT INTO ledger (kind, payload) VALUES ('x', '{}')")
        finally:
            monkeypatch.setattr(sqlite3, "connect", original_connect)


def test_write_classifies_oserror_enospc(home, monkeypatch) -> None:
    """OSError(errno.ENOSPC, ...) → StoreFull."""
    from krellbot.storage import database as db_mod

    class _RaisingConn(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._fired = False

        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                return super().execute(sql, parameters)
            if not self._fired:
                self._fired = True
                raise OSError(errno.ENOSPC, "no space")
            return super().execute(sql, parameters)

    def _factory(*args, **kwargs):
        return _RaisingConn(*args, **kwargs)

    original_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", _factory)
    try:
        store = db_mod.OperationalStore(home / "enospc.sqlite")
        with pytest.raises(StoreFull), store.transaction():
            store.connect().execute("INSERT INTO ledger (kind, payload) VALUES ('x', '{}')")
    finally:
        monkeypatch.setattr(sqlite3, "connect", original_connect)


def test_write_releases_lock_after_translate(home, monkeypatch) -> None:
    """After _Write translates an error, the in-process lock is released:
    a following ``transaction()`` must succeed.
    """
    from krellbot.storage import database as db_mod

    class _RaisingConn(sqlite3.Connection):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._fired = False

        def execute(self, sql, parameters=()):
            if sql == "BEGIN IMMEDIATE":
                return super().execute(sql, parameters)
            if not self._fired:
                self._fired = True
                raise sqlite3.OperationalError("database is locked")
            return super().execute(sql, parameters)

    def _factory(*args, **kwargs):
        return _RaisingConn(*args, **kwargs)

    original_connect = sqlite3.connect
    monkeypatch.setattr(sqlite3, "connect", _factory)
    try:
        store = db_mod.OperationalStore(home / "lock-recover.sqlite")
        with pytest.raises(StoreBusy), store.transaction():
            store.connect().execute("INSERT INTO ledger (kind, payload) VALUES ('x', '{}')")
    finally:
        monkeypatch.setattr(sqlite3, "connect", original_connect)

    assert store._held is False, store._held
    assert not store._write.locked(), "threading.Lock should not be held"

    with store.transaction() as fresh_conn:
        fresh_conn.execute("INSERT INTO ledger (kind, payload) VALUES ('ok', '{}')")


# ---------------------------------------------------------------------------
# Test 15: StoreError hierarchy and codes.
# ---------------------------------------------------------------------------


def test_store_error_subclass_relationships_and_codes() -> None:
    assert issubclass(StoreBusy, StoreError)
    assert issubclass(StoreBusy, RuntimeError)
    assert issubclass(StoreCorrupt, StoreError)
    assert issubclass(StoreCorrupt, RuntimeError)
    assert issubclass(StoreFull, StoreError)
    assert issubclass(StoreFull, RuntimeError)

    assert StoreBusy("x").code == "store_busy"
    assert StoreCorrupt("x").code == "store_corrupt"
    assert StoreFull("x").code == "store_full"
    assert StoreError("x").code == "store_error"

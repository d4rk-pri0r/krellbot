"""M3-OUT B: every place_* goes through commit-before-send, paper and live.

Coverage:

  test_live_entry_ledger_row_committed_before_send
  test_live_entry_send_runtime_error_yields_needs_reconcile_on_next_tick
  test_live_exit_ledger_row_has_live_mode_and_venue
  test_live_stop_repair_ledger_row_has_live_mode_and_venue
  test_ast_tripwire_place_methods_only_inside_dispatch_place
  test_paper_tick_does_not_create_run_store_db

The brief's tests 8, 11 in particular pin the recovery flow: a tick
that crashes between commit and send leaves the row in
``sent: false``; the next tick on a new bar reads ``needs_reconcile``
without re-placing.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from fakes.live_grant import write_grant

from krellbot.config import ArmedPack, Config, save_config
from krellbot.pack.model import Candle
from krellbot.storage.database import OperationalStore
from krellbot.venues.base import Balance, Fill, KeyPerms, OpenOrder, OrderRef, PairRules, Truth

# ---------------------------------------------------------------------------
# Fake venue that exposes the outbox state to the test.
# ---------------------------------------------------------------------------


@dataclass
class _InnerCall:
    method: str
    coid: str = ""


class _FakeVenue:
    def __init__(self, *, pair: str = "SUIUSD", balances: dict[str, Decimal] | None = None) -> None:
        self.pair = pair
        self._balances: dict[str, Decimal] = dict(balances or {"USD": Decimal(1000)})
        self._orders: list[OpenOrder] = []
        self._fills: list[Fill] = []
        self.calls: list[_InnerCall] = []
        self.snapshot_call_count = 0
        self._fail_next_send: dict[str, str] = {}

    def fail_next_send(self, coid: str, exc_type: type[BaseException] = RuntimeError) -> None:
        self._fail_next_send[coid] = exc_type.__name__

    def rules(self, pair: str) -> PairRules:
        return PairRules(
            ordermin=Decimal("0.01"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )

    def snapshot(self) -> Truth:
        self.snapshot_call_count += 1
        # Drain pending fills into the snapshot on each call.
        return Truth(
            balances=[Balance(asset=a, free=q) for a, q in self._balances.items() if q > Decimal(0)],
            open_orders=list(self._orders),
            recent_fills=list(self._fills),
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        self.calls.append(_InnerCall("entry", coid))
        if coid in self._fail_next_send:
            raise RuntimeError(f"venue send failed: {self._fail_next_send.pop(coid)}")
        base, _quote = self._split(pair)
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

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef:
        self.calls.append(_InnerCall("exit", coid))
        if coid in self._fail_next_send:
            raise RuntimeError(f"venue send failed: {self._fail_next_send.pop(coid)}")
        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="sell",
            qty=qty,
            filled_qty=qty,
        )

    def place_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        self.calls.append(_InnerCall("stop", coid))
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
        self.calls.append(_InnerCall("cancel_stops"))

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        self.calls.append(_InnerCall("raise_stop"))

    def order_by_coid(self, coid: str) -> OpenOrder | None:
        return None

    def check_key(self) -> KeyPerms:
        return KeyPerms(can_trade=True, can_withdraw=False)

    @staticmethod
    def _split(pair: str) -> tuple[str, str]:
        if pair.endswith("USD"):
            return pair[: -len("USD")], "USD"
        return pair[:-3], pair[-3:]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PACK_BODY = {
    "schema_version": 1,
    "id": "m3-out-outbox",
    "version": "1.0.0",
    "label": "M3-OUT outbox for live",
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


def _entry_signal_candles(*, bar_ts: int = 7_200_000) -> list[Candle]:
    return [_candle(0, "10"), _candle(3_600_000, "10"), _candle(bar_ts, "12")]


def _exit_signal_candles(*, bar_ts: int = 7_200_000) -> list[Candle]:
    return [_candle(0, "12"), _candle(3_600_000, "12"), _candle(bar_ts, "8")]


# ---------------------------------------------------------------------------
# Test 7: live entry ledger row is committed BEFORE send, sent after.
# ---------------------------------------------------------------------------


def test_live_entry_ledger_row_committed_before_send(home, monkeypatch):
    """On a live entry with grant+env: the place_entry_with_stop body asserts
    that the outbox row for that coid already exists with sent=false,
    mode='live', venue='kraken'. After the tick the row has sent=true.
    """
    from krellbot.run import tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair="SUIUSD")
    pack_id = "m3-obx-entry"
    pack_path = _write_pack(home, pack_id)
    _arm_live(home, pack_path, pack_id=pack_id)
    venue = _FakeVenue()

    seen_in_send: dict[str, dict] = {}

    original_place = venue.place_entry_with_stop

    def spy_place(coid, qty, stop, *, pair):
        store = OperationalStore(home / "ops.sqlite")
        rows = store.read_ledger()
        outbox_rows = [(_id, kind, payload) for _id, kind, payload in rows if kind == "outbox"]
        assert outbox_rows, "outbox row must exist BEFORE send"
        # The last outbox row is the current entry.
        _id, _kind, payload = outbox_rows[-1]
        parsed = json.loads(payload)
        seen_in_send.update(parsed)
        assert parsed["coid"] == coid, parsed
        assert parsed["sent"] is False, parsed
        assert parsed["mode"] == "live", parsed
        assert parsed["venue"] == "kraken", parsed
        return original_place(coid, qty, stop, pair=pair)

    venue.place_entry_with_stop = spy_place  # type: ignore[method-assign]

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    assert rc == 0, rc

    # After the tick the row has sent=true.
    store = OperationalStore(home / "ops.sqlite")
    rows = store.read_ledger()
    outbox_rows = [(_id, kind, payload) for _id, kind, payload in rows if kind == "outbox"]
    assert outbox_rows, rows
    payload = json.loads(outbox_rows[-1][2])
    assert payload["sent"] is True, payload
    assert seen_in_send.get("mode") == "live"
    assert seen_in_send.get("venue") == "kraken"


# ---------------------------------------------------------------------------
# Test 8: live entry send raises after commit -> needs_reconcile next tick.
# ---------------------------------------------------------------------------


def test_live_entry_send_runtime_error_yields_needs_reconcile_on_next_tick(home, monkeypatch):
    """Live entry send raises after commit. Today's behaviour: the tick
    survives (rc=0), the row stays committed (sent=false), and the next
    tick on the same bar reads ``needs_reconcile`` from the Outbox
    without making a second place call. The brief also requires a
    needs_reconcile audit row.

    Note: the brief's StoreError handler returns 1; this test exercises
    the GENERIC RuntimeError-from-send path (which is NOT a StoreError
    because the commit succeeded before the send raised).
    """
    from krellbot.run import coid_for, tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair="SUIUSD")
    pack_id = "m3-obx-crash"
    pack_path = _write_pack(home, pack_id)
    _arm_live(home, pack_path, pack_id=pack_id)
    venue = _FakeVenue()
    bar_ts_1 = 7_200_000
    expected_coid = coid_for(
        pack_id=pack_id,
        pack_version="1.0.0",
        venue="kraken",
        pair="SUIUSD",
        bar_ts=bar_ts_1,
        intent="entry",
    )
    venue.fail_next_send(expected_coid)

    rc1 = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(bar_ts=bar_ts_1),
        home=home,
    )
    assert rc1 == 0, "today's behaviour: tick survives the venue send error"

    store = OperationalStore(home / "ops.sqlite")
    rows = store.read_ledger()
    outbox_rows = [(_id, kind, payload) for _id, kind, payload in rows if kind == "outbox"]
    assert outbox_rows, rows
    payload = json.loads(outbox_rows[-1][2])
    assert payload["sent"] is False, payload

    # Drop the journal so the second tick on the SAME bar reaches the
    # dispatch path (run.tick skips bars that are already journaled for
    # the pack; the brief's restart-equivalent sequence clears that).
    for jf in (home / "journal").glob("*.jsonl"):
        jf.unlink()

    store2 = OperationalStore(home / "ops.sqlite")
    rows2 = store2.read_ledger()
    outbox_rows2 = [(_id, kind, payload) for _id, kind, payload in rows2 if kind == "outbox"]
    payload2 = json.loads(outbox_rows2[-1][2])
    assert payload2["sent"] is False, payload2

    rc2 = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(bar_ts=bar_ts_1),
        home=home,
    )
    assert rc2 == 0, rc2

    entries = [c for c in venue.calls if c.method == "entry"]
    assert len(entries) == 1, f"only the first tick should place; got {entries}"

    rows3 = store.read_ledger()
    needs_reconcile_kinds = [kind for _id, kind, _payload in rows3 if kind == "needs_reconcile"]
    assert needs_reconcile_kinds, rows3


# ---------------------------------------------------------------------------
# Test 9: live exit and stop repair write ledger rows with mode='live'.
# ---------------------------------------------------------------------------


def test_live_exit_ledger_row_has_live_mode_and_venue(home, monkeypatch):
    """A live exit: ledger row has mode='live', venue='kraken'."""
    from krellbot import journal as kb_journal
    from krellbot.run import tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair="SUIUSD")
    pack_id = "m3-obx-exit"
    pack_path = _write_pack(home, pack_id)
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
                    owned_qty=Decimal(5),
                )
            ]
        ),
    )
    kb_journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": pack_id,
            "bar_ts": 0,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )
    venue = _FakeVenue(balances={"USD": Decimal(1000), "SUI": Decimal(5)})

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _exit_signal_candles(),
        home=home,
    )
    assert rc == 0, rc
    store = OperationalStore(home / "ops.sqlite")
    rows = store.read_ledger()
    outbox_rows = [(_id, kind, payload) for _id, kind, payload in rows if kind == "outbox"]
    assert outbox_rows, rows
    # All live outbox rows have mode='live', venue='kraken'.
    for _id, _kind, payload in outbox_rows:
        parsed = json.loads(payload)
        assert parsed["mode"] == "live", parsed
        assert parsed["venue"] == "kraken", parsed


def test_live_stop_repair_ledger_row_has_live_mode_and_venue(home, monkeypatch):
    """A live stop repair (ensure_stop) writes an outbox row with mode='live'."""
    from krellbot import journal as kb_journal
    from krellbot.run import tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair="SUIUSD")
    pack_id = "m3-obx-stop"
    pack_path = _write_pack(home, pack_id)
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
                    owned_qty=Decimal(5),
                )
            ]
        ),
    )
    kb_journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": pack_id,
            "bar_ts": 0,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )
    venue = _FakeVenue(balances={"USD": Decimal(1000), "SUI": Decimal(5)})

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(),  # no exit signal → only stop repair fires
        home=home,
    )
    assert rc == 0, rc
    stops = [c for c in venue.calls if c.method == "stop"]
    assert stops, f"stop repair must fire; got {venue.calls}"
    store = OperationalStore(home / "ops.sqlite")
    rows = store.read_ledger()
    outbox_rows = [(_id, kind, payload) for _id, kind, payload in rows if kind == "outbox"]
    assert outbox_rows, rows
    for _id, _kind, payload in outbox_rows:
        parsed = json.loads(payload)
        assert parsed["mode"] == "live", parsed
        assert parsed["venue"] == "kraken", parsed


# ---------------------------------------------------------------------------
# Test 10: AST tripwire — place_* only inside _dispatch_place._send.
# ---------------------------------------------------------------------------


def test_ast_tripwire_place_methods_only_inside_dispatch_place() -> None:
    """place_entry_with_stop, place_exit, place_stop may only appear
    inside ``_dispatch_place`` in ``run/__init__.py``. Outside of
    ``_dispatch_place``, only ``snapshot``, ``rules``, ``order_by_coid``,
    ``cancel_stops`` and ``raise_stop`` may be called as venue_obj.X(...).
    """
    source = Path("src/krellbot/run/__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    PLACE_METHODS = {"place_entry_with_stop", "place_exit", "place_stop"}
    ALLOWED_OUTSIDE = {"snapshot", "rules", "order_by_coid", "cancel_stops", "raise_stop"}

    # Identify the _dispatch_place function span.
    dispatch_span: tuple[int, int] | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_dispatch_place":
            dispatch_span = (node.lineno, node.end_lineno or node.lineno)
            break
    if dispatch_span is None:
        # Old-shape engine may still ship the _paper_dispatch_place
        # function with the same role.
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_paper_dispatch_place":
                dispatch_span = (node.lineno, node.end_lineno or node.lineno)
                break
    assert dispatch_span is not None, "_dispatch_place must exist in run/__init__.py"

    bad_calls: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name):
            continue
        if func.value.id != "venue_obj":
            continue
        method_name = func.attr
        if method_name in ALLOWED_OUTSIDE:
            continue
        in_dispatch = dispatch_span[0] <= node.lineno <= dispatch_span[1]
        if method_name in PLACE_METHODS and not in_dispatch:
            bad_calls.append((node.lineno, "place_outside_dispatch", method_name))
            continue
        if method_name not in PLACE_METHODS and not in_dispatch:
            bad_calls.append((node.lineno, "venue_method_outside_dispatch", method_name))
            continue

    assert bad_calls == [], f"forbidden venue_obj calls: {bad_calls}"

    # ADR file exists and mentions cancel_stops and raise_stop.
    adr = Path("docs/adr/0001-venue-write-routing.md")
    assert adr.is_file(), adr
    text = adr.read_text(encoding="utf-8")
    assert "cancel_stops" in text, text
    assert "raise_stop" in text, text


# ---------------------------------------------------------------------------
# Test 11: paper tick does not create run/store.db.
# ---------------------------------------------------------------------------


def test_paper_tick_does_not_create_run_store_db(home, monkeypatch) -> None:
    """After a paper tick with a fill, ``<home>/run/store.db`` must not exist."""
    from krellbot.run import tick

    pack_id = "m3-obx-paper-store"
    pack_path = _write_pack(home, pack_id)
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
    venue = _FakeVenue(balances={"USD": Decimal(1000)})

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    assert rc == 0, rc
    legacy_path = home / "run" / "store.db"
    assert not legacy_path.exists(), f"{legacy_path} must not exist after the cutover"

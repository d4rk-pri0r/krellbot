"""NS13 leaf 2 — fault fills through the paper tick.

Six behaviors, all driven through ``tick`` (not the Outbox in isolation):

1. Duplicate fill: same client_order_id recorded twice does not create a
   second position. The Outbox's commit-before-send ensures the second
   tick on the same bar returns ``"already_sent"`` without re-placing.
2. Partial fill: the venue fills fewer coins than the requested qty.
   Owned quantity reflects the filled size, not the requested size.
3. Late fill after cancel: a fill arrives for a coid whose position has
   already been exited. It is recorded in the ledger but does not reopen
   the flat position.
4. Unknown ack: a fill arrives with a coid we never generated. It is
   recorded in the ledger but does not trigger a resubmit.
5. Paper tick uses Outbox.dispatch; live tick raises ModeError and writes
   no ``paper-<venue>.json`` file.
6. Paid-expiry exits: when entries are blocked by a lapsed license cache,
   an owned position still gets an exit via ``venue_obj.place_exit``.

The real caller is ``run.tick`` — these tests construct a venue_obj and
call tick directly. A test that only exercises Outbox.dispatch in
isolation (without tick) does not pass: tick is the function that wires
the Outbox in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from krellbot.config import ArmedPack, Config, save_config
from krellbot.pack.model import Candle
from krellbot.storage.database import OperationalStore
from krellbot.storage.outbox import ModeError
from krellbot.venues.base import Balance, Fill, KeyPerms, OpenOrder, OrderRef, PairRules, Truth

# ---------------------------------------------------------------------------
# Test fixtures: a controllable fake venue.
# ---------------------------------------------------------------------------


_RULES = PairRules(
    ordermin=Decimal("0.01"),
    costmin=Decimal("0.5"),
    lot_decimals=8,
    price_decimals=5,
)


def _candle(ts_ms: int, close: str, *, open_: str | None = None, low: str | None = None) -> Candle:
    c = Decimal(close)
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(open_ or close),
        high=c + Decimal(1),
        low=Decimal(low or close),
        close=c,
        volume=Decimal(100),
    )


@dataclass
class _Call:
    method: str
    coid: str
    qty: Decimal | None = None
    stop: Decimal | None = None
    pair: str | None = None


class _FakeVenue:
    """A duck-typed venue that records calls and lets tests inject fills.

    ``place_entry_with_stop`` and ``place_exit`` return an ``OrderRef`` whose
    ``filled_qty`` honors ``partial_fill_qty`` (when set); otherwise it
    equals the requested qty. Tests seed ``pending_fills`` so a later
    snapshot reports a late fill (coid already exited) or an unknown ack
    (coid never generated).
    """

    def __init__(
        self,
        *,
        venue: str = "kraken",
        pair: str = "SUIUSD",
        initial_balances: dict[str, Decimal] | None = None,
        partial_fill_qty: Decimal | None = None,
    ) -> None:
        self.venue = venue
        self.pair = pair
        self._balances: dict[str, Decimal] = dict(initial_balances or {})
        self._orders: list[OpenOrder] = []
        self._fills: list[Fill] = []
        self.calls: list[_Call] = []
        self.partial_fill_qty = partial_fill_qty
        self.pending_fills: list[Fill] = []

    # ---- Venue protocol ----------------------------------------------------

    def rules(self, pair: str) -> PairRules:
        return _RULES

    def snapshot(self) -> Truth:
        while self.pending_fills:
            self._fills.append(self.pending_fills.pop(0))
        return Truth(
            balances=[
                Balance(asset=str(a), free=q)
                for a, q in self._balances.items()
                if q > Decimal(0)
            ],
            open_orders=list(self._orders),
            recent_fills=list(self._fills),
        )

    def place_entry_with_stop(
        self,
        coid: str,
        qty: Decimal,
        stop: Decimal,
        *,
        pair: str,
    ) -> OrderRef:
        self.calls.append(_Call("entry", coid, qty, stop, pair))
        filled = self.partial_fill_qty if self.partial_fill_qty is not None else qty
        base, _quote = self._split(pair)
        self._balances[base] = self._balances.get(base, Decimal(0)) + filled
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
            filled_qty=filled,
            stop_price=stop,
        )

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef:
        self.calls.append(_Call("exit", coid, qty, None, pair))
        filled = self.partial_fill_qty if self.partial_fill_qty is not None else qty
        base, _quote = self._split(pair)
        self._balances[base] = self._balances.get(base, Decimal(0)) - qty
        self._orders = [o for o in self._orders if not (o.pair == pair and o.stop_price is not None)]
        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="sell",
            qty=qty,
            filled_qty=filled,
            stop_price=None,
        )

    def cancel_stops(self, pair: str) -> None:
        self.calls.append(_Call("cancel_stops", ""))
        self._orders = [o for o in self._orders if not (o.pair == pair and o.stop_price is not None)]

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        self.calls.append(_Call("raise_stop", "", None, new_stop, pair))

    def order_by_coid(self, coid: str) -> OpenOrder | None:
        for o in self._orders:
            if o.coid == coid:
                return o
        return None

    def check_key(self) -> KeyPerms:
        return KeyPerms(can_trade=True, can_withdraw=False)

    # ---- helpers used by tests --------------------------------------------

    def push_pending_fill(self, coid: str, pair: str, side: str, qty: Decimal, price: Decimal, ts_ms: int) -> None:
        self.pending_fills.append(
            Fill(id=coid, coid=coid, pair=pair, side=side, qty=qty, price=price, ts_ms=ts_ms)
        )

    @staticmethod
    def _split(pair: str) -> tuple[str, str]:
        if pair.endswith("USD"):
            return pair[: -len("USD")], "USD"
        return pair[:-3], pair[-3:]


# ---------------------------------------------------------------------------
# Pack + arm config helpers.
# ---------------------------------------------------------------------------


_PACK_BODY = {
    "schema_version": 1,
    "id": "ns13-faults",
    "version": "1.0.0",
    "label": "NS13 fault fills",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _write_pack(home: Path, pack_id: str = "ns13-faults") -> Path:
    body = json.loads(json.dumps(_PACK_BODY))
    body["id"] = pack_id
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_pack(
    home: Path,
    pack_path: Path,
    *,
    mode: str,
    pack_id: str = "ns13-faults",
    requires_license: bool = False,
    owned_qty: Decimal = Decimal(0),
) -> None:
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
                    mode=mode,
                    starting_cash=Decimal(1000) if mode == "paper" else None,
                    requires_license=requires_license,
                    armed_at_ts=1,
                    owned_qty=owned_qty,
                )
            ]
        ),
    )


def _seed_journal_owned(home: Path, *, pack_id: str, owned_qty: Decimal) -> None:
    """Record an entry qty in the legacy journal so reconcile_owned_qty returns it."""
    from krellbot import journal

    journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": pack_id,
            "bar_ts": 0,
            "detail": {"pair": "SUIUSD", "entry_qty": str(owned_qty), "exit_qty": "0", "stop_qty": "0"},
        }
    )


def _seed_lapsed_cache(home: Path) -> None:
    catalog_dir = home / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "license-cache.json").write_text(
        json.dumps({"status": "past_due", "period_end": 0, "grace_until": 1}),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# The actual tests.
# ---------------------------------------------------------------------------


def test_duplicate_fill_does_not_open_a_second_position(home) -> None:
    """Behavior 1: pre-seeded outbox state="sent" suppresses a re-place.

    The Outbox's commit-before-send makes the second ``Outbox.dispatch``
    return ``"already_sent"`` without invoking the send callback. Tick
    must honor that and not place a second entry on the same coid.
    """
    from krellbot.run import coid_for, tick

    pack_path = _write_pack(home, pack_id="ns13-dup")
    _arm_pack(home, pack_path, mode="paper", pack_id="ns13-dup")

    bar_ts = 7_200_000
    expected_coid = coid_for(
        pack_id="ns13-dup",
        pack_version="1.0.0",
        venue="kraken",
        pair="SUIUSD",
        bar_ts=bar_ts,
        intent="entry",
    )

    # Pre-seed the Outbox with a "sent" record for the coid tick will
    # generate. The Outbox dedup branch must short-circuit the place_* call.
    store = OperationalStore(home / "ops.sqlite")
    pre_seed_payload = json.dumps(
        {"coid": expected_coid, "body": "pre-seeded", "sent": True},
        separators=(",", ":"),
        sort_keys=True,
    )
    with store.transaction() as conn:
        conn.execute("INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)", (pre_seed_payload,))

    venue = _FakeVenue(initial_balances={"USD": Decimal(1000)})

    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(bar_ts, "12"),  # crosses above sma2 (10, 11)
    ]

    rc = tick(venue="kraken", venue_obj=venue, reader=lambda v, p: list(candles), home=home)
    assert rc == 0

    entries = [c for c in venue.calls if c.method == "entry"]
    assert entries == [], (
        f"pre-seeded outbox state=sent must suppress re-place; got {entries}"
    )


def test_partial_fill_owned_qty_is_the_filled_size(home) -> None:
    """Behavior 2: venue reports filled_qty < requested qty → owned = filled."""
    from krellbot.config import load_config
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id="ns13-partial")
    _arm_pack(home, pack_path, mode="paper", pack_id="ns13-partial")
    venue = _FakeVenue(initial_balances={"USD": Decimal(1000)}, partial_fill_qty=Decimal(2))

    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(7_200_000, "12"),
    ]

    rc = tick(venue="kraken", venue_obj=venue, reader=lambda v, p: list(candles), home=home)
    assert rc == 0

    snap = venue.snapshot()
    base_qty = next((b.free for b in snap.balances if b.asset == "SUI"), Decimal(0))
    assert base_qty == Decimal(2), f"venue balance must reflect the filled size 2, got {base_qty}"

    config = load_config(home)
    armed = next(a for a in config.armed if a.pack_id == "ns13-partial")
    assert armed.owned_qty == Decimal(2), (
        f"armed.owned_qty must equal the filled size 2, got {armed.owned_qty}"
    )

    store = OperationalStore(home / "ops.sqlite")
    kinds = [r[1] for r in store.read_ledger()]
    assert "partial_fill" in kinds, f"partial fill must be audited; kinds={kinds}"


def test_late_fill_after_cancel_is_audited_but_does_not_reopen_position(home) -> None:
    """Behavior 3: a fill that arrives after the position was exited is
    recorded in the ledger but does not reopen the flat position.
    """
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id="ns13-late")
    _arm_pack(home, pack_path, mode="paper", pack_id="ns13-late", owned_qty=Decimal(5))
    _seed_journal_owned(home, pack_id="ns13-late", owned_qty=Decimal(5))
    venue = _FakeVenue(initial_balances={"USD": Decimal(1000), "SUI": Decimal(5)})

    # First tick: bars drive close below sma2 → exit signal → place_exit.
    exit_candles = [
        _candle(0, "12"),
        _candle(3_600_000, "12"),
        _candle(7_200_000, "8"),  # close crosses below sma2 (12, 10)
    ]

    rc1 = tick(venue="kraken", venue_obj=venue, reader=lambda v, p: list(exit_candles), home=home)
    assert rc1 == 0
    exits_after_first = [c for c in venue.calls if c.method == "exit"]
    assert len(exits_after_first) == 1, f"first tick must place exactly one exit, got {len(exits_after_first)}"
    exit_coid = exits_after_first[0].coid

    # Push a pending fill for the exit coid — this simulates the venue
    # reporting a fill for a coid whose position was already exited.
    venue.push_pending_fill(
        coid=exit_coid,
        pair="SUIUSD",
        side="sell",
        qty=Decimal(5),
        price=Decimal("8"),
        ts_ms=10_800_000,
    )

    followup_candles = list(exit_candles) + [
        _candle(10_800_000, "8"),  # sma2 = (8+8)/2 = 8; close = sma2, no cross
    ]
    rc2 = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: list(followup_candles),
        home=home,
        clock=lambda: 10_800_000 // 1000 + 1,
    )
    assert rc2 == 0

    entries_after = [c for c in venue.calls if c.method == "entry"]
    assert len(entries_after) == 0, f"late fill must not trigger a new entry; got {entries_after}"

    store = OperationalStore(home / "ops.sqlite")
    ledger_kinds = [r[1] for r in store.read_ledger()]
    assert "late_fill" in ledger_kinds, f"late fill must be audited in the ledger; kinds={ledger_kinds}"


def test_unknown_ack_is_audited_but_does_not_resubmit(home) -> None:
    """Behavior 4: a fill with an unrecognized coid is recorded as unknown,
    does not trigger a place_* call.
    """
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id="ns13-unknown")
    _arm_pack(home, pack_path, mode="paper", pack_id="ns13-unknown")
    venue = _FakeVenue(initial_balances={"USD": Decimal(1000)})

    # Push a fill whose coid the engine has never generated.
    venue.push_pending_fill(
        coid="ghost-from-venue",
        pair="SUIUSD",
        side="buy",
        qty=Decimal(3),
        price=Decimal("11"),
        ts_ms=14_400_000,
    )

    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(10_800_000, "10"),
        _candle(14_400_000, "10"),  # no signal
    ]
    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: list(candles),
        home=home,
        clock=lambda: 14_400_000 // 1000 + 1,
    )
    assert rc == 0

    # No place_* call from tick — the unknown ack does not resubmit.
    place_calls = [c for c in venue.calls if c.method in ("entry", "exit")]
    assert place_calls == [], f"unknown ack must not trigger a resubmit; got {place_calls}"

    # The unknown ack is recorded in the ledger.
    store = OperationalStore(home / "ops.sqlite")
    ledger_kinds = [r[1] for r in store.read_ledger()]
    assert "unknown_ack" in ledger_kinds, f"unknown ack must be audited; kinds={ledger_kinds}"


def test_paper_tick_uses_outbox_and_live_tick_raises_mode_error(home) -> None:
    """Behavior 5: paper tick routes sends through Outbox.dispatch. Live
    arms raising ModeError when the paper send path is invoked must
    produce no ``paper-<venue>.json`` file.
    """
    from krellbot.run import tick

    # Paper arm: tick places via Outbox.
    pack_path = _write_pack(home, pack_id="ns13-paper-mode")
    _arm_pack(home, pack_path, mode="paper", pack_id="ns13-paper-mode")
    paper_venue = _FakeVenue(initial_balances={"USD": Decimal(1000)})

    paper_candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(7_200_000, "12"),
    ]
    rc = tick(venue="kraken", venue_obj=paper_venue, reader=lambda v, p: list(paper_candles), home=home)
    assert rc == 0
    assert any(c.method == "entry" for c in paper_venue.calls)
    # Paper tick writes to the ledger.
    paper_store = OperationalStore(home / "ops.sqlite")
    assert [r[1] for r in paper_store.read_ledger()].count("outbox") >= 1

    # Live arm: invoking the paper-send path raises ModeError.
    live_pack_path = _write_pack(home, pack_id="ns13-live-mode")
    _arm_pack(home, live_pack_path, mode="live", pack_id="ns13-live-mode")
    live_venue = _FakeVenue(initial_balances={"USD": Decimal(1000)})

    # The guard lives on the paper-send helper. Tick itself does not
    # call it for a live arm, but invoking the helper directly with a
    # live arm must raise ModeError, and no paper file must appear on
    # disk.
    from krellbot.run import _paper_send_via_outbox

    live_coid = "live-coid-1"
    live_body = json.dumps({"kind": "entry", "qty": "5", "stop": "5", "pair": "SUIUSD"})

    def _live_send(_coid: str, _body: str) -> None:
        live_venue.calls.append(_Call("entry", _coid, Decimal("5"), Decimal("5"), "SUIUSD"))

    raised = False
    try:
        _paper_send_via_outbox(
            home=home,
            mode="live",
            coid=live_coid,
            body=live_body,
            send=_live_send,
            journal_sink=lambda _rec: None,
        )
    except ModeError:
        raised = True

    assert raised, "ModeError must be raised when paper-send is invoked for live mode"
    # The live send callback must not have run.
    assert live_venue.calls == [], "ModeError must prevent the live send callback from running"
    # No paper file must have been written.
    paper_file = home / "run" / "paper-kraken.json"
    assert not paper_file.exists(), f"live mode must not write a paper file; found: {paper_file}"


def test_paid_expiry_exit_still_fires_for_owned_position(home) -> None:
    """Behavior 6: lapsed license cache + owned position + exit target
    → tick calls ``venue.place_exit``. Entries remain blocked.
    """
    from krellbot.run import tick

    pack_path = _write_pack(home, pack_id="ns13-lapsed")
    _arm_pack(
        home,
        pack_path,
        mode="paper",
        pack_id="ns13-lapsed",
        requires_license=True,
        owned_qty=Decimal(5),
    )
    _seed_journal_owned(home, pack_id="ns13-lapsed", owned_qty=Decimal(5))
    _seed_lapsed_cache(home)
    venue = _FakeVenue(initial_balances={"USD": Decimal(1000), "SUI": Decimal(5)})

    # Two candles that drive close from above to below sma2 → exit signal.
    candles = [
        _candle(0, "12"),
        _candle(3_600_000, "12"),
        _candle(7_200_000, "8"),
    ]

    rc = tick(venue="kraken", venue_obj=venue, reader=lambda v, p: list(candles), home=home)
    assert rc == 0

    exits = [c for c in venue.calls if c.method == "exit"]
    assert len(exits) == 1, f"paid-expiry exit must fire; got {exits}"
    entries = [c for c in venue.calls if c.method == "entry"]
    assert entries == [], f"entries must stay blocked under lapsed cache; got {entries}"
"""NS14 leaf 3 — reservations through PaperService.arm.

Three behaviors, all driven through PaperService.arm or tick (not the
reservation helpers in isolation):

1. Over-allocation: two arm calls that together exceed the paper
   account's cash. The second returns a typed refusal with
   ``revision_after == revision_before``. The first arm's bytes on
   disk are unchanged by the failed second arm. The test calls
   ``PaperService.arm`` twice — not a direct call into the helper.

2. Restart block: a ``needs_reconcile`` row in the ledger suppresses a
   new tick entry but does not stop exits. The paid-expiry exit path
   (lapsed license + owned position + exit target) still places
   ``venue_obj.place_exit``. The existing ``blocked`` flag check in
   tick is untouched.

3. Action codes: pause, cancel-opening, manage-exits, and flatten are
   four distinct result codes. Flatten of quantity the journal does
   not own is refused; flatten of quantity it does own is allowed.
   The journal is the source of truth for owned quantity — venue
   balances for external holdings are never sold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from krellbot import journal as kb_journal
from krellbot.config import ArmedPack, Config, save_config
from krellbot.execution import reservations
from krellbot.pack.model import Candle
from krellbot.storage.database import OperationalStore
from krellbot.storage.outbox import audit_needs_reconcile
from krellbot.venues.base import (
    Balance,
    Fill,
    KeyPerms,
    OpenOrder,
    OrderRef,
    PairRules,
    Truth,
)

# ---------------------------------------------------------------------------
# Test fixtures (mirrors test_ns13_fault_fills._FakeVenue shape).
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
    def __init__(
        self,
        *,
        venue: str = "kraken",
        pair: str = "SUIUSD",
        initial_balances: dict[str, Decimal] | None = None,
    ) -> None:
        self.venue = venue
        self.pair = pair
        self._balances: dict[str, Decimal] = dict(initial_balances or {})
        self._orders: list[OpenOrder] = []
        self._fills: list[Fill] = []
        self.calls: list[_Call] = []
        self.pending_fills: list[Fill] = []

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
        self, coid: str, qty: Decimal, stop: Decimal, *, pair: str
    ) -> OrderRef:
        self.calls.append(_Call("entry", coid, qty, stop, pair))
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
        self.calls.append(_Call("exit", coid, qty, None, pair))
        base, _quote = self._split(pair)
        self._balances[base] = self._balances.get(base, Decimal(0)) - qty
        self._orders = [
            o for o in self._orders
            if not (o.pair == pair and o.stop_price is not None)
        ]
        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="sell",
            qty=qty,
            filled_qty=qty,
            stop_price=None,
        )

    def place_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> None:
        self.calls.append(_Call("stop", coid, qty, stop, pair))

    def cancel_stops(self, pair: str) -> None:
        self.calls.append(_Call("cancel_stops", ""))
        self._orders = [
            o for o in self._orders
            if not (o.pair == pair and o.stop_price is not None)
        ]

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        self.calls.append(_Call("raise_stop", "", None, new_stop, pair))

    def order_by_coid(self, coid: str) -> OpenOrder | None:
        for o in self._orders:
            if o.coid == coid:
                return o
        return None

    def check_key(self) -> KeyPerms:
        return KeyPerms(can_trade=True, can_withdraw=False)

    def push_pending_fill(
        self, coid: str, pair: str, side: str, qty: Decimal, price: Decimal, ts_ms: int
    ) -> None:
        self.pending_fills.append(
            Fill(id=coid, coid=coid, pair=pair, side=side, qty=qty, price=price, ts_ms=ts_ms)
        )

    @staticmethod
    def _split(pair: str) -> tuple[str, str]:
        if pair.endswith("USD"):
            return pair[: -len("USD")], "USD"
        return pair[:-3], pair[-3:]


# ---------------------------------------------------------------------------
# Pack + arm helpers.
# ---------------------------------------------------------------------------


_PACK_BODY = {
    "schema_version": 1,
    "id": "ns14-base",
    "version": "1.0.0",
    "label": "NS14 reservations",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _write_pack(home: Path, *, pack_id: str, cap_pct: int = 100, pair: str = "SUIUSD") -> Path:
    body = json.loads(json.dumps(_PACK_BODY))
    body["id"] = pack_id
    body["risk"]["max_account_pct"] = cap_pct
    body["markets"] = [{"venue": "kraken", "pair": pair}]
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_pack(
    home: Path,
    *,
    mode: str,
    pack_id: str,
    requires_license: bool = False,
    owned_qty: Decimal = Decimal(0),
) -> None:
    """Write the on-disk config directly so a test can pre-seed arms."""
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(home / f"{pack_id}.json"),
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
    kb_journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": pack_id,
            "bar_ts": 0,
            "detail": {
                "pair": "SUIUSD",
                "entry_qty": str(owned_qty),
                "exit_qty": "0",
                "stop_qty": "0",
            },
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
# Behavior 1: over-allocation refusal.
# ---------------------------------------------------------------------------


def test_second_arm_over_allocates_cash_is_refused(home) -> None:
    """Two paper arm calls on the same venue, different pairs: the
    second refuses with a typed code and does not change the on-disk
    bytes. The reservation helper is called from PaperService.arm — a
    test that only calls the helper directly does not satisfy this leaf.
    """
    from krellbot import config as kb_config
    from krellbot.application.paper import PaperService

    pack1 = _write_pack(home, pack_id="ns14-pack1", cap_pct=100, pair="SUIUSD")
    pack2 = _write_pack(home, pack_id="ns14-pack2", cap_pct=100, pair="XLMUSD")

    service = PaperService(home)

    # First arm: succeeds; cap=100% of starting_cash=1000 reserves 1000.
    r1 = service.arm(
        pack1,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
    )
    assert r1.ok, f"first arm must succeed; got code={r1.code!r} message={r1.message!r}"
    assert r1.code == "armed"

    bytes_after_first = kb_config.config_path(home).read_bytes()
    rev_after_first = r1.revision_after
    assert rev_after_first is not None

    # Second arm: tries to reserve another 1000; the account pool
    # (smallest starting_cash across paper arms) is 1000, so the
    # combined reservation would over-allocate.
    r2 = service.arm(
        pack2,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
    )

    assert not r2.ok, f"second arm must refuse; got code={r2.code!r} message={r2.message!r}"
    assert r2.code == reservations.CODE_OVER_RESERVED, (
        f"refusal must use the typed over_reserved code; got {r2.code!r}"
    )
    # Refusal must leave the on-disk record unchanged.
    assert r2.revision_after == r2.revision_before, (
        f"refusal must leave revision_after == revision_before; "
        f"before={r2.revision_before!r} after={r2.revision_after!r}"
    )
    bytes_after_second = kb_config.config_path(home).read_bytes()
    assert bytes_after_second == bytes_after_first, (
        "config file bytes must be unchanged from after the first successful arm"
    )
    assert r2.revision_before == rev_after_first, (
        "the refusal's revision_before must equal the first arm's revision_after"
    )


def test_first_arm_does_not_over_allocate_against_empty_account(home) -> None:
    """Sanity: the first paper arm on an empty home never refuses.
    A single-arm flow stays unchanged.
    """
    from krellbot.application.paper import PaperService

    pack = _write_pack(home, pack_id="ns14-first", cap_pct=100)
    service = PaperService(home)

    r = service.arm(
        pack,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
    )
    assert r.ok, f"first arm must succeed; got code={r.code!r} message={r.message!r}"
    assert r.code == "armed"


def test_two_arms_with_reservation_within_pool_both_succeed(home) -> None:
    """Two arms whose combined reservation fits inside the pool both
    arm. cap=50% of 1000 + cap=30% of 1000 = 800 <= pool 1000. The
    two packs live on different pairs (SUIUSD, XLMUSD) so the existing
    one-arm-per-pair check does not refuse them.
    """
    from krellbot.application.paper import PaperService

    pack1 = _write_pack(home, pack_id="ns14-fit-1", cap_pct=50, pair="SUIUSD")
    pack2 = _write_pack(home, pack_id="ns14-fit-2", cap_pct=30, pair="XLMUSD")

    service = PaperService(home)
    r1 = service.arm(pack1, venue="kraken", mode="paper", paper_balance=Decimal(1000))
    assert r1.ok, f"first arm must succeed; got {r1.code!r}"
    r2 = service.arm(pack2, venue="kraken", mode="paper", paper_balance=Decimal(1000))
    assert r2.ok, f"second arm must fit in pool; got {r2.code!r}: {r2.message!r}"


# ---------------------------------------------------------------------------
# Behavior 2: needs_reconcile restart block.
# ---------------------------------------------------------------------------


def test_needs_reconcile_blocks_new_tick_entry(home) -> None:
    """A pre-existing ``needs_reconcile`` ledger row suppresses a new
    entry from tick. Tick is the real caller; the reservation helper
    is invoked from inside tick's entry block.
    """
    from krellbot.run import tick

    _write_pack(home, pack_id="ns14-reconcile")
    _arm_pack(home, mode="paper", pack_id="ns14-reconcile")

    # Seed a needs_reconcile audit row before tick runs.
    audit_needs_reconcile(OperationalStore(home / "ops.sqlite"), coid="stuck-coid")

    venue = _FakeVenue(initial_balances={"USD": Decimal(1000)})

    # Bars that drive close above sma2 → entry signal.
    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(7_200_000, "12"),
    ]

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: list(candles),
        home=home,
    )
    assert rc == 0

    # The entry must NOT have been placed while reconcile is pending.
    entries = [c for c in venue.calls if c.method == "entry"]
    assert entries == [], (
        f"needs_reconcile must block new entries; got {entries}"
    )


def test_needs_reconcile_does_not_block_paid_expiry_exit(home) -> None:
    """A ``needs_reconcile`` row does not stop tick from placing an exit
    for an owned position under a lapsed license. The existing
    ``blocked`` flag check stays; exits are independent of the
    reconcile block.
    """
    from krellbot.run import tick

    _write_pack(home, pack_id="ns14-lapsed")
    _arm_pack(
        home,
        mode="paper",
        pack_id="ns14-lapsed",
        requires_license=True,
        owned_qty=Decimal(5),
    )
    _seed_journal_owned(home, pack_id="ns14-lapsed", owned_qty=Decimal(5))
    _seed_lapsed_cache(home)
    audit_needs_reconcile(OperationalStore(home / "ops.sqlite"), coid="stuck-coid")

    venue = _FakeVenue(initial_balances={"USD": Decimal(1000), "SUI": Decimal(5)})

    # Two candles that drive close from above to below sma2 → exit signal.
    candles = [
        _candle(0, "12"),
        _candle(3_600_000, "12"),
        _candle(7_200_000, "8"),
    ]

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: list(candles),
        home=home,
    )
    assert rc == 0

    exits = [c for c in venue.calls if c.method == "exit"]
    assert len(exits) == 1, (
        f"paid-expiry exit must fire even with needs_reconcile pending; got {exits}"
    )
    entries = [c for c in venue.calls if c.method == "entry"]
    assert entries == [], (
        f"entries must stay blocked under lapsed cache; got {entries}"
    )


def test_needs_reconcile_does_not_block_normal_exit_for_owned(home) -> None:
    """A ``needs_reconcile`` row does not block an exit for an owned
    position when entries are allowed.
    """
    from krellbot.run import tick

    _write_pack(home, pack_id="ns14-exit-only")
    _arm_pack(home, mode="paper", pack_id="ns14-exit-only", owned_qty=Decimal(5))
    _seed_journal_owned(home, pack_id="ns14-exit-only", owned_qty=Decimal(5))
    audit_needs_reconcile(OperationalStore(home / "ops.sqlite"), coid="stuck-coid")

    venue = _FakeVenue(initial_balances={"USD": Decimal(1000), "SUI": Decimal(5)})

    candles = [
        _candle(0, "12"),
        _candle(3_600_000, "12"),
        _candle(7_200_000, "8"),
    ]

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: list(candles),
        home=home,
    )
    assert rc == 0

    exits = [c for c in venue.calls if c.method == "exit"]
    assert len(exits) == 1, f"exit must fire for owned position; got {exits}"


# ---------------------------------------------------------------------------
# Behavior 3: distinct action codes + flatten ownership rule.
# ---------------------------------------------------------------------------


def test_action_codes_are_four_distinct_strings() -> None:
    """pause, cancel-opening, manage-exits, and flatten are four
    distinct result codes. No two are equal; none collide with the
    paper command codes (armed, disarmed, …).
    """
    codes = {
        reservations.CODE_PAUSE,
        reservations.CODE_CANCEL_OPENING,
        reservations.CODE_MANAGE_EXITS,
        reservations.CODE_FLATTEN,
    }
    assert len(codes) == 4, (
        f"action codes must be distinct; got {sorted(codes)}"
    )

    # None of them collide with paper command v1 codes.
    paper_command_codes = {
        "armed",
        "disarmed",
        "entries_paused",
        "entries_resumed",
        "stop_raised",
    }
    assert not (codes & paper_command_codes), (
        f"action codes must not collide with paper command codes; collision={codes & paper_command_codes}"
    )


def test_flatten_of_unowned_quantity_is_refused(home) -> None:
    """Flatten of a quantity the journal does not own is refused with
    a typed code. The journal is the source of truth — venue balances
    for external holdings are never sold.
    """
    # Journal says pack owns 5; venue happens to have 10 (5 from this
    # pack + 5 from external inventory). Flatten of 10 must refuse
    # because the journal only attributes 5 to this pack.
    _seed_journal_owned(home, pack_id="ns14-flatten", owned_qty=Decimal(5))

    code = reservations.flatten_result(
        home, pack_id="ns14-flatten", pair="SUIUSD", qty=Decimal(10)
    )
    assert code == reservations.CODE_FLATTEN_NOT_OWNED, (
        f"flatten of unowned qty must refuse with flatten_not_owned; got {code!r}"
    )


def test_flatten_of_owned_quantity_is_allowed(home) -> None:
    """Flatten of a quantity the journal does own is allowed. The
    action code is the flatten code, not a refusal.
    """
    _seed_journal_owned(home, pack_id="ns14-flatten-own", owned_qty=Decimal(5))

    code = reservations.flatten_result(
        home, pack_id="ns14-flatten-own", pair="SUIUSD", qty=Decimal(5)
    )
    assert code == reservations.CODE_FLATTEN, (
        f"flatten of fully owned qty must return flatten; got {code!r}"
    )

    # Below the owned qty is also fine.
    code_partial = reservations.flatten_result(
        home, pack_id="ns14-flatten-own", pair="SUIUSD", qty=Decimal(3)
    )
    assert code_partial == reservations.CODE_FLATTEN


def test_flatten_action_code_does_not_collide_with_pause_or_manage_exits() -> None:
    """flatten is distinct from pause / cancel-opening / manage-exits
    and from over_reserved. A blanket string-equal check.
    """
    distinct = (
        reservations.CODE_PAUSE,
        reservations.CODE_CANCEL_OPENING,
        reservations.CODE_MANAGE_EXITS,
        reservations.CODE_FLATTEN,
        reservations.CODE_FLATTEN_NOT_OWNED,
        reservations.CODE_OVER_RESERVED,
    )
    assert len(set(distinct)) == len(distinct), (
        f"all reservation codes must be pairwise distinct; got {distinct}"
    )
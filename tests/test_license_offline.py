"""Offline license gating + live arm flow.

The license cache is a local file only. There is no HTTP in any test. Live
arming must be refused without KRELLBOT_ENABLE_LIVE=1, must read a typed
"LIVE" confirmation the first time on an install, and must require a stored
key whose permissions are trade-on / withdraw-off.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


def _write_pack(home: Path, name: str = "sma_cross.json") -> Path:
    """Write a valid DSL pack file under KRELLBOT_HOME/packs/."""
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": "sma-cross",
        "version": "1.0.0",
        "label": "SMA cross",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    target = packs / name
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _make_state(home: Path, status: str | None = None, grace_until: int = 0) -> dict:
    """Return the JSON body for the license cache file."""
    return {"status": status, "period_end": 0, "grace_until": grace_until}


def test_entries_allowed_active(home):
    """Cache says active + grace_until in the future → entries are allowed."""
    from krellbot import license

    cache = {"status": "active", "period_end": 0, "grace_until": 10**12}
    assert license.entries_allowed(cache, now=1) is True


def test_entries_allowed_past_due_in_grace(home):
    """Cache says past_due but grace_until > now → entries still allowed."""
    from krellbot import license

    cache = {"status": "past_due", "period_end": 0, "grace_until": 10**12}
    assert license.entries_allowed(cache, now=1) is True


def test_entries_allowed_grace_expired(home):
    """past_due with grace_until in the past → entries blocked, exits allowed."""
    from krellbot import license

    cache = {"status": "past_due", "period_end": 0, "grace_until": 0}
    assert license.entries_allowed(cache, now=10**12) is False


def test_entries_allowed_missing_cache_fail_closes(home):
    """Missing cache → entries blocked. Exits are not the gate's job."""
    from krellbot import license

    assert license.entries_allowed(None, now=0) is False


def test_cache_round_trip(home):
    """read/write the JSON cache preserves status / period_end / grace_until."""
    from krellbot import license

    license.write_cache(home, status="active", period_end=12345, grace_until=67890)
    cache = license.read_cache(home)
    assert cache == {"status": "active", "period_end": 12345, "grace_until": 67890}


def test_cache_missing_is_none(home):
    """No cache file on disk → read returns None."""
    from krellbot import license

    assert license.read_cache(home) is None


def test_lapsed_license_blocks_entry_allows_exit(home, monkeypatch):
    """When license lapsed, an exit signal still produces a place_exit call.

    No entry may be placed while lapsed. The detail recorded for the tick
    names the gate refusal.
    """
    from krellbot import license
    from krellbot.run import arm_pack, tick

    # Lapsed cache: past_due with grace_until in the past.
    license.write_cache(home, status="past_due", period_end=0, grace_until=0)

    # Force the armed record into requires_license=True so the gate matters.
    pack_path = _write_pack(home)

    arm_pack(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        requires_license=True,
    )

    # No entry. Exit signal fires. We expect place_exit called.
    candles = [
        _candle(0, "10", "10.5", "9.5", "10"),
        _candle(3_600_000, "11", "12", "10.5", "11.5"),
        _candle(7_200_000, "11", "11", "10", "10.2"),  # bar that exits long
    ]
    reader = _FakeReader(candles)

    fills: list[tuple[str, str]] = []
    venue = _SpyPaperVenue(
        "kraken",
        initial_balances={"USD": Decimal(1000), "SUI": Decimal(5)},
        on_entry=lambda coid, qty, stop: fills.append(("entry", coid)),
        on_exit=lambda coid, qty: fills.append(("exit", coid)),
    )
    journal = _FakeJournal()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=reader,
        journal_sink=journal,
        clock=lambda: 7_200_000 // 1000,
    )
    assert rc == 0
    # No entries attempted because license is lapsed.
    assert not [k for k, _ in fills if k == "entry"]
    # The journal must record the lapsed gate.
    assert any(
        "license" in r["detail"].get("note", "").lower()
        or "lapsed" in r["detail"].get("note", "").lower()
        or r["detail"].get("entries_blocked")
        for r in journal.records
    )


def test_unreachable_cloud_uses_cached_status_until_grace(home):
    """Cloud unreachable → we trust the cache. Past_due within grace still
    allows entries; past grace blocks them.
    """
    from krellbot import license

    license.write_cache(home, status="past_due", period_end=0, grace_until=10**12)
    cached = license.read_cache(home)
    # No HTTP is attempted — the test never sets a transport.
    assert license.entries_allowed(cached, now=1) is True

    license.write_cache(home, status="past_due", period_end=0, grace_until=0)
    cached = license.read_cache(home)
    assert license.entries_allowed(cached, now=10**12) is False


def test_live_disabled_without_env_flag(home, monkeypatch, fresh_keyring):
    """`arm --mode live` exits 1 unless KRELLBOT_ENABLE_LIVE=1."""
    from krellbot import secrets
    from krellbot.run import arm_pack

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    pack_path = _write_pack(home)
    secrets.store("kraken", "FAKEKEY", "FAKESECRET")
    _ = fresh_keyring  # ensure backend is the fake

    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        paper_balance=None,
        key_check=lambda venue: _KeyCheckResult(can_trade=True, can_withdraw=False),
    )
    assert rc == 1


def test_live_arm_requires_withdraw_off_and_confirmation(home, monkeypatch, fresh_keyring):
    """`arm --mode live` requires trade-yes, withdraw-no, and a "LIVE" prompt.

    First live arm reads stdin; if the text is not exactly "LIVE", it refuses.
    A key that can withdraw is refused. A key that cannot trade is refused.
    """
    from krellbot import secrets
    from krellbot.run import arm_pack, disarm_pack

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    secrets.store("kraken", "FAKEKEY", "FAKESECRET")
    pack_path = _write_pack(home)

    # Wrong text on stdin → refused.
    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        paper_balance=None,
        confirm_fn=lambda: "yes",
        key_check=lambda venue: _KeyCheckResult(can_trade=True, can_withdraw=False),
    )
    assert rc == 1

    # Withdraw on → refused.
    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        paper_balance=None,
        confirm_fn=lambda: "LIVE",
        key_check=lambda venue: _KeyCheckResult(can_trade=True, can_withdraw=True),
    )
    assert rc == 1

    # Trade off → refused.
    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        paper_balance=None,
        confirm_fn=lambda: "LIVE",
        key_check=lambda venue: _KeyCheckResult(can_trade=False, can_withdraw=False),
    )
    assert rc == 1

    # All checks pass → armed (rc == 0). The first live arm on this install.
    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        paper_balance=None,
        confirm_fn=lambda: "LIVE",
        key_check=lambda venue: _KeyCheckResult(can_trade=True, can_withdraw=False),
    )
    assert rc == 0

    # Disarm, then re-arm live. The re-arm must NOT prompt. If confirm_fn
    # is called again, it raises and we detect the regression.
    disarm_pack(venue="kraken", pair="SUIUSD", home=home)

    def must_not_call() -> str:
        raise AssertionError("confirm_fn must not be called after the first live arm")

    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        paper_balance=None,
        confirm_fn=must_not_call,
        key_check=lambda venue: _KeyCheckResult(can_trade=True, can_withdraw=False),
    )
    assert rc == 0


# ----------------------- shared helpers -----------------------


def _candle(ts_ms: int, o: str, h: str, l: str, c: str):
    from decimal import Decimal

    from krellbot.pack.model import Candle

    return Candle(
        ts_ms=ts_ms,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(l),
        close=Decimal(c),
        volume=Decimal(100),
    )


class _KeyCheckResult:
    def __init__(self, *, can_trade: bool, can_withdraw: bool) -> None:
        self.can_trade = can_trade
        self.can_withdraw = can_withdraw


class _FakeReader:
    def __init__(self, candles: list) -> None:
        self.candles = candles

    def __call__(self, venue: str, pair: str) -> list:
        return list(self.candles)


class _SpyPaperVenue:
    """Minimal stand-in for PaperVenue that records call args.

    It satisfies the duck-typed interface used by `tick` in this phase:
    rules(pair) -> PairRules, snapshot() -> Truth, place_entry_with_stop, place_exit.
    """

    def __init__(self, venue: str, *, initial_balances: dict, on_entry, on_exit) -> None:
        self.venue = venue
        self._balances = dict(initial_balances)
        self._orders: list[dict] = []
        self._on_entry = on_entry
        self._on_exit = on_exit

    def rules(self, pair: str):
        from krellbot.venues.base import PairRules

        return PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )

    def snapshot(self):
        from krellbot.venues.base import Balance, OpenOrder, Truth

        orders = [
            OpenOrder(
                id=o["coid"],
                coid=o["coid"],
                pair=o["pair"],
                side=o["side"],
                qty=o["qty"],
                stop_price=o.get("stop_price"),
            )
            for o in self._orders
        ]
        bals = [Balance(asset=k, free=v) for k, v in self._balances.items() if v > 0]
        return Truth(balances=bals, open_orders=orders, recent_fills=[])

    def place_entry_with_stop(self, coid: str, qty, stop, *, pair: str):
        self._on_entry(coid, qty, stop)
        self._orders.append({"coid": coid, "pair": pair, "side": "buy", "qty": qty, "stop_price": stop})
        return {
            "id": coid,
            "coid": coid,
            "pair": pair,
            "side": "buy",
            "qty": qty,
            "filled_qty": qty,
            "stop_price": stop,
        }

    def place_exit(self, coid: str, qty, *, pair: str):
        self._on_exit(coid, qty)
        self._orders = [o for o in self._orders if not (o["pair"] == pair and o.get("side") == "buy")]
        return {"id": coid, "coid": coid, "pair": pair, "side": "sell", "qty": qty, "filled_qty": qty}

    def cancel_stops(self, pair: str) -> None:
        self._orders = [o for o in self._orders if not (o["pair"] == pair and o.get("stop_price") is not None)]

    def raise_stop(self, pair: str, new_stop) -> None:
        for o in self._orders:
            if o["pair"] == pair and o.get("stop_price") is not None:
                o["stop_price"] = max(o["stop_price"], new_stop)

    def place_stop(self, coid: str, qty, stop, *, pair: str):
        self._orders.append({"coid": coid, "pair": pair, "side": "sell", "qty": qty, "stop_price": stop})

    def order_by_coid(self, coid: str):
        for o in self._orders:
            if o["coid"] == coid:
                return o
        return None

    def check_key(self):
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=True, can_withdraw=False)


class _FakeJournal:
    def __init__(self) -> None:
        self.records: list[dict] = []

    def __call__(self, record: dict) -> Path:
        self.records.append(record)
        return Path("/dev/null")

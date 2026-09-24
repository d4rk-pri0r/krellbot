"""Paper venue: state in `$KRELLBOT_HOME/run/paper-<venue>.json`, no HTTP.

The paper venue implements the `Venue` protocol. State is a JSON document
with `balances`, `open_orders`, `recent_fills`. Every write goes through
`paths.atomic_write` so a crash mid-write never leaves a half-baked file.

Costs match Phase 3:
    * Kraken taker fee = 40 bps
    * Coinbase taker fee = 120 bps
    * Slippage = 5 bps each side

A market entry fills at last_close * (1 + buy_slip). A stop fills on a
closed bar whose low <= stop, at min(stop, open) * (1 - sell_slip), before
any new signal fill. For Kraken paper, if a Kraken key is stored AND a
validate transport was injected, the venue also POSTs AddOrder with
validate=true; the validate POST never records a fill.

The candle reader is injected. The CLI uses `--offline-candles <csv>` to
populate the reader; tests inject a static list.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any, Protocol

from krellbot import paths as kb_paths
from krellbot.venues.base import (
    Balance,
    Fill,
    KeyPerms,
    OpenOrder,
    OrderRef,
    PairRules,
    Truth,
)

STATE_FILENAME_TEMPLATE = "paper-{venue}.json"
KRAKEN_TAKER_BPS = 40
COINBASE_TAKER_BPS = 120
SLIPPAGE_BPS = 5


def _fee_bps_for(venue: str) -> int:
    return KRAKEN_TAKER_BPS if venue == "kraken" else COINBASE_TAKER_BPS


def _state_path(home: Path, venue: str) -> Path:
    return Path(home) / "run" / STATE_FILENAME_TEMPLATE.format(venue=venue)


class CandleReader(Protocol):
    """Anything with `__call__(venue, pair) -> list[Candle]`."""

    def __call__(self, venue: str, pair: str) -> list: ...


class ValidateTransport(Protocol):
    """An HTTP-shaped object for the Kraken validate=true POST."""

    def post(self, url: str, body: dict, headers: dict) -> dict: ...


class PaperVenue:
    """A local-only venue that records fills in a JSON state file."""

    def __init__(
        self,
        venue: str,
        *,
        rules_provider: Callable[[str], PairRules],
        candle_reader: CandleReader,
        home: Path,
        starting_cash: Decimal | None = None,
        has_stored_key: bool = False,
        validate_transport: ValidateTransport | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.venue = venue
        self._rules_provider = rules_provider
        self._reader = candle_reader
        self._home = Path(home)
        self._fee_bps = _fee_bps_for(venue)
        self._slip = Decimal(SLIPPAGE_BPS) / Decimal(10_000)
        self._has_stored_key = has_stored_key
        self._validate_transport = validate_transport
        self._clock = clock
        self._state = self._load_state()
        if starting_cash is not None and not self._state.get("seeded"):
            self._state["balances"]["USD"] = starting_cash
            self._state["seeded"] = True
            self._persist()

    # ---- Venue protocol ----------------------------------------------------

    def rules(self, pair: str) -> PairRules:
        return self._rules_provider(pair)

    def snapshot(self) -> Truth:
        self._apply_triggered_stops()
        return _to_truth(self._state)

    def place_entry_with_stop(
        self,
        coid: str,
        qty: Decimal,
        stop: Decimal,
        *,
        pair: str,
    ) -> OrderRef:
        existing = self.order_by_coid(coid)
        if existing is not None:
            return OrderRef(
                id=existing.id,
                coid=existing.coid,
                pair=existing.pair,
                side=existing.side,
                qty=existing.qty,
                filled_qty=existing.qty,
                stop_price=existing.stop_price,
            )
        for fill in self._state.get("recent_fills", []):
            if fill.get("coid") == coid:
                rules = self.rules(pair)
                return OrderRef(
                    id=coid,
                    coid=coid,
                    pair=pair,
                    side="buy",
                    qty=_quantize(qty, rules.lot_decimals),
                    filled_qty=_quantize(qty, rules.lot_decimals),
                    stop_price=_quantize(stop, rules.price_decimals),
                )
        self._apply_triggered_stops()
        rules = self.rules(pair)
        if qty < rules.ordermin:
            raise ValueError("qty below ordermin")
        last_close = self._last_close_for(pair)
        if last_close is None:
            raise ValueError("paper: no candle available to price entry")
        # Buy slippage applied to last close.
        buy_price = (last_close * (Decimal(1) + self._slip)).quantize(
            Decimal(1).scaleb(-rules.price_decimals), rounding=ROUND_DOWN
        )
        # Validate notional after slippage.
        notional = qty * buy_price
        if notional < rules.costmin:
            raise ValueError("notional below costmin")

        # Fee subtracted from quote balance.
        fee = (notional * Decimal(self._fee_bps) / Decimal(10_000)).quantize(
            Decimal(1).scaleb(-rules.price_decimals), rounding=ROUND_DOWN
        )
        base, quote = _base_quote(pair)
        self._state["balances"][quote] = self._state["balances"].get(quote, Decimal(0)) - notional - fee
        self._state["balances"][base] = self._state["balances"].get(base, Decimal(0)) + qty

        ts_ms = int((self._clock() if self._clock else _now_seconds()) * 1000)
        self._state["recent_fills"].append(
            {
                "id": coid,
                "coid": coid,
                "pair": pair,
                "side": "buy",
                "qty": _quantize(qty, rules.lot_decimals),
                "price": buy_price,
                "ts_ms": ts_ms,
            }
        )

        # Rest the stop.
        stop_q = _quantize(stop, rules.price_decimals)
        self._state["open_orders"].append(
            {
                "coid": coid,
                "pair": pair,
                "side": "sell",
                "qty": _quantize(qty, rules.lot_decimals),
                "stop_price": stop_q,
                "ts_ms": ts_ms,
            }
        )

        self._persist()
        self._state["last_applied_ts"] = self._latest_bar_ts(pair)

        # Kraken paper shape check: validate=true POST, no fill.
        if self.venue == "kraken" and self._has_stored_key and self._validate_transport is not None:
            self._validate_transport.post(
                "https://api.kraken.com/0/private/AddOrder",
                {
                    "ordertype": "market",
                    "type": "buy",
                    "pair": pair,
                    "volume": format(qty, "f"),
                    "validate": "true",
                },
                {},
            )

        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="buy",
            qty=_quantize(qty, rules.lot_decimals),
            filled_qty=_quantize(qty, rules.lot_decimals),
            stop_price=stop_q,
        )

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef:
        rules = self.rules(pair)
        last_close = self._last_close_for(pair)
        if last_close is None:
            raise ValueError("paper: no candle available to price exit")
        sell_price = (last_close * (Decimal(1) - self._slip)).quantize(
            Decimal(1).scaleb(-rules.price_decimals), rounding=ROUND_DOWN
        )
        proceeds = qty * sell_price
        fee = (proceeds * Decimal(self._fee_bps) / Decimal(10_000)).quantize(
            Decimal(1).scaleb(-rules.price_decimals), rounding=ROUND_DOWN
        )
        base, quote = _base_quote(pair)
        self._state["balances"][base] = self._state["balances"].get(base, Decimal(0)) - qty
        self._state["balances"][quote] = self._state["balances"].get(quote, Decimal(0)) + proceeds - fee

        ts_ms = int((self._clock() if self._clock else _now_seconds()) * 1000)
        self._state["recent_fills"].append(
            {
                "id": coid,
                "coid": coid,
                "pair": pair,
                "side": "sell",
                "qty": _quantize(qty, rules.lot_decimals),
                "price": sell_price,
                "ts_ms": ts_ms,
            }
        )
        # Remove the resting stop + entry order for this pair+coid.
        self._state["open_orders"] = [
            o
            for o in self._state["open_orders"]
            if not (o.get("pair") == pair and (o.get("coid") == coid or o.get("stop_price") is not None))
        ]
        self._persist()
        return OrderRef(
            id=coid,
            coid=coid,
            pair=pair,
            side="sell",
            qty=_quantize(qty, rules.lot_decimals),
            filled_qty=_quantize(qty, rules.lot_decimals),
            stop_price=None,
        )

    def cancel_stops(self, pair: str) -> None:
        self._state["open_orders"] = [
            o for o in self._state["open_orders"] if not (o["pair"] == pair and o.get("stop_price") is not None)
        ]
        self._persist()

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        rules = self.rules(pair)
        price = _quantize(new_stop, rules.price_decimals)
        for o in self._state["open_orders"]:
            if o["pair"] == pair and o.get("stop_price") is not None:
                current = Decimal(str(o["stop_price"]))
                if price > current:
                    o["stop_price"] = format(price, "f")
        self._persist()

    def order_by_coid(self, coid: str) -> OpenOrder | None:
        for o in self._state["open_orders"]:
            if o.get("coid") == coid:
                return OpenOrder(
                    id=str(o.get("id", o.get("coid", ""))),
                    coid=str(o.get("coid", "")),
                    pair=str(o.get("pair", "")),
                    side=str(o.get("side", "")),
                    qty=Decimal(str(o.get("qty", "0"))),
                    stop_price=(Decimal(str(o["stop_price"])) if o.get("stop_price") is not None else None),
                )
        return None

    def check_key(self) -> KeyPerms:
        # Paper venue is always trade-yes / withdraw-off.
        return KeyPerms(can_trade=True, can_withdraw=False)

    def place_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> None:
        """Rest a stop order without placing an entry.

        Used by the engine to repair missing stops on positions that the
        pack already owns (from a prior tick or recovered from a crash).
        No fill is recorded; only the resting stop lands in the order book.
        """
        rules = self.rules(pair)
        q = _quantize(qty, rules.lot_decimals)
        s = _quantize(stop, rules.price_decimals)
        if q < rules.ordermin:
            raise ValueError("qty below ordermin")
        ts_ms = int((self._clock() if self._clock else _now_seconds()) * 1000)
        self._state["open_orders"].append(
            {
                "coid": coid,
                "pair": pair,
                "side": "sell",
                "qty": q,
                "stop_price": s,
                "ts_ms": ts_ms,
            }
        )
        self._persist()

    # ---- paper-specific helpers (used by the engine) ----------------------

    def record_stop_fill(self, coid: str, qty: Decimal, price: Decimal, *, pair: str) -> None:
        """Land a stop fill at the given price. Removes the resting stop.

        Called by the engine after it computes the stop price from the bar.
        """
        rules = self.rules(pair)
        q = _quantize(qty, rules.lot_decimals)
        p = _quantize(price, rules.price_decimals)
        base, quote = _base_quote(pair)
        # Sell qty from base, add proceeds to quote.
        proceeds = q * p
        fee = (proceeds * Decimal(self._fee_bps) / Decimal(10_000)).quantize(
            Decimal(1).scaleb(-rules.price_decimals), rounding=ROUND_DOWN
        )
        self._state["balances"][base] = self._state["balances"].get(base, Decimal(0)) - q
        self._state["balances"][quote] = self._state["balances"].get(quote, Decimal(0)) + proceeds - fee

        ts_ms = int((self._clock() if self._clock else _now_seconds()) * 1000)
        self._state["recent_fills"].append(
            {
                "id": coid,
                "coid": coid,
                "pair": pair,
                "side": "sell",
                "qty": q,
                "price": p,
                "ts_ms": ts_ms,
                "kind": "stop",
            }
        )
        # Drop the resting stop for this pair.
        self._state["open_orders"] = [
            o for o in self._state["open_orders"] if not (o["pair"] == pair and o.get("stop_price") is not None)
        ]
        self._persist()

    def balances(self) -> dict[str, Decimal]:
        """Return the current balances mapping (Decimal-valued)."""
        return {k: Decimal(str(v)) for k, v in self._state.get("balances", {}).items()}

    def owned_qty(self, pair: str) -> Decimal:
        """Return the base balance for the pair."""
        base, _ = _base_quote(pair)
        return self._state["balances"].get(base, Decimal(0))

    def resting_stop(self, pair: str) -> Decimal | None:
        """Return the stop price resting on this pair, or None."""
        for o in self._state["open_orders"]:
            if o["pair"] == pair and o.get("stop_price") is not None:
                return Decimal(str(o["stop_price"]))
        return None

    # ---- internals ---------------------------------------------------------

    def _latest_bar_ts(self, pair: str) -> int:
        candles = self._reader(self.venue, pair) or []
        if not candles:
            return int(self._state.get("last_applied_ts", -1))
        return int(candles[-1].ts_ms)

    def _apply_triggered_stops(self) -> None:
        """Fill a resting stop when a newer closed bar's low touches it.

        The entry bar is marked applied when the entry is placed, so the stop
        just attached cannot fire on that same bar. A later bar fires at
        min(stop, open) * (1 - sell slippage), before any new signal fill.
        """
        pairs = {str(o.get("pair", "")) for o in self._state.get("open_orders", []) if o.get("stop_price") is not None}
        if not pairs:
            return
        changed = False
        for pair in sorted(pairs):
            candles = list(self._reader(self.venue, pair) or [])
            last_applied = int(self._state.get("last_applied_ts", -1))
            for candle in candles:
                if int(candle.ts_ms) <= last_applied:
                    continue
                self._state["last_applied_ts"] = int(candle.ts_ms)
                changed = True
                stop = self.resting_stop(pair)
                if stop is None or Decimal(str(candle.low)) > stop:
                    continue
                qty = next(
                    (
                        Decimal(str(o.get("qty", "0")))
                        for o in self._state["open_orders"]
                        if o.get("pair") == pair and o.get("stop_price") is not None
                    ),
                    Decimal(0),
                )
                fill = min(stop, Decimal(str(candle.open))) * (Decimal(1) - self._slip)
                self.record_stop_fill(f"stop-{pair}-{candle.ts_ms}", qty, fill, pair=pair)
        if changed:
            self._persist()

    def _last_close_for(self, pair: str) -> Decimal | None:
        candles = self._reader(self.venue, pair) or []
        if not candles:
            return None
        return Decimal(str(candles[-1].close))

    def _load_state(self) -> dict[str, Any]:
        path = _state_path(self._home, self.venue)
        if not path.exists():
            return {
                "venue": self.venue,
                "balances": {},
                "open_orders": [],
                "recent_fills": [],
                "seeded": False,
            }
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}
        raw.setdefault("venue", self.venue)
        raw.setdefault("balances", {})
        raw.setdefault("open_orders", [])
        raw.setdefault("recent_fills", [])
        raw.setdefault("seeded", True)
        return raw

    def _persist(self) -> None:
        path = _state_path(self._home, self.venue)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = json.dumps(self._state, sort_keys=True, default=_decimal_default)
        kb_paths.atomic_write(path, body.encode("utf-8"))


# ---- helpers --------------------------------------------------------------


def _base_quote(pair: str) -> tuple[str, str]:
    """Split a Kraken-style pair like 'SUIUSD' into (base, quote)."""
    if not pair:
        return ("", "")
    if pair.endswith("USD"):
        return pair[: -len("USD")], "USD"
    if len(pair) >= 6:
        return pair[:-3], pair[-3:]
    return pair, ""


def _quantize(value: Decimal, decimals: int) -> Decimal:
    if decimals < 0:
        return value
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)


def _decimal_default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError(f"not JSON serializable: {type(obj).__name__}")


def _to_truth(state: dict) -> Truth:
    balances = [
        Balance(asset=str(k), free=Decimal(str(v))) for k, v in state.get("balances", {}).items() if Decimal(str(v)) > 0
    ]
    orders: list[OpenOrder] = []
    for o in state.get("open_orders", []):
        orders.append(
            OpenOrder(
                id=str(o.get("id", o.get("coid", ""))),
                coid=str(o.get("coid", "")),
                pair=str(o.get("pair", "")),
                side=str(o.get("side", "")),
                qty=Decimal(str(o.get("qty", "0"))),
                stop_price=(Decimal(str(o["stop_price"])) if o.get("stop_price") is not None else None),
            )
        )
    fills: list[Fill] = []
    for f in state.get("recent_fills", []):
        fills.append(
            Fill(
                id=str(f.get("id", "")),
                coid=str(f.get("coid", "")),
                pair=str(f.get("pair", "")),
                side=str(f.get("side", "")),
                qty=Decimal(str(f.get("qty", "0"))),
                price=Decimal(str(f.get("price", "0"))),
                ts_ms=int(f.get("ts_ms", 0)),
            )
        )
    return Truth(balances=balances, open_orders=orders, recent_fills=fills)


def _now_seconds() -> float:
    import time

    return time.time()


def default_rules(pair: str) -> PairRules:
    """Minimums checked against the public Kraken AssetPairs response.

    SUIUSD on 2026-09-23: ordermin 5, costmin 0.5, lot_decimals 5,
    pair_decimals 4. Unknown pairs are refused rather than given a fake minimum.
    """
    if pair == "SUIUSD":
        return PairRules(
            ordermin=Decimal(5),
            costmin=Decimal("0.5"),
            lot_decimals=5,
            price_decimals=4,
        )
    raise ValueError(f"paper rules are not loaded for {pair}")

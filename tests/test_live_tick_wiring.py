"""Task B: live tick wiring — env gate, key gate, trade-only order placement,
paper routing, and lapsed-license exit allowance.

The brief sets out five cases:
    1. Live arm, env unset -> exit 1, no order POST.
    2. Live arm, env=1, withdraw-capable key -> exit 1, no order POST.
    3. Live arm, env=1, trade-only key -> place_entry_with_stop fires with
       the armed pair; coid matches `coid_for`; a second tick on the same
       bar does not place a second order.
    4. Paper arm, env=1 -> the object passed to `run.tick` is a PaperVenue.
    5. Lapsed license cache -> no entry POST; an exit for a qty the journal
       already owns is still placed.

A fake transport and a fake Kraken transport are injected so no socket is
opened.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from fakes.fake_keyring import FakeKeyring
from fakes.fake_kraken import FakeKrakenTransport

KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


def _write_pack(home: Path, *, tf: str = "1h", pair: str = "SUIUSD", pack_id: str = "live-wiring") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Live wiring",
        "author": "krellbot tests",
        "timeframe": tf,
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm(
    home: Path,
    pack_path: Path,
    *,
    mode: str,
    pair: str = "SUIUSD",
    requires_license: bool = False,
    pack_id: str = "live-wiring",
) -> None:
    from krellbot.config import ArmedPack, Config, save_config

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
                    pair=pair,
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode=mode,
                    starting_cash=Decimal(1000) if mode == "paper" else None,
                    requires_license=requires_license,
                    armed_at_ts=1,
                )
            ]
        ),
    )


def _candle(ts_ms: int, close: str, *, open_: str | None = None, low: str | None = None):
    from krellbot.pack.model import Candle

    close_d = Decimal(close)
    return Candle(
        ts_ms=ts_ms,
        open=Decimal(open_ or close),
        high=close_d + Decimal(1),
        low=Decimal(low or close),
        close=close_d,
        volume=Decimal(100),
    )


def _fake_fetch(candles):
    """A no-network fetch returning `candles` for every (venue, pair, tf, transport)."""

    def fetch(venue, pair, tf, transport):
        return list(candles)

    return fetch


def _store_kraken_key(keyring: FakeKeyring, *, key: str = KRAKEN_TEST_KEY, secret: str = KRAKEN_TEST_SECRET) -> None:
    from krellbot import sanitize

    sanitize.register_secret(key, secret)
    keyring.set_password("krellbot:kraken", "key", key)
    keyring.set_password("krellbot:kraken", "secret", secret)


class _FundedKrakenTransport(FakeKrakenTransport):
    """A Kraken transport that always reports a USD balance.

    The engine snapshots three times per tick (initial, order_by_coid,
    _cash_for); each snapshot is a POST to Balance. Without an always-on
    balance the second/third snapshot sees empty USD and the entry's costmin
    check fails. The engine's `_cash_for` resolves "SUIUSD" to quote
    "USD", so the snapshot reports the asset as "USD".
    """

    def post(self, url, form, headers):
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "Balance":
            return {"error": [], "result": {"USD": "1000"}}
        return super().post(url, form, headers)


# --- helpers ---------------------------------------------------------------


def _asset_pairs_for(pair: str) -> dict:
    return {
        pair: {
            "ordermin": "5",
            "costmin": "0.5",
            "lot_decimals": 5,
            "pair_decimals": 4,
        }
    }


# ---- tests ----------------------------------------------------------------


def test_live_arm_with_env_unset_exits_1_and_posts_nothing(home, fresh_keyring, monkeypatch):
    """Live arm, KRELLBOT_ENABLE_LIVE unset: cmd_tick exits 1, no order POST."""
    from krellbot.cli import cmd_tick

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    pack_path = _write_pack(home)
    _arm(home, pack_path, mode="live")
    _store_kraken_key(fresh_keyring)

    transport = FakeKrakenTransport(responses=[{"result": {"txid": ["TX"]}}])

    rc = cmd_tick(["--venue", "kraken"], fetch=_fake_fetch([]), transport=transport)

    assert rc == 1
    assert not any(c.url.endswith("/AddOrder") for c in transport.calls)


def test_live_arm_with_withdraw_capable_key_exits_1_and_posts_nothing(home, fresh_keyring, monkeypatch, capsys):
    """Live arm, env=1, key WithdrawMethods returns methods -> WithdrawCapableError -> exit 1."""
    from krellbot.cli import cmd_tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home)
    _arm(home, pack_path, mode="live")
    _store_kraken_key(fresh_keyring)

    transport = FakeKrakenTransport(
        withdraw_methods=[{"method": "Bitcoin", "address": "abc"}],
    )

    rc = cmd_tick(["--venue", "kraken"], fetch=_fake_fetch([]), transport=transport)
    out = capsys.readouterr().out

    assert rc == 1
    assert "withdraw" in out
    assert "live is off" not in out
    assert not any(c.url.endswith("/AddOrder") for c in transport.calls)


def test_live_arm_with_trade_only_key_places_entry_and_dedupes(home, fresh_keyring, monkeypatch):
    """Live arm, env=1, trade-only key: place_entry_with_stop fires once on
    the entry bar with the armed pair. The coid matches `coid_for` for the
    entry intent. A second tick on the same bar does not POST a second
    AddOrder.
    """
    from krellbot.cli import cmd_tick
    from krellbot.run import coid_for

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home, pack_id="lw-entry")
    _arm(home, pack_path, mode="live", pack_id="lw-entry")
    _store_kraken_key(fresh_keyring)

    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(7_200_000, "12"),  # close crosses above sma2 (10 -> 11)
    ]

    transport = _FundedKrakenTransport(
        responses=[
            {"result": {"txid": ["TX-1"]}},
            {"result": {"txid": ["TX-2"]}},
        ],
        asset_pairs=_asset_pairs_for("SUIUSD"),
    )

    rc1 = cmd_tick(["--venue", "kraken"], fetch=_fake_fetch(candles), transport=transport)

    assert rc1 == 0
    adds = [c for c in transport.calls if c.url.endswith("/AddOrder")]
    assert len(adds) == 1, f"expected exactly one AddOrder on entry tick, got {len(adds)}"
    add = adds[0]
    assert add.form["pair"] == "SUIUSD"
    assert add.form["type"] == "buy"
    bar_ts = candles[-1].ts_ms
    expected_coid = coid_for(
        pack_id="lw-entry",
        pack_version="1.0.0",
        venue="kraken",
        pair="SUIUSD",
        bar_ts=bar_ts,
        intent="entry",
    )
    assert add.form["cl_ord_id"] == expected_coid

    # Second tick on the same bar: run.tick's `_already_journaled` skips
    # the pack iteration; no second AddOrder.
    rc2 = cmd_tick(["--venue", "kraken"], fetch=_fake_fetch(candles), transport=transport)
    assert rc2 == 0
    adds_after = [c for c in transport.calls if c.url.endswith("/AddOrder")]
    assert len(adds_after) == 1, f"second tick must not place another order; got {len(adds_after)}"


def test_paper_arm_with_env_1_passes_paper_venue_to_run_tick(home, fresh_keyring, monkeypatch):
    """Paper arm, env=1: the object passed to `run.tick` is a PaperVenue.

    `venue_for_tick` returns the PaperVenue for `armed.mode == "paper"`;
    cmd_tick does not build PaperVenue itself for a live arm. Even with
    KRELLBOT_ENABLE_LIVE=1, a paper arm stays on PaperVenue.
    """
    from krellbot.cli import cmd_tick
    from krellbot.venues.paper import PaperVenue

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home, pack_id="lw-paper")
    _arm(home, pack_path, mode="paper", pack_id="lw-paper")

    captured: list[tuple[str, object, object]] = []
    transport = FakeKrakenTransport()

    def spy(*, venue, venue_obj, reader, **kwargs):
        captured.append((venue, venue_obj, reader))
        return 0

    monkeypatch.setattr("krellbot.run.tick", spy)

    rc = cmd_tick(["--venue", "kraken"], fetch=_fake_fetch([]), transport=transport)

    assert rc == 0
    assert len(captured) == 1
    venue_arg, venue_obj_arg, _reader_arg = captured[0]
    assert venue_arg == "kraken"
    assert isinstance(venue_obj_arg, PaperVenue)
    # The Kraken transport must not have been touched for a paper tick.
    assert transport.calls == []


def test_paper_tick_with_a_stored_key_posts_validate_true(home, fresh_keyring, monkeypatch):
    """A paper entry with a stored Kraken key posts validate=true and does not treat it as a fill."""
    from krellbot.cli import cmd_tick

    pack_path = _write_pack(home, pack_id="paper-validate")
    _arm(home, pack_path, mode="paper", pack_id="paper-validate")
    _store_kraken_key(fresh_keyring)
    candles = [
        _candle(0, "10"),
        _candle(3_600_000, "10"),
        _candle(7_200_000, "12"),
    ]
    transport = FakeKrakenTransport(asset_pairs=_asset_pairs_for("SUIUSD"))

    rc = cmd_tick(["--venue", "kraken"], fetch=_fake_fetch(candles), transport=transport)

    assert rc == 0
    validates = [c for c in transport.calls if c.form.get("validate") == "true"]
    assert len(validates) == 1
    assert validates[0].form["pair"] == "SUIUSD"
    assert all(c.form.get("validate") == "true" for c in transport.calls if c.url.endswith("/AddOrder"))


def test_lapsed_license_blocks_entry_but_allows_exit(home, fresh_keyring, monkeypatch):
    """Lapsed license cache: no entry POST; an exit for a quantity the
    journal already owns is still placed.

    Setup: a live arm with `requires_license=True`, a position recorded in
    the journal, and base on the snapshot. The latest bar triggers an exit
    (close crosses below sma2).
    """
    from krellbot import journal
    from krellbot.cli import cmd_tick
    from krellbot.config import ArmedPack, Config, save_config
    from krellbot.run import coid_for

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home, pack_id="lw-lapsed")
    _arm(home, pack_path, mode="live", requires_license=True, pack_id="lw-lapsed")
    _store_kraken_key(fresh_keyring)

    # Lapsed cache: status past_due + grace_until in the past.
    catalog_dir = home / "catalog"
    catalog_dir.mkdir(parents=True, exist_ok=True)
    (catalog_dir / "license-cache.json").write_text(
        json.dumps({"status": "past_due", "period_end": 0, "grace_until": 1}),
        encoding="utf-8",
    )

    # Pre-existing position. Journal says this pack bought 5 SUI on bar 0.
    journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "lw-lapsed",
            "bar_ts": 0,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )
    config = Config(
        armed=[
            ArmedPack(
                pack_path=str(pack_path),
                pack_sha256="0" * 64,
                pack_id="lw-lapsed",
                pack_version="1.0.0",
                venue="kraken",
                pair="SUIUSD",
                cap=Decimal(100),
                stop=Decimal(5),
                mode="live",
                starting_cash=None,
                requires_license=True,
                armed_at_ts=1,
                owned_qty=Decimal(5),
            )
        ]
    )
    save_config(home, config)

    # OpenOrders: a buy already in place (from the earlier entry). AddOrder
    # response queue holds an exit sell fill.
    open_orders = {
        "open": {
            "O-LIVED": {
                "userref": 1,
                "cl_ord_id": "stop-lw-lapsed",
                "vol": "5",
                "stopprice": "5",
                "descr": {"pair": "SUIUSD", "type": "buy", "ordertype": "stop-loss", "price": "5"},
            }
        }
    }

    class _FundedForExit(_FundedKrakenTransport):
        def post(self, url, form, headers):
            endpoint = url.rsplit("/", 1)[-1]
            if endpoint == "Balance":
                return {"error": [], "result": {"SUI": "5"}}
            return super().post(url, form, headers)

    transport = _FundedForExit(
        responses=[{"result": {"txid": ["TX-EXIT"]}}],
        asset_pairs=_asset_pairs_for("SUIUSD"),
        open_orders={"error": [], "result": open_orders},
    )

    # Two candles that drive close from above to below sma2.
    candles = [
        _candle(0, "12"),
        _candle(3_600_000, "12"),
        _candle(7_200_000, "8"),
    ]

    rc = cmd_tick(["--venue", "kraken"], fetch=_fake_fetch(candles), transport=transport)

    assert rc == 0
    adds = [c for c in transport.calls if c.url.endswith("/AddOrder")]
    # Exactly one AddOrder POST (the exit). No entry POST.
    assert len(adds) == 1, f"expected one exit POST, got {len(adds)}: {[c.form for c in adds]}"
    add = adds[0]
    assert add.form["type"] == "sell"
    assert add.form["pair"] == "SUIUSD"
    exit_coid = coid_for(
        pack_id="lw-lapsed",
        pack_version="1.0.0",
        venue="kraken",
        pair="SUIUSD",
        bar_ts=candles[-1].ts_ms,
        intent="exit",
    )
    assert add.form["cl_ord_id"] == exit_coid

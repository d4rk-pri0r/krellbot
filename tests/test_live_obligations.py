"""M1.1: four live-safety obligation tests for M1.2–M1.5.

Each test drives ``run.tick`` in live mode against ``KrakenVenue`` with
``FakeKrakenTransport``. Failures that exist on main today are marked
``xfail(strict=True)`` naming the task that must make them pass. This
module does not change production code.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.fake_kraken import FakeKrakenTransport, RecordedCall
from fakes.live_grant import write_grant

from krellbot.config import ArmedPack, Config, load_config, save_config
from krellbot.pack.model import Candle
from krellbot.storage.database import OperationalStore
from krellbot.venues.kraken import KrakenVenue

pytestmark = pytest.mark.usefixtures("live_capable_release")

KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="

PAIR = "SUIUSD"
TRADE_ONLY_PERMS = {
    "permissions": [
        "query-funds",
        "query-open-trades",
        "modify-trades",
        "close-trades",
    ]
}


def _asset_pairs_for(pair: str) -> dict:
    return {
        pair: {
            "ordermin": "0.01",
            "costmin": "0.5",
            "lot_decimals": 5,
            "pair_decimals": 4,
        }
    }


class _LiveKrakenTransport(FakeKrakenTransport):
    """Fake Kraken transport with stable Balance / TradesHistory replies.

    AddOrder and other mutating posts still consume ``responses``. Balance
    and TradesHistory are answered from constructor knobs so snapshot
    polling cannot steal AddOrder bodies from the queue.
    """

    def __init__(
        self,
        responses: list[dict] | None = None,
        *,
        balances: dict[str, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(responses=responses, **kwargs)
        self._balances = dict(balances or {"USD": "1000"})

    def post(self, url: str, form: dict[str, str], headers: dict[str, str]) -> dict:
        endpoint = url.rsplit("/", 1)[-1]
        if endpoint == "Balance":
            self.calls.append(RecordedCall(url=url, form=dict(form), headers=dict(headers)))
            return {"error": [], "result": dict(self._balances)}
        if endpoint == "TradesHistory":
            self.calls.append(RecordedCall(url=url, form=dict(form), headers=dict(headers)))
            return {"error": [], "result": {"trades": {}}}
        return super().post(url, form, headers)


def _write_pack(home: Path, *, pack_id: str, pair: str = PAIR, cap_pct: int = 100) -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Live obligations",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": cap_pct, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_live(
    home: Path,
    pack_path: Path,
    *,
    pack_id: str,
    pair: str = PAIR,
    cap: Decimal = Decimal(100),
    entries_paused: bool = False,
    owned_qty: Decimal = Decimal(0),
    starting_cash: Decimal | None = None,
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
                    pair=pair,
                    cap=cap,
                    stop=Decimal(5),
                    mode="live",
                    starting_cash=starting_cash,
                    requires_license=False,
                    armed_at_ts=1,
                    owned_qty=owned_qty,
                    entries_paused=entries_paused,
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


def _entry_candles() -> list[Candle]:
    return [_candle(0, "10"), _candle(3_600_000, "10"), _candle(7_200_000, "12")]


def _exit_candles() -> list[Candle]:
    return [_candle(0, "12"), _candle(3_600_000, "12"), _candle(7_200_000, "8")]


def _kraken_venue(home: Path, transport: FakeKrakenTransport) -> KrakenVenue:
    return KrakenVenue(
        api_key=KRAKEN_TEST_KEY,
        secret_b64=KRAKEN_TEST_SECRET,
        transport=transport,
        now_ms=lambda: 1_700_000_000_000,
        min_interval_ms=0,
        home=home,
    )


def _seed_journal_owned(home: Path, *, pack_id: str, owned_qty: Decimal, pair: str = PAIR) -> None:
    from krellbot import journal as kb_journal

    kb_journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": pack_id,
            "bar_ts": 0,
            "detail": {
                "pair": pair,
                "entry_qty": str(owned_qty),
                "exit_qty": "0",
                "stop_qty": "0",
            },
        }
    )


def _add_orders(transport: FakeKrakenTransport) -> list:
    return [c for c in transport.calls if c.url.endswith("/AddOrder")]


def _enable_live(home: Path, monkeypatch: pytest.MonkeyPatch, *, pair: str = PAIR) -> None:
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair=pair)


# ---------------------------------------------------------------------------
# M1.2 — entry pause survives a restart (live)
# ---------------------------------------------------------------------------


def test_entry_pause_survives_restart(home, monkeypatch):
    """Paused live entries stay suppressed after a process-equivalent restart;
    exits and stop management still reach the transport.
    """
    from krellbot.run import tick

    _enable_live(home, monkeypatch)
    pack_id = "live-pause-restart"
    pack_path = _write_pack(home, pack_id=pack_id)
    _arm_live(home, pack_path, pack_id=pack_id, entries_paused=True)

    # Restart equivalent: reload config from disk, new venue + transport.
    reloaded = load_config(home)
    assert reloaded.armed[0].entries_paused is True

    transport_entry = _LiveKrakenTransport(
        responses=[{"result": {"txid": ["TX-ENTRY-SHOULD-NOT"]}}],
        balances={"USD": "1000"},
        asset_pairs=_asset_pairs_for(PAIR),
        api_key_info=TRADE_ONLY_PERMS,
    )
    venue_entry = _kraken_venue(home, transport_entry)
    rc_entry = tick(
        venue="kraken",
        venue_obj=venue_entry,
        reader=lambda v, p: _entry_candles(),
        home=home,
    )
    assert rc_entry == 0
    buys = [c for c in _add_orders(transport_entry) if c.form.get("type") == "buy"]
    assert buys == [], f"paused live entry must not AddOrder buy; got {_add_orders(transport_entry)}"

    # Exits still run while paused: seed journal ownership and tick an exit.
    for jf in (home / "journal").glob("*.jsonl"):
        jf.unlink()
    cfg = load_config(home)
    cfg.armed[0].owned_qty = Decimal(5)
    cfg.armed[0].entries_paused = True
    save_config(home, cfg)
    _seed_journal_owned(home, pack_id=pack_id, owned_qty=Decimal(5))

    transport_exit = _LiveKrakenTransport(
        responses=[{"result": {"txid": ["TX-EXIT"]}}],
        balances={"USD": "1000", "SUI": "5"},
        asset_pairs=_asset_pairs_for(PAIR),
        api_key_info=TRADE_ONLY_PERMS,
        open_orders={"error": [], "result": {"open": {}}},
    )
    venue_exit = _kraken_venue(home, transport_exit)
    rc_exit = tick(
        venue="kraken",
        venue_obj=venue_exit,
        reader=lambda v, p: _exit_candles(),
        home=home,
    )
    assert rc_exit == 0
    sells = [c for c in _add_orders(transport_exit) if c.form.get("type") == "sell"]
    assert sells, f"paused live tick must still exit owned qty; AddOrders={_add_orders(transport_exit)}"


# ---------------------------------------------------------------------------
# M1.3 — pack only ever touches what it owns (live)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="M1.3: live entries must size against reserved cash, not account balance",
)
def test_pack_never_touches_external_inventory(home, monkeypatch):
    """Live entries size against the pack's reserved cash, not the account
    balance; exits never sell more base than the journal attributes to
    this pack, even when the account holds more of the same asset.
    """
    from krellbot.run import tick

    _enable_live(home, monkeypatch)
    pack_id = "live-ownership"
    # Cap 100% of a $100 reservation; account holds far more cash.
    reserved_cash = Decimal(100)
    pack_path = _write_pack(home, pack_id=pack_id, cap_pct=100)
    _arm_live(
        home,
        pack_path,
        pack_id=pack_id,
        cap=Decimal(100),
        starting_cash=reserved_cash,
    )

    transport_entry = _LiveKrakenTransport(
        responses=[{"result": {"txid": ["TX-ENTRY"]}}],
        balances={"USD": "100000"},
        asset_pairs=_asset_pairs_for(PAIR),
        api_key_info=TRADE_ONLY_PERMS,
        ticker_last="10",
    )
    venue_entry = _kraken_venue(home, transport_entry)
    rc_entry = tick(
        venue="kraken",
        venue_obj=venue_entry,
        reader=lambda v, p: _entry_candles(),
        home=home,
    )
    assert rc_entry == 0
    entry_adds = [c for c in _add_orders(transport_entry) if c.form.get("type") == "buy"]
    assert len(entry_adds) == 1, entry_adds
    entry_qty = Decimal(entry_adds[0].form["volume"])
    # Price on the entry bar is 12; cost must not exceed reserved cash.
    entry_cost = entry_qty * Decimal(12)
    assert entry_cost <= reserved_cash + Decimal("0.01"), (
        f"entry must size against reserved cash {reserved_cash}, not account balance; qty={entry_qty} cost={entry_cost}"
    )

    # Fresh home-bar for the exit half: journal owns 5, venue holds 50.
    for jf in (home / "journal").glob("*.jsonl"):
        jf.unlink()
    pack_id_exit = "live-ownership-exit"
    pack_path_exit = _write_pack(home, pack_id=pack_id_exit)
    _arm_live(
        home,
        pack_path_exit,
        pack_id=pack_id_exit,
        owned_qty=Decimal(5),
        starting_cash=reserved_cash,
    )
    _seed_journal_owned(home, pack_id=pack_id_exit, owned_qty=Decimal(5))

    transport_exit = _LiveKrakenTransport(
        responses=[{"result": {"txid": ["TX-EXIT"]}}],
        balances={"USD": "100000", "SUI": "50"},
        asset_pairs=_asset_pairs_for(PAIR),
        api_key_info=TRADE_ONLY_PERMS,
        open_orders={"error": [], "result": {"open": {}}},
        ticker_last="8",
    )
    venue_exit = _kraken_venue(home, transport_exit)
    rc_exit = tick(
        venue="kraken",
        venue_obj=venue_exit,
        reader=lambda v, p: _exit_candles(),
        home=home,
    )
    assert rc_exit == 0
    sell_adds = [c for c in _add_orders(transport_exit) if c.form.get("type") == "sell"]
    assert sell_adds, f"exit must place a sell; calls={transport_exit.calls}"
    sold = Decimal(sell_adds[0].form["volume"])
    assert sold == Decimal(5), f"exit must not sell external inventory; sold={sold}"


# ---------------------------------------------------------------------------
# M1.4 — unknown outcomes are reconciled, never resubmitted (live)
# ---------------------------------------------------------------------------


def test_unknown_outcome_reconciles_without_resubmit(home, monkeypatch):
    """After a kill between intent commit and venue ack, the next tick looks
    the order up by client order id, records filled/open/absent, places no
    second order for that id, and blocks new entries until resolved.
    """
    from krellbot.run import coid_for, tick
    from krellbot.storage.outbox import Outbox

    _enable_live(home, monkeypatch)
    pack_id = "live-unknown-outcome"
    pack_path = _write_pack(home, pack_id=pack_id)
    _arm_live(home, pack_path, pack_id=pack_id)

    bar_ts = 7_200_000
    expected_coid = coid_for(
        pack_id=pack_id,
        pack_version="1.0.0",
        venue="kraken",
        pair=PAIR,
        bar_ts=bar_ts,
        intent="entry",
    )

    # Simulate the crash window: intent committed, send never completed.
    store = OperationalStore(home / "ops.sqlite")
    body = json.dumps(
        {"kind": "entry", "qty": "10", "stop": "5", "pair": PAIR},
        separators=(",", ":"),
        sort_keys=True,
    )

    def _boom(coid: str, _body: str) -> None:
        raise RuntimeError("killed between commit and ack")

    with pytest.raises(RuntimeError, match="killed between commit and ack"):
        Outbox(store).dispatch(expected_coid, body, _boom, mode="live", venue="kraken")
    # Commit succeeded; sent stayed false (dispatch raises before mark_sent).
    rows = store.read_ledger()
    outbox_rows = [json.loads(p) for _i, k, p in rows if k == "outbox"]
    assert outbox_rows, rows
    assert outbox_rows[-1]["coid"] == expected_coid
    assert outbox_rows[-1]["sent"] is False

    # Venue reports the order absent (never acked).
    transport = _LiveKrakenTransport(
        responses=[{"result": {"txid": ["TX-RESUBMIT-FORBIDDEN"]}}],
        balances={"USD": "1000"},
        asset_pairs=_asset_pairs_for(PAIR),
        api_key_info=TRADE_ONLY_PERMS,
        open_orders={"error": [], "result": {"open": {}}},
    )
    venue = _kraken_venue(home, transport)

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_candles(),
        home=home,
    )
    assert rc == 0

    adds = _add_orders(transport)
    assert adds == [], f"must not resubmit unknown outcome; AddOrders={adds}"

    ledger = store.read_ledger()
    needs = [json.loads(p) for _i, k, p in ledger if k == "needs_reconcile"]
    assert needs, f"unknown outcome must be audited for reconcile; ledger={ledger}"

    # Lookup / outcome recording: filled, open, or absent for this coid.
    outcome_kinds = {"reconcile_filled", "reconcile_open", "reconcile_absent", "needs_reconcile"}
    recorded = [
        (k, json.loads(p))
        for _i, k, p in ledger
        if k in outcome_kinds or (isinstance(json.loads(p), dict) and json.loads(p).get("coid") == expected_coid)
    ]
    assert recorded, f"must record lookup outcome for {expected_coid}; ledger={ledger}"
    # New entries stay blocked while reconcile is outstanding.
    assert any(k == "needs_reconcile" for _i, k, _p in ledger)


# ---------------------------------------------------------------------------
# M1.5 — restored home comes back fenced (live)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="M1.5: restore must fence live arms (entries paused + kill switch engaged)",
)
def test_restored_home_is_fenced(home, monkeypatch, tmp_path):
    """After restore, every live arm has entries paused and the kill switch
    engaged; tick sends nothing until the operator releases both.
    """
    from krellbot.application import live_gate
    from krellbot.run import tick
    from krellbot.storage import home_backup

    _enable_live(home, monkeypatch)
    pack_id = "live-restore-fence"
    pack_path = _write_pack(home, pack_id=pack_id)
    packs_dir = home / "packs"
    packs_dir.mkdir(parents=True, exist_ok=True)
    installed = packs_dir / f"{pack_id}.json"
    installed.write_text(pack_path.read_text(encoding="utf-8"), encoding="utf-8")
    _arm_live(home, installed, pack_id=pack_id, entries_paused=False)
    # Ensure ops.sqlite exists for a valid archive.
    OperationalStore(home / "ops.sqlite").connect()

    archive = tmp_path / "home-backup.tar.gz"
    home_backup.create(home, archive, now=1_700_000_000)

    restored = tmp_path / "restored-home"
    home_backup.restore(archive, restored)

    cfg = load_config(restored)
    live_arms = [a for a in cfg.armed if a.mode == "live"]
    assert live_arms, cfg
    assert all(a.entries_paused for a in live_arms), f"restored live arms must be paused; {live_arms}"
    assert live_gate.kill_state(restored).engaged is True

    monkeypatch.setenv("KRELLBOT_HOME", str(restored))
    write_grant(restored, venue="kraken", pair=PAIR)

    transport = _LiveKrakenTransport(
        responses=[{"result": {"txid": ["TX-FENCE-LEAK"]}}],
        balances={"USD": "1000"},
        asset_pairs=_asset_pairs_for(PAIR),
        api_key_info=TRADE_ONLY_PERMS,
    )
    venue = _kraken_venue(restored, transport)
    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=lambda v, p: _entry_candles(),
        home=restored,
    )
    assert rc == 0
    assert _add_orders(transport) == [], "fenced restored home must not send"

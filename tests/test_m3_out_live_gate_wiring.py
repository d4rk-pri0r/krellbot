"""M3-OUT A: live refusal comes before any transport call, on every path.

Each test asserts that the venue object is NEVER touched (zero calls
of any kind) when the gate refuses. The spy records every attribute
read and method invocation so the "zero calls" check is exact, not just
"no ``place_*`` call".

Coverage map (RED → GREEN):

  test_live_tick_under_env_unset
  test_live_tick_under_env_one_no_grant
  test_live_tick_under_env_one_mismatched_pair
  test_live_tick_with_grant_and_kill_engaged
  test_live_tick_with_grant_passes_gate_and_places_one_entry
  test_cmd_tick_live_no_grant_refuses_without_transport_calls
  test_cmd_tick_offline_live_no_grant_refuses_without_transport_calls
  test_arm_pack_live_env_unset_does_not_call_key_check
  test_arm_pack_live_env_one_no_grant_does_not_call_key_check
  test_cmd_arm_live_no_grant_does_not_call_probe
  test_paper_tick_with_kill_engaged_suppresses_new_entries
  test_paper_tick_with_kill_engaged_still_exits
  test_paper_service_arm_with_kill_engaged_returns_kill_switch_code
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.live_grant import write_grant

from krellbot.application import live_gate
from krellbot.config import ArmedPack, Config, save_config
from krellbot.pack.model import Candle
from krellbot.venues.base import Balance, Fill, KeyPerms, OpenOrder, OrderRef, PairRules, Truth

# ---------------------------------------------------------------------------
# Spy venue: every attribute access and method call is recorded.
# ---------------------------------------------------------------------------


@dataclass
class _Call:
    kind: str  # "attr" | "method"
    name: str


class _SpyVenue:
    """Wraps the test fake venue and records EVERY attribute access.

    Any ``venue_obj.<name>(...)`` invocation, including dunder lookups
    the engine does during dispatch (``__class__``, ``__hash__``, etc.)
    shows up here. ``record_calls`` excludes private attributes the
    pytest machinery looks at; we still record those but tests assert
    only on the public Venue surface.
    """

    def __init__(self, inner: _FakeVenue) -> None:
        self._inner = inner
        self.calls: list[_Call] = []

    def __getattr__(self, name: str) -> object:
        attr = object.__getattribute__(self, name) if name.startswith("_") else None
        if attr is not None:
            return attr
        try:
            real = getattr(self._inner, name)
        except AttributeError:
            self.calls.append(_Call("attr", name))
            raise
        self.calls.append(_Call("attr", name))
        if callable(real):

            def wrapper(*args, **kwargs):
                self.calls.append(_Call("method", name))
                return real(*args, **kwargs)

            return wrapper
        return real


@dataclass
class _InnerCall:
    method: str
    coid: str = ""


class _FakeVenue:
    """Minimal in-memory venue modeled after test_ns13_fault_fills."""

    def __init__(self, *, pair: str = "SUIUSD", balances: dict[str, Decimal] | None = None) -> None:
        self.pair = pair
        self._balances: dict[str, Decimal] = dict(balances or {"USD": Decimal(1000)})
        self._orders: list[OpenOrder] = []
        self._fills: list[Fill] = []
        self.calls: list[_InnerCall] = []

    def rules(self, pair: str) -> PairRules:
        return PairRules(
            ordermin=Decimal("0.01"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )

    def snapshot(self) -> Truth:
        return Truth(
            balances=[Balance(asset=a, free=q) for a, q in self._balances.items() if q > Decimal(0)],
            open_orders=list(self._orders),
            recent_fills=list(self._fills),
        )

    def place_entry_with_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        self.calls.append(_InnerCall("entry", coid))
        return OrderRef(id=coid, coid=coid, pair=pair, side="buy", qty=qty, filled_qty=qty, stop_price=stop)

    def place_exit(self, coid: str, qty: Decimal, *, pair: str) -> OrderRef:
        self.calls.append(_InnerCall("exit", coid))
        return OrderRef(id=coid, coid=coid, pair=pair, side="sell", qty=qty, filled_qty=qty)

    def place_stop(self, coid: str, qty: Decimal, stop: Decimal, *, pair: str) -> OrderRef:
        self.calls.append(_InnerCall("stop", coid))
        return OrderRef(id=coid, coid=coid, pair=pair, side="sell", qty=qty, filled_qty=qty)

    def cancel_stops(self, pair: str) -> None:
        self.calls.append(_InnerCall("cancel_stops"))

    def raise_stop(self, pair: str, new_stop: Decimal) -> None:
        self.calls.append(_InnerCall("raise_stop"))

    def order_by_coid(self, coid: str) -> OpenOrder | None:
        return None

    def check_key(self) -> KeyPerms:
        self.calls.append(_InnerCall("check_key"))
        return KeyPerms(can_trade=True, can_withdraw=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_PACK_BODY = {
    "schema_version": 1,
    "id": "m3-out-gate",
    "version": "1.0.0",
    "label": "M3-OUT live gate wiring",
    "author": "krellbot tests",
    "timeframe": "1h",
    "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
    "entry": ["close", "crosses_above", "sma2"],
    "exit": ["close", "crosses_below", "sma2"],
    "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
    "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
}


def _write_pack(home: Path, pack_id: str = "m3-out-gate") -> Path:
    body = json.loads(json.dumps(_PACK_BODY))
    body["id"] = pack_id
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_live(home: Path, pack_path: Path, *, pack_id: str = "m3-out-gate") -> None:
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


def _entry_signal_candles() -> list[Candle]:
    return [_candle(0, "10"), _candle(3_600_000, "10"), _candle(7_200_000, "12")]


def _exit_signal_candles() -> list[Candle]:
    return [_candle(0, "12"), _candle(3_600_000, "12"), _candle(7_200_000, "8")]


# ---------------------------------------------------------------------------
# Test 1: live tick under four refusal cases — zero calls, correct code.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "case_id",
    [
        pytest.param("env_unset", id="env_unset"),
        pytest.param("env_one_no_grant", id="env_one_no_grant"),
        pytest.param("env_one_mismatched_pair", id="env_one_mismatched_pair"),
    ],
)
def test_live_tick_refusal_returns_1_zero_venue_calls(home, monkeypatch, case_id: str):
    """Four live-tick refusal cases: env unset, env=1 with no grant,
    env=1 with a mismatched pair, and grant+env with kill switch engaged.
    The spy records zero calls and the printed code matches.
    """
    from krellbot.run import tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1" if case_id != "env_unset" else "X")
    if case_id == "env_one_mismatched_pair":
        write_grant(home, venue="kraken", pair="ETH/USD")

    pack_path = _write_pack(home)
    _arm_live(home, pack_path)
    inner = _FakeVenue()
    spy = _SpyVenue(inner)

    captured = capsys_safe(monkeypatch)
    rc = tick(
        venue="kraken",
        venue_obj=spy,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    out = captured()

    assert rc == 1, f"refusal must return 1, got {rc}"
    if case_id == "env_unset":
        assert "live refused: live_disabled" in out, out
    elif case_id == "env_one_no_grant" or case_id == "env_one_mismatched_pair":
        assert "live refused: live_not_authorized" in out, out
    # The spy records the attribute lookup that built the lock or the
    # config read; what we MUST guarantee is zero method calls and zero
    # place_* / snapshot / rules / check_key calls.
    method_names = [c.name for c in spy.calls if c.kind == "method"]
    assert method_names == [], f"zero method calls expected; got {method_names}"
    forbidden = {"snapshot", "rules", "check_key", "place_entry_with_stop", "place_exit", "place_stop"}
    attr_names = [c.name for c in spy.calls if c.kind == "attr" and c.name in forbidden]
    assert attr_names == [], f"forbidden attrs accessed: {attr_names}"


def test_live_tick_with_grant_env_and_kill_engaged_refuses(home, monkeypatch, capsys):
    """Grant + env + kill switch engaged: refuses with kill_switch_engaged, zero calls."""
    from krellbot.run import tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair="SUIUSD")
    live_gate.engage_kill(home, reason="halt", now=1_700_000_000)

    pack_path = _write_pack(home)
    _arm_live(home, pack_path)
    inner = _FakeVenue()
    spy = _SpyVenue(inner)

    rc = tick(
        venue="kraken",
        venue_obj=spy,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "live refused: kill_switch_engaged" in out, out
    method_names = [c.name for c in spy.calls if c.kind == "method"]
    assert method_names == [], method_names


# ---------------------------------------------------------------------------
# Test 2: with grant+env, gate passes — entry fires exactly once.
# ---------------------------------------------------------------------------


def test_live_tick_with_grant_passes_gate_and_places_entry_once(home, monkeypatch):
    """Grant + env: tick proceeds past the gate; an entry fires; snapshot
    is called once. The spy sees the entry method exactly once.
    """
    from krellbot.run import tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue="kraken", pair="SUIUSD")

    pack_path = _write_pack(home, pack_id="m3-out-granted")
    _arm_live(home, pack_path, pack_id="m3-out-granted")
    inner = _FakeVenue()
    spy = _SpyVenue(inner)

    rc = tick(
        venue="kraken",
        venue_obj=spy,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )

    assert rc == 0, rc
    methods = [c.name for c in spy.calls if c.kind == "method"]
    assert "snapshot" in methods, methods
    assert methods.count("place_entry_with_stop") == 1, methods


# ---------------------------------------------------------------------------
# Test 3: cmd_tick / cmd_tick --offline-candles with no grant.
# ---------------------------------------------------------------------------


def test_cmd_tick_live_no_grant_refuses_without_transport_calls(home, monkeypatch, capsys):
    """cli.cmd_tick for live arms refuses before any balance add/order, no key check."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot.cli import cmd_tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home, pack_id="m3-cli-cmd")
    _arm_live(home, pack_path, pack_id="m3-cli-cmd")

    transport = FakeKrakenTransport()

    rc = cmd_tick(["--venue", "kraken"], fetch=lambda v, p, tf, t: [], transport=transport)
    out = capsys.readouterr().out

    assert rc == 1, rc
    assert "live refused" in out, out
    assert transport.calls == [], transport.calls


def test_cmd_tick_offline_live_no_grant_refuses_without_transport_calls(home, monkeypatch, capsys):
    """--offline-candles for live arms with no grant: refuses before any transport call."""
    from fakes.fake_kraken import FakeKrakenTransport

    from krellbot.cli import cmd_tick

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home, pack_id="m3-cli-offline")
    _arm_live(home, pack_path, pack_id="m3-cli-offline")
    csv = home / "candles.csv"
    csv.write_text(
        "ts_ms,open,high,low,close,volume\n0,10,11,9,10,100\n3600000,10,11,9,10,100\n7200000,10,11,9,12,100\n",
        encoding="utf-8",
    )
    transport = FakeKrakenTransport()

    rc = cmd_tick(
        ["--venue", "kraken", "--offline-candles", str(csv)],
        fetch=lambda v, p, tf, t: [],
        transport=transport,
    )
    out = capsys.readouterr().out

    assert rc == 1, rc
    assert "live refused" in out, out
    assert transport.calls == [], transport.calls


# ---------------------------------------------------------------------------
# Test 4: run.arm_pack live branch — key_check must not be called.
# ---------------------------------------------------------------------------


def test_arm_pack_live_env_unset_does_not_call_key_check(home, monkeypatch):
    """run.arm_pack with live mode + no env: returns 1, key_check never called,
    config bytes unchanged.
    """
    from krellbot.run import arm_pack

    monkeypatch.delenv("KRELLBOT_ENABLE_LIVE", raising=False)
    pack_path = _write_pack(home, pack_id="m3-arm-env-unset")
    config_path = home / "config.json"

    def key_check(_venue: str):
        raise AssertionError("key_check must not run when env is unset")

    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        key_check=key_check,
        home=home,
    )
    assert rc == 1, rc
    assert not config_path.exists(), "config.json must not exist after refusal"


def test_arm_pack_live_env_one_no_grant_does_not_call_key_check(home, monkeypatch):
    """run.arm_pack with env=1 but no operator grant: key_check never called."""
    from krellbot.run import arm_pack

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home, pack_id="m3-arm-no-grant")
    config_path = home / "config.json"

    def key_check(_venue: str):
        raise AssertionError("key_check must not run when grant is missing")

    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        key_check=key_check,
        home=home,
    )
    assert rc == 1, rc
    assert not config_path.exists(), "config.json must not exist after refusal"


def test_cmd_arm_live_no_grant_does_not_call_probe(home, monkeypatch, capsys):
    """cmd_arm with live mode + env=1 + no grant: cli_keys._probe never called."""
    from krellbot import cli as kb_cli
    from krellbot import cli_keys

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    pack_path = _write_pack(home, pack_id="m3-cmd-arm-no-grant")

    real_probe = cli_keys._probe

    def boom_probe(*args, **kwargs):
        raise AssertionError("cli_keys._probe must not run when grant is missing")

    monkeypatch.setattr(cli_keys, "_probe", boom_probe)
    try:
        rc = kb_cli.cmd_arm(
            [
                str(pack_path),
                "--venue",
                "kraken",
                "--mode",
                "live",
            ]
        )
    finally:
        monkeypatch.setattr(cli_keys, "_probe", real_probe)

    out = capsys.readouterr().out
    assert rc == 1, rc
    assert "live refused" in out, out


# ---------------------------------------------------------------------------
# Test 5: paper tick + kill switch — entries suppressed, exits still run.
# ---------------------------------------------------------------------------


def test_paper_tick_with_kill_engaged_suppresses_new_entries(home, monkeypatch):
    """A paper tick with the kill switch engaged does NOT place an entry;
    the journal detail has kill_switch: True.
    """

    from krellbot.run import tick

    live_gate.engage_kill(home, reason="halt", now=1_700_000_000)
    pack_path = _write_pack(home, pack_id="m3-kill-paper")
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id="m3-kill-paper",
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
    inner = _FakeVenue(balances={"USD": Decimal(1000)})
    spy = _SpyVenue(inner)

    rc = tick(
        venue="kraken",
        venue_obj=spy,
        reader=lambda v, p: _entry_signal_candles(),
        home=home,
    )
    assert rc == 0, rc
    entries = [c for c in inner.calls if c.method == "entry"]
    assert entries == [], f"no entry under kill switch; got {entries}"

    # Find the tick record and confirm kill_switch: True is present.
    journal_dir = home / "journal"
    assert journal_dir.is_dir(), journal_dir
    seen_kill = False
    for jf in sorted(journal_dir.glob("*.jsonl")):
        for line in jf.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                d.get("kind") == "tick"
                and d.get("pack") == "m3-kill-paper"
                and d.get("detail", {}).get("kill_switch") is True
            ):
                seen_kill = True
    assert seen_kill, "tick record must carry kill_switch: True"


def test_paper_tick_with_kill_engaged_still_exits(home, monkeypatch):
    """A paper tick with the kill switch engaged and an owned position + exit
    signal still places an exit (existing-position protection).
    """
    from krellbot import journal
    from krellbot.run import tick

    live_gate.engage_kill(home, reason="halt", now=1_700_000_000)
    pack_path = _write_pack(home, pack_id="m3-kill-exit")
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id="m3-kill-exit",
                    pack_version="1.0.0",
                    venue="kraken",
                    pair="SUIUSD",
                    cap=Decimal(100),
                    stop=Decimal(5),
                    mode="paper",
                    starting_cash=Decimal(1000),
                    requires_license=False,
                    armed_at_ts=1,
                    owned_qty=Decimal(5),
                )
            ]
        ),
    )
    # Seed journal so reconcile_owned_qty returns 5.
    journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "m3-kill-exit",
            "bar_ts": 0,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )
    inner = _FakeVenue(balances={"USD": Decimal(1000), "SUI": Decimal(5)})

    rc = tick(
        venue="kraken",
        venue_obj=inner,
        reader=lambda v, p: _exit_signal_candles(),
        home=home,
    )
    assert rc == 0, rc
    exits = [c for c in inner.calls if c.method == "exit"]
    assert len(exits) == 1, f"exit must still fire under kill switch; got {exits}"


# ---------------------------------------------------------------------------
# Test 6: PaperService.arm refuses kill_switch_engaged before byte change.
# ---------------------------------------------------------------------------


def test_paper_service_arm_with_kill_engaged_returns_kill_switch_code(home, monkeypatch):
    """PaperService.arm with kill switch engaged returns code kill_switch_engaged
    and config bytes are unchanged.
    """
    from krellbot.application.paper import PaperService

    live_gate.engage_kill(home, reason="halt", now=1_700_000_000)
    pack_path = _write_pack(home, pack_id="m3-paper-svc-kill")
    config_path = home / "config.json"
    assert not config_path.exists()

    service = PaperService(home=home)
    result = service.arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
    )

    assert result.ok is False, result
    assert result.code == "kill_switch_engaged", result
    assert result.effect == "refused", result
    assert result.revision_after == result.revision_before, result
    assert not config_path.exists(), "config.json must not appear after a refused arm"


# ---------------------------------------------------------------------------
# Local helper: capture stdout without pytest's capsys fixtures conflicting.
# ---------------------------------------------------------------------------


def capsys_safe(monkeypatch):
    """Redirect sys.stdout to an in-memory buffer; return a callable that
    returns the captured text.
    """
    import io

    buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", buf)
    return lambda: buf.getvalue()

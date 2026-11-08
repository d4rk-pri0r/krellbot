"""Synthetic paper buys must fund the existing execution price and fee."""

import contextlib
import io
import json
import os
import subprocess
import sys
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

import pytest

from krellbot.application.paper import PaperService
from krellbot.pack.model import Candle
from krellbot.run import tick
from krellbot.venues.paper import PaperVenue, default_rules
from tests.test_ns04_research_service import PACK_DICT


def _bars():
    return [Candle(i * 3_600_000, Decimal(10), Decimal(10), Decimal(10), Decimal(10), Decimal(100)) for i in range(3)]


@pytest.mark.parametrize("venue,fee_bps", [("kraken", 40), ("coinbase", 120)])
@pytest.mark.parametrize("funding", ["raw-notional", "slipped-notional", "exact"])
def test_entry_refusal_is_byte_identical_and_exact_funding_deduplicates(home, venue, fee_bps, funding):
    qty = Decimal(100)
    price = (Decimal(10) * Decimal("1.0005")).quantize(Decimal("0.00001"), rounding=ROUND_DOWN)
    notional = qty * price
    fee = (notional * fee_bps / 10000).quantize(Decimal("0.00001"), rounding=ROUND_DOWN)
    cash = {"raw-notional": qty * 10, "slipped-notional": notional, "exact": notional + fee}[funding]
    calls = []

    class ValidationSpy:
        def post(self, *args):
            calls.append(args)

    paper = PaperVenue(
        venue,
        rules_provider=default_rules,
        candle_reader=lambda *_: _bars(),
        home=home,
        starting_cash=cash,
        has_stored_key=True,
        validate_transport=ValidationSpy(),
    )
    state = home / "run" / f"paper-{venue}.json"
    before = state.read_bytes()
    if funding != "exact":
        with pytest.raises(ValueError, match="insufficient"):
            paper.place_entry_with_stop("synthetic-buy", qty, Decimal(5), pair="SUIUSD")
        assert state.read_bytes() == before
        assert not paper.snapshot().recent_fills and not paper.snapshot().open_orders
        assert calls == []
    else:
        order = paper.place_entry_with_stop("synthetic-buy", qty, Decimal(5), pair="SUIUSD")
        assert Decimal(json.loads(state.read_text())["balances"]["USD"]) == 0
        after = state.read_bytes()
        existing = paper.order_by_coid("synthetic-buy")
        repeated = paper.place_entry_with_stop("synthetic-buy", qty, Decimal(5), pair="SUIUSD")
        assert repeated.id == order.id and repeated.coid == order.coid and repeated.qty == order.qty
        assert repeated.side == existing.side  # Existing dedup returns the resting stop's side.
        assert state.read_bytes() == after
        assert len(paper.snapshot().recent_fills) == len(paper.snapshot().open_orders) == 1


def test_triggered_stop_settlement_is_not_rolled_back_on_unfunded_new_buy(home):
    bars = _bars()
    paper = PaperVenue(
        "kraken", rules_provider=default_rules, candle_reader=lambda *_: bars, home=home, starting_cash=Decimal(1000)
    )
    paper.place_entry_with_stop("synthetic-old", Decimal(10), Decimal(9), pair="SUIUSD")
    state = home / "run" / "paper-kraken.json"
    before_cash = Decimal(json.loads(state.read_text())["balances"]["USD"])
    bars.append(Candle(10_800_000, Decimal(8), Decimal(8), Decimal(8), Decimal(8), Decimal(100)))
    with pytest.raises(ValueError, match="insufficient"):
        paper.place_entry_with_stop("synthetic-unfunded", Decimal(1000), Decimal(4), pair="SUIUSD")
    saved = json.loads(state.read_text())
    assert Decimal(saved["balances"]["USD"]) > before_cash
    assert [f["side"] for f in saved["recent_fills"]] == ["buy", "sell"]
    assert not saved["open_orders"]
    assert all(f["coid"] != "synthetic-unfunded" for f in saved["recent_fills"])


def _public_flow(home, cap):
    pack = {
        **PACK_DICT,
        "label": "Synthetic affordability flow",
        "entry": ["close", ">=", "sma2"],
        "exit": ["close", "<", "sma2"],
        "risk": {"max_account_pct": cap, "stop": {"type": "pct", "pct": 50}},
    }
    path = home / "synthetic-pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        result = PaperService(home=home).arm(path, venue="kraken", mode="paper", paper_balance=Decimal(1000))
        assert result.ok
        paper = PaperVenue(
            "kraken",
            rules_provider=default_rules,
            candle_reader=lambda *_: _bars(),
            home=home,
            starting_cash=Decimal(1000),
        )
        assert tick(venue="kraken", venue_obj=paper, reader=lambda *_: _bars(), home=home) == 0


@pytest.mark.parametrize("cap,filled", [(100, False), (99, True)])
def test_public_arm_tick_and_new_process_readback_never_create_insolvent_cash(home, cap, filled):
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"}}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        KRELLBOT_HOME=str(home),
        TMPDIR=str(home),
        TMP=str(home),
        TEMP=str(home),
        PYTHONPATH=str(Path(__file__).resolve().parents[1]),
        KRELLBOT_ENABLE_LIVE="0",
        PYTHON_KEYRING_BACKEND="keyring.backends.null.Keyring",
    )
    script = "from pathlib import Path;import sys;from tests.test_paper_entry_quote_affordability import _public_flow;_public_flow(Path(sys.argv[1]),int(sys.argv[2]))"
    subprocess.run([sys.executable, "-c", script, str(home), str(cap)], env=env, cwd=home, check=True, timeout=30)
    read = "from pathlib import Path;import sys;print((Path(sys.argv[1])/'run/paper-kraken.json').read_text())"
    result = subprocess.run(
        [sys.executable, "-c", read, str(home)],
        env=env,
        cwd=home,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    state = json.loads(result.stdout)
    assert Decimal(state["balances"]["USD"]) >= 0
    assert len(state["recent_fills"]) == len(state["open_orders"]) == int(filled)

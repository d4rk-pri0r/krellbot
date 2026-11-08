"""Fresh synthetic paper arm/tick processes must keep replay identity per market."""

import contextlib
import inspect
import io
import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot import run
from krellbot.application.paper import PaperService
from krellbot.pack.model import Candle
from krellbot.storage.database import OperationalStore
from krellbot.venues.base import PairRules
from krellbot.venues.paper import PaperVenue
from tests.test_ns04_research_service import PACK_DICT


def _invoke(home, action, venue, pair):
    bars = [
        Candle(i * 3_600_000, Decimal(c), Decimal(c) + 1, Decimal(c) - 1, Decimal(c), Decimal(100))
        for i, c in enumerate([10, 9, 12])
    ]
    with contextlib.redirect_stdout(io.StringIO()):
        if action == "arm":
            pack = {
                **PACK_DICT,
                "label": "Synthetic replay namespace fixture",
                "risk": {"max_account_pct": 10, "stop": {"type": "pct", "pct": 50}},
                "markets": [{"venue": venue, "pair": pair}],
            }
            path = home / f"synthetic-{venue}-{pair}.json"
            path.write_text(json.dumps(pack), encoding="utf-8")
            result = PaperService(home=home).arm(path, venue=venue, mode="paper", paper_balance=Decimal(1000))
            return {"ok": result.ok, "code": result.code}

        def reader(*_):
            return bars

        paper = PaperVenue(
            venue,
            rules_provider=lambda _: PairRules(Decimal("0.0001"), Decimal("0.5"), 8, 5),
            candle_reader=reader,
            home=home,
            starting_cash=Decimal(1000),
        )
        rc = run.tick(venue=venue, venue_obj=paper, reader=reader, home=home) if action == "tick" else 0
        truth = paper.snapshot()
    records = [
        json.loads(line)
        for path in (home / "journal").glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    outbox = [
        json.loads(payload)
        for _, kind, payload in OperationalStore(home / "ops.sqlite").read_ledger()
        if kind == "outbox"
    ]
    return {
        "rc": rc,
        "fills": [f.coid for f in truth.recent_fills],
        "stops": [o.coid for o in truth.open_orders],
        "ticks": [(r["venue"], r["detail"]["pair"]) for r in records if r.get("kind") == "tick"],
        "outbox": [(r["coid"], r["sent"]) for r in outbox],
    }


def _fresh(home, action, venue, pair):
    script = """
import json, sys
from pathlib import Path
from tests.test_tick_journal_market_identity import _invoke
def deny_network(event, args):
    if event in ('socket.connect', 'socket.getaddrinfo'): raise AssertionError('network forbidden')
sys.addaudithook(deny_network)
print(json.dumps(_invoke(Path(sys.argv[1]), *sys.argv[2:])))
"""
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
    result = subprocess.run(
        [sys.executable, "-c", script, str(home), action, venue, pair],
        cwd=home,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.parametrize(
    "markets",
    [
        [("kraken", "SUIUSD"), ("coinbase", "SUI-USD")],
        [("coinbase", "SUI-USD"), ("kraken", "SUIUSD")],
        [("kraken", "SUIUSD"), ("kraken", "BTCUSD")],
    ],
)
def test_public_arm_tick_persisted_fills_journal_outbox_and_fresh_repeat(home, markets):
    for venue, pair in markets:
        assert _fresh(home, "arm", venue, pair)["ok"]
    for venue, pair in markets:
        assert _fresh(home, "tick", venue, pair)["rc"] == 0
    states = {_venue: _fresh(home, "read", _venue, _pair) for _venue, _pair in markets}
    assert sum(len(state["fills"]) for state in states.values()) == 2
    assert sum(len(state["stops"]) for state in states.values()) == 2
    state = next(iter(states.values()))
    assert sorted(map(tuple, state["ticks"])) == sorted(markets)
    assert len(state["outbox"]) == 2 and all(sent for _, sent in state["outbox"])
    for venue, pair in markets:
        repeated = _fresh(home, "tick", venue, pair)
        assert repeated == states[venue]


def _seen(home, pack="synthetic", bar=123):
    # The private helper gains identity arguments; keep BASE runnable so RED
    # demonstrates matching behavior rather than an unexpected-keyword error.
    kwargs = (
        {"venue": "kraken", "pair": "SUIUSD"} if "venue" in inspect.signature(run._already_journaled).parameters else {}
    )
    return run._already_journaled(home, pack, bar, **kwargs)


@pytest.mark.parametrize(
    "venue,pair,expected",
    [
        ("kraken", "SUIUSD", True),
        ("coinbase", "SUIUSD", False),
        ("kraken", "BTCUSD", False),
        (None, None, True),
        ("", "", True),
        ({}, [], True),
        (123, 456, True),
        (" ", " ", True),
        (None, "BTCUSD", False),
        ("coinbase", None, False),
        ("kraken", None, True),
        (None, "SUIUSD", True),
    ],
)
def test_explicit_market_mismatch_only_excludes_usable_dimensions(home, venue, pair, expected):
    directory = home / "journal"
    directory.mkdir()
    path = directory / "synthetic.jsonl"
    record = {
        "kind": "tick",
        "pack": "synthetic",
        "bar_ts": 123,
        "venue": venue,
        "detail": {"pair": pair},
        "pack_version": "old",
    }
    path.write_text("not-json\n" + json.dumps(record) + "\n", encoding="utf-8")
    before = path.read_bytes()
    assert _seen(home) is expected
    assert not _seen(home, pack="different") and not _seen(home, bar=124)
    assert path.read_bytes() == before


def test_missing_dimensions_and_read_errors_keep_existing_conservative_behavior(home, monkeypatch):
    directory = home / "journal"
    directory.mkdir()
    path = directory / "synthetic.jsonl"
    path.write_text(json.dumps({"kind": "tick", "pack": "synthetic", "bar_ts": 123}) + "\n", encoding="utf-8")
    assert _seen(home)
    before = path.read_bytes()

    def unreadable(*args, **kwargs):
        raise OSError("synthetic read refusal")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", unreadable)
        assert not _seen(home)
    assert path.read_bytes() == before


@pytest.mark.parametrize("detail", [None, [], "unusable"])
def test_nonobject_legacy_detail_and_exact_neighbor_remain_conservative(home, detail):
    directory = home / "journal"
    directory.mkdir()
    path = directory / "synthetic.jsonl"
    record = {"kind": "tick", "pack": "synthetic", "bar_ts": 123, "venue": "kraken", "detail": detail}
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    assert _seen(home)
    wrong = {**record, "venue": "coinbase"}
    exact = {**record, "detail": {"pair": "SUIUSD"}, "pack_version": "new"}
    path.write_text(json.dumps(wrong) + "\n" + json.dumps(exact) + "\n", encoding="utf-8")
    assert _seen(home)

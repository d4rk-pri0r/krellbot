"""v0.9.6 TEMPORARY paper-only release policy.

Owner decision: v0.9.6 is paper-only regardless of environment, stored
keys, authorization files, or previously armed live state. The release is
not a permanent removal of live trading; an owner-approved code/release
change can re-enable it, so the policy lives in one code constant rather
than in configuration.

Every test here runs with the shipped default (policy enforced). The
``live_capable_release`` fixture used by older live-mechanics suites is a
test-only simulation of that future re-enable; no environment variable,
config setting, or UI control reaches it.
"""

from __future__ import annotations

import base64
import json
from decimal import Decimal
from pathlib import Path

import pytest
from fakes.fake_coinbase import FakeCoinbaseTransport
from fakes.fake_kraken import FakeKrakenTransport
from fakes.live_grant import write_grant

from krellbot import release_policy
from krellbot.application import live_gate
from krellbot.venues.base import PairRules
from krellbot.venues.paper import PaperVenue

PAIR = "SUIUSD"
KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enable_live(monkeypatch) -> None:
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")


def _write_pack(home: Path, *, pack_id: str = "paper-only", mode_pair: str = PAIR) -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "Paper only",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": "kraken", "pair": mode_pair}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _kraken_venue(home: Path, transport: FakeKrakenTransport) -> object:
    from krellbot.venues.kraken import KrakenVenue

    return KrakenVenue(
        api_key=KRAKEN_TEST_KEY,
        secret_b64=KRAKEN_TEST_SECRET,
        transport=transport,
        now_ms=lambda: 1_700_000_000_000,
        min_interval_ms=0,
        home=home,
    )


def _coinbase_venue(transport: FakeCoinbaseTransport) -> object:
    from krellbot.venues.coinbase import CoinbaseVenue

    seed = b"\x02" * 32
    from cryptography.hazmat.primitives.asymmetric import ed25519

    priv = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    secret = base64.b64encode(seed + priv.public_key().public_bytes_raw()).decode("ascii")
    return CoinbaseVenue(
        api_key_name="orgs/abc/keys/xyz",
        api_secret=secret,
        transport=transport,
        product_id="BTC-USD",
        now_fn=lambda: 1_700_000_000,
        nonce_fn=lambda: "dd" * 16,
    )


# ---------------------------------------------------------------------------
# Gate: policy is checked first and refuses even a fully-authorized setup
# ---------------------------------------------------------------------------


def test_gate_refuses_even_with_env_one_and_operator_grant(home, monkeypatch):
    _enable_live(monkeypatch)
    write_grant(home, venue="kraken", pair=PAIR)

    result = live_gate.check_live_send(home, venue="kraken", pair=PAIR, env={"KRELLBOT_ENABLE_LIVE": "1"})

    assert result.ok is False
    assert result.code == live_gate.CODE_PAPER_ONLY_RELEASE
    assert "v0.9.6" in result.message
    assert "paper" in result.message.lower()


def test_gate_refusal_happens_before_auth_or_kill_state_reads(home, monkeypatch):
    """No credential or authorization state is consulted once policy refuses."""
    _enable_live(monkeypatch)
    write_grant(home, venue="kraken", pair=PAIR)

    def _must_not_call(*args, **kwargs):
        raise AssertionError("policy refusal must not read operator state")

    monkeypatch.setattr(live_gate, "read_authorization", _must_not_call)
    monkeypatch.setattr(live_gate, "kill_state", _must_not_call)

    result = live_gate.check_live_send(home, venue="kraken", pair=PAIR, env={"KRELLBOT_ENABLE_LIVE": "1"})

    assert result.code == live_gate.CODE_PAPER_ONLY_RELEASE


def test_gate_cannot_be_reenabled_by_env_config_or_auth_file(home, monkeypatch):
    write_grant(home, venue="kraken", pair=PAIR)
    for env in (
        {"KRELLBOT_ENABLE_LIVE": "1"},
        {"KRELLBOT_ENABLE_LIVE": "true", "KRELLBOT_PAPER_ONLY": "0"},
        {"KRELLBOT_ALLOW_LIVE": "1", "KRELLBOT_LIVE": "1"},
    ):
        result = live_gate.check_live_send(home, venue="kraken", pair=PAIR, env=env)
        assert result.ok is False
        assert result.code == live_gate.CODE_PAPER_ONLY_RELEASE


def test_live_status_reports_paper_only_release(home, monkeypatch):
    _enable_live(monkeypatch)
    write_grant(home, venue="kraken", pair=PAIR)

    status = live_gate.live_status(home, env={"KRELLBOT_ENABLE_LIVE": "1"})

    assert status["live_enabled"] is False
    assert status["release_policy"] == "paper_only"
    assert status["release_policy_code"] == live_gate.CODE_PAPER_ONLY_RELEASE
    # Promotion remains owner-deferred; that part of the contract is unchanged.
    assert status["promotion_available"] is False
    assert status["promotion_code"] == live_gate.CODE_PROMOTION_DEFERRED


def test_promotion_refuses_with_paper_only_code(home):
    write_grant(home, venue="kraken", pair=PAIR)
    result = live_gate.check_promotion(
        home,
        venue="kraken",
        pair=PAIR,
        revision_id="rev-1",
        env={"KRELLBOT_ENABLE_LIVE": "1"},
    )
    assert result.ok is False
    assert result.code == live_gate.CODE_PAPER_ONLY_RELEASE


# ---------------------------------------------------------------------------
# CLI / application entry points
# ---------------------------------------------------------------------------


def test_live_arm_refused_before_keyring_or_key_probe(home, monkeypatch, capsys):
    from krellbot import secrets as kb_secrets
    from krellbot.run import arm_pack

    _enable_live(monkeypatch)
    write_grant(home, venue="kraken", pair=PAIR)
    pack_path = _write_pack(home)

    probes: list[str] = []
    monkeypatch.setattr(kb_secrets, "get", lambda venue: probes.append(f"key:{venue}") or ("k", "s"))

    rc = arm_pack(
        pack_path,
        venue="kraken",
        mode="live",
        home=home,
        key_check=lambda venue: probes.append(f"probe:{venue}"),
    )

    out = capsys.readouterr().out
    assert rc == 1
    assert probes == []
    assert "paper-only" in out.lower() or live_gate.CODE_PAPER_ONLY_RELEASE in out
    from krellbot.config import load_config

    assert load_config(home).armed == []


def test_tick_refuses_previously_live_armed_state_before_touching_venue(home, monkeypatch):
    from krellbot.config import ArmedPack, Config, load_config, save_config
    from krellbot.run import tick

    _enable_live(monkeypatch)
    write_grant(home, venue="kraken", pair=PAIR)
    pack_path = _write_pack(home)
    save_config(
        home,
        Config(
            armed=[
                ArmedPack(
                    pack_path=str(pack_path),
                    pack_sha256="0" * 64,
                    pack_id="paper-only",
                    pack_version="1.0.0",
                    venue="kraken",
                    pair=PAIR,
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

    class _NoTouchVenue:
        def __getattr__(self, name):
            raise AssertionError(f"policy refusal must not touch venue_obj.{name}")

    records: list[dict] = []
    rc = tick(
        venue="kraken",
        venue_obj=_NoTouchVenue(),
        reader=lambda venue, pair: [],
        journal_sink=lambda record: records.append(record) or Path("unused"),
        home=home,
    )

    assert rc == 1
    assert records, "a refusal tick must be journaled"
    detail = records[-1]["detail"]
    assert detail["reason"] == "live_refused"
    assert detail["code"] == live_gate.CODE_PAPER_ONLY_RELEASE
    assert load_config(home).armed[0].mode == "live"  # untouched, not silently flipped


def test_cli_venue_for_tick_refuses_before_secrets_or_transport(home, fresh_keyring, monkeypatch):
    from krellbot import cli, sanitize
    from krellbot.config import ArmedPack, Config, save_config

    _enable_live(monkeypatch)
    write_grant(home, venue="kraken", pair=PAIR)
    sanitize.register_secret(KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET)
    fresh_keyring.set_password("krellbot:kraken", "key", KRAKEN_TEST_KEY)
    fresh_keyring.set_password("krellbot:kraken", "secret", KRAKEN_TEST_SECRET)
    pack_path = _write_pack(home)
    armed = ArmedPack(
        pack_path=str(pack_path),
        pack_sha256="0" * 64,
        pack_id="paper-only",
        pack_version="1.0.0",
        venue="kraken",
        pair=PAIR,
        cap=Decimal(100),
        stop=Decimal(5),
        mode="live",
        starting_cash=None,
        requires_license=False,
        armed_at_ts=1,
    )
    save_config(home, Config(armed=[armed]))

    transport = FakeKrakenTransport()
    result = cli.venue_for_tick(home, [armed], transport=transport, fetch=lambda *a, **k: [])

    assert isinstance(result, str)
    assert "paper-only" in result.lower() or live_gate.CODE_PAPER_ONLY_RELEASE in result
    assert transport.calls == []


# ---------------------------------------------------------------------------
# Venue adapters: direct public real-order methods fail closed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda venue: venue.place_entry_with_stop("c1", Decimal(1), Decimal(10), pair=PAIR), id="entry"),
        pytest.param(lambda venue: venue.place_exit("c2", Decimal(1), pair=PAIR), id="exit"),
        pytest.param(lambda venue: venue.cancel_stops(PAIR), id="cancel_stops"),
        pytest.param(lambda venue: venue.raise_stop(PAIR, Decimal(11)), id="raise_stop"),
    ],
)
def test_kraken_mutations_refused_without_transport_call(home, call):
    transport = FakeKrakenTransport()
    venue = _kraken_venue(home, transport)

    with pytest.raises(release_policy.PaperOnlyReleaseError) as excinfo:
        call(venue)

    assert excinfo.value.code == live_gate.CODE_PAPER_ONLY_RELEASE
    assert transport.calls == []


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(
            lambda venue: venue.place_entry_with_stop("c1", Decimal("0.1"), Decimal(100), pair="BTC-USD"),
            id="entry",
        ),
        pytest.param(lambda venue: venue.place_exit("c2", Decimal("0.1"), pair="BTC-USD"), id="exit"),
        pytest.param(lambda venue: venue.cancel_stops("BTC-USD"), id="cancel_stops"),
        pytest.param(lambda venue: venue.raise_stop("BTC-USD", Decimal(101)), id="raise_stop"),
    ],
)
def test_coinbase_mutations_refused_without_transport_call(call):
    transport = FakeCoinbaseTransport()
    venue = _coinbase_venue(transport)

    with pytest.raises(release_policy.PaperOnlyReleaseError) as excinfo:
        call(venue)

    assert excinfo.value.code == live_gate.CODE_PAPER_ONLY_RELEASE
    assert transport.calls == []


def test_kraken_read_only_surfaces_still_work(home):
    """Key checks and snapshots are reads; the release policy must not blanket-ban them."""
    transport = FakeKrakenTransport(
        api_key_info={
            "permissions": [
                "query-funds",
                "query-open-trades",
                "modify-trades",
                "close-trades",
            ]
        }
    )
    venue = _kraken_venue(home, transport)
    perms = venue.check_key()
    assert perms is not None
    assert perms.can_trade is True
    assert transport.calls, "read-only key check must still reach the transport"


# ---------------------------------------------------------------------------
# Paper execution remains functional, and the policy is reversible in code
# ---------------------------------------------------------------------------


def test_paper_arm_and_paper_order_still_work(home):
    from krellbot.pack.model import Candle
    from krellbot.run import _dispatch_place, arm_pack

    pack_path = _write_pack(home)
    rc = arm_pack(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), home=home)
    assert rc == 0

    rules = PairRules(ordermin=Decimal("0.0001"), costmin=Decimal("0.5"), lot_decimals=4, price_decimals=2)
    candle = Candle(
        ts_ms=1_700_000_000_000,
        open=Decimal(10),
        high=Decimal(11),
        low=Decimal(9),
        close=Decimal(10),
        volume=Decimal(100),
    )
    paper = PaperVenue(
        "kraken",
        rules_provider=lambda pair: rules,
        candle_reader=lambda venue, pair: [candle],
        home=home,
        starting_cash=Decimal(1000),
    )
    body = json.dumps({"kind": "entry", "qty": "1", "stop": "5", "pair": PAIR}, separators=(",", ":"), sort_keys=True)
    state, ref = _dispatch_place(home=home, mode="paper", venue=None, coid="paper-coid-1", body=body, venue_obj=paper)
    assert state == "sent"
    assert ref is not None


def test_owner_approved_code_change_can_reenable_live(home, monkeypatch):
    """The seam is a single code constant; flipping it (release change) restores the old gate."""
    write_grant(home, venue="kraken", pair=PAIR)
    monkeypatch.setattr(release_policy, "PAPER_ONLY_RELEASE", False)

    result = live_gate.check_live_send(home, venue="kraken", pair=PAIR, env={"KRELLBOT_ENABLE_LIVE": "1"})
    assert result.ok is True
    assert result.code == live_gate.CODE_OK

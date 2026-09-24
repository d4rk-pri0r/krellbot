"""Phase 11: community packs + opt-in telemetry.

The four required tests:

    * test_telemetry_off_by_default_sends_nothing
    * test_payload_has_no_forbidden_fields
    * test_community_banner_on_list_show_arm
    * test_community_install_refuses_a_foreign_url

Plus a few small helpers that make the assertions deterministic.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BANNER = "Community pack. Unverified. No guarantee."


# ------------------------------ CLI helpers --------------------------------


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the krellbot CLI with HOME + KRELLBOT_HOME pointed at `home`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_HOME"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"
    env["PYTHONPATH"] = str(REPO / "src")
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


def _write_pack(home: Path, name: str, data: dict) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    path = packs / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8", newline="")
    return path


def _write_community_pack(home: Path, name: str, data: dict) -> Path:
    community = home / "packs" / "community"
    community.mkdir(parents=True, exist_ok=True)
    path = community / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8", newline="")
    return path


def _valid_pack() -> dict:
    return json.loads((REPO / "tests" / "fixtures" / "packs" / "valid.json").read_text())


@pytest.fixture
def home(monkeypatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


# ------------------------------ required tests -----------------------------


def test_telemetry_off_by_default_sends_nothing(home):
    """A fresh install has no telemetry.json. `maybe_send` returns without
    calling the injected transport and nothing is written to disk."""
    from krellbot import telemetry as kb_telemetry

    calls: list[tuple[str, bytes, dict]] = []

    class SpyTransport:
        def post(self, url: str, body: bytes, headers: dict):
            calls.append((url, body, headers))

    sample = {
        "pack_id": "x",
        "pack_version": "1.0.0",
        "venue": "kraken",
        "pair": "SUIUSD",
        "side": "buy",
        "bar_ts": 0,
        "modeled_px": "10",
        "fill_px": "10.005",
        "qty_bucket": kb_telemetry.qty_bucket(Decimal("50.025")),
        "fee_bps": 40,
    }
    rc = kb_telemetry.maybe_send(home, sample, transport=SpyTransport())
    assert rc is None
    assert calls == []
    # No telemetry state file should exist after a no-op call.
    assert not (home / "telemetry.json").exists()


def test_payload_has_no_forbidden_fields(home):
    """An enabled install's payload has exactly the eleven allowed keys. No
    balance, key, license, IP, or raw quantity leaves the machine."""
    from krellbot import telemetry as kb_telemetry

    sent: list[dict] = []

    class SpyTransport:
        def __init__(self):
            self.calls = 0

        def post(self, url: str, body: bytes, headers: dict):
            self.calls += 1
            sent.append(json.loads(body))

    spy = SpyTransport()
    # Operator types `y` to enable.
    assert kb_telemetry.enable(home, stdin_fn=lambda: "y") is True

    # Build a payload exactly the way `tick` does.
    fill_qty = Decimal(5)
    fill_px = Decimal("10.005")
    notional = fill_qty * fill_px
    payload = {
        "pack_id": "trend-follow",
        "pack_version": "1.0.0",
        "venue": "kraken",
        "pair": "SUIUSD",
        "side": "buy",
        "bar_ts": 0,
        "modeled_px": "10",
        "fill_px": str(fill_px),
        "qty_bucket": kb_telemetry.qty_bucket(notional),
        "fee_bps": 40,
    }
    kb_telemetry.maybe_send(home, payload, transport=spy)

    assert spy.calls == 1
    body = sent[0]

    # Exactly the eleven allowed keys, nothing else.
    assert set(body.keys()) == set(kb_telemetry.PAYLOAD_KEYS)
    # The forbidden substrings never appear.
    forbidden_substrings = ("balance", "license")
    for substr in forbidden_substrings:
        assert substr not in json.dumps(body).lower()
    # The forbidden exact keys never appear (we already checked keys above,
    # but be explicit about ip / raw qty / api key).
    for k in ("balance", "key", "license", "ip", "qty"):
        assert k not in body
    # qty_bucket is the bucketed value, not the raw quantity.
    assert body["qty_bucket"] != str(fill_qty)
    assert isinstance(body["qty_bucket"], int)


def test_community_banner_on_list_show_arm(home):
    """`list`, `show`, and `arm` of a community pack print the banner. A user
    pack in `packs/` does not. The banner line is exactly:
    `Community pack. Unverified. No guarantee.`"""
    user_pack = _valid_pack()
    user_pack["label"] = "User trend"
    user_pack["markets"] = [{"venue": "kraken", "pair": "BTCUSD"}]
    _write_pack(home, "user_trend", user_pack)

    community_pack = dict(_valid_pack(), label="Community trend", id="community-trend")
    _write_community_pack(home, "community_trend", community_pack)

    # `list` must mention the user pack label, the community pack label, AND
    # the banner only for the community one.
    r = _run_cli(home, "list")
    assert r.returncode == 0, r.stderr
    assert "User trend" in r.stdout
    assert "Community trend" in r.stdout
    assert r.stdout.count(BANNER) == 1

    # `show <community-id>` prints the banner; `show <user-id>` does not.
    r_community = _run_cli(home, "show", "community-trend")
    assert r_community.returncode == 0, r_community.stderr
    assert BANNER in r_community.stdout

    r_user = _run_cli(home, "show", "user_trend")
    assert r_user.returncode == 0, r_user.stderr
    assert BANNER not in r_user.stdout

    # `arm` of the community pack prints the banner. `arm` of the user pack
    # does not. The arm call requires --venue kraken --mode paper and a
    # --paper-balance because the pack has no license requirement when it
    # is under packs/community/ (catalog.requires_license_for returns False
    # for community packs).
    community_path = home / "packs" / "community" / "community_trend.json"
    r_arm_community = _run_cli(
        home,
        "arm",
        str(community_path),
        "--venue",
        "kraken",
        "--mode",
        "paper",
        "--paper-balance",
        "1000",
    )
    assert r_arm_community.returncode == 0, r_arm_community.stderr
    assert BANNER in r_arm_community.stdout

    user_path = home / "packs" / "user_trend.json"
    r_arm_user = _run_cli(
        home,
        "arm",
        str(user_path),
        "--venue",
        "kraken",
        "--mode",
        "paper",
        "--paper-balance",
        "1000",
    )
    assert r_arm_user.returncode == 0, r_arm_user.stderr
    assert BANNER not in r_arm_user.stdout


def test_community_install_refuses_a_foreign_url(home):
    """A community-pack URL whose host is not `raw.githubusercontent.com`
    (or whose path is outside `/d4rk-pri0r/krellbot-community-packs/`) is
    refused by `install`. The CLI prints the error and exits non-zero."""
    from krellbot import community as kb_community

    class FakeTransport:
        def __init__(self, mapping: dict[str, bytes]):
            self.mapping = mapping
            self.calls: list[str] = []

        def get(self, url: str) -> bytes:
            self.calls.append(url)
            if url in self.mapping:
                return self.mapping[url]
            raise AssertionError(f"unexpected url: {url}")

    index_body = json.dumps(
        {
            "packs": [
                {
                    "id": "evil-pack",
                    "url": "https://example.com/d4rk-pri0r/krellbot-community-packs/evil.json",
                }
            ]
        }
    ).encode("utf-8")

    transport = FakeTransport({kb_community.INDEX_URL: index_body})
    with pytest.raises(kb_community.ForeignUrlError):
        kb_community.install("evil-pack", transport=transport, home=home)

    # Nothing should have been written under packs/community/.
    assert not (home / "packs" / "community").exists() or not list((home / "packs" / "community").glob("*.json"))


# ------------------------------ extra coverage -----------------------------


def test_community_install_writes_bytes_verbatim(home):
    """The pack's `author` field survives a `community install` unchanged."""
    from krellbot import community as kb_community

    pack_bytes = json.dumps(
        {
            "schema_version": 1,
            "id": "good-pack",
            "version": "1.2.3",
            "label": "Good",
            "author": 'Some author with \\u00e9 and "quotes"',
            "timeframe": "1h",
            "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
            "entry": ["close", ">", "sma20"],
            "exit": ["close", "<", "sma20"],
            "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
            "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
        }
    ).encode("utf-8")

    index_body = json.dumps(
        {
            "packs": [
                {
                    "id": "good-pack",
                    "url": "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/good-pack.json",
                }
            ]
        }
    ).encode("utf-8")

    class FakeTransport:
        def __init__(self):
            self.calls: list[str] = []

        def get(self, url: str) -> bytes:
            self.calls.append(url)
            if url == kb_community.INDEX_URL:
                return index_body
            if url.endswith("/good-pack.json"):
                return pack_bytes
            raise AssertionError(f"unexpected url: {url}")

    transport = FakeTransport()
    target = kb_community.install("good-pack", transport=transport, home=home)

    assert target == home / "packs" / "community" / "good-pack.json"
    assert target.read_bytes() == pack_bytes


def test_telemetry_n_answer_does_not_enable(home):
    """`telemetry enable` with `n` does not enable. The transport is never
    called and no telemetry.json is written."""
    from krellbot import telemetry as kb_telemetry

    class SpyTransport:
        def __init__(self):
            self.calls = 0

        def post(self, url, body, headers):
            self.calls += 1

    spy = SpyTransport()
    assert kb_telemetry.enable(home, stdin_fn=lambda: "n") is False
    assert not kb_telemetry.is_enabled(home)
    assert not (home / "telemetry.json").exists()

    kb_telemetry.maybe_send(
        home,
        {
            "pack_id": "x",
            "pack_version": "1",
            "venue": "kraken",
            "pair": "SUIUSD",
            "side": "buy",
            "bar_ts": 0,
            "modeled_px": "0",
            "fill_px": "0",
            "qty_bucket": 0,
            "fee_bps": 40,
        },
        transport=spy,
    )
    assert spy.calls == 0


def test_telemetry_qty_bucket_floor_log2(home):
    """`qty_bucket` is floor(log2(USD notional)) so the precise size of a
    trade never leaves the machine."""
    from krellbot import telemetry as kb_telemetry

    assert kb_telemetry.qty_bucket(Decimal(0)) == 0
    assert kb_telemetry.qty_bucket(Decimal(1)) == 0
    assert kb_telemetry.qty_bucket(Decimal(2)) == 1
    assert kb_telemetry.qty_bucket(Decimal(3)) == 1
    assert kb_telemetry.qty_bucket(Decimal(4)) == 2
    assert kb_telemetry.qty_bucket(Decimal(100)) == 6
    assert kb_telemetry.qty_bucket(Decimal(1024)) == 10
    assert kb_telemetry.qty_bucket(Decimal(1023)) == 9


def test_discover_includes_community_packs(home):
    """`krellbot.pack.discover` returns both user and community packs."""
    from krellbot.pack import discover

    user_pack = _valid_pack()
    user_pack["label"] = "User trend"
    _write_pack(home, "user_trend", user_pack)

    community_pack = dict(_valid_pack(), label="Community trend", id="community-trend")
    _write_community_pack(home, "community_trend", community_pack)

    found = discover(home)
    labels = sorted(p[2].get("label") for p in found)
    assert labels == ["Community trend", "User trend"]


def test_tick_calls_maybe_send_on_enabled_paper_fill(home, fresh_keyring):
    """End-to-end: enable telemetry, run a paper tick that produces a fill,
    confirm the spy transport sees one POST with the eleven allowed keys."""
    from krellbot import telemetry as kb_telemetry
    from krellbot.pack.model import Candle
    from krellbot.run import arm_pack, tick
    from krellbot.venues.paper import PaperVenue, default_rules

    assert kb_telemetry.enable(home, stdin_fn=lambda: "y") is True

    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    pack_path = packs / "above.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "above-threshold",
                "version": "1.0.0",
                "label": "Above threshold",
                "author": "krellbot tests",
                "timeframe": "1h",
                "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
                "entry": ["close", ">", "sma2"],
                "exit": ["close", "<", "sma2"],
                "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
                "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
            }
        ),
        encoding="utf-8",
    )

    arm_pack(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        requires_license=False,
    )

    # Given bar 2 close = 11.5 and sma2(2) = 10.75, the entry condition fires.
    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
        Candle(
            ts_ms=3_600_000,
            open=Decimal(11),
            high=Decimal(12),
            low=Decimal(10),
            close=Decimal("11.5"),
            volume=Decimal(100),
        ),
    ]

    class _Reader:
        def __call__(self, venue, pair):
            return list(candles)

    sent: list[dict] = []

    class SpyTransport:
        def post(self, url, body, headers):
            sent.append({"url": url, "body": json.loads(body), "headers": headers})

    venue = PaperVenue(
        "kraken",
        rules_provider=default_rules,
        candle_reader=_Reader(),
        home=home,
        starting_cash=Decimal(1000),
    )

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=_Reader(),
        transport=SpyTransport(),
        clock=lambda: 3_600.0,
    )
    assert rc == 0

    # One telemetry POST for the entry fill.
    assert len(sent) == 1
    body = sent[0]["body"]
    assert sent[0]["url"] == kb_telemetry.DEFAULT_URL
    assert set(body.keys()) == set(kb_telemetry.PAYLOAD_KEYS)
    assert body["pack_id"] == "above-threshold"
    assert body["pack_version"] == "1.0.0"
    assert body["venue"] == "kraken"
    assert body["pair"] == "SUIUSD"
    assert body["side"] == "buy"
    assert body["fee_bps"] == 40
    assert isinstance(body["qty_bucket"], int)
    assert body["install_id"] != ""
    for forbidden in ("balance", "license", "ip", "qty"):
        assert forbidden not in body


def test_install_accepts_the_published_index_array(home):
    """The public index.json is a list, not an object with a packs key."""
    from krellbot import community as kb_community

    pack = b'{"id":"trend-follow","author":"community-example"}'
    url_wanted = "https://raw.githubusercontent.com/d4rk-pri0r/krellbot-community-packs/main/packs/trend-follow.json"
    index = json.dumps(
        [{"id": "trend-follow", "author": "community-example", "label": "Trend follow", "url": url_wanted}]
    ).encode()

    class Fake:
        def get(self, url: str) -> bytes:
            if url == kb_community.INDEX_URL:
                return index
            if url == url_wanted:
                return pack
            raise AssertionError(url)

    target = kb_community.install("trend-follow", transport=Fake(), home=home)
    assert target.read_bytes() == pack


def test_maybe_send_drops_forbidden_fields(home):
    from krellbot import telemetry as kb_telemetry

    sent: list[dict] = []

    class Spy:
        def post(self, url, body, headers):
            sent.append(json.loads(body))

    assert kb_telemetry.enable(home, stdin_fn=lambda: "y") is True
    kb_telemetry.maybe_send(
        home,
        {
            "pack_id": "trend-follow",
            "pack_version": "1.0.0",
            "venue": "kraken",
            "pair": "SUIUSD",
            "side": "buy",
            "bar_ts": 0,
            "modeled_px": "10",
            "fill_px": "10",
            "qty_bucket": 5,
            "fee_bps": 40,
            "balance": "99999",
            "license": "kb_secret",
            "qty": "5",
            "ip": "203.0.113.5",
        },
        Spy(),
    )
    assert set(sent[0]) == set(kb_telemetry.PAYLOAD_KEYS)
    assert "99999" not in json.dumps(sent[0])
    assert "kb_secret" not in json.dumps(sent[0])


def test_enabled_send_uses_the_default_transport(home, monkeypatch):
    from krellbot import telemetry as kb_telemetry

    calls: list[str] = []

    class Spy:
        def post(self, url, body, headers):
            calls.append(url)

    monkeypatch.setattr(kb_telemetry, "UrllibTransport", lambda: Spy())
    assert kb_telemetry.enable(home, stdin_fn=lambda: "y") is True
    chosen = kb_telemetry.resolve_transport(home, None)
    chosen.post("https://krellbot.dev/api/telemetry", b"{}", {})
    assert calls == ["https://krellbot.dev/api/telemetry"]
    kb_telemetry.disable(home)
    assert kb_telemetry.resolve_transport(home, None) is None

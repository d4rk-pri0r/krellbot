"""NS03 — shared paper command service and persisted entry pause.

Tests first. The application service in `krellbot.application.paper` is the
single boundary that owns paper arm, disarm, pause entries, resume entries,
and raise-stop. CLI and the dashboard route through it; live arm stays on
the legacy live path.

Every test uses an isolated home so the real ~/.krellbot is never read and no
network call is made. The fake keyring backend is loaded by conftest before
any `import keyring` resolves a backend.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

# ---- helpers -------------------------------------------------------------


def _write_dsl_pack(
    home: Path,
    *,
    pack_id: str = "trend-follow",
    version: str = "1.0.0",
    pair: str = "SUIUSD",
    venue: str = "kraken",
    stop_pct: int = 5,
) -> Path:
    """Write a runnable DSL pack under <home>/packs/."""
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": version,
        "label": "Trend follow",
        "author": "krellbot ns03 tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": stop_pct}},
        "markets": [{"venue": venue, "pair": pair}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _write_legacy_pack(home: Path) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    target = packs / "legacy.json"
    target.write_text(
        json.dumps(
            {
                "id": "old-style",
                "public_label": "Old Reliable",
                "rule": "Plain English.",
                "timeframe": "1h",
            }
        ),
        encoding="utf-8",
    )
    return target


def _config_bytes(home: Path) -> bytes:
    config_path = home / "config.json"
    if not config_path.exists():
        return b""
    return config_path.read_bytes()


def _journal_files(home: Path) -> list[Path]:
    journal_dir = home / "journal"
    if not journal_dir.is_dir():
        return []
    return sorted(journal_dir.glob("*.jsonl"))


def _journal_bytes(home: Path) -> bytes:
    out = bytearray()
    for path in _journal_files(home):
        out.extend(path.read_bytes())
    return bytes(out)


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run the CLI in a subprocess with KRELLBOT_HOME set to a tmp dir.

    Strips inherited KRELLBOT_* secrets so a test cannot leak them and
    points HOME/USERPROFILE at the same tmp dir for consistency.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["KRELLBOT_HOME"] = str(home)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_ENABLE_LIVE"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


class _StaticReader:
    def __init__(self, candles):
        self.candles = list(candles)

    def __call__(self, venue, pair):
        return list(self.candles)


class _JournalSink:
    def __init__(self):
        self.records: list[dict] = []

    def __call__(self, record):
        self.records.append(record)
        return Path("/dev/null")


class _BaseVenue:
    """Minimal in-memory venue matching the engine's protocol surface."""

    def __init__(self):
        self.orders: list[dict] = []
        self.fills: list[dict] = []
        self.balances: dict[str, Decimal] = {"USD": Decimal(1000), "SUI": Decimal(0)}
        self.entry_calls: list[str] = []
        self.exit_calls: list[str] = []

    def rules(self, pair):
        from krellbot.venues.base import PairRules

        return PairRules(
            ordermin=Decimal("0.0001"),
            costmin=Decimal("0.5"),
            lot_decimals=8,
            price_decimals=5,
        )

    def snapshot(self):
        from krellbot.venues.base import Balance, Fill, OpenOrder, Truth

        orders = [
            OpenOrder(
                id=o["coid"],
                coid=o["coid"],
                pair=o["pair"],
                side=o["side"],
                qty=o["qty"],
                stop_price=o.get("stop_price"),
            )
            for o in self.orders
        ]
        fills = [
            Fill(
                id=f.get("id", ""),
                coid=f.get("coid", ""),
                pair=f.get("pair", ""),
                side=f.get("side", ""),
                qty=f.get("qty", Decimal(0)),
                price=f.get("price", Decimal(0)),
                ts_ms=int(f.get("ts_ms", 0)),
            )
            for f in self.fills
        ]
        bals = [Balance(asset=k, free=v) for k, v in self.balances.items() if v > 0]
        return Truth(balances=bals, open_orders=orders, recent_fills=fills)

    def place_entry_with_stop(self, coid, qty, stop, *, pair):
        self.entry_calls.append(coid)
        self.orders.append({"coid": coid, "pair": pair, "side": "buy", "qty": qty, "stop_price": stop})
        self.balances["SUI"] = self.balances.get("SUI", Decimal(0)) + qty
        self.fills.append(
            {
                "id": coid,
                "coid": coid,
                "pair": pair,
                "side": "buy",
                "qty": qty,
                "price": Decimal(10),
                "ts_ms": 0,
            }
        )
        return {
            "id": coid,
            "coid": coid,
            "pair": pair,
            "side": "buy",
            "qty": qty,
            "filled_qty": qty,
            "stop_price": stop,
        }

    def place_stop(self, coid, qty, stop, *, pair):
        self.orders.append({"coid": coid, "pair": pair, "side": "sell", "qty": qty, "stop_price": stop})

    def place_exit(self, coid, qty, *, pair):
        self.exit_calls.append(coid)
        self.fills.append(
            {"id": coid, "coid": coid, "pair": pair, "side": "sell", "qty": qty, "price": Decimal(10), "ts_ms": 0}
        )
        self.orders = [o for o in self.orders if not (o["pair"] == pair and o.get("side") == "buy")]
        return {"id": coid, "coid": coid, "pair": pair, "side": "sell", "qty": qty, "filled_qty": qty}

    def cancel_stops(self, pair):
        self.orders = [o for o in self.orders if not (o["pair"] == pair and o.get("stop_price") is not None)]

    def raise_stop(self, pair, new_stop):
        for o in self.orders:
            if o["pair"] == pair and o.get("stop_price") is not None:
                o["stop_price"] = max(o["stop_price"], new_stop)

    def order_by_coid(self, coid):
        for o in self.orders:
            if o["coid"] == coid:
                return o
        return None

    def check_key(self):
        from krellbot.venues.base import KeyPerms

        return KeyPerms(can_trade=True, can_withdraw=False)


# ---- 1. service arm returns typed `armed`; CLI arm returns 0 and same bytes


def test_service_arm_returns_typed_armed_result(home) -> None:
    """The paper service is the single boundary for arm. Its result carries
    schema_version, correlation_id, a stable code, and effect='changed'.
    """
    from krellbot.application.paper import CommandResultV1, PaperService

    pack_path = _write_dsl_pack(home)

    service = PaperService(home=home, clock=lambda: 1234.0)
    result = service.arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="arm-1",
    )

    assert isinstance(result, CommandResultV1)
    assert result.schema_version == "1"
    assert result.correlation_id == "arm-1"
    assert result.code == "armed"
    assert result.ok is True
    assert result.effect == "changed"
    assert result.message  # non-empty safe message
    assert result.revision_before != result.revision_after
    # No secret/path leakage.
    for forbidden in ("/", "secret", "exception", "traceback", str(home), "FakeKeyring"):
        assert forbidden not in result.message, (forbidden, result.message)


def test_cli_and_service_arm_produce_same_on_disk_record(home) -> None:
    """Service arm and CLI arm produce identical armed config records."""
    from krellbot.application.paper import PaperService
    from krellbot.config import load_config

    pack_path = _write_dsl_pack(home, pack_id="cli-svc-1")

    service = PaperService(home=home, clock=lambda: 5678.0)
    service_result = service.arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="svc-arm",
    )
    assert service_result.ok

    config_service = load_config(home)
    assert len(config_service.armed) == 1
    service_record = config_service.armed[0]

    # Disarm and re-arm via the CLI to compare.
    service.disarm(venue="kraken", pair="SUIUSD", correlation_id="svc-disarm")

    r = _run_cli(
        home,
        "arm",
        str(pack_path),
        "--venue",
        "kraken",
        "--mode",
        "paper",
        "--paper-balance",
        "1000",
    )
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)

    config_cli = load_config(home)
    assert len(config_cli.armed) == 1
    cli_record = config_cli.armed[0]

    # Same on-disk shape: pack_id, venue, pair, mode, cap, stop, starting_cash.
    for field in ("pack_id", "venue", "pair", "mode", "cap", "stop", "starting_cash"):
        assert getattr(service_record, field) == getattr(cli_record, field), (
            field,
            getattr(service_record, field),
            getattr(cli_record, field),
        )
    # CLI keeps the current stdout sentence for success.
    assert "armed cli-svc-1" in r.stdout
    assert "kraken" in r.stdout
    assert "SUIUSD" in r.stdout


# ---- 2. pause survives reload; entries suppressed; protection still runs


def test_pause_persists_and_survives_reload(home) -> None:
    """`pause_entries` flips `entries_paused=True` in config; reload sees it."""
    from krellbot.application.paper import PaperService
    from krellbot.config import load_config

    pack_path = _write_dsl_pack(home)
    service = PaperService(home=home)
    service.arm(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), correlation_id="arm-2")

    pause_result = service.pause_entries(venue="kraken", pair="SUIUSD", correlation_id="pause-1")
    assert pause_result.ok
    assert pause_result.code == "entries_paused"
    assert pause_result.effect == "changed"

    config = load_config(home)
    armed = config.armed[0]
    assert armed.entries_paused is True

    # Reload from disk and re-verify.
    config2 = load_config(home)
    assert config2.armed[0].entries_paused is True


def test_pause_suppresses_new_entries_but_keeps_protection(home) -> None:
    """While `entries_paused=True`, a fresh entry signal must not place a new
    order; a seeded owned journal position must still be processed
    (protection / stop placement / exit).
    """
    from krellbot import journal as kb_journal
    from krellbot.application.paper import PaperService
    from krellbot.config import load_config, save_config
    from krellbot.run import tick

    pack_path = _write_dsl_pack(home)
    service = PaperService(home=home)
    service.arm(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), correlation_id="arm-3")
    service.pause_entries(venue="kraken", pair="SUIUSD", correlation_id="pause-2")

    # Seed an owned position via the journal so the engine sees open qty.
    kb_journal.append(
        {
            "ts": 1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": 1,
            "detail": {"pair": "SUIUSD", "entry_qty": "5", "exit_qty": "0", "stop_qty": "0"},
        }
    )
    config = load_config(home)
    for armed in config.armed:
        if armed.venue == "kraken":
            armed.owned_qty = Decimal(5)
    save_config(home, config)

    # A bar that would otherwise be an entry signal: SMA20 sits below
    # the last close for several bars so close > sma20 → entry signal.
    from krellbot.pack.model import Candle

    candles = [
        Candle(ts_ms=0, open=Decimal(10), high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(100)),
        Candle(
            ts_ms=3_600_000,
            open=Decimal(11),
            high=Decimal(12),
            low=Decimal("10.5"),
            close=Decimal("11.5"),
            volume=Decimal(100),
        ),
        Candle(
            ts_ms=7_200_000,
            open=Decimal("11.5"),
            high=Decimal(13),
            low=Decimal(11),
            close=Decimal("12.5"),
            volume=Decimal(100),
        ),
        Candle(
            ts_ms=10_800_000,
            open=Decimal("12.5"),
            high=Decimal(14),
            low=Decimal(12),
            close=Decimal("13.5"),
            volume=Decimal(100),
        ),
        Candle(
            ts_ms=14_400_000,
            open=Decimal("13.5"),
            high=Decimal(15),
            low=Decimal(13),
            close=Decimal("14.5"),
            volume=Decimal(100),
        ),
    ]

    venue = _BaseVenue()
    venue.balances["SUI"] = Decimal(5)
    sink = _JournalSink()

    rc = tick(
        venue="kraken",
        venue_obj=venue,
        reader=_StaticReader(candles),
        journal_sink=sink,
        clock=lambda: 14_400_000 // 1000,
    )
    assert rc == 0

    # Pause must suppress new exposure: no entry coid recorded.
    tick_records = [r for r in sink.records if r.get("kind") == "tick"]
    assert tick_records, "engine must journal a tick record"
    assert venue.entry_calls == [], f"paused tick must not place new entries; entry_calls={venue.entry_calls}"

    # Protection must still run: the engine placed a stop for the seeded position.
    placed_stop = [o for o in venue.orders if o.get("side") == "sell" and o.get("stop_price") is not None]
    assert placed_stop, "paused tick must still place a stop for the seeded position"


# ---- 3. pause/resume idempotent; invalid pack/venue; live mode refused


def test_pause_and_resume_are_idempotent(home) -> None:
    """Repeated pause and resume return stable idempotent codes."""
    from krellbot.application.paper import PaperService

    pack_path = _write_dsl_pack(home)
    service = PaperService(home=home)

    service.arm(pack_path, venue="kraken", mode="paper", paper_balance=Decimal(1000), correlation_id="arm-4")

    first = service.pause_entries(venue="kraken", pair="SUIUSD", correlation_id="pause-a")
    second = service.pause_entries(venue="kraken", pair="SUIUSD", correlation_id="pause-b")
    assert first.ok and first.code == "entries_paused"
    assert second.ok and second.code == "already_paused"
    assert first.effect == "changed"
    assert second.effect == "unchanged"

    resume_a = service.resume_entries(venue="kraken", pair="SUIUSD", correlation_id="resume-a")
    resume_b = service.resume_entries(venue="kraken", pair="SUIUSD", correlation_id="resume-b")
    assert resume_a.ok and resume_a.code == "entries_resumed"
    assert resume_b.ok and resume_b.code == "already_resumed"
    assert resume_a.effect == "changed"
    assert resume_b.effect == "unchanged"


def test_invalid_pack_venue_and_live_mode_leave_bytes_unchanged(home) -> None:
    """Invalid inputs to the paper service refuse before any config or
    journal byte changes. A live-mode request to the paper service is
    refused for the same reason — the service is paper-only.
    """
    from krellbot.application.paper import PaperService

    # No on-disk config yet: compare against empty bytes.
    before_config = _config_bytes(home)
    before_journal = _journal_bytes(home)

    service = PaperService(home=home)

    # 1. Unknown venue.
    missing = home / "packs" / "missing.json"
    r_venue = service.arm(missing, venue="not-a-venue", mode="paper", paper_balance=Decimal(1000), correlation_id="x1")
    assert r_venue.ok is False
    assert r_venue.code == "unknown_venue"
    assert r_venue.effect == "refused"

    # 2. Pack file does not exist.
    r_path = service.arm(missing, venue="kraken", mode="paper", paper_balance=Decimal(1000), correlation_id="x2")
    assert r_path.ok is False
    assert r_path.code == "invalid_request"
    assert r_path.effect == "refused"

    # 3. Legacy pack on disk.
    legacy = _write_legacy_pack(home)
    r_legacy = service.arm(legacy, venue="kraken", mode="paper", paper_balance=Decimal(1000), correlation_id="x3")
    assert r_legacy.ok is False
    assert r_legacy.code == "legacy_pack_not_runnable"
    assert r_legacy.effect == "refused"

    # 4. Live mode requested to the paper service.
    pack = _write_dsl_pack(home)
    r_live = service.arm(pack, venue="kraken", mode="live", paper_balance=Decimal(1000), correlation_id="x4")
    assert r_live.ok is False
    assert r_live.code == "invalid_request"
    assert r_live.effect == "refused"

    # 5. Negative paper balance.
    r_neg = service.arm(pack, venue="kraken", mode="paper", paper_balance=Decimal(-1), correlation_id="x5")
    assert r_neg.ok is False
    assert r_neg.code == "invalid_balance"
    assert r_neg.effect == "refused"

    # Bytes must be unchanged on disk.
    assert _config_bytes(home) == before_config
    assert _journal_bytes(home) == before_journal


# ---- 4. explicit home wins over KRELLBOT_HOME


def test_explicit_home_wins_over_environment(tmp_path, monkeypatch) -> None:
    """When KRELLBOT_HOME points at a different dir, the explicit `home`
    the service was constructed with still wins.
    """
    from krellbot.application.paper import PaperService
    from krellbot.config import load_config

    explicit = tmp_path / "explicit"
    explicit.mkdir()
    other = tmp_path / "other-home"
    other.mkdir()

    # Force paths.home() and KRELLBOT_HOME to the "wrong" dir.
    monkeypatch.setenv("KRELLBOT_HOME", str(other))
    monkeypatch.setenv("HOME", str(other))
    monkeypatch.setenv("USERPROFILE", str(other))

    pack_path = _write_dsl_pack(explicit)
    service = PaperService(home=explicit)
    result = service.arm(
        pack_path,
        venue="kraken",
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="explicit-home",
    )
    assert result.ok, result.message

    # The config landed in the explicit home, not in $KRELLBOT_HOME.
    assert (explicit / "config.json").exists(), "config must be under explicit home"
    assert not (other / "config.json").exists(), "KRELLBOT_HOME must not be written"

    # And load_config on the explicit home sees the armed record.
    config = load_config(explicit)
    assert len(config.armed) == 1
    assert config.armed[0].venue == "kraken"


# ---- 5. CLI refuses invalid requests with current stdout and codes


def test_cli_arm_refused_inputs_preserve_return_codes(home) -> None:
    """CLI arm keeps its existing 0/1/2 contract for refused inputs."""
    pack_path = _write_dsl_pack(home)

    # Unknown venue → 2 (invalid input).
    r = _run_cli(home, "arm", str(pack_path), "--venue", "not-a-venue", "--mode", "paper", "--paper-balance", "1000")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)

    # Missing paper balance → 2.
    r = _run_cli(home, "arm", str(pack_path), "--venue", "kraken", "--mode", "paper")
    assert r.returncode == 2

    # Second arm on same (venue, pair) → 1 (state refusal).
    first = _run_cli(home, "arm", str(pack_path), "--venue", "kraken", "--mode", "paper", "--paper-balance", "1000")
    assert first.returncode == 0, (first.returncode, first.stdout, first.stderr)
    second = _run_cli(home, "arm", str(pack_path), "--venue", "kraken", "--mode", "paper", "--paper-balance", "1000")
    assert second.returncode == 1, (second.returncode, second.stdout, second.stderr)
    assert "already armed" in second.stdout

    # Legacy pack → 2 (legacy: not runnable).
    legacy = _write_legacy_pack(home)
    r = _run_cli(home, "arm", str(legacy), "--venue", "kraken", "--mode", "paper", "--paper-balance", "1000")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "legacy" in r.stdout.lower()

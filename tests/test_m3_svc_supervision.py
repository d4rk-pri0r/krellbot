"""M3-SVC NS15 supervision: scheduled tick, wake gap, service status.

The brief (M3-SVC) requires:
  1. `krellbot tick` with no `--venue` ticks every armed venue, in sorted order.
  2. `service.runner.main(['tick', ...])` delegates to `krellbot.cli.main`.
  3. `service/supervise.py` records a `wake_gap` journal entry when the
     gap since the last tick is at least `TICK_STALE_SECONDS` (default 7200).
  4. `krellbot service status [--root PATH]` prints a one-line JSON object.

The tests below are RED: they pin the contract the brief spells out.
The implementation makes them GREEN.
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared helpers (copied from the legacy tick tests so the fake shapes match)
# ---------------------------------------------------------------------------


def _pack_json(pack_id: str, venue: str, pair: str, tf: str) -> dict:
    return {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": pack_id,
        "author": "krellbot tests",
        "timeframe": tf,
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": venue, "pair": pair}],
    }


def _write_pack(home: Path, *, pack_id: str, venue: str, pair: str, tf: str = "1h") -> Path:
    body = _pack_json(pack_id, venue, pair, tf)
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path, *, pack_id: str, venue: str, pair: str) -> None:
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
                    venue=venue,
                    pair=pair,
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


def _arm_papers(home: Path, *arms: dict) -> None:
    """Arm multiple packs in a single config.json write."""
    from krellbot.config import ArmedPack, Config, save_config

    armed = []
    for a in arms:
        armed.append(
            ArmedPack(
                pack_path=a["pack_path"],
                pack_sha256="0" * 64,
                pack_id=a["pack_id"],
                pack_version="1.0.0",
                venue=a["venue"],
                pair=a["pair"],
                cap=Decimal(100),
                stop=Decimal(5),
                mode="paper",
                starting_cash=Decimal(1000),
                requires_license=False,
                armed_at_ts=1,
            )
        )
    save_config(home, Config(armed=armed))


class _SilentTransport:
    def __init__(self):
        self.gets: list[str] = []
        self.posts: list[str] = []

    def get(self, url, headers=None):
        self.gets.append(url)
        return {"error": [], "result": {}}

    def post(self, url, form, headers):
        self.posts.append(url)
        return {"error": [], "result": {}}


def _read_journal(home: Path) -> list[dict]:
    records: list[dict] = []
    journal_dir = home / "journal"
    if not journal_dir.is_dir():
        return records
    for path in sorted(journal_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


# ---------------------------------------------------------------------------
# 1. `cli.main(['krellbot', 'tick'])` with no --venue ticks every armed venue
# ---------------------------------------------------------------------------


def test_cli_tick_no_venue_ticks_every_armed_venue(home, fresh_keyring, monkeypatch, capsys):
    """No --venue: tick every venue in sorted unique order. Each prints a header."""
    from krellbot import cli

    pack_k = _write_pack(home, pack_id="kraken-pack", venue="kraken", pair="SUIUSD")
    pack_c = _write_pack(home, pack_id="coinbase-pack", venue="coinbase", pair="SUIUSD")
    _arm_papers(
        home,
        {"pack_path": str(pack_k), "pack_id": "kraken-pack", "venue": "kraken", "pair": "SUIUSD"},
        {"pack_path": str(pack_c), "pack_id": "coinbase-pack", "venue": "coinbase", "pair": "SUIUSD"},
    )

    def fake_fetch(venue, pair, tf, transport):
        return []

    transport = _SilentTransport()
    monkeypatch.setattr("krellbot.cli._default_fetch", fake_fetch)
    monkeypatch.setattr("krellbot.cli._default_transport", lambda: transport)

    rc = cli.main(["krellbot", "tick"])
    captured = capsys.readouterr()
    out = captured.out
    err = captured.err

    assert rc == 0, f"expected rc=0, got {rc}; stdout={out!r}; stderr={err!r}"
    # Sorted unique venues: coinbase, kraken (alphabetical).
    coinbase_idx = out.find("== tick coinbase ==")
    kraken_idx = out.find("== tick kraken ==")
    assert coinbase_idx != -1, f"missing coinbase header; out={out!r}; err={err!r}"
    assert kraken_idx != -1, f"missing kraken header; out={out!r}; err={err!r}"
    assert coinbase_idx < kraken_idx, "venues must be processed in sorted order"

    # Both venues produced journal records
    records = _read_journal(home)
    venues_journaled = {r["venue"] for r in records if r.get("kind") == "tick"}
    assert venues_journaled == {"kraken", "coinbase"}, f"missing venue journal: {venues_journaled}"


def test_cli_tick_no_venue_no_arms_prints_message_and_returns_0(home, fresh_keyring, capsys):
    """No armed packs at all: print 'no armed packs' and return 0."""
    from krellbot import cli

    rc = cli.main(["krellbot", "tick"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "no armed packs" in out


def test_cli_tick_offline_candles_without_venue_still_refuses(home, fresh_keyring, capsys):
    """--offline-candles without --venue: rc=2 with the refused message (single-venue arg behavior)."""
    from krellbot import cli

    rc = cli.main(["krellbot", "tick", "--offline-candles", "never.csv"])
    captured = capsys.readouterr()

    assert rc == 2
    assert "--venue is required" in captured.err


# ---------------------------------------------------------------------------
# 2. `service.runner.main(['tick', ...])` delegates to cli.main
# ---------------------------------------------------------------------------


def test_runner_main_tick_delegates_to_cli_cmd_tick(monkeypatch):
    """runner.main(['tick']) calls cli.cmd_tick; its rc propagates; rc=1 -> 1."""
    from krellbot.service import runner

    captured = []

    def fake_cmd_tick(args, *, fetch=None, transport=None):
        captured.append(list(args))
        return 1

    monkeypatch.setattr("krellbot.cli.cmd_tick", fake_cmd_tick)
    # `runner.main` does a lazy import inside; we patched the attribute so the
    # lazy import resolves to our fake.
    rc = runner.main(["tick"])
    assert rc == 1
    assert captured == [[]], f"expected cmd_tick called with [], got {captured!r}"

    # Sanity: rc=0 propagates as 0.
    monkeypatch.setattr("krellbot.cli.cmd_tick", lambda args, *, fetch=None, transport=None: 0)
    rc = runner.main(["tick"])
    assert rc == 0


def test_runner_main_non_tick_argv_returns_2(monkeypatch, capsys):
    """Any argv not starting with 'tick' exits 2 and prints usage."""
    from krellbot.service import runner

    rc = runner.main(["nope"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "usage" in captured.err.lower()


# ---------------------------------------------------------------------------
# 3. Unit args are still exactly 'tick'. cli.main under that argv ticks.
# ---------------------------------------------------------------------------


def _expected_unit_path(write_root: Path) -> Path | dict[str, Path]:
    if sys.platform == "darwin":
        return write_root / "Library" / "LaunchAgents" / "dev.krellbot.tick.plist"
    if sys.platform.startswith("linux"):
        d = write_root / ".config" / "systemd" / "user"
        return {"timer": d / "krellbot-tick.timer", "service": d / "krellbot-tick.service"}
    if sys.platform == "win32":
        return write_root / "Tasks" / "krellbot-tick.xml"
    raise RuntimeError(f"unsupported test platform: {sys.platform}")


def _unit_contents(path: Path | dict[str, Path]) -> str:
    if isinstance(path, dict):
        return "\n".join(p.read_text(encoding="utf-8") for p in path.values())
    return path.read_text(encoding="utf-8")


def test_install_unit_args_end_with_tick_and_cli_tick_under_that_argv_ticks(home, fresh_keyring, monkeypatch, capsys):
    """Parse the rendered unit. The trailing arg is 'tick'. cli.main(['krellbot','tick']) ticks armed venues."""
    from krellbot import cli
    from krellbot.service import install

    # Install the service with a write_root inside the test home so we touch
    # nothing outside tmp_path.
    rc = install(home, executable="/usr/local/bin/krellbot", write_root=home)
    assert rc == 0, f"install rc={rc}"

    unit = _expected_unit_path(home)
    body = _unit_contents(unit)
    # The unit's command line must call the executable with the literal arg `tick`.
    # This holds for every platform's unit bytes.
    if sys.platform == "darwin":
        # <key>ProgramArguments</key><array>...<string>{exe}</string><string>tick</string>
        assert "<string>tick</string>" in body
    elif sys.platform.startswith("linux"):
        assert "ExecStart=" in body
        assert body.endswith("tick\n") or " tick\n" in body
    elif sys.platform == "win32":
        # <Arguments>/d /c set "KRELLBOT_HOME=..." && "..." tick</Arguments>
        assert "tick</Arguments>" in body

    # Now arm a venue and call cli.main(['krellbot','tick']) under the same
    # argv shape the scheduler unit invokes. The tick must succeed for both
    # venues present in config.json.
    pack_k = _write_pack(home, pack_id="kraken-pack", venue="kraken", pair="SUIUSD")
    pack_c = _write_pack(home, pack_id="coinbase-pack", venue="coinbase", pair="SUIUSD")
    _arm_papers(
        home,
        {"pack_path": str(pack_k), "pack_id": "kraken-pack", "venue": "kraken", "pair": "SUIUSD"},
        {"pack_path": str(pack_c), "pack_id": "coinbase-pack", "venue": "coinbase", "pair": "SUIUSD"},
    )

    def fake_fetch(venue, pair, tf, transport):
        return []

    transport = _SilentTransport()
    monkeypatch.setattr("krellbot.cli._default_fetch", fake_fetch)
    monkeypatch.setattr("krellbot.cli._default_transport", lambda: transport)

    rc2 = cli.main(["krellbot", "tick"])
    out = capsys.readouterr().out
    assert rc2 == 0
    assert "== tick coinbase ==" in out
    assert "== tick kraken ==" in out


# ---------------------------------------------------------------------------
# 4. Wake gap: record_wake_gap journals supervision/wake_gap only past threshold
# ---------------------------------------------------------------------------


def _seed_tick(home: Path, ts: int, venue: str = "kraken") -> None:
    import datetime as _dt

    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    month = _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime("%Y-%m")
    path = journal_dir / f"{month}.jsonl"
    rec = {
        "ts": ts,
        "kind": "tick",
        "venue": venue,
        "pack": "demo",
        "bar_ts": ts * 1000,
        "detail": {"reason": "warmup", "pair": "SUIUSD"},
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def test_wake_gap_records_journal_when_past_threshold(home, fresh_keyring):
    """A gap of >= TICK_STALE_SECONDS is journaled and returned; a gap below the threshold returns None."""
    from krellbot.service import supervise

    T = 1_700_000_000
    _seed_tick(home, T)

    gap_small = supervise.record_wake_gap(home, "kraken", now=T + 60)
    assert gap_small is None
    wake_now = [
        r
        for r in _read_journal(home)
        if r.get("kind") == "supervision" and r.get("detail", {}).get("event") == "wake_gap"
    ]
    assert wake_now == [], "no wake_gap record expected when below threshold"

    gap = supervise.record_wake_gap(home, "kraken", now=T + 36000)
    assert gap == 36000
    records = _read_journal(home)
    wake = [r for r in records if r.get("kind") == "supervision" and r.get("detail", {}).get("event") == "wake_gap"]
    assert len(wake) == 1, f"expected one wake_gap record, got {wake!r}"
    assert wake[0]["venue"] == "kraken"
    assert wake[0]["detail"]["gap_s"] == 36000
    assert wake[0]["detail"]["last_tick_ts"] == T
    assert wake[0]["pack"] == "-"
    assert wake[0]["bar_ts"] == 0


def test_wake_gap_returns_none_when_no_tick_records(home, fresh_keyring):
    """No journal entries at all: record_wake_gap returns None and journals nothing."""
    from krellbot.service import supervise

    gap = supervise.record_wake_gap(home, "kraken", now=1_700_000_000 + 36000)
    assert gap is None
    assert _read_journal(home) == []


def test_wake_gap_default_threshold_is_tick_stale_seconds():
    """record_wake_gap's default threshold is the doctor TICK_STALE_SECONDS (7200)."""
    import inspect

    from krellbot import doctor
    from krellbot.service import supervise

    sig = inspect.signature(supervise.record_wake_gap)
    assert "threshold" in sig.parameters
    assert sig.parameters["threshold"].default == doctor.TICK_STALE_SECONDS


# ---------------------------------------------------------------------------
# 5. Sleep/wake recovery: 10h gap journals wake_gap; one tick evaluates only
#    the latest bar with no replay for B2-B10.
# ---------------------------------------------------------------------------


def test_sleep_wake_recovery_journals_wake_gap_and_ticks_only_latest(home, fresh_keyring, monkeypatch, capsys):
    """Two ticks, the second 10h after the first. wake_gap is recorded, fetch is called once, no replay."""
    from krellbot import cli
    from krellbot.pack.model import Candle

    pack_path = _write_pack(home, pack_id="sw-pack", venue="kraken", pair="SUIUSD")
    _arm_paper(home, pack_path, pack_id="sw-pack", venue="kraken", pair="SUIUSD")

    base_time = 1_700_000_000.0
    HOUR_MS = 3_600_000
    B1_ms = int(base_time * 1000)
    B11_ms = B1_ms + 10 * HOUR_MS

    fake_time = [base_time]
    monkeypatch.setattr("krellbot.run._now_seconds", lambda: fake_time[0])
    monkeypatch.setattr("krellbot.cli._now_seconds_tick", lambda: fake_time[0])

    fetch_calls: list[tuple] = []

    def fake_fetch(venue, pair, tf, transport):
        fetch_calls.append((venue, pair, tf, fake_time[0]))
        if fake_time[0] == base_time:
            return [Candle(B1_ms, Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(100))]
        candles = []
        for i in range(11):
            ts = B1_ms + i * HOUR_MS
            candles.append(Candle(ts, Decimal(10), Decimal(11), Decimal(9), Decimal(10), Decimal(100)))
        return candles

    transport = _SilentTransport()
    monkeypatch.setattr("krellbot.cli._default_fetch", fake_fetch)
    monkeypatch.setattr("krellbot.cli._default_transport", lambda: transport)

    rc1 = cli.main(["krellbot", "tick", "--venue", "kraken"])
    assert rc1 == 0
    assert len(fetch_calls) == 1, f"first tick should call fetch once, got {len(fetch_calls)}"

    fake_time[0] = base_time + 10 * 3600

    rc2 = cli.main(["krellbot", "tick", "--venue", "kraken"])
    assert rc2 == 0
    assert len(fetch_calls) == 2, (
        f"second tick should call fetch once (no replay for B2-B10); got {len(fetch_calls)} calls"
    )

    records = _read_journal(home)
    tick_records = [r for r in records if r.get("kind") == "tick"]
    bar_tss = sorted({r.get("bar_ts") for r in tick_records})
    assert B1_ms in bar_tss, f"B1 tick record missing; got bar_tss={bar_tss}"
    assert B11_ms in bar_tss, f"B11 tick record missing; got bar_tss={bar_tss}"

    wake_records = [
        r for r in records if r.get("kind") == "supervision" and r.get("detail", {}).get("event") == "wake_gap"
    ]
    assert wake_records, "expected at least one wake_gap record"
    gap = wake_records[-1]["detail"]["gap_s"]
    assert gap >= 36000, f"wake_gap too small: {gap}"

    status_rc, status_body = _run_service_status(home, cli, ["krellbot", "service", "status"])
    assert status_rc == 0
    status = json.loads(status_body.strip())
    assert status["last_tick_stale"] is False


# ---------------------------------------------------------------------------
# 6. Tick lock: leftover lockfile with no holder does NOT block; held lock does.
# ---------------------------------------------------------------------------


def test_leftover_lockfile_without_holder_does_not_block_tick(home, fresh_keyring, monkeypatch, capsys):
    """A stale <home>/run/<venue>.lock with no flock holder must not block the tick."""
    from krellbot import cli

    pack_path = _write_pack(home, pack_id="leftover-pack", venue="kraken", pair="SUIUSD")
    _arm_paper(home, pack_path, pack_id="leftover-pack", venue="kraken", pair="SUIUSD")

    # Create a stray lock file with no flock holder. TickLock.acquire() uses
    # fcntl.flock on the file; a file with no flock holder is acquirable.
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "kraken.lock").write_bytes(b"")

    def fake_fetch(venue, pair, tf, transport):
        return []

    transport = _SilentTransport()
    monkeypatch.setattr("krellbot.cli._default_fetch", fake_fetch)
    monkeypatch.setattr("krellbot.cli._default_transport", lambda: transport)

    rc = cli.main(["krellbot", "tick", "--venue", "kraken"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "another tick running" not in out


def test_held_tick_lock_makes_tick_print_another_tick_running(home, fresh_keyring, monkeypatch, capsys):
    """A TickLock held by the test blocks the tick: print 'another tick running', rc=0."""
    from krellbot import cli
    from krellbot.run.lock import TickLock

    pack_path = _write_pack(home, pack_id="held-pack", venue="kraken", pair="SUIUSD")
    _arm_paper(home, pack_path, pack_id="held-pack", venue="kraken", pair="SUIUSD")

    # Acquire the lock in this process so the next acquire inside run.tick
    # is blocked. Release at the end.
    held = TickLock(home, "kraken")
    assert held.acquire()

    def fake_fetch(venue, pair, tf, transport):
        return []

    transport = _SilentTransport()
    monkeypatch.setattr("krellbot.cli._default_fetch", fake_fetch)
    monkeypatch.setattr("krellbot.cli._default_transport", lambda: transport)

    try:
        rc = cli.main(["krellbot", "tick", "--venue", "kraken"])
        out = capsys.readouterr().out
        assert rc == 0
        assert "another tick running" in out
    finally:
        held.release()


# ---------------------------------------------------------------------------
# 7. service status JSON shape and side-effect freedom
# ---------------------------------------------------------------------------


def _run_service_status(home, cli, argv):
    """Invoke cli.main(argv) and capture (rc, body) for the status command."""
    import io as _io
    from contextlib import redirect_stdout

    buf = _io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(argv)
    return rc, buf.getvalue()


def test_service_status_json_shape_without_install(home, fresh_keyring):
    """With no install, status prints one JSON object with all required fields."""
    from krellbot import cli

    rc, body = _run_service_status(home, cli, ["krellbot", "service", "status"])
    assert rc == 0
    parsed = json.loads(body.strip())
    assert isinstance(parsed, dict)
    assert set(parsed.keys()) == {
        "schema_version",
        "installed",
        "owner_present",
        "owner",
        "krellbot_home",
        "home_matches_owner",
        "last_tick_age_s",
        "last_tick_stale",
        "last_wake_gap_s",
    }
    assert parsed["schema_version"] == "1"
    assert parsed["installed"] is False
    assert parsed["owner_present"] is False
    assert parsed["owner"] is None
    assert parsed["home_matches_owner"] is False
    assert parsed["last_tick_age_s"] is None
    assert parsed["last_tick_stale"] is True  # no journal at all
    assert parsed["last_wake_gap_s"] is None


def test_service_status_after_install_with_root(home, fresh_keyring):
    """After install(write_root=tmp), status reports installed=True, home_matches_owner=True."""
    from krellbot import cli
    from krellbot.service import install

    rc = install(home, executable="/usr/local/bin/krellbot", write_root=home)
    assert rc == 0

    rc2, body = _run_service_status(home, cli, ["krellbot", "service", "status"])
    assert rc2 == 0
    parsed = json.loads(body.strip())
    assert parsed["installed"] is True
    assert parsed["owner_present"] is True
    assert isinstance(parsed["owner"], dict)
    assert parsed["owner"]["executable"] == "/usr/local/bin/krellbot"
    assert parsed["owner"]["krellbot_home"] == str(home)
    assert "interval" in parsed["owner"]
    assert parsed["home_matches_owner"] is True
    assert parsed["krellbot_home"] == str(home)


def test_service_status_writes_nothing(home, fresh_keyring):
    """`service status` does not modify the home directory."""
    from krellbot import cli

    before = sorted(p for p in home.rglob("*") if p.is_file())

    rc, _body = _run_service_status(home, cli, ["krellbot", "service", "status"])
    assert rc == 0

    after = sorted(p for p in home.rglob("*") if p.is_file())
    assert before == after, "service status must not write any file"

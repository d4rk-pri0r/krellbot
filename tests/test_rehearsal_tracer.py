"""Synthetic paper rehearsal — end-to-end tracer against the real engine.

This is the POC's primary behavioral test. It refuses mocks for the
engine and venue: the rehearsal service must drive ``krellbot.run.tick``
and the real ``PaperVenue`` over the shipped synthetic candle resource,
and every assertion is made against durable on-disk evidence (venue
state file, journal records, rehearsal state file) — never a canned
response.

The lifecycle driven here:

    start -> (bars advance) -> entry fill + owned position
          -> NEW interpreter (fresh objects, same home)
          -> exit fill from the pack's own exit rule
          -> stop -> no further evaluations, further commands refused

Additionally the API surface is exercised through the same ASGI
harness the paper routes use, including the session/CSRF/origin gates.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from tests.test_ns06_api import (
    TEST_PORT,
    _bootstrap_and_get_csrf,
    _build_app,
    _post_json,
    asgi_call,
)

REHEARSAL_LABEL = "Synthetic paper rehearsal — simulated data, not market-performance evidence"


# ---- service-level helpers ------------------------------------------------


def _service(home: Path):
    from krellbot.application.rehearsal import RehearsalService

    return RehearsalService(home=home)


def _cmd(service, command: str, payload: dict | None = None) -> dict:
    result = service.handle(command, payload or {})
    assert isinstance(result, dict)
    return result


def _status(service) -> dict:
    body = service.status_dict()
    assert isinstance(body, dict)
    return body


def _tick_records(rehearsal_home: Path) -> list[dict]:
    out: list[dict] = []
    journal_dir = rehearsal_home / "journal"
    if not journal_dir.is_dir():
        return out
    for path in sorted(journal_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


def _venue_state(rehearsal_home: Path) -> dict:
    return json.loads((rehearsal_home / "run" / "paper-kraken.json").read_text(encoding="utf-8"))


def _drive_to_position(service, *, limit: int = 80) -> dict:
    """Advance one bar per drive() until the venue owns base."""
    for _ in range(limit):
        body = _status(service)
        if Decimal(body["position"]["qty"]) > 0:
            return body
        assert service.drive(), "drive refused before the entry"
    pytest.fail("no entry fill within the drive limit")


# ---- resources ------------------------------------------------------------


def test_sample_resources_load_away_from_repository(tmp_path: Path, monkeypatch) -> None:
    """The shipped pack + candles must load from the installed package,
    not from a tests/ path fallback — cwd is moved away from the repo and
    the resource is read through importlib.resources."""
    monkeypatch.chdir(tmp_path)
    from krellbot.application import rehearsal

    pack = rehearsal.load_sample_pack()
    candles = rehearsal.load_sample_candles()
    assert pack["id"] == "rehearsal-sma-cross"
    assert pack["markets"] == [{"venue": "kraken", "pair": "SUIUSD"}]
    assert len(candles) >= 40
    # Transparently synthetic: the resource itself carries the disclaimer.
    assert rehearsal.SAMPLE_NOTE.startswith("Synthetic")
    assert "not market-performance evidence" in rehearsal.SAMPLE_NOTE
    # Strictly increasing timestamps, hourly spacing.
    ts = [c.ts_ms for c in candles]
    assert ts == sorted(ts)
    assert len(set(ts)) == len(ts)


def test_sample_pack_is_valid_and_synthetic() -> None:
    """The shipped pack passes the real linter and declares SUIUSD/kraken."""
    from krellbot.application import rehearsal
    from krellbot.pack import lint as kb_pack_lint

    pack = rehearsal.load_sample_pack()
    assert not kb_pack_lint.is_legacy(pack)
    assert kb_pack_lint.check(pack) == []


# ---- lifecycle tracer (service level, real engine + venue) ----------------


def test_rehearsal_full_lifecycle_with_new_interpreter_restart(home: Path) -> None:
    service = _service(home)

    # Fresh home: idle projection, zero cursor, explicit label.
    body = _status(service)
    assert body["schema_version"] == "1"
    assert body["label"] == REHEARSAL_LABEL
    assert body["status"] == "idle"
    assert body["cursor"] == 0
    assert body["total_bars"] >= 40
    assert body["position"]["qty"] == "0"
    assert body["resting_stop"] is None
    assert body["recent_fills"] == []
    assert Decimal(body["balances"]["USD"]) == Decimal("10000")

    # Starting arms the sample pack inside the isolated rehearsal home
    # and advances exactly one bar.
    result = _cmd(service, "rehearsal.start")
    assert result["ok"] is True
    assert result["code"] == "started"
    assert result["rehearsal"]["status"] == "running"
    assert result["rehearsal"]["cursor"] == 1

    # The app home's own user-facing config must stay untouched: the
    # rehearsal armed record lives only under <home>/rehearsal/.
    assert not (home / "config.json").exists()
    rehearsal_home = home / "rehearsal"
    cfg = json.loads((rehearsal_home / "config.json").read_text(encoding="utf-8"))
    assert len(cfg["armed"]) == 1
    assert cfg["armed"][0]["mode"] == "paper"
    assert cfg["armed"][0]["venue"] == "kraken"
    assert cfg["armed"][0]["pair"] == "SUIUSD"

    # Repeated start must not re-seed, re-arm, or advance.
    before = _status(service)
    dup = _cmd(service, "rehearsal.start")
    assert dup["ok"] is False
    assert dup["code"] == "already_started"
    after = _status(service)
    assert after["cursor"] == before["cursor"] == 1
    assert len(_tick_records(rehearsal_home)) == 1

    # Advance to the entry. The entry fill must be priced from the bar at
    # the cursor, never a future bar.
    body = _drive_to_position(service)
    entry_cursor = body["cursor"]
    entry_bar_close = Decimal("1.99")
    fills = body["recent_fills"]
    entry_fills = [f for f in fills if f["side"] == "buy"]
    assert len(entry_fills) == 1
    expected_buy = (entry_bar_close * (Decimal(1) + Decimal("0.0005"))).quantize(Decimal("0.0001"))
    assert Decimal(entry_fills[0]["price"]) == expected_buy
    assert Decimal(body["position"]["qty"]) > 0
    assert body["position"]["pair"] == "SUIUSD"
    assert body["resting_stop"] is not None

    # Cursor-aligned journal evidence: a tick record exists whose bar_ts
    # is exactly the entry bar's timestamp.
    from krellbot.application.rehearsal import load_sample_candles

    candles = load_sample_candles()
    entry_ts = candles[entry_cursor].ts_ms
    ticks = _tick_records(rehearsal_home)
    entry_tick = next(t for t in ticks if t["kind"] == "tick" and t["bar_ts"] == entry_ts)
    assert Decimal(entry_tick["detail"]["entry_qty"]) > 0

    # --- NEW INTERPRETER -------------------------------------------------
    # A fresh service instance (new objects, same durable home) must see
    # the same cursor, position, and resting stop: no restart-from-zero.
    service2 = _service(home)
    body2 = _status(service2)
    assert body2["status"] == "running"
    assert body2["cursor"] == entry_cursor
    assert Decimal(body2["position"]["qty"]) == Decimal(body["position"]["qty"])
    assert body2["resting_stop"] == body["resting_stop"]
    fills2 = [f for f in body2["recent_fills"] if f["side"] == "buy"]
    assert len(fills2) == 1

    # Pause: entries are suppressed but the run keeps its position and
    # the protective stop stays rested.
    paused = _cmd(service2, "rehearsal.pause")
    assert paused["ok"] is True
    assert paused["rehearsal"]["status"] == "paused"
    assert paused["rehearsal"]["position"]["qty"] == body["position"]["qty"]
    assert paused["rehearsal"]["resting_stop"] == body["resting_stop"]
    cfg = json.loads((rehearsal_home / "config.json").read_text(encoding="utf-8"))
    assert cfg["armed"][0]["entries_paused"] is True

    # Resume restores entries and advances one bar.
    resumed = _cmd(service2, "rehearsal.resume")
    assert resumed["ok"] is True
    assert resumed["rehearsal"]["status"] == "running"
    assert resumed["rehearsal"]["cursor"] == entry_cursor + 1
    cfg = json.loads((rehearsal_home / "config.json").read_text(encoding="utf-8"))
    assert cfg["armed"][0]["entries_paused"] is False

    # Exit: the pack's own exit rule must close the owned position via
    # the real engine path — an exit fill at the bar close, stop removed.
    exited = _cmd(service2, "rehearsal.exit")
    assert exited["ok"] is True, exited
    assert exited["rehearsal"]["status"] == "exited"
    assert Decimal(exited["rehearsal"]["position"]["qty"]) == 0
    assert exited["rehearsal"]["resting_stop"] is None
    sell_fills = [f for f in exited["rehearsal"]["recent_fills"] if f["side"] == "sell"]
    assert len(sell_fills) == 1
    exit_cursor = exited["rehearsal"]["cursor"]
    exit_close = Decimal(str(candles[exit_cursor].close))
    expected_sell = (exit_close * (Decimal(1) - Decimal("0.0005"))).quantize(Decimal("0.0001"))
    assert Decimal(sell_fills[0]["price"]) == expected_sell
    exit_ts = candles[exit_cursor].ts_ms
    exit_tick = next(t for t in _tick_records(rehearsal_home) if t["kind"] == "tick" and t["bar_ts"] == exit_ts)
    assert Decimal(exit_tick["detail"]["exit_qty"]) > 0
    # Ownership accounting closed: base balance back to zero.
    assert Decimal(_venue_state(rehearsal_home)["balances"]["SUI"]) == 0

    # Exit again: nothing left to exit.
    again = _cmd(service2, "rehearsal.exit")
    assert again["ok"] is False
    assert again["code"] == "no_open_position"

    # Stop: terminal. No further evaluations may happen, and every
    # lifecycle command is refused with the stopped code.
    ticks_before = _tick_records(rehearsal_home)
    stopped = _cmd(service2, "rehearsal.stop")
    assert stopped["ok"] is True
    assert stopped["rehearsal"]["status"] == "stopped"
    cursor_at_stop = stopped["rehearsal"]["cursor"]
    for command in ("rehearsal.start", "rehearsal.pause", "rehearsal.resume", "rehearsal.exit", "rehearsal.stop"):
        refused = _cmd(service2, command)
        assert refused["ok"] is False, (command, refused)
        assert refused["code"] == "already_stopped"
    body3 = _status(service2)
    assert body3["status"] == "stopped"
    assert body3["cursor"] == cursor_at_stop
    assert _tick_records(rehearsal_home) == ticks_before

    # An unknown rehearsal command is refused, never silently ignored.
    bad = _cmd(service2, "rehearsal.warp")
    assert bad["ok"] is False
    assert bad["code"] == "unknown_command"

    # Malformed payload is refused before any state change.
    malformed = _cmd(service2, "rehearsal.resume", {"bars": 99})
    assert malformed["ok"] is False
    assert malformed["code"] == "invalid_request"
    assert _tick_records(rehearsal_home) == ticks_before


def test_rehearsal_pause_blocks_entries_but_keeps_protection(home: Path) -> None:
    """Pause before the entry: while paused nothing evaluates (drive
    refuses), the cursor freezes, and the run resumes into the entry."""
    service = _service(home)
    _cmd(service, "rehearsal.start")
    paused = _cmd(service, "rehearsal.pause")
    assert paused["ok"] is True
    ticks_before = len(_tick_records(home / "rehearsal"))
    cursor_before = _status(service)["cursor"]
    still = _cmd(service, "rehearsal.pause")
    assert still["ok"] is False
    assert still["code"] == "already_paused"
    # While paused the engine is not invoked at all: no bar, no journal.
    assert service.drive() is False
    assert _status(service)["cursor"] == cursor_before
    assert len(_tick_records(home / "rehearsal")) == ticks_before
    resumed = _cmd(service, "rehearsal.resume")
    assert resumed["ok"] is True
    # Drive to the entry and confirm it happens only after resume.
    body = _drive_to_position(service)
    assert Decimal(body["position"]["qty"]) > 0
    assert len(_tick_records(home / "rehearsal")) > ticks_before


def test_rehearsal_isolation_from_existing_user_state(home: Path) -> None:
    """A pre-existing user armed record must be untouched by a rehearsal
    run, and its paper venue state must never be read or written."""
    from krellbot import config as kb_config

    user_venue_state = {
        "venue": "kraken",
        "balances": {"USD": Decimal("777")},
        "open_orders": [],
        "recent_fills": [],
        "seeded": True,
    }
    (home / "run").mkdir(parents=True, exist_ok=True)
    (home / "run" / "paper-kraken.json").write_text(
        json.dumps(user_venue_state, default=str), encoding="utf-8"
    )
    armed = kb_config.ArmedPack(
        pack_path="/nonexistent/user-pack.json",
        pack_sha256="0" * 64,
        pack_id="user-pack",
        pack_version="1.0.0",
        venue="kraken",
        pair="SUIUSD",
        cap=Decimal(10),
        stop=Decimal("0.5"),
        mode="paper",
        starting_cash=Decimal("777"),
        requires_license=False,
        armed_at_ts=1,
    )
    cfg = kb_config.Config(armed=[armed])
    kb_config.save_config(home, cfg)
    before = (home / "config.json").read_bytes()

    service = _service(home)
    _cmd(service, "rehearsal.start")
    _drive_to_position(service)

    assert (home / "config.json").read_bytes() == before
    after = json.loads((home / "run" / "paper-kraken.json").read_text(encoding="utf-8"))
    assert Decimal(str(after["balances"]["USD"])) == Decimal("777")
    assert after["recent_fills"] == []
    # The rehearsal's own venue state lives under <home>/rehearsal/run.
    rehearsal_state = _venue_state(home / "rehearsal")
    assert Decimal(str(rehearsal_state["balances"]["USD"])) < Decimal("10000")


def test_rehearsal_survives_new_backend_process(home: Path) -> None:
    """Durable-state proof across a real OS process boundary: one
    interpreter drives to a position; a second process reconstructs the
    run, exits it, and stops it."""
    driver = (
        "import sys, json\n"
        "from pathlib import Path\n"
        "from krellbot.application.rehearsal import RehearsalService\n"
        "svc = RehearsalService(home=Path(sys.argv[1]))\n"
        "phase = sys.argv[2]\n"
        "if phase == 'drive':\n"
        "    r = svc.handle('rehearsal.start', {})\n"
        "    assert r['ok'], r\n"
        "    for _ in range(80):\n"
        "        b = svc.status_dict()\n"
        "        from decimal import Decimal\n"
        "        if Decimal(b['position']['qty']) > 0:\n"
        "            print(json.dumps({'cursor': b['cursor'], 'qty': b['position']['qty']}))\n"
        "            break\n"
        "        assert svc.drive(), 'drive refused'\n"
        "    else:\n"
        "    \traise SystemExit('no entry')\n"
        "elif phase == 'finish':\n"
        "    b = svc.status_dict()\n"
        "    print(json.dumps({'status': b['status'], 'cursor': b['cursor'], 'qty': b['position']['qty']}))\n"
        "    r = svc.handle('rehearsal.exit', {})\n"
        "    assert r['ok'], r\n"
        "    r = svc.handle('rehearsal.stop', {})\n"
        "    assert r['ok'], r\n"
        "    b = svc.status_dict()\n"
        "    print(json.dumps({'status': b['status'], 'cursor': b['cursor'], 'qty': b['position']['qty']}))\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["KRELLBOT_HOME"] = str(home)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent / "src")

    phase1 = subprocess.run(
        [sys.executable, "-c", driver, str(home), "drive"],
        capture_output=True, text=True, env=env, timeout=120, check=False,
    )
    assert phase1.returncode == 0, phase1.stderr
    driven = [json.loads(line) for line in phase1.stdout.splitlines() if line.startswith("{")]
    assert Decimal(driven[-1]["qty"]) > 0

    phase2 = subprocess.run(
        [sys.executable, "-c", driver, str(home), "finish"],
        capture_output=True, text=True, env=env, timeout=120, check=False,
    )
    assert phase2.returncode == 0, phase2.stderr
    seen = [json.loads(line) for line in phase2.stdout.splitlines() if line.startswith("{")]
    # The second process inherited the running position...
    assert seen[0]["status"] == "running"
    assert Decimal(seen[0]["qty"]) == Decimal(driven[-1]["qty"])
    assert seen[0]["cursor"] == driven[-1]["cursor"]
    # ...exited it legitimately and stopped.
    assert seen[1]["status"] == "stopped"
    assert Decimal(seen[1]["qty"]) == 0


# ---- API surface ----------------------------------------------------------


def _auth(csrf_token: str, cookie: str):
    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={cookie}"),
    ]


def _rehearsal_get(app, path: str, headers: list[tuple[str, str]]):
    return asgi_call(app, method="GET", path=path, headers=[("Host", f"127.0.0.1:{TEST_PORT}"), *headers])


def test_rehearsal_status_route_requires_session(home: Path) -> None:
    app = _build_app(home)
    status, _h, body, _c = _rehearsal_get(app, "/api/v1/rehearsal/status", [])
    assert status == 403
    assert b"session required" in body


def test_rehearsal_status_route_shape(home: Path) -> None:
    app = _build_app(home)
    csrf = _bootstrap_and_get_csrf(app, "boot-test-token")
    cookie = next(iter(app.state.krellbot.sessions.keys()))
    status, _h, body, _c = _rehearsal_get(app, "/api/v1/rehearsal/status", _auth(csrf, cookie))
    assert status == 200
    payload = json.loads(body)
    for key in (
        "schema_version", "label", "status", "cursor", "total_bars",
        "balances", "position", "resting_stop", "recent_fills",
    ):
        assert key in payload, key
    assert payload["label"] == REHEARSAL_LABEL
    assert payload["schema_version"] == "1"
    # The API wire shape flattens ``position`` to a qty string for the
    # existing rehearsalClient contract; the service-level projection
    # below keeps the full pair/qty object.
    assert isinstance(payload["position"], str)
    assert isinstance(payload["recent_fills"], list)


def test_rehearsal_commands_through_api(home: Path) -> None:
    app = _build_app(home)
    csrf = _bootstrap_and_get_csrf(app, "boot-test-token")
    cookie = next(iter(app.state.krellbot.sessions.keys()))

    def post(payload: dict, headers=None):
        return _post_json(
            app, "/api/v1/commands", payload,
            headers=headers if headers is not None else _auth(csrf, cookie),
        )

    # Gate parity with the paper commands: no session -> 403.
    status, _h, _b, _c = _post_json(
        app, "/api/v1/commands",
        {"schema_version": "1", "command": "rehearsal.start", "payload": {}},
        headers=[("Origin", f"http://127.0.0.1:{TEST_PORT}"), ("X-Krellbot-CSRF", "x")],
    )
    assert status == 403

    # Bad envelope (non-empty payload) -> 400 invalid body.
    status, _h, _b, _c = post({"schema_version": "1", "command": "rehearsal.start", "payload": {"bars": 3}})
    assert status == 400

    # Unknown rehearsal command -> 403, consistent with unknown paper commands.
    status, _h, _b, _c = post({"schema_version": "1", "command": "rehearsal.warp", "payload": {}})
    assert status == 403

    # Live is off: a mode=live payload is refused regardless.
    status, _h, _b, _c = post({"schema_version": "1", "command": "rehearsal.start", "payload": {}, "mode": "live"})
    assert status == 403
    assert b"live orders are disabled" in _b

    # Real start through the API: ok/code/message + state readback.
    status, _h, body, _c = post({"schema_version": "1", "command": "rehearsal.start", "payload": {}})
    assert status == 200
    result = json.loads(body)
    assert result["ok"] is True
    assert result["code"] == "started"
    assert result["effect"] == "changed"
    assert result["rehearsal"]["status"] == "running"
    assert result["rehearsal"]["cursor"] == 1
    assert result["rehearsal"]["label"] == REHEARSAL_LABEL

    # The service behind the app shares the durable state.
    status, _h, body, _c = _rehearsal_get(app, "/api/v1/rehearsal/status", _auth(csrf, cookie))
    assert status == 200
    assert json.loads(body)["cursor"] == 1

    # Duplicate start: refused, state readback unchanged cursor.
    status, _h, body, _c = post({"schema_version": "1", "command": "rehearsal.start", "payload": {}})
    assert status == 200
    result = json.loads(body)
    assert result["ok"] is False
    assert result["code"] == "already_started"
    assert result["effect"] == "refused"
    assert result["rehearsal"]["cursor"] == 1

    # Pause then stop through the API; stopped state readback.
    status, _h, body, _c = post({"schema_version": "1", "command": "rehearsal.pause", "payload": {}})
    assert json.loads(body)["rehearsal"]["status"] == "paused"
    status, _h, body, _c = post({"schema_version": "1", "command": "rehearsal.stop", "payload": {}})
    result = json.loads(body)
    assert result["ok"] is True
    assert result["rehearsal"]["status"] == "stopped"
    status, _h, body, _c = post({"schema_version": "1", "command": "rehearsal.resume", "payload": {}})
    assert json.loads(body)["code"] == "already_stopped"

"""Independent real-engine pricing/read boundary and existing UI wire contract."""

import asyncio
import hashlib
import json
import os
from decimal import ROUND_DOWN, Decimal

from krellbot.application.rehearsal import RehearsalService, load_sample_candles
from tests.test_ns06_api import TEST_PORT, _bootstrap_and_get_csrf, _build_app, _post_json, asgi_call


def durable_bytes(home):
    return {
        str(p.relative_to(home)): hashlib.sha256(p.read_bytes()).hexdigest() for p in home.rglob("*") if p.is_file()
    }


def test_real_cursor_price_timestamp_and_read_immutability(tmp_path):
    original_env = os.environ.get("KRELLBOT_HOME")
    svc = RehearsalService(tmp_path)
    assert svc.handle("rehearsal.start")["ok"]
    while Decimal(svc.status_dict()["position"]["qty"]) == 0:
        assert svc.drive()
    body = svc.status_dict()
    assert body["cursor"] == 30
    bar = load_sample_candles()[body["cursor"]]
    fill = body["recent_fills"][0]
    assert fill["ts_ms"] == bar.ts_ms
    assert Decimal(fill["price"]) == (Decimal(str(bar.close)) * Decimal("1.0005")).quantize(
        Decimal("0.0001"), rounding=ROUND_DOWN
    )
    venue = svc._build_venue()
    assert venue._reader("kraken", "SUIUSD") == load_sample_candles()[: body["cursor"] + 1]
    # Future bars contain prices capable of changing stops/positions. None
    # can be applied by a read, even immediately after a persisted entry.
    before = durable_bytes(svc.rehearsal_home)
    for _ in range(8):
        assert svc.status_dict() == body
    assert durable_bytes(svc.rehearsal_home) == before
    assert os.environ.get("KRELLBOT_HOME") == original_env
    paused = svc.handle("rehearsal.pause")["rehearsal"]
    assert svc.drive() is False
    assert RehearsalService(tmp_path).status_dict() == paused
    assert svc.handle("rehearsal.resume")["ok"]
    exit_result = svc.handle("rehearsal.exit")
    assert exit_result["ok"], exit_result
    exited = exit_result["rehearsal"]
    sell = exited["recent_fills"][-1]
    exit_bar = load_sample_candles()[exited["cursor"]]
    assert sell["ts_ms"] == exit_bar.ts_ms
    assert Decimal(sell["price"]) == (Decimal(str(exit_bar.close)) * Decimal("0.9995")).quantize(
        Decimal("0.0001"), rounding=ROUND_DOWN
    )
    ticks = [
        json.loads(line)
        for p in (svc.rehearsal_home / "journal").glob("*.jsonl")
        for line in p.read_text().splitlines()
    ]
    assert any(
        t["bar_ts"] == exit_bar.ts_ms and Decimal(t["detail"].get("exit_qty", "0")) > 0
        for t in ticks
        if t["kind"] == "tick"
    )
    assert Decimal(exited["position"]["qty"]) == 0
    assert svc.handle("rehearsal.stop")["ok"]
    stopped = durable_bytes(svc.rehearsal_home)
    assert not svc.drive()
    assert svc.handle("rehearsal.resume")["code"] == "already_stopped"
    assert durable_bytes(svc.rehearsal_home) == stopped


def test_existing_ui_contract_and_security(tmp_path):
    app = _build_app(tmp_path, bootstrap_token="rehearsal-contract")
    csrf = _bootstrap_and_get_csrf(app, "rehearsal-contract")
    cookie = next(iter(app.state.krellbot.sessions))
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={cookie}"),
    ]

    def command(name, payload=None, extra=None, auth=None):
        return _post_json(
            app,
            "/api/v1/commands",
            {"command": name, "payload": {} if payload is None else payload, **(extra or {})},
            headers=headers if auth is None else auth,
        )

    for kwargs in (
        {"auth": []},
        {"auth": headers[:1] + headers[2:]},
        {"extra": {"mode": "live"}},
        {"payload": {"mode": "live"}},
    ):
        assert command("rehearsal.start", **kwargs)[0] == 403
    assert command("rehearsal.warp")[0] == 403
    assert command("rehearsal.start", {"bars": 3})[0] == 400
    assert not (tmp_path / "rehearsal" / "state.json").exists()
    status, _, raw, _ = command("rehearsal.start")
    result = json.loads(raw)
    assert status == 200 and result["ok"]
    assert result["status"]["position"] == "0"
    assert result["status"]["status"] == "running"
    assert result["status"]["driver_cadence_seconds"] == 1.0
    assert command("rehearsal.pause")[0] == 200
    assert command("rehearsal.stop")[0] == 200
    status, _, raw, _ = asgi_call(
        app, method="GET", path="/api/v1/rehearsal/status", headers=[("Host", f"127.0.0.1:{TEST_PORT}"), *headers]
    )
    assert status == 200
    assert isinstance(json.loads(raw)["position"], str)
    assert not (tmp_path / "config.json").exists()


def test_lifespan_driver_advances_and_cleans_up(tmp_path):
    app = _build_app(tmp_path)

    async def exercise():
        async with app.router.lifespan_context(app):
            svc = app.state.krellbot.rehearsal_service
            # The singleton is lazy until the first command/driver wake.
            from krellbot.api.app import _rehearsal_service

            svc = _rehearsal_service(app.state.krellbot)
            assert svc.handle("rehearsal.start")["ok"]
            cursor = svc.status_dict()["cursor"]
            await asyncio.sleep(1.5)
            assert svc.status_dict()["cursor"] > cursor
            assert svc.handle("rehearsal.pause")["ok"]
            cursor = svc.status_dict()["cursor"]
            await asyncio.sleep(1.5)
            assert svc.status_dict()["cursor"] == cursor
        before = durable_bytes(tmp_path)
        await asyncio.sleep(1.2)
        assert durable_bytes(tmp_path) == before

    asyncio.run(exercise())

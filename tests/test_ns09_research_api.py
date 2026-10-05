"""NS09a — research result read.

Tests-first. The result route, the result storage on the JobManager, and
the default research runner's "keep the receipt" behavior do not exist
before this NS lands.

Behavior under test:

  1. A successful runner outcome is stored with the job.
     ``GET /api/v1/jobs/{id}/result`` returns that stored object after
     the same session gate as ``GET /api/v1/jobs/{id}``.

  2. The stored object keeps ``legacy_receipt`` and ``trace`` exactly
     as the runner returned them. Do not add missing keys. Do not
     replace a missing fee, equity, or drawdown value with ``0``.

  3. A running, queued, cancelled, or failed job has no result. The
     result route returns ``404`` with ``{"code": "result_unavailable"}``
     and no receipt body.

  4. The default research runner must stop dropping the receipt.
     On ``ResearchResult.ok``, store ``legacy_receipt`` and
     ``detail["trace"]`` with the result ref. On refusal, store no
     receipt.

  5. Cancelling a running job still leaves ``result_ref`` empty and the
     result route unavailable.

Test layout:

  * Use the existing ASGI test client and ``_build_app(home, runner=...)``
    pattern from ``tests/test_ns06_jobs.py``.
  * Inject a runner for the storage proof. One test may monkeypatch
    ``ResearchService.run`` to prove the default runner keeps the receipt
    object.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from tests.test_ns06_api import TEST_PORT, asgi_call
from tests.test_ns06_jobs import (
    _bootstrap_session,
    _build_app,
    _cancel_job,
    _get_job,
    _submit_job,
)

# ---------------------------------------------------------------------------
# Result route helpers
# ---------------------------------------------------------------------------


def _get_result(
    app,
    csrf: str,
    session: str,
    job_id: str,
    *,
    headers: list[tuple[str, str]] | None = None,
):
    """GET /api/v1/jobs/{id}/result with full auth and return (status, body_dict)."""

    if headers is None:
        headers = [
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", csrf),
            ("Cookie", f"krellbot_session={session}"),
        ]
    path = f"/api/v1/jobs/{job_id}/result"
    status, _hdrs, raw_body, _cookies = asgi_call(app, method="GET", path=path, headers=headers)
    decoded = json.loads(raw_body) if raw_body else None
    return status, decoded


def _wait_for_terminal(app, csrf, session, job_id, *, timeout: float = 2.0) -> dict:
    """Poll the job snapshot until it reaches a terminal state."""

    deadline = time.monotonic() + timeout
    snap: dict | None = None
    while time.monotonic() < deadline:
        _s, snap = _get_job(app, csrf, session, job_id)
        if snap["state"] in {"succeeded", "failed", "cancelled"}:
            return snap
        time.sleep(0.005)
    raise AssertionError(f"job {job_id} never reached terminal state: {snap}")


def _blocking_runner_event() -> tuple[Any, threading.Event, list]:
    """Return ``(runner, release_event, captures)`` mirroring ``_make_event_runner``."""

    event = threading.Event()
    captures: list[dict] = []

    def runner(request):
        captures.append(dict(request) if isinstance(request, dict) else {"request": repr(request)})
        event.wait()
        return {"ok": True}

    return runner, event, captures


# ---------------------------------------------------------------------------
# 1. Storing and retrieving a successful result
# ---------------------------------------------------------------------------


def test_result_route_returns_stored_object_for_succeeded_job(home: Path) -> None:
    """A runner that returns ``ok=True`` with a receipt stores it; the
    result route returns the same object."""

    receipt = {
        "engine_version": "test-1",
        "pack_sha256": "abc",
        "data_manifest_sha256": "def",
        "venue": "kraken",
        "pair": "SUIUSD",
        "tf": "1h",
        "from": 0,
        "to": 1000,
        "fee_bps": 40,
        "slippage_bps": 5,
        "slippage_mult": 1.0,
        "metrics": {"trade_count": 0},
        "equity_curve": [],
    }
    trace = [
        {
            "bar_ts": 0,
            "warmup": True,
            "input": {"ts_ms": 0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0},
            "indicators": {"sma20": None},
            "conditions": [],
            "target": {"long": False, "stop_price": None, "reason": "warmup"},
        }
    ]
    ref = "backtest:result-1:jobid"

    def runner(request):
        return {
            "ok": True,
            "result_ref": ref,
            "legacy_receipt": receipt,
            "trace": trace,
        }

    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "result-1"})
    job_id = submitted["id"]

    final = _wait_for_terminal(app, csrf, session, job_id)
    assert final["state"] == "succeeded", final
    assert final["result_ref"] == ref, final

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 200, (status, body)
    # The stored object is exactly the runner's receipt + trace. No extra
    # keys. No ``0`` substituted for missing fields.
    assert set(body.keys()) == {"legacy_receipt", "trace"}, sorted(body.keys())
    assert body["legacy_receipt"] == receipt, body["legacy_receipt"]
    assert body["trace"] == trace, body["trace"]
    # The contract requires a schema_version. The brief says "Do not add
    # missing keys" — but the JobV1 schema includes schema_version on
    # every endpoint, and the existing receipt already carries version
    # data inside its keys. We don't add keys to the *receipt*; we just
    # keep what the runner sent.

    # The same receipt is returned on every call; storage is stable.
    status2, body2 = _get_result(app, csrf, session, job_id)
    assert status2 == 200
    assert body2 == body


def test_result_route_keeps_runner_supplied_keys_without_substituting_zero(
    home: Path,
) -> None:
    """The stored object must keep the runner's exact keys. Missing fee /
    equity / drawdown values must stay missing — no ``0`` substitution."""

    receipt = {
        "engine_version": "test-minimal",
        "pack_sha256": "abc",
        # Note: deliberately omit fee_bps / metrics / equity_curve. The
        # server must not fill them in.
    }
    trace = [{"bar_ts": 0, "warmup": True}]

    def runner(request):
        return {
            "ok": True,
            "result_ref": "ref-minimal",
            "legacy_receipt": receipt,
            "trace": trace,
        }

    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "result-min"})
    job_id = submitted["id"]
    _wait_for_terminal(app, csrf, session, job_id)

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 200, (status, body)
    assert body["legacy_receipt"] == receipt
    # No silently-added fee/equity/drawdown.
    assert "fee_bps" not in body["legacy_receipt"]
    assert "equity_curve" not in body["legacy_receipt"]
    assert "drawdown" not in body["legacy_receipt"]
    # The trace entry must also stay exact.
    assert body["trace"] == trace


# ---------------------------------------------------------------------------
# 2. Result unavailable for non-success terminal states
# ---------------------------------------------------------------------------


def test_result_unavailable_for_failed_job(home: Path) -> None:
    """A failed job returns ``404 result_unavailable`` from the result route."""

    def boom(_request):
        raise RuntimeError("simulated failure")

    app = _build_app(home, runner=boom)
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "fail-r"})
    job_id = submitted["id"]
    final = _wait_for_terminal(app, csrf, session, job_id)
    assert final["state"] == "failed", final
    assert final["result_ref"] is None, final

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 404, (status, body)
    assert body == {"code": "result_unavailable"}, body
    # No receipt body.
    assert "legacy_receipt" not in body
    assert "trace" not in body


def test_result_unavailable_for_refused_runner_outcome(home: Path) -> None:
    """A runner that returns ``ok=False`` (e.g. refusal) stores no result."""

    def refusing_runner(_request):
        return {"ok": False}

    app = _build_app(home, runner=refusing_runner)
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "refuse-r"})
    job_id = submitted["id"]
    final = _wait_for_terminal(app, csrf, session, job_id)
    # The default runner treats "ok=False" as a failed job. Either way
    # the result must be unavailable.
    assert final["state"] == "failed", final
    assert final["result_ref"] is None, final

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 404, (status, body)
    assert body == {"code": "result_unavailable"}, body


def test_result_unavailable_for_running_job(home: Path) -> None:
    """A job that is still running has no stored result."""

    runner, release, _captures = _blocking_runner_event()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "run-r"})
    job_id = submitted["id"]
    assert submitted["state"] == "running", submitted

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 404, (status, body)
    assert body == {"code": "result_unavailable"}, body
    # No receipt leaked into the response.
    assert "legacy_receipt" not in body

    release.set()


def test_result_unavailable_for_queued_job(home: Path) -> None:
    """A queued job has no stored result yet."""

    runner, release, _captures = _blocking_runner_event()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)

    accepted: list[dict] = []
    # 1 running + 4 queued = full cap.
    for i in range(5):
        _s, body = _submit_job(app, csrf, session, {"correlation_id": f"q-{i}"})
        assert _s == 200, (_s, body)
        accepted.append(body)

    # Find the queued ones (the first should be running).
    queued_ids = [j["id"] for j in accepted if j["state"] == "queued"]
    assert len(queued_ids) >= 1, [j["state"] for j in accepted]

    for qid in queued_ids:
        status, body = _get_result(app, csrf, session, qid)
        assert status == 404, (qid, status, body)
        assert body == {"code": "result_unavailable"}, (qid, body)

    release.set()


def test_result_unavailable_for_cancelled_job(home: Path) -> None:
    """Cancel before success leaves ``result_ref`` empty and the result
    route unavailable."""

    runner, release, _captures = _blocking_runner_event()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)

    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "cancel-r"})
    job_id = submitted["id"]

    # Cancel mid-flight.
    _cs, cancel_body = _cancel_job(app, csrf, session, job_id)
    assert _cs == 200, (_cs, cancel_body)
    assert cancel_body["state"] == "cancelling", cancel_body

    # While it's still cancelling, the result is unavailable.
    status_mid, body_mid = _get_result(app, csrf, session, job_id)
    assert status_mid == 404, (status_mid, body_mid)
    assert body_mid == {"code": "result_unavailable"}, body_mid

    release.set()

    final = _wait_for_terminal(app, csrf, session, job_id)
    assert final["state"] == "cancelled", final
    assert final["result_ref"] is None, final

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 404, (status, body)
    assert body == {"code": "result_unavailable"}, body


# ---------------------------------------------------------------------------
# 3. Result route auth gate mirrors GET /api/v1/jobs/{id}
# ---------------------------------------------------------------------------


def test_result_route_requires_session_cookie(home: Path) -> None:
    """Without a session cookie the result route is 403."""

    app = _build_app(home, runner=lambda _r: {"ok": True, "result_ref": "x"})
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "auth-r"})
    job_id = submitted["id"]

    # Missing cookie.
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
    ]
    status, _body = _get_result(app, csrf, "", job_id, headers=headers)
    assert status == 403, status


def test_result_route_rejects_non_loopback_origin(home: Path) -> None:
    """A non-loopback Origin on the result route is 403."""

    app = _build_app(home, runner=lambda _r: {"ok": True, "result_ref": "x"})
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "origin-r"})
    job_id = submitted["id"]

    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", "http://evil.example.com"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _body = _get_result(app, csrf, session, job_id, headers=headers)
    assert status == 403, status


def test_result_route_404s_for_unknown_job(home: Path) -> None:
    """An unknown job id returns ``not_found`` (not ``result_unavailable``)."""

    app = _build_app(home, runner=lambda _r: {"ok": True, "result_ref": "x"})
    csrf, session = _bootstrap_session(app)
    status, body = _get_result(app, csrf, session, "does-not-exist")
    assert status == 404, (status, body)
    # Unknown id is not_found, not result_unavailable — they're separate
    # conditions: the job is unknown vs. the job is known but has no
    # result yet.
    assert body["code"] == "not_found", body


# ---------------------------------------------------------------------------
# 4. Default runner keeps the receipt on ResearchResult.ok
# ---------------------------------------------------------------------------


def test_default_runner_keeps_legacy_receipt_and_trace_on_ok(home: Path, monkeypatch) -> None:
    """With no injected runner, ``ResearchService.run`` returns ``ok=True``
    with ``legacy_receipt`` and a trace; the API stores both and the result
    route returns them."""

    from krellbot.application import research as research_module

    receipt = {
        "engine_version": "default-runner-1",
        "pack_sha256": "defaultpack",
        "data_manifest_sha256": "defaultdata",
        "venue": "kraken",
        "pair": "SUIUSD",
        "tf": "1h",
        "from": 0,
        "to": 1000,
        "fee_bps": 40,
        "slippage_bps": 5,
        "slippage_mult": 1.0,
        "metrics": {"trade_count": 0},
        "equity_curve": [],
    }
    trace = [
        {
            "bar_ts": 0,
            "warmup": True,
            "input": {"ts_ms": 0, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 0.0},
            "indicators": {},
            "conditions": [],
            "target": {"long": False, "stop_price": None, "reason": "warmup"},
        }
    ]

    def fake_run(self, request):
        return research_module.ResearchResult(
            ok=True,
            legacy_receipt=receipt,
            detail={"schema_version": "1", "trace": trace},
            refusal=None,
        )

    monkeypatch.setattr(research_module.ResearchService, "run", fake_run)

    # Build an app without an injected runner so the default runner runs.
    from krellbot.api.app import create_app

    token = f"boot-{home.name}-{id(home)}-default"
    app = create_app(home=home, port=TEST_PORT, bootstrap_token=token)
    csrf, session = _bootstrap_session(app)

    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "default-ok"})
    job_id = submitted["id"]
    final = _wait_for_terminal(app, csrf, session, job_id)
    assert final["state"] == "succeeded", final
    assert final["result_ref"] is not None, final

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 200, (status, body)
    assert body["legacy_receipt"] == receipt, body["legacy_receipt"]
    assert body["trace"] == trace, body["trace"]


def test_default_runner_drops_receipt_on_refusal(home: Path, monkeypatch) -> None:
    """When ``ResearchService.run`` returns ``ok=False``, no receipt is
    stored and the result route is unavailable."""

    from krellbot.application import research as research_module

    def fake_run(self, request):
        return research_module.ResearchResult(
            ok=False,
            legacy_receipt=None,
            detail={
                "schema_version": "1",
                "refusal": {"code": "missing_pack", "message": "no pack"},
            },
            refusal={"code": "missing_pack", "message": "no pack"},
        )

    monkeypatch.setattr(research_module.ResearchService, "run", fake_run)

    from krellbot.api.app import create_app

    token = f"boot-{home.name}-{id(home)}-refuse"
    app = create_app(home=home, port=TEST_PORT, bootstrap_token=token)
    csrf, session = _bootstrap_session(app)

    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "default-refuse"})
    job_id = submitted["id"]
    final = _wait_for_terminal(app, csrf, session, job_id)
    # Refusal is a failure: no result_ref.
    assert final["state"] == "failed", final
    assert final["result_ref"] is None, final

    status, body = _get_result(app, csrf, session, job_id)
    assert status == 404, (status, body)
    assert body == {"code": "result_unavailable"}, body


# ---------------------------------------------------------------------------
# 5. Concurrent reader does not race with worker finalization
# ---------------------------------------------------------------------------


def test_result_route_is_stable_after_succeeded(home: Path) -> None:
    """Once a job is succeeded, the result route returns the same body on
    every call until the app process dies. (Storage is in-process; not the
    ledger.)"""

    receipt = {"engine_version": "stable-1", "pack_sha256": "x"}
    trace: list = []

    def runner(request):
        return {
            "ok": True,
            "result_ref": "stable-ref",
            "legacy_receipt": receipt,
            "trace": trace,
        }

    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "stable-r"})
    job_id = submitted["id"]
    _wait_for_terminal(app, csrf, session, job_id)

    first_status, first_body = _get_result(app, csrf, session, job_id)
    assert first_status == 200
    for _ in range(3):
        status, body = _get_result(app, csrf, session, job_id)
        assert status == 200
        assert body == first_body

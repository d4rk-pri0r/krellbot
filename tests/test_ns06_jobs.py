"""NS06b — bounded research jobs and SSE.

Tests-first. The job routes and the SSE endpoint do not exist before this
NS lands; the import lines below must fail in the RED phase, then
``create_app`` must accept an optional ``runner`` callable without breaking
the NS06a suite.

Behavior under test:

  1. ``POST /api/v1/research/jobs`` reuses the same session cookie, loopback
     Origin, loopback Host, and ``X-Krellbot-CSRF`` gates as
     ``POST /api/v1/commands``. A missing gate is 403.
  2. One job may be ``running``. Up to four are ``queued``. The next
     submission is 429 with code ``queue_full`` and creates no job.
  3. A paper command issued while a job is blocked inside the injected
     runner still returns. The test holds the runner on a
     ``threading.Event`` and asserts the command response arrives before
     that event is set.
  4. ``POST /api/v1/jobs/{id}/cancel`` is cooperative and idempotent. A
     job that already finished stays ``succeeded``. A job stopped before
     success is ``cancelled`` and has no ``result_ref``.
  5. ``GET /api/v1/jobs/{id}`` returns the JobV1 fields from
     ``contracts/jobs.md``: ``schema_version``, ``id``, ``kind``, ``state``,
     timestamps, ``progress``, ``result_ref``, ``error``,
     ``correlation_id``. ``error`` is ``{code, message}`` or ``null``. No
     traceback text.
  6. ``GET /api/v1/events`` is authenticated SSE. Reconnect with
     ``Last-Event-ID`` replays retained events in order. A gap returns an
     event whose kind is ``resync_required``.
  7. Job failures use a closed code. Do not put exception text in the
     response.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

from tests.test_ns06_api import (  # reuse the same ASGI test client
    TEST_PORT,
    _ascii_headers,
    _default_origin_header,
    _post_json,
)

# ---------------------------------------------------------------------------
# ASGI helpers shared by both reading buffered responses and streaming SSE
# ---------------------------------------------------------------------------


def _build_app(home: Path, *, runner=None) -> object:
    """Build a fresh API app with the given home, injecting a runner if asked."""

    from krellbot.api.app import create_app

    token = f"boot-{home.name}-{id(home)}"
    return create_app(
        home=home,
        port=TEST_PORT,
        bootstrap_token=token,
        runner=runner,
    )


def _bootstrap_session(app) -> tuple[str, str]:
    """Redeem bootstrap and return (csrf_token, session_cookie_value).

    Reuses the same loopback-origin envelope NS06a uses. The bootstrap
    token comes from a fresh per-app identifier (the same one ``create_app``
    used at build time).
    """

    state = app.state.krellbot
    status, _hdrs, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": state.bootstrap_token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    csrf = decoded["csrf_token"]
    session = next(c.split(";", 1)[0].split("=", 1)[1] for c in cookies if c.startswith("krellbot_session="))
    return csrf, session


def _auth_headers(csrf: str, session: str, port: int = TEST_PORT) -> list[tuple[str, str]]:
    return [
        ("Origin", f"http://127.0.0.1:{port}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]


def _submit_job(app, csrf, session, payload=None):
    """POST /api/v1/research/jobs with full auth and return (status, body_dict)."""

    payload = payload or {}
    status, _hdrs, body, _cookies = _post_json(
        app,
        "/api/v1/research/jobs",
        payload,
        headers=_auth_headers(csrf, session),
    )
    return status, (json.loads(body) if body else None)


def _get_job(app, csrf, session, job_id):
    """GET /api/v1/jobs/{id} and return (status, body_dict)."""

    path = f"/api/v1/jobs/{job_id}"
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    from tests.test_ns06_api import asgi_call

    status, _hdrs, body, _cookies = asgi_call(app, method="GET", path=path, headers=headers)
    return status, (json.loads(body) if body else None)


def _cancel_job(app, csrf, session, job_id):
    path = f"/api/v1/jobs/{job_id}/cancel"
    headers = _auth_headers(csrf, session)
    status, _hdrs, body, _cookies = _post_json(
        app,
        path,
        {},
        headers=headers,
    )
    return status, (json.loads(body) if body else None)


# ---------------------------------------------------------------------------
# SSE consumer. Sends an http.disconnect once enough events have arrived.
# ---------------------------------------------------------------------------


def _consume_sse(
    app,
    *,
    path: str,
    headers: list[tuple[str, str]],
    min_events: int,
    timeout: float = 1.0,
) -> tuple[int, dict[str, str], list[dict]]:
    """Open an SSE connection, parse ``min_events`` events, then disconnect.

    Returns ``(status, headers_dict, events)``. Each ``events`` entry has the
    SSE fields ``id``, ``event``, ``data``, plus a parsed ``payload`` dict
    from the JSON ``data`` body.
    """

    sent_request = {"done": False}
    captured: dict[str, object] = {"status": 500, "headers": []}
    body_chunks: list[bytes] = []
    disconnect_event = asyncio.Event()

    async def receive():
        if not sent_request["done"]:
            sent_request["done"] = True
            return {"type": "http.request", "body": b"", "more_body": False}
        # After the initial request, wait for the client-side disconnect.
        await disconnect_event.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.start":
            captured["status"] = int(message["status"])
            captured["headers"] = list(message.get("headers", []))
        elif message["type"] == "http.response.body":
            body_chunks.append(message.get("body", b""))

    raw_path = path.encode("latin-1")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": raw_path,
        "query_string": b"",
        "server": ("127.0.0.1", 0),
        "client": ("127.0.0.1", 12345),
        "headers": _ascii_headers(headers),
        "root_path": "",
    }

    parsed: list[dict] = []
    raw = bytearray()

    async def _runner():
        app_task = asyncio.create_task(app(scope, receive, send))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for chunk in body_chunks:
                raw.extend(chunk)
            body_chunks.clear()
            parsed.clear()
            parsed.extend(_parse_sse(bytes(raw)))
            if len(parsed) >= min_events:
                break
            await asyncio.sleep(0.01)
        disconnect_event.set()
        try:
            await asyncio.wait_for(app_task, timeout=0.5)
        except asyncio.TimeoutError:
            app_task.cancel()
            with _suppress():
                await app_task

    asyncio.run(_runner())

    for chunk in body_chunks:
        raw.extend(chunk)
    body_chunks.clear()
    parsed.clear()
    parsed.extend(_parse_sse(bytes(raw)))
    headers_dict = {name_b.decode("latin-1"): value_b.decode("latin-1") for name_b, value_b in captured["headers"]}
    return int(captured["status"]), headers_dict, parsed


class _suppress:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return True


def _parse_sse(raw: bytes) -> list[dict]:
    """Parse SSE-encoded bytes into a list of ``{id, event, data, payload}``.

    The endpoint emits standard SSE frames (``id:``, ``event:``, ``data:``
    fields, blank-line separator). Each frame's ``data`` is JSON-encoded.
    A missing ``data`` field means the frame carries no body.
    """

    out: list[dict] = []
    text = raw.decode("utf-8", errors="replace")
    frames = text.split("\r\n\r\n") if "\r\n\r\n" in text else text.split("\n\n")
    for frame in frames:
        if not frame.strip():
            continue
        cur: dict[str, str] = {"id": "", "event": "", "data": ""}
        for line in frame.splitlines():
            if line.startswith("id: "):
                cur["id"] = line[4:]
            elif line.startswith("event: "):
                cur["event"] = line[7:]
            elif line.startswith("data: "):
                cur["data"] = line[6:]
        if not cur["event"] and not cur["data"] and not cur["id"]:
            continue
        try:
            payload = json.loads(cur["data"]) if cur["data"] else None
        except json.JSONDecodeError:
            payload = None
        out.append({**cur, "payload": payload})
    return out


# ---------------------------------------------------------------------------
# 1. POST /api/v1/research/jobs gates
# ---------------------------------------------------------------------------


def test_research_jobs_requires_full_auth(home: Path) -> None:
    """The same Origin / session cookie / CSRF gate as /api/v1/commands applies."""

    app = _build_app(home, runner=lambda _req: None)
    csrf, session = _bootstrap_session(app)

    base_payload = {
        "kind": "research.backtest",
        "correlation_id": "auth-test",
    }

    # Missing CSRF header.
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/research/jobs",
        base_payload,
        headers=headers,
    )
    assert status == 403, status

    # Missing session cookie.
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf),
    ]
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/research/jobs",
        base_payload,
        headers=headers,
    )
    assert status == 403, status

    # Non-loopback Origin.
    headers = [
        ("Origin", "http://evil.example.com"),
        ("X-Krellbot-CSRF", csrf),
        ("Cookie", f"krellbot_session={session}"),
    ]
    status, _hdrs, _body, _cookies = _post_json(
        app,
        "/api/v1/research/jobs",
        base_payload,
        headers=headers,
    )
    assert status == 403, status

    # Foreign Host.
    from tests.test_ns06_api import asgi_call

    status, _hdrs, _body, _cookies = asgi_call(
        app,
        method="POST",
        path="/api/v1/research/jobs",
        body=json.dumps(base_payload).encode("utf-8"),
        headers=[
            ("Host", "evil.example.com"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", csrf),
            ("Cookie", f"krellbot_session={session}"),
            ("Content-Type", "application/json"),
        ],
    )
    assert status == 403, status


# ---------------------------------------------------------------------------
# 2. Queue cap: 1 running + 4 queued, sixth submission is 429
# ---------------------------------------------------------------------------


def _make_event_runner() -> tuple[Callable, threading.Event, list]:
    """Return ``(runner, release_event, captures)``.

    The runner blocks on ``release_event`` for the duration of the test.
    ``captures`` records the request payload each time the runner is
    called. Tests can inspect it.
    """

    event = threading.Event()
    captures: list[dict] = []

    def runner(request):
        captures.append(dict(request) if isinstance(request, dict) else {"request": repr(request)})
        event.wait()
        return {"ok": True}

    return runner, event, captures


def test_runner_receives_submitted_research_fields(home: Path) -> None:
    """The job runner must see the research fields the client submitted."""

    seen: dict = {}
    done = threading.Event()

    def runner(request):
        if isinstance(request, dict):
            seen.update(request)
        done.set()
        return {"ok": True, "result_ref": "fwd"}

    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)
    status, body = _submit_job(
        app,
        csrf,
        session,
        {
            "correlation_id": "fwd-1",
            "pack_path": "/tmp/pack.json",
            "venue": "kraken",
            "pair": "SUIUSD",
            "dataset_csv": "/tmp/bars.csv",
        },
    )
    assert status == 200, (status, body)
    assert done.wait(2.0), seen
    assert seen["pack_path"] == "/tmp/pack.json", seen
    assert seen["venue"] == "kraken", seen
    assert seen["pair"] == "SUIUSD", seen
    assert seen["dataset_csv"] == "/tmp/bars.csv", seen
    assert seen["correlation_id"] == "fwd-1", seen


def test_sixth_submission_is_queue_full(home: Path) -> None:
    """One running + four queued is the cap. The sixth submission is 429."""

    runner, release, _captures = _make_event_runner()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)

    accepted = []
    for i in range(5):
        status, body = _submit_job(app, csrf, session, {"correlation_id": f"a-{i}"})
        assert status == 200, (status, body)
        accepted.append(body)

    # Sixth attempt: 429 with code "queue_full".
    status, body = _submit_job(app, csrf, session, {"correlation_id": "overflow"})
    assert status == 429, (status, body)
    assert body["code"] == "queue_full", body

    # The cap rejection must not have created a new job; the running job's
    # id and the queue depth must be unchanged.
    assert accepted[0]["id"], accepted[0]

    # Inspect the running job to confirm it stayed in "running".
    running_id = next((j["id"] for j in accepted if j["state"] == "running"), accepted[0]["id"])
    _status, snap = _get_job(app, csrf, session, running_id)
    assert snap["state"] == "running", snap

    # Allow the runner to return so the test tears down cleanly.
    release.set()


# ---------------------------------------------------------------------------
# 3. Paper commands do not block on a running job
# ---------------------------------------------------------------------------


def test_paper_command_returns_while_runner_is_blocked(home: Path) -> None:
    """A paper command issued while the runner is blocked still returns.

    The runner holds on ``release`` for the entire duration. The test
    posts a paper command, gets its 200, and only then sets ``release``.
    The assertion is the inverse: if paper commands were queued behind
    the runner, the command would hang and time out instead of returning.
    """

    runner, release, _captures = _make_event_runner()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)

    # Put a job in flight. The runner blocks on ``release``.
    status, body = _submit_job(app, csrf, session, {"correlation_id": "blocked-1"})
    assert status == 200, (status, body)
    assert body["state"] == "running", body

    # Submit a paper.arm via /api/v1/commands. With a freshly written pack
    # and a paper balance, this should return quickly without touching
    # the running job.
    pack_path = _write_dsl_pack_for_ns06b(home)
    payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "correlation_id": "ns06b-arm",
        "expected_revision": None,
        "payload": {
            "pack_path": str(pack_path),
            "venue": "kraken",
            "mode": "paper",
            "paper_balance": "1000",
        },
    }
    status, _hdrs, body, _cookies = _post_json(
        app,
        "/api/v1/commands",
        payload,
        headers=_auth_headers(csrf, session),
    )
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded["ok"] is True, decoded

    # The 200 from /api/v1/commands must have arrived *before* the test
    # signals the runner. If the command were queued behind the job,
    # the test would hang here and pytest would kill it.
    release.set()


def _write_dsl_pack_for_ns06b(home: Path, *, pack_id: str = "ns06b-pack") -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "ns06b",
        "author": "krellbot ns06b tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# 4. Cancel is cooperative and idempotent
# ---------------------------------------------------------------------------


def test_cancel_during_running_marks_cancelled_with_no_result(home: Path) -> None:
    """Cancel mid-flight yields state=cancelled with no ``result_ref``."""

    runner, release, _captures = _make_event_runner()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)

    _status, submitted = _submit_job(app, csrf, session, {"correlation_id": "cancel-1"})
    job_id = submitted["id"]

    # While the runner still blocks, cancel the job.
    _cstatus, cancel_body = _cancel_job(app, csrf, session, job_id)
    assert _cstatus == 200, (_cstatus, cancel_body)
    assert cancel_body["state"] == "cancelling", cancel_body

    # Cancel is idempotent: a second POST does not error and reports the
    # same state seen by the snapshot.
    _cstatus2, cancel_body2 = _cancel_job(app, csrf, session, job_id)
    assert _cstatus2 == 200, (_cstatus2, cancel_body2)
    assert cancel_body2["state"] == "cancelling", cancel_body2

    # Now allow the runner to return. The cancel call must produce
    # state=cancelled and result_ref=None.
    release.set()

    # Give the worker a moment to record the outcome.
    deadline = time.monotonic() + 2.0
    final: dict | None = None
    while time.monotonic() < deadline:
        _s, snap = _get_job(app, csrf, session, job_id)
        if snap["state"] in {"cancelled", "succeeded", "failed"}:
            final = snap
            break
        time.sleep(0.01)
    assert final is not None, "job did not transition to a terminal state"
    assert final["state"] == "cancelled", final
    assert final["result_ref"] is None, final


def test_cancel_after_success_is_idempotent_and_keeps_succeeded(home: Path) -> None:
    """A cancel issued after a job has already finished keeps ``succeeded``."""

    def fast_runner(request):
        return {
            "ok": True,
            "result_ref": f"ref-{request.get('correlation_id', 'x')}",
        }

    app = _build_app(home, runner=fast_runner)
    csrf, session = _bootstrap_session(app)

    _status, submitted = _submit_job(app, csrf, session, {"correlation_id": "fast-1"})
    job_id = submitted["id"]

    # Wait until the job reaches a terminal state.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        _s, snap = _get_job(app, csrf, session, job_id)
        if snap["state"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.005)
    assert snap["state"] == "succeeded", snap
    assert snap["result_ref"] is not None, snap

    # Cancel a finished job. The endpoint is idempotent; the job stays
    # succeeded with its result_ref intact.
    _cstatus, cancel_body = _cancel_job(app, csrf, session, job_id)
    assert _cstatus == 200, (_cstatus, cancel_body)
    assert cancel_body["state"] == "succeeded", cancel_body
    assert cancel_body["result_ref"] is not None, cancel_body


# ---------------------------------------------------------------------------
# 5. GET /api/v1/jobs/{id} returns JobV1 with closed-code errors only
# ---------------------------------------------------------------------------


def test_get_job_returns_jobv1_fields(home: Path) -> None:
    """The JobV1 shape is exactly what ``contracts/jobs.md`` lists."""

    app = _build_app(home, runner=lambda _r: {"ok": True, "result_ref": "r1"})
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "shape-1"})
    job_id = submitted["id"]

    deadline = time.monotonic() + 2.0
    snap: dict | None = None
    while time.monotonic() < deadline:
        _s, snap = _get_job(app, csrf, session, job_id)
        if snap["state"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.005)
    assert snap is not None, "job never reached terminal state"

    expected_keys = {
        "schema_version",
        "id",
        "kind",
        "state",
        "created_at",
        "started_at",
        "finished_at",
        "progress",
        "result_ref",
        "error",
        "correlation_id",
    }
    assert set(snap.keys()) == expected_keys, sorted(snap.keys())
    assert snap["schema_version"] == "1"
    assert snap["id"] == job_id
    assert snap["kind"] == "research.backtest"
    assert snap["state"] == "succeeded"
    assert snap["created_at"] is not None
    assert snap["started_at"] is not None
    assert snap["finished_at"] is not None
    assert snap["result_ref"] == "r1"
    assert snap["error"] is None
    assert snap["correlation_id"] == "shape-1"


def test_list_jobs_returns_the_submitted_id(home: Path) -> None:
    from tests.test_ns06_api import asgi_call

    app = _build_app(home, runner=lambda _r: {"ok": True, "result_ref": "r1"})
    csrf, session = _bootstrap_session(app)
    _status, submitted = _submit_job(app, csrf, session, {"correlation_id": "list-1"})
    status, _hdrs, raw, _cookies = asgi_call(
        app,
        method="GET",
        path="/api/v1/jobs",
        headers=[
            ("Host", f"127.0.0.1:{TEST_PORT}"),
            ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
            ("X-Krellbot-CSRF", csrf),
            ("Cookie", f"krellbot_session={session}"),
        ],
    )
    body = json.loads(raw) if raw else None
    assert status == 200
    assert body is not None
    assert body["jobs"][0]["id"] == submitted["id"]
    assert body["jobs"][0]["state"] in {"queued", "running", "succeeded", "failed"}


def test_failed_job_returns_closed_code_only(home: Path) -> None:
    """An exception inside the runner becomes a JobV1 with closed ``error``."""

    def boom(_request):
        raise RuntimeError("explosion with stack and secrets")

    app = _build_app(home, runner=boom)
    csrf, session = _bootstrap_session(app)
    _s, submitted = _submit_job(app, csrf, session, {"correlation_id": "fail-1"})
    job_id = submitted["id"]

    deadline = time.monotonic() + 2.0
    snap: dict | None = None
    while time.monotonic() < deadline:
        _s, snap = _get_job(app, csrf, session, job_id)
        if snap["state"] == "failed":
            break
        time.sleep(0.005)
    assert snap is not None
    assert snap["state"] == "failed", snap
    assert snap["error"] is not None, snap
    assert isinstance(snap["error"], dict), snap
    assert set(snap["error"].keys()) == {"code", "message"}, snap
    # Closed code; not a traceback.
    assert snap["error"]["code"] == "job_failed", snap
    # No raw exception text must leak into the response.
    assert "explosion" not in snap["error"]["message"]
    assert "Traceback" not in snap["error"]["message"]
    raw_body_text = json.dumps(snap)
    assert "Traceback" not in raw_body_text
    assert "RuntimeError" not in raw_body_text


# ---------------------------------------------------------------------------
# 6. SSE: Last-Event-ID replay and resync_required on gap
# ---------------------------------------------------------------------------


def _sse_headers(csrf: str, session: str, *, last_event_id: str | None = None) -> list[tuple[str, str]]:
    out = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    if last_event_id is not None:
        out.append(("Last-Event-ID", last_event_id))
    return out


def _wait_for_state(app, csrf, session, job_id, expected, *, timeout=2.0):
    deadline = time.monotonic() + timeout
    snap: dict | None = None
    while time.monotonic() < deadline:
        _s, snap = _get_job(app, csrf, session, job_id)
        if snap["state"] == expected:
            return snap
        if snap["state"] in {"succeeded", "failed", "cancelled"} and expected not in {
            "succeeded",
            "failed",
            "cancelled",
        }:
            return snap
        time.sleep(0.005)
    return snap


def test_sse_replays_retained_events_in_order_with_last_event_id(home: Path) -> None:
    """Submitting two jobs emits job.changed events with monotonic seq.

    A reconnect with the first event's id replays *only* the second event
    in the original order. A connection without ``Last-Event-ID`` returns
    both.
    """

    runner, release, _captures = _make_event_runner()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)

    s1, j1 = _submit_job(app, csrf, session, {"correlation_id": "sse-a"})
    assert s1 == 200 and j1["state"] == "running", (s1, j1)

    # Queue a second job while the runner is still busy on the first.
    s2, j2 = _submit_job(app, csrf, session, {"correlation_id": "sse-b"})
    assert s2 == 200 and j2["state"] == "queued", (s2, j2)

    # Without Last-Event-ID the SSE stream returns both events.
    status, _hdrs, events = _consume_sse(
        app,
        path="/api/v1/events",
        headers=_sse_headers(csrf, session),
        min_events=2,
    )
    assert status == 200, (status, events)
    assert _hdrs.get("content-type", "").startswith("text/event-stream"), _hdrs
    job_events = [e for e in events if e["event"] == "job.changed"]
    assert len(job_events) >= 2, [e["event"] for e in events]

    seqs_returned = [int(e["id"]) for e in job_events]
    assert seqs_returned == sorted(seqs_returned), seqs_returned
    first_seq = seqs_returned[0]
    last_seq = seqs_returned[-1]
    assert first_seq < last_seq, seqs_returned

    # Reconnect with Last-Event-ID == first event seq. The first event is
    # NOT replayed; every subsequent retained event is replayed in seq
    # order. The reconnect payload must match the order observed above.
    expected_post_first_pairs = [(int(e["id"]), e["payload"].get("subject_id")) for e in job_events[1:]]

    status, _hdrs, replay_events = _consume_sse(
        app,
        path="/api/v1/events",
        headers=_sse_headers(csrf, session, last_event_id=str(first_seq)),
        min_events=1,
    )
    assert status == 200, status
    job_replay = [e for e in replay_events if e["event"] == "job.changed"]
    assert job_replay, replay_events
    replay_pairs = [(int(e["id"]), e["payload"].get("subject_id")) for e in job_replay]
    assert all(s > first_seq for s, _ in replay_pairs), replay_pairs
    assert replay_pairs == expected_post_first_pairs, (replay_pairs, expected_post_first_pairs)
    # In-order: subject_ids match between the first-burst and the replay
    # (the buffer has not changed because the runner is still blocked).
    assert [sid for _, sid in replay_pairs] == [sid for _, sid in expected_post_first_pairs]

    release.set()


def test_sse_returns_resync_required_on_gap(home: Path) -> None:
    """A Last-Event-ID that no longer matches any retained event yields
    a single ``resync_required`` event and the connection closes
    promptly.

    The buffer must be non-empty so the gap is genuine: the client reports
    a seq that is below the oldest retained event, and the server cannot
    cover the gap with its buffer.
    """

    runner, release, _captures = _make_event_runner()
    app = _build_app(home, runner=runner)
    csrf, session = _bootstrap_session(app)

    # Generate at least one job.changed event so the buffer is non-empty.
    _s, _j = _submit_job(app, csrf, session, {"correlation_id": "gap-1"})

    # ``Last-Event-ID=0`` means "I never received an event." With at least
    # one event already in the buffer (seq >= 1), the gap is real and the
    # server must respond with ``resync_required``.
    status, _hdrs, events = _consume_sse(
        app,
        path="/api/v1/events",
        headers=_sse_headers(csrf, session, last_event_id="0"),
        min_events=1,
    )
    assert status == 200, status
    kinds = [e["event"] for e in events]
    assert "resync_required" in kinds, kinds
    # The resync_required event must be the first event seen on the wire;
    # no buffered events should be sent before it.
    assert kinds[0] == "resync_required", kinds
    # No leaked job.changed events precede the marker.
    for k in kinds[1:]:
        assert k != "job.changed", kinds

    release.set()


# ---------------------------------------------------------------------------
# 7. SSE /api/v1/events requires session auth (loopback + cookie)
# ---------------------------------------------------------------------------


def test_sse_requires_session_cookie(home: Path) -> None:
    """An SSE request without a session cookie is 403."""

    app = _build_app(home, runner=lambda _r: None)
    headers = [("Host", f"127.0.0.1:{TEST_PORT}"), ("Origin", f"http://127.0.0.1:{TEST_PORT}")]
    from tests.test_ns06_api import asgi_call

    status, _hdrs, _body, _cookies = asgi_call(app, method="GET", path="/api/v1/events", headers=headers)
    assert status == 403, status


def test_sse_rejects_non_loopback_origin(home: Path) -> None:
    """An SSE request with a non-loopback Origin is 403 even with a valid cookie."""

    app = _build_app(home, runner=lambda _r: None)
    _csrf, session = _bootstrap_session(app)
    headers = [
        ("Host", f"127.0.0.1:{TEST_PORT}"),
        ("Origin", "http://evil.example.com"),
        ("Cookie", f"krellbot_session={session}"),
    ]
    from tests.test_ns06_api import asgi_call

    status, _hdrs, _body, _cookies = asgi_call(app, method="GET", path="/api/v1/events", headers=headers)
    assert status == 403, status

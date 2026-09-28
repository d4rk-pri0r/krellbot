"""Loopback HTTP API factory and routes."""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from krellbot.api.jobs import (
    JOB_ERROR_NOT_FOUND,
    JOB_KIND_RESEARCH_BACKTEST,
    JobManager,
    QueueFull,
)
from krellbot.api.security import (
    generate_csrf_token,
    generate_session_token,
    is_loopback_host,
    is_loopback_origin,
)

SCHEMA_VERSION = "1"
SESSION_COOKIE = "krellbot_session"
CSRF_HEADER = "X-Krellbot-CSRF"

PAPER_COMMANDS = (
    "paper.arm",
    "paper.disarm",
    "paper.pause_entries",
    "paper.resume_entries",
    "paper.raise_stop",
)


@dataclass
class _AppState:
    home: Path
    port: int
    bootstrap_token: str
    bootstrap_used: bool = False
    sessions: dict[str, str] = field(default_factory=dict)
    jobs: JobManager = field(default=None)  # type: ignore[assignment]


def _state(app: FastAPI) -> _AppState:
    return app.state.krellbot


def _gate_state_change(request: Request, s: _AppState) -> Response | None:
    """Apply the session-cookie + CSRF + loopback-origin gate for state changes."""

    origin = request.headers.get("origin", "")
    if not is_loopback_origin(origin, port=s.port):
        return JSONResponse({"detail": "origin not loopback"}, status_code=403)

    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return JSONResponse({"detail": "session required"}, status_code=403)
    expected_csrf = s.sessions.get(session_id)
    presented_csrf = request.headers.get(CSRF_HEADER, "")
    if not expected_csrf or not hmac.compare_digest(expected_csrf, presented_csrf):
        return JSONResponse({"detail": "csrf required"}, status_code=403)

    return None


def _gate_get(request: Request, s: _AppState) -> Response | None:
    """Apply the session-cookie + loopback-origin gate for read endpoints."""

    origin = request.headers.get("origin", "")
    if not is_loopback_origin(origin, port=s.port):
        return JSONResponse({"detail": "origin not loopback"}, status_code=403)
    session_id = request.cookies.get(SESSION_COOKIE)
    if not session_id:
        return JSONResponse({"detail": "session required"}, status_code=403)
    return None


def _format_sse(event_id: str, event_name: str, data_payload: dict) -> bytes:
    """Render a single SSE frame. JSON-encode the payload as ``data:``."""

    data = json.dumps(data_payload, sort_keys=True, separators=(",", ":"))
    lines = [
        f"id: {event_id}",
        f"event: {event_name}",
        f"data: {data}",
        "",
        "",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _format_resync_marker(last_event_id: str) -> bytes:
    """Render a ``resync_required`` SSE marker with no body."""

    lines = ["event: resync_required", f"id: {last_event_id}", "data: ", "", ""]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def create_app(
    home: Path,
    *,
    port: int,
    bootstrap_token: str,
    runner: Callable | None = None,
) -> FastAPI:
    state = _AppState(
        home=Path(home),
        port=port,
        bootstrap_token=bootstrap_token,
        jobs=JobManager(home=Path(home), runner=runner),
    )

    app = FastAPI(
        title="krellbot.api",
        version=SCHEMA_VERSION,
    )
    app.state.krellbot = state

    @app.middleware("http")
    async def _enforce_loopback_host(request: Request, call_next):
        host = request.headers.get("host", "")
        if not is_loopback_host(host, port=port):
            return JSONResponse({"detail": "loopback only"}, status_code=403)
        return await call_next(request)

    @app.post("/api/v1/session/bootstrap")
    async def bootstrap(request: Request) -> Response:
        s = _state(request.app)
        origin = request.headers.get("origin", "")
        if not is_loopback_origin(origin, port=s.port):
            return JSONResponse({"detail": "origin not loopback"}, status_code=403)

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        submitted = payload.get("token", "")
        if not isinstance(submitted, str) or not hmac.compare_digest(submitted, s.bootstrap_token):
            return JSONResponse({"detail": "wrong token"}, status_code=403)
        if s.bootstrap_used:
            return JSONResponse({"detail": "token already redeemed"}, status_code=403)
        s.bootstrap_used = True

        session_id = generate_session_token()
        csrf_token = generate_csrf_token()
        s.sessions[session_id] = csrf_token

        body = {"schema_version": SCHEMA_VERSION, "csrf_token": csrf_token}
        response = JSONResponse(body, status_code=200)
        response.set_cookie(
            key=SESSION_COOKIE,
            value=session_id,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    @app.post("/api/v1/commands")
    async def commands(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        command = payload.get("command", "")
        inner = payload.get("payload") or {}
        if not isinstance(command, str) or not isinstance(inner, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        correlation_id = payload.get("correlation_id") or ""

        if command.startswith("live."):
            return JSONResponse({"detail": "live orders are disabled"}, status_code=403)
        if inner.get("mode") == "live":
            return JSONResponse({"detail": "live orders are disabled"}, status_code=403)
        if command not in PAPER_COMMANDS:
            return JSONResponse({"detail": f"unknown command {command}"}, status_code=403)

        from krellbot.application.paper import PaperService

        service = PaperService(home=s.home)

        if command == "paper.arm":
            result = service.arm(
                Path(inner["pack_path"]),
                venue=inner["venue"],
                mode=inner.get("mode", "paper"),
                paper_balance=Decimal(inner["paper_balance"]),
                correlation_id=correlation_id,
            )
        elif command == "paper.disarm":
            result = service.disarm(
                venue=inner["venue"],
                pair=inner["pair"],
                correlation_id=correlation_id,
            )
        elif command == "paper.pause_entries":
            result = service.pause_entries(
                venue=inner["venue"],
                pair=inner["pair"],
                correlation_id=correlation_id,
            )
        elif command == "paper.resume_entries":
            result = service.resume_entries(
                venue=inner["venue"],
                pair=inner["pair"],
                correlation_id=correlation_id,
            )
        elif command == "paper.raise_stop":
            result = service.raise_stop(
                venue=inner["venue"],
                pair=inner["pair"],
                new_stop=Decimal(inner["new_stop"]),
                correlation_id=correlation_id,
            )
        else:
            return JSONResponse({"detail": f"unknown command {command}"}, status_code=403)

        return JSONResponse(result.to_dict(), status_code=200)

    @app.post("/api/v1/research/jobs")
    async def research_jobs(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse({"detail": "invalid body"}, status_code=400)

        kind = payload.get("kind", JOB_KIND_RESEARCH_BACKTEST)
        if not isinstance(kind, str):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        correlation_id = payload.get("correlation_id")
        if not isinstance(correlation_id, str):
            correlation_id = ""

        try:
            job = s.jobs.submit(kind=kind, correlation_id=correlation_id, request=payload)
        except QueueFull as qf:
            return JSONResponse(
                {"code": qf.code, "message": qf.message, "schema_version": SCHEMA_VERSION},
                status_code=429,
            )

        return JSONResponse(job.to_dict(), status_code=200)

    @app.get("/api/v1/jobs/{job_id}")
    async def get_job(request: Request, job_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        snap = s.jobs.get(job_id)
        if snap is None:
            return JSONResponse(
                {"code": JOB_ERROR_NOT_FOUND, "message": "job not found"},
                status_code=404,
            )
        return JSONResponse(snap.to_dict(), status_code=200)

    @app.post("/api/v1/jobs/{job_id}/cancel")
    async def cancel_job(request: Request, job_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            pass

        snap = s.jobs.cancel(job_id)
        if snap is None:
            return JSONResponse(
                {"code": JOB_ERROR_NOT_FOUND, "message": "job not found"},
                status_code=404,
            )
        return JSONResponse(snap.to_dict(), status_code=200)

    @app.get("/api/v1/events")
    async def events(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_get(request, s)
        if denied is not None:
            return denied

        buffer = s.jobs.event_buffer()
        last_event_id_raw = request.headers.get("Last-Event-ID") or None
        last_event_id: int | None
        if last_event_id_raw is None:
            last_event_id = None
        else:
            try:
                last_event_id = int(last_event_id_raw)
            except (TypeError, ValueError):
                return JSONResponse({"detail": "bad last event id"}, status_code=400)

        gap = last_event_id is not None and buffer.is_gap(last_event_id)
        to_replay = [] if gap else buffer.replay(last_event_id)

        async def _emit():
            if gap:
                yield _format_resync_marker(str(last_event_id))
                return
            for event in to_replay:
                yield _format_sse(
                    event_id=event.event_id,
                    event_name=event.kind,
                    data_payload=event.to_dict(),
                )

        headers = {"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        return StreamingResponse(_emit(), media_type="text/event-stream", headers=headers)

    @app.get("/api/v1/capabilities")
    async def capabilities() -> Response:
        body = {
            "schema_version": SCHEMA_VERSION,
            "paper_commands": list(PAPER_COMMANDS),
            "research": True,
            "live_orders": False,
        }
        return JSONResponse(body, status_code=200)

    return app

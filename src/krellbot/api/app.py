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
    JOB_ERROR_RESULT_UNAVAILABLE,
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
from krellbot.application.strategy import (
    DraftNotRunnable,
    RevisionNotFound,
    StrategyDraftService,
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
    draft_service: object = field(default=None)  # StrategyDraftService singleton per home
    paper_service: object = field(default=None)  # PaperService singleton per home


def _state(app: FastAPI) -> _AppState:
    return app.state.krellbot


def _draft_service(s: _AppState) -> StrategyDraftService:
    """Lazily build the strategy-draft service bound to the app's home."""

    if s.draft_service is None:
        s.draft_service = StrategyDraftService(home=s.home)
    return s.draft_service


def _paper_service(s: _AppState):
    """Lazily build the paper service bound to the app's home."""

    if s.paper_service is None:
        from krellbot.application.paper import PaperService

        s.paper_service = PaperService(home=s.home)
    return s.paper_service


def _resolve_dist_dir(dist_dir: Path | None) -> Path:
    """Resolve the frontend ``dist`` directory.

    The default walks up from this file to the repo root and points at
    ``<repo>/frontend/dist``. Tests may inject a throwaway directory.
    """

    if dist_dir is not None:
        return Path(dist_dir)
    repo_root = Path(__file__).resolve().parent.parent.parent.parent
    return repo_root / "frontend" / "dist"


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
    dist_dir: Path | None = None,
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

    from krellbot.api import static as _static

    _static.register(app, _resolve_dist_dir(dist_dir))

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

        service = _paper_service(s)

        if command == "paper.arm":
            # ``paper.arm`` may be addressed by ``pack_path`` (legacy) or
            # by ``revision_id`` for a draft (NS08a). Draft addressing
            # resolves the on-disk draft bytes without rewriting the
            # file. A non-runnable draft is refused before any config
            # byte changes.
            pack_path = inner.get("pack_path")
            revision_id = inner.get("revision_id")
            if not pack_path and not revision_id:
                return JSONResponse({"detail": "invalid body"}, status_code=400)
            if revision_id:
                try:
                    draft = _draft_service(s)
                    pack_path, _pack = draft.pack_for_arm(revision_id)
                except RevisionNotFound:
                    return JSONResponse(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "code": "draft_not_found",
                            "ok": False,
                            "message": f"draft {revision_id} not found",
                            "effect": "refused",
                            "revision_before": None,
                            "revision_after": None,
                        },
                        status_code=404,
                    )
                except DraftNotRunnable as exc:
                    return JSONResponse(
                        {
                            "schema_version": SCHEMA_VERSION,
                            "code": "draft_not_runnable",
                            "ok": False,
                            "message": str(exc),
                            "effect": "refused",
                            "revision_before": None,
                            "revision_after": None,
                        },
                        status_code=403,
                    )
            result = service.arm(
                Path(pack_path),
                venue=inner["venue"],
                mode=inner.get("mode", "paper"),
                paper_balance=Decimal(inner["paper_balance"]),
                correlation_id=correlation_id,
            )
            if revision_id and result.ok:
                try:
                    _draft_service(s).mark_deployed(revision_id)
                except (RevisionNotFound, DraftNotRunnable):
                    pass
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

    @app.get("/api/v1/jobs/{job_id}/result")
    async def get_job_result(request: Request, job_id: str) -> Response:
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
        result = s.jobs.result_for(job_id)
        if result is None:
            # The job is known and not succeeded: running, cancelling,
            # cancelled, queued, or failed. Per the contract the result
            # route is unavailable in those states.
            return JSONResponse(
                {"code": JOB_ERROR_RESULT_UNAVAILABLE},
                status_code=404,
            )
        return JSONResponse(result, status_code=200)

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

    # ---- strategy drafts (NS08a) --------------------------------------

    def _resolve_pack_field(payload: dict) -> tuple[dict | None, Response | None]:
        """Return ``(pack, None)`` or ``(None, bad_request)``."""

        if not isinstance(payload, dict):
            return None, JSONResponse({"detail": "invalid body"}, status_code=400)
        raw = payload.get("pack")
        if not isinstance(raw, dict):
            return None, JSONResponse({"detail": "invalid body"}, status_code=400)
        return raw, None

    @app.post("/api/v1/strategies/drafts")
    async def create_draft(request: Request) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        pack, err = _resolve_pack_field(payload)
        if err is not None:
            return err

        try:
            summary = _draft_service(s).create(pack)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse(summary, status_code=200)

    @app.put("/api/v1/strategies/drafts/{revision_id}")
    async def edit_draft(request: Request, revision_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        try:
            payload = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return JSONResponse({"detail": "invalid body"}, status_code=400)
        pack, err = _resolve_pack_field(payload)
        if err is not None:
            return err

        try:
            summary = _draft_service(s).edit(revision_id, pack)
        except RevisionNotFound:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "draft_not_found",
                    "message": f"draft {revision_id} not found",
                },
                status_code=404,
            )
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return JSONResponse(summary, status_code=200)

    @app.post("/api/v1/strategies/drafts/{revision_id}/validate")
    async def validate_draft(request: Request, revision_id: str) -> Response:
        s = _state(request.app)
        denied = _gate_state_change(request, s)
        if denied is not None:
            return denied

        # Body is optional. Eat it so a trailing JSON parse error does
        # not 400 a valid request.
        try:
            await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            pass

        try:
            summary = _draft_service(s).validate(revision_id)
        except RevisionNotFound:
            return JSONResponse(
                {
                    "schema_version": SCHEMA_VERSION,
                    "code": "draft_not_found",
                    "message": f"draft {revision_id} not found",
                },
                status_code=404,
            )
        return JSONResponse(summary, status_code=200)

    return app

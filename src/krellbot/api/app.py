"""Loopback HTTP API factory and routes."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

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


def _state(app: FastAPI) -> _AppState:
    return app.state.krellbot


def create_app(home: Path, *, port: int, bootstrap_token: str) -> FastAPI:
    state = _AppState(home=Path(home), port=port, bootstrap_token=bootstrap_token)

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

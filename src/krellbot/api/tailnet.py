"""Opt-in login behind Tailscale Serve, never a public listener.

Serve authenticates the peer and replaces inbound Tailscale-User-Login headers.
Only the explicitly configured owner and HTTPS origin are admitted here. The
backend must remain loopback-only; local processes are already trusted by the
ordinary workstation's bootstrap model.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from krellbot.api.security import generate_csrf_token, generate_session_token


@dataclass(frozen=True)
class TailnetAccess:
    origin: str
    user: str

    @classmethod
    def from_options(cls, origin: str | None, user: str | None) -> TailnetAccess | None:
        if origin is None and user is None:
            return None
        if not origin or not user:
            raise ValueError("--tailscale-origin and --tailscale-user must be supplied together")
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not (parsed.hostname or "").endswith(".ts.net")
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("--tailscale-origin must be an HTTPS .ts.net origin with no path")
        # Validate any explicit port before the listener is created.
        _ = parsed.port
        return cls(origin, user)

    def install(self, app: FastAPI, sessions: dict[str, str], *, port: int, dist_dir: Path) -> None:
        expected_host = urlsplit(self.origin).netloc
        no_store = {"Cache-Control": "no-store"}

        @app.middleware("http")
        async def tailscale_login(request: Request, call_next):
            # Uvicorn proxy_headers is disabled: client is the actual TCP peer,
            # not an untrusted X-Forwarded-For value.
            if (
                request.client is None
                or request.client.host not in {"127.0.0.1", "::1"}
                or request.headers.get("host") != expected_host
                or request.headers.get("tailscale-user-login") != self.user
            ):
                return JSONResponse({"detail": "Tailscale owner login required"}, status_code=403, headers=no_store)
            origin = request.headers.get("origin")
            if origin is not None and origin != self.origin:
                return JSONResponse({"detail": "origin not allowed"}, status_code=403, headers=no_store)
            path = request.url.path
            if path == "/login":
                if request.method == "GET":
                    styles = "".join(
                        f'<link rel="stylesheet" href="/assets/{html.escape(css.name, quote=True)}">'
                        for css in sorted((dist_dir / "assets").glob("*.css"))
                    )
                    return HTMLResponse(
                        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width, initial-scale=1">'
                        f"<title>Log in · Krellbot</title>{styles}</head>"
                        '<body style="background:var(--navy,#0E1C29);color:var(--text,#E9F0F5);'
                        'font-family:Manrope,system-ui,sans-serif">'
                        '<main style="max-width:32rem;margin:12vh auto;padding:2rem;'
                        'background:var(--surface,#14222E);border-radius:12px">'
                        "<h1>Krellbot</h1><p>Your private paper workstation.</p>"
                        "<p>Use the owner account already signed in on this device in Tailscale. "
                        "No separate Krellbot password or exchange key is needed.</p>"
                        '<form method="post" action="/login"><button type="submit" '
                        'style="min-height:44px;padding:0.75rem 1rem;background:var(--sage,#B3DDA8);'
                        'color:var(--navy,#0E1C29);border-radius:7px;font:inherit">'
                        "Log in with Tailscale</button></form></main></body></html>",
                        headers={
                            **no_store,
                            "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                            "frame-ancestors 'none'; form-action 'self'; base-uri 'none'",
                        },
                    )
                if request.method != "POST" or origin != self.origin:
                    return JSONResponse({"detail": "same-origin login required"}, status_code=403, headers=no_store)
                session_id = generate_session_token()
                sessions[session_id] = generate_csrf_token()
                response = RedirectResponse("/", status_code=303, headers=no_store)
                response.set_cookie(
                    "krellbot_session", session_id, httponly=True, secure=True, samesite="strict", path="/"
                )
                return response
            if path == "/api/v1/session/bootstrap":
                return JSONResponse({"detail": "use Tailscale login"}, status_code=403, headers=no_store)
            if request.cookies.get("krellbot_session") not in sessions and not path.startswith("/assets/"):
                if path.startswith("/api/") or request.method != "GET":
                    return JSONResponse({"detail": "session required"}, status_code=401, headers=no_store)
                return RedirectResponse("/login", status_code=303, headers=no_store)
            # Normalize only AFTER peer, identity, Host and Origin validation.
            # The existing session/CSRF/live gates remain unchanged downstream.
            request.scope["headers"] = [
                (key, f"127.0.0.1:{port}".encode())
                if key == b"host"
                else (key, f"http://127.0.0.1:{port}".encode())
                if key == b"origin"
                else (key, value)
                for key, value in request.scope["headers"]
            ]
            return await call_next(request)

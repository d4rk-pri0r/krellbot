"""Open the loopback dashboard URL in the user's browser.

This is the only place the gate token is touched by name outside the
server itself. The helper takes an injected opener so tests can verify
which URL is handed off without launching a real browser. The token
never lands on disk and is not put in an env var.
"""

from __future__ import annotations

from typing import Callable

from krellbot.ui.server import DashboardServer


def token_url(server: DashboardServer) -> str:
    """Build the gated loopback URL for a started `server`.

    Pure helper — no I/O, no side effects. Shared by the `--open`
    launcher path and the plain-print path so the URL format lives in
    exactly one place.
    """
    return f"http://127.0.0.1:{server.bound_port}/{server.token}/"


def open_url(server: DashboardServer, opener: Callable[[str], bool]) -> str:
    """Build the gated URL for `server` and hand it to `opener`.

    The opener is expected to follow the `webbrowser.open` contract
    (return True when it launched something, False otherwise). Network
    and child-process failures (no DISPLAY, missing executable) bubble up
    as OSError; we swallow them so the URL is always returned for the
    caller to print.

    The token is part of the URL the opener receives, but no other side
    channel persists it.
    """
    url = token_url(server)
    try:
        opener(url)
    except (OSError, RuntimeError):
        pass
    return url

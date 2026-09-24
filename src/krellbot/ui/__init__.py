"""Dashboard UI server.

The server binds to 127.0.0.1 only, on a random (or user-chosen) port, with
a 32-byte hex token gating access. It serves a small static dashboard and
exposes a few form-driven actions that mirror `arm` / `disarm` / `stop` /
`adopt` from the CLI. There is no call to a live venue.

Public surface:

    DashboardServer(home, port=0) -> .start() / .stop()
        .token        the gate token (also the session cookie value)
        .csrf         the CSRF token (also the krellbot_csrf cookie value)
        .bound_host   always "127.0.0.1"
        .bound_port   the port the OS picked (0 before start())
"""

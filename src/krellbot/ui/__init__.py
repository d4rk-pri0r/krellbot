"""Dashboard UI server.

The server binds to 127.0.0.1 only, on a random (or user-chosen) port, with
a 32-byte hex token gating access. It serves a small static dashboard and
exposes a few form-driven actions that mirror `arm` / `disarm` / `stop` /
`adopt` from the CLI. The Exchange form posts to this loopback server; its
handler sends an authenticated HTTPS permission request to the selected
Kraken or Coinbase venue before storing a trade-only key in the OS keychain.
The dashboard does not send exchange credentials to krellbot.dev. Other
dashboard GETs do not probe the venue or read the key for status.

Public surface:

    DashboardServer(home, port=0) -> .start() / .stop()
        .token        the gate token (also the session cookie value)
        .csrf         the CSRF token (also the krellbot_csrf cookie value)
        .bound_host   always "127.0.0.1"
        .bound_port   the port the OS picked (0 before start())
"""

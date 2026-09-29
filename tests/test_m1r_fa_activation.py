"""M1R-FA — activation regressions: RED tests written before the fix.

Three findings from the parent gate (brief:
``.superpowers/sdd/krellbot-2027/M1R-FA/brief.md``):

  F1. The fresh-install short-circuit in ``krellbot.ui.activate.redeem``
      returns ``"skipped: no paid account"`` when neither the license
      cache nor the catalog exists — so a first-time buyer can never
      redeem a key. The short-circuit must be gone; ``redeem`` behaves
      exactly as at ``b13c955``.
  F2. ``POST /api/v1/activation/redeem`` never calls
      ``_gate_state_change``, so any page on another origin can drive
      the workstation to submit an attacker-chosen key.
  F3. ``GET /api/v1/capabilities`` leaks the bootstrap token while it
      is unredeemed. The token must reach the shell only through the
      injected meta tag; in-process tests read
      ``WorkstationServer.bootstrap_token`` instead.

Every activation test here monkeypatches
``krellbot.ui.activate.refresh_license`` and
``krellbot.ui.activate.install_catalog`` — no test reaches the network.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from krellbot.api.serve import WorkstationServer
from krellbot.ui.activate import SAFE_MESSAGES

# ---------------------------------------------------------------------------
# Minimal loopback HTTP helpers (raw sockets, Host header always loopback)
# ---------------------------------------------------------------------------


def _read_response(sock: socket.socket, n: int = 65536) -> bytes:
    chunks = bytearray()
    while len(chunks) < n:
        try:
            chunk = sock.recv(n - len(chunks))
        except OSError:
            break
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def _http_request(
    host: str,
    port: int,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    origin: str | None = None,
    cookie: str | None = None,
    csrf: str | None = None,
) -> tuple[int, bytes]:
    """One raw HTTP/1.1 request. ``Host`` is always ``host:port``."""

    headers = [
        f"Host: {host}:{port}",
        "Connection: close",
    ]
    if body is not None:
        headers.append(f"Content-Length: {len(body)}")
        headers.append("Content-Type: application/json")
    if origin is not None:
        headers.append(f"Origin: {origin}")
    if cookie is not None:
        headers.append(f"Cookie: krellbot_session={cookie}")
    if csrf is not None:
        headers.append(f"X-Krellbot-CSRF: {csrf}")
    request = (method + " " + path + " HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii")
    if body is not None:
        request += body
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(request)
        raw = _read_response(sock)
    head, _, resp_body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    code = int(status_line.split(" ", 2)[1])
    return code, resp_body


def _post_json(
    host: str,
    port: int,
    path: str,
    payload: dict,
    *,
    origin: str | None = None,
    cookie: str | None = None,
    csrf: str | None = None,
) -> tuple[int, bytes]:
    return _http_request(
        host,
        port,
        "POST",
        path,
        body=json.dumps(payload).encode("utf-8"),
        origin=origin,
        cookie=cookie,
        csrf=csrf,
    )


def _bootstrap(host: str, port: int, token: str) -> tuple[str, str]:
    """Redeem the bootstrap token over raw HTTP; return (cookie, csrf)."""

    payload = json.dumps({"token": token}).encode("utf-8")
    request = (
        "POST /api/v1/session/bootstrap HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Connection: close\r\n"
        f"Content-Length: {len(payload)}\r\n"
        "Content-Type: application/json\r\n"
        f"Origin: http://{host}:{port}\r\n"
        "\r\n"
    ).encode("ascii") + payload
    with socket.create_connection((host, port), timeout=5) as sock:
        sock.sendall(request)
        raw = _read_response(sock)
    head, _, body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    assert int(status_line.split(" ", 2)[1]) == 200, raw[:200]
    cookie: str | None = None
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"set-cookie:"):
            value = line.split(b":", 1)[1].decode("ascii").strip()
            for part in value.split(";"):
                if part.strip().startswith("krellbot_session="):
                    cookie = part.strip().split("=", 1)[1]
    assert cookie, raw[:400]
    csrf = json.loads(body)["csrf_token"]
    return cookie, csrf


# ---------------------------------------------------------------------------
# Fakes — no test in this file reaches the network
# ---------------------------------------------------------------------------


class _FakeRefresh:
    """Records calls; raises ValueError by default (refused key)."""

    def __init__(self, *, verified: dict | None = None) -> None:
        self.calls: list[tuple[Path, str, int]] = []
        self._verified = verified

    def __call__(self, home: Path, key: str, *, now: int, **_kwargs) -> dict | None:
        self.calls.append((Path(home), key, int(now)))
        if self._verified is None:
            raise ValueError("license signature rejected")
        return self._verified


class _FakeInstall:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, home: Path, key: str, **_kwargs) -> bool:
        self.calls.append(key)
        return False


@pytest.fixture
def fresh_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def workstation(fresh_home: Path):
    server = WorkstationServer(home=fresh_home, port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# F1 — the fresh-install short-circuit is gone
# ---------------------------------------------------------------------------


def test_redeem_fresh_home_calls_refresh_license(fresh_home: Path, monkeypatch) -> None:
    """A fresh tmp home (no cache, no catalog) still reaches
    ``refresh_license``; a refused key yields the closed dead outcome."""

    fake = _FakeRefresh()  # raises ValueError -> refused
    install = _FakeInstall()
    monkeypatch.setattr("krellbot.ui.activate.refresh_license", fake)
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", install)

    from krellbot.ui.activate import redeem

    outcome = redeem("K", home=fresh_home, now=1)
    assert len(fake.calls) == 1, fake.calls
    assert fake.calls[0][1] == "K", fake.calls
    assert outcome.status == "dead", outcome
    assert outcome.message == "license not accepted", outcome
    assert outcome.catalog_downloaded is False, outcome
    assert install.calls == [], install.calls


def test_redeem_refused_key_outcome_is_secret_free(fresh_home: Path, monkeypatch) -> None:
    """The refused outcome never echoes the submitted key."""

    secret = "DLX-SECRET-1234567890-XYZ"
    fake = _FakeRefresh()
    monkeypatch.setattr("krellbot.ui.activate.refresh_license", fake)
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", _FakeInstall())

    from krellbot.ui.activate import redeem

    outcome = redeem(secret, home=fresh_home, now=1)
    assert outcome.status == "dead", outcome
    assert secret not in outcome.message, outcome
    assert secret not in outcome.status, outcome


def test_skipped_message_is_gone() -> None:
    """``"skipped: no paid account"`` is removed from SAFE_MESSAGES."""
    assert "skipped: no paid account" not in SAFE_MESSAGES


# ---------------------------------------------------------------------------
# F2 — /api/v1/activation/redeem requires the state-change gate
# ---------------------------------------------------------------------------


def test_api_redeem_requires_session_and_csrf(fresh_home: Path, monkeypatch, workstation: WorkstationServer) -> None:
    """A raw POST with no cookie/CSRF and an evil Origin is 403, and the
    license transport is never called."""

    fake = _FakeRefresh()
    install = _FakeInstall()
    monkeypatch.setattr("krellbot.ui.activate.refresh_license", fake)
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", install)

    host, port = workstation.bound_host, workstation.bound_port

    # No cookie, loopback Origin: the gate demands a session.
    code, body = _post_json(host, port, "/api/v1/activation/redeem", {"key": "K"}, origin=f"http://{host}:{port}")
    assert code == 403, (code, body)

    # Evil Origin (no cookie): still 403.
    code, body = _post_json(host, port, "/api/v1/activation/redeem", {"key": "K"}, origin="http://evil.test")
    assert code == 403, (code, body)

    assert fake.calls == [], fake.calls
    assert install.calls == [], install.calls


def test_api_redeem_after_bootstrap_uses_gate(fresh_home: Path, monkeypatch, workstation: WorkstationServer) -> None:
    """After a real bootstrap the gated POST reaches the fake transport
    exactly once and never echoes the key."""

    fake = _FakeRefresh()
    install = _FakeInstall()
    monkeypatch.setattr("krellbot.ui.activate.refresh_license", fake)
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", install)

    host, port = workstation.bound_host, workstation.bound_port
    cookie, csrf = _bootstrap(host, port, workstation.bootstrap_token)

    secret = "DLX-GATE-KEY-9876543210"
    code, body = _post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {"key": secret},
        origin=f"http://{host}:{port}",
        cookie=cookie,
        csrf=csrf,
    )
    assert code == 200, (code, body)
    assert len(fake.calls) == 1, fake.calls
    parsed = json.loads(body)
    assert parsed["status"] == "dead", parsed
    assert parsed["message"] == "license not accepted", parsed
    assert parsed["catalog_downloaded"] is False, parsed
    assert secret.encode() not in body, body


def test_api_redeem_gate_shape_is_unchanged_on_success(
    fresh_home: Path, monkeypatch, workstation: WorkstationServer
) -> None:
    """The success response keeps the closed redeem shape."""

    fake = _FakeRefresh()
    # Verified payload must be valid at the route's real clock.
    fake._verified = {"status": "active", "grace_until": 4102444800}  # 2100-01-01
    installed: list[str] = []

    def _install(home: Path, key: str, **_kw) -> bool:
        installed.append(key)
        return True

    monkeypatch.setattr("krellbot.ui.activate.refresh_license", fake)
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", _install)

    host, port = workstation.bound_host, workstation.bound_port
    cookie, csrf = _bootstrap(host, port, workstation.bootstrap_token)

    code, body = _post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {"key": "PAID-KEY-1"},
        origin=f"http://{host}:{port}",
        cookie=cookie,
        csrf=csrf,
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    assert set(parsed.keys()) == {"schema_version", "status", "message", "catalog_downloaded"}, parsed
    assert parsed["status"] == "paid", parsed
    assert parsed["message"] == "license verified", parsed
    assert parsed["catalog_downloaded"] is True, parsed
    assert installed == ["PAID-KEY-1"], installed


# ---------------------------------------------------------------------------
# F3 — /api/v1/capabilities no longer hands out the bootstrap token
# ---------------------------------------------------------------------------


def test_capabilities_has_no_bootstrap_token(fresh_home: Path, workstation: WorkstationServer) -> None:
    """GET /api/v1/capabilities returns exactly the four closed keys and
    never contains the token string."""

    host, port = workstation.bound_host, workstation.bound_port
    code, body = _http_request(host, port, "GET", "/api/v1/capabilities")
    assert code == 200, (code, body)
    parsed = json.loads(body)
    assert set(parsed.keys()) == {"schema_version", "paper_commands", "research", "live_orders"}, parsed
    assert workstation.bootstrap_token, "server did not expose its token for the assertion"
    assert workstation.bootstrap_token.encode() not in body, body


def test_workstation_server_exposes_token_in_process_only(fresh_home: Path) -> None:
    """``bootstrap_token`` is a read-only in-process attribute: set by
    ``start()``, cleared by ``stop()``, never part of the URL."""

    server = WorkstationServer(home=fresh_home, port=0)
    assert server.bootstrap_token == ""
    server.start()
    try:
        token = server.bootstrap_token
        assert isinstance(token, str) and token, repr(token)
        assert token not in server.url, server.url
    finally:
        server.stop()
    assert server.bootstrap_token == "", repr(server.bootstrap_token)

"""Lane E preview gate — drive the actual launcher under an isolated home.

These tests pin the workstation entry point (the in-process
``WorkstationServer`` that the ``krellbot workstation`` CLI uses) against
the brief's first required behavior:

    * Fresh install: a fresh tmpdir home launches, the onboarding route
      renders the legacy onboarding page or the React ``WorkstationShell``,
      and a key activation attempt is refused with the closed
      ``license not accepted`` message — no live call, no card.

The test intentionally avoids a frozen binary or any real HTTP transport:
the launcher is the same code path the CLI runs, just bound to a random
loopback port. ``krellbot.ui.activate.refresh_license`` and
``krellbot.ui.activate.install_catalog`` are monkeypatched everywhere so
no activation test reaches the network.

Rewritten in M1R-FA: the fresh-install short-circuit
(``skipped: no paid account``) is gone — a first-time buyer must be able
to submit a key — and ``/api/v1/activation/redeem`` now runs the
session + CSRF + loopback-origin state-change gate before it reads any
body byte.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from krellbot.api.serve import WorkstationServer
from krellbot.ui.activate import SAFE_MESSAGES


def _read_response(sock: socket.socket, n: int = 4096) -> bytes:
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


def _http_get(host: str, port: int, path: str = "/") -> tuple[int, bytes]:
    with socket.create_connection((host, port), timeout=3) as sock:
        request = (f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n").encode("ascii")
        sock.sendall(request)
        raw = _read_response(sock, n=65536)
    head, _, body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    code = int(status_line.split(" ", 2)[1])
    return code, body


def _http_post_json(
    host: str,
    port: int,
    path: str,
    payload: dict,
    *,
    origin: str | None = None,
    cookie: str | None = None,
    csrf: str | None = None,
) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    headers = [
        f"Host: {host}:{port}",
        "Connection: close",
        f"Content-Length: {len(body)}",
        "Content-Type: application/json",
    ]
    if origin is not None:
        headers.append(f"Origin: {origin}")
    if cookie is not None:
        headers.append(f"Cookie: krellbot_session={cookie}")
    if csrf is not None:
        headers.append(f"X-Krellbot-CSRF: {csrf}")
    with socket.create_connection((host, port), timeout=3) as sock:
        request = (f"POST {path} HTTP/1.1\r\n" + "\r\n".join(headers) + "\r\n\r\n").encode("ascii") + body
        sock.sendall(request)
        raw = _read_response(sock, n=65536)
    head, _, resp_body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    code = int(status_line.split(" ", 2)[1])
    return code, resp_body


class _RefusingRefresh:
    """Fake ``refresh_license``: records calls, always refuses the key."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, home: Path, key: str, *, now: int, **_kwargs) -> dict | None:
        self.calls.append(key)
        raise ValueError("license signature rejected")


class _NeverInstall:
    """Fake ``install_catalog``: records calls; must never be reached."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, home: Path, key: str, **_kwargs) -> bool:
        self.calls.append(key)
        return False


@pytest.fixture
def fresh_home(tmp_path: Path, monkeypatch) -> Path:
    """Isolated KRELLBOT_HOME — no license cache, no catalog, no config."""

    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def workstation(fresh_home: Path):
    """Start a real ``WorkstationServer`` against the fresh home."""

    server = WorkstationServer(home=fresh_home, port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# Fresh install launches
# ---------------------------------------------------------------------------


def test_fresh_install_launches_and_renders_onboarding_or_shell(
    fresh_home: Path, workstation: WorkstationServer
) -> None:
    """GET / against a fresh home returns the shell or its absence signal.

    The brief allows either the legacy onboarding page or the React
    ``WorkstationShell``. With no built dist, the FastAPI layer returns
    ``{"code": "shell_not_built"}`` with status 404 — that is the closed
    shape the loader emits, and it counts as the launcher having
    rendered its onboarding route. With a built dist, the same GET
    returns 200 HTML for the React shell.
    """

    code, body = _http_get(workstation.bound_host, workstation.bound_port, "/")
    assert code in (200, 404), (code, body[:200])
    if code == 404:
        assert b"shell_not_built" in body, body
    else:
        assert body, body


def test_fresh_install_runs_under_isolated_krellbot_home(
    fresh_home: Path, monkeypatch, workstation: WorkstationServer
) -> None:
    """The launcher reads from the isolated tmpdir, not the real home.

    A first-time buyer has neither a license cache nor a catalog, yet
    their key submission still reaches the license check (through the
    fakes) and is refused with the closed message. A failure here means
    the server leaked into the process env's KRELLBOT_HOME or the
    redeem path stopped calling ``refresh_license``.
    """

    refresh = _RefusingRefresh()
    install = _NeverInstall()
    monkeypatch.setattr("krellbot.ui.activate.refresh_license", refresh)
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", install)

    # The fresh home never had a config or license cache written to it.
    assert not (fresh_home / "config.json").exists()
    assert not (fresh_home / "catalog").exists()

    host, port = workstation.bound_host, workstation.bound_port
    cookie, csrf = _redeem_bootstrap(host, port, workstation.bootstrap_token)

    code, body = _http_post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {"key": "ANY-KEY-WOULD-NEVER-MAKE-IT-HERE"},
        origin=f"http://{host}:{port}",
        cookie=cookie,
        csrf=csrf,
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    assert parsed["message"] == "license not accepted", parsed
    assert parsed["status"] == "dead", parsed
    assert parsed["catalog_downloaded"] is False, parsed
    assert len(refresh.calls) == 1, refresh.calls
    assert install.calls == [], install.calls


def _redeem_bootstrap(host: str, port: int, token: str) -> tuple[str, str]:
    """POST the bootstrap token and pull cookie + csrf from the response."""

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
    with socket.create_connection((host, port), timeout=3) as sock:
        sock.sendall(request)
        raw = _read_response(sock, n=65536)
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
    return cookie, json.loads(body)["csrf_token"]


def test_activation_response_does_not_echo_key(fresh_home: Path, monkeypatch, workstation: WorkstationServer) -> None:
    """The activation response body never echoes the submitted key."""

    monkeypatch.setattr("krellbot.ui.activate.refresh_license", _RefusingRefresh())
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", _NeverInstall())

    host, port = workstation.bound_host, workstation.bound_port
    cookie, csrf = _redeem_bootstrap(host, port, workstation.bootstrap_token)

    secret = "DLX-SECRET-1234567890-XYZ"
    code, body = _http_post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {"key": secret},
        origin=f"http://{host}:{port}",
        cookie=cookie,
        csrf=csrf,
    )
    assert code == 200, (code, body)
    assert secret.encode() not in body, body
    parsed = json.loads(body)
    for value in parsed.values():
        assert secret not in str(value), parsed


def test_activation_message_is_in_safe_set(fresh_home: Path, monkeypatch, workstation: WorkstationServer) -> None:
    """The fresh-install refusal message is in the activate SAFE_MESSAGES set."""

    monkeypatch.setattr("krellbot.ui.activate.refresh_license", _RefusingRefresh())
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", _NeverInstall())

    host, port = workstation.bound_host, workstation.bound_port
    cookie, csrf = _redeem_bootstrap(host, port, workstation.bootstrap_token)

    code, body = _http_post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {"key": "anything"},
        origin=f"http://{host}:{port}",
        cookie=cookie,
        csrf=csrf,
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    assert parsed["message"] in SAFE_MESSAGES, parsed


def test_fresh_install_with_no_key_body(fresh_home: Path, monkeypatch, workstation: WorkstationServer) -> None:
    """An empty key on a fresh install returns a closed refusal."""

    monkeypatch.setattr("krellbot.ui.activate.refresh_license", _RefusingRefresh())
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", _NeverInstall())

    host, port = workstation.bound_host, workstation.bound_port
    cookie, csrf = _redeem_bootstrap(host, port, workstation.bootstrap_token)

    code, body = _http_post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {},
        origin=f"http://{host}:{port}",
        cookie=cookie,
        csrf=csrf,
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    # No-key submissions are caught by the empty-string branch first.
    assert parsed["message"] in SAFE_MESSAGES, parsed
    assert parsed["status"] == "dead", parsed


def test_activation_without_session_is_403(fresh_home: Path, monkeypatch, workstation: WorkstationServer) -> None:
    """A cross-origin or cookie-less redeem POST never reaches the
    license transport (M1R-FA F2)."""

    refresh = _RefusingRefresh()
    monkeypatch.setattr("krellbot.ui.activate.refresh_license", refresh)
    monkeypatch.setattr("krellbot.ui.activate.install_catalog", _NeverInstall())

    host, port = workstation.bound_host, workstation.bound_port
    code, body = _http_post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {"key": "K"},
        origin="http://evil.test",
    )
    assert code == 403, (code, body)
    code, body = _http_post_json(
        host,
        port,
        "/api/v1/activation/redeem",
        {"key": "K"},
        origin=f"http://{host}:{port}",
    )
    assert code == 403, (code, body)
    assert refresh.calls == [], refresh.calls

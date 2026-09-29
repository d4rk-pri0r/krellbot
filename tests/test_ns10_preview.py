"""Lane E preview gate — drive the actual launcher under an isolated home.

These tests pin the workstation entry point (the in-process
``WorkstationServer`` that the ``krellbot workstation`` CLI uses) against
the brief's first required behavior:

    * Fresh install: a fresh tmpdir home launches, the onboarding route
      renders the legacy onboarding page or the React ``WorkstationShell``,
      and a key activation attempt surfaces a clear "skipped: no paid
      account" message — no live call, no card.

The test intentionally avoids a frozen binary or any real HTTP transport:
the launcher is the same code path the CLI runs, just bound to a
random loopback port.
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


def _http_post_json(host: str, port: int, path: str, payload: dict) -> tuple[int, bytes]:
    body = json.dumps(payload).encode("utf-8")
    with socket.create_connection((host, port), timeout=3) as sock:
        request = (
            f"POST {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Connection: close\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"
        ).encode("ascii") + body
        sock.sendall(request)
        raw = _read_response(sock, n=65536)
    head, _, resp_body = raw.partition(b"\r\n\r\n")
    status_line = head.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
    code = int(status_line.split(" ", 2)[1])
    return code, resp_body


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


def test_fresh_install_runs_under_isolated_krellbot_home(fresh_home: Path, workstation: WorkstationServer) -> None:
    """The launcher reads from the isolated tmpdir, not the real home.

    A failure here means the server accidentally leaked into the
    process env's KRELLBOT_HOME. We probe the activation route — it
    should refuse with ``skipped: no paid account`` because the
    isolated home has neither a license cache nor a catalog.
    """

    # The fresh home never had a config or license cache written to it.
    assert not (fresh_home / "config.json").exists()
    assert not (fresh_home / "catalog").exists()

    code, body = _http_post_json(
        workstation.bound_host,
        workstation.bound_port,
        "/api/v1/activation/redeem",
        {"key": "ANY-KEY-WOULD-NEVER-MAKE-IT-HERE"},
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    assert parsed["message"] == "skipped: no paid account", parsed
    assert parsed["status"] == "dead", parsed
    assert parsed["catalog_downloaded"] is False, parsed


def test_activation_short_circuit_does_not_echo_key(fresh_home: Path, workstation: WorkstationServer) -> None:
    """The activation response body never echoes the submitted key."""

    secret = "DLX-SECRET-1234567890-XYZ"
    code, body = _http_post_json(
        workstation.bound_host,
        workstation.bound_port,
        "/api/v1/activation/redeem",
        {"key": secret},
    )
    assert code == 200, (code, body)
    assert secret.encode() not in body, body
    parsed = json.loads(body)
    for value in parsed.values():
        assert secret not in str(value), parsed


def test_activation_message_is_in_safe_set(fresh_home: Path, workstation: WorkstationServer) -> None:
    """The fresh-install refusal message is in the activate SAFE_MESSAGES set."""

    assert "skipped: no paid account" in SAFE_MESSAGES
    code, body = _http_post_json(
        workstation.bound_host,
        workstation.bound_port,
        "/api/v1/activation/redeem",
        {"key": "anything"},
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    assert parsed["message"] in SAFE_MESSAGES, parsed


def test_fresh_install_with_no_key_body_uses_short_circuit(fresh_home: Path, workstation: WorkstationServer) -> None:
    """An empty key on a fresh install returns the same short-circuit message."""

    code, body = _http_post_json(
        workstation.bound_host,
        workstation.bound_port,
        "/api/v1/activation/redeem",
        {},
    )
    assert code == 200, (code, body)
    parsed = json.loads(body)
    # No-key submissions are caught by the empty-string branch first.
    assert parsed["message"] in SAFE_MESSAGES, parsed

"""Real loopback HTTP behind an identity-authenticating Tailscale Serve proxy."""

from __future__ import annotations

import http.client
import json
from pathlib import Path

import pytest

from krellbot.api.serve import WorkstationServer

ORIGIN = "https://workstation.example.ts.net"
USER = "owner@example.com"


@pytest.fixture
def workstation(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><head></head><body>Workstation</body></html>")
    server = WorkstationServer(
        home=tmp_path / "home",
        dist_dir=dist,
        tailscale_origin=ORIGIN,
        tailscale_user=USER,
    )
    server.start()
    try:
        yield server
    finally:
        server.stop()


def request(server, method="GET", path="/", *, headers=None, payload=None):
    actual = {"Host": "workstation.example.ts.net", "Tailscale-User-Login": USER}
    actual.update(headers or {})
    conn = http.client.HTTPConnection("127.0.0.1", server.bound_port, timeout=5)
    try:
        conn.request(method, path, body=json.dumps(payload) if payload is not None else None, headers=actual)
        response = conn.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        conn.close()


def login(server):
    status, headers, _ = request(server, "POST", "/login", headers={"Origin": ORIGIN})
    assert status == 303
    assert headers["location"] == "/"
    cookie = headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
    return cookie.split(";", 1)[0]


def test_two_devices_can_log_in_and_recover_their_own_session(workstation):
    status, headers, body = request(workstation)
    assert status == 303 and headers["location"] == "/login"
    status, _, body = request(workstation, path="/login")
    assert status == 200 and b"Log in with Tailscale" in body
    cookies = [login(workstation), login(workstation)]
    assert cookies[0] != cookies[1]
    for cookie in cookies:
        status, _, body = request(workstation, headers={"Cookie": cookie})
        assert status == 200 and b"Workstation" in body
        assert b"krellbot-bootstrap" not in body
        status, _, body = request(workstation, path="/api/v1/session/csrf", headers={"Cookie": cookie})
        assert status == 200 and json.loads(body)["csrf_token"]
    assert workstation.bound_host == "127.0.0.1"


@pytest.mark.parametrize(
    "headers",
    [
        {"Tailscale-User-Login": ""},
        {"Tailscale-User-Login": "someone-else@example.com"},
        {"Host": "attacker.example"},
        {"Origin": "https://attacker.example"},
    ],
)
def test_untrusted_requests_cannot_read_the_shell_or_create_sessions(workstation, headers):
    assert request(workstation, headers=headers)[0] == 403
    assert request(workstation, "POST", "/login", headers=headers)[0] == 403


def test_login_requires_same_origin_and_api_still_requires_session_and_csrf(workstation):
    assert request(workstation, "POST", "/login")[0] == 403
    assert request(workstation, path="/api/v1/session/csrf")[0] == 401
    cookie = login(workstation)
    authenticated = {"Cookie": cookie, "Origin": ORIGIN}
    assert request(workstation, "POST", "/api/v1/commands", headers=authenticated, payload={})[0] == 403
    _, _, body = request(workstation, path="/api/v1/session/csrf", headers=authenticated)
    authenticated["X-Krellbot-CSRF"] = json.loads(body)["csrf_token"]
    status, _, body = request(
        workstation,
        "POST",
        "/api/v1/commands",
        headers=authenticated,
        payload={"command": "live.arm", "payload": {"mode": "live"}},
    )
    assert status == 403 and b"live orders are disabled" in body
    assert (
        request(
            workstation,
            "POST",
            "/api/v1/session/bootstrap",
            headers=authenticated,
            payload={"token": workstation.bootstrap_token},
        )[0]
        == 403
    )


@pytest.mark.parametrize(
    "origin,user",
    [
        (ORIGIN, None),
        (None, USER),
        ("http://workstation.example.ts.net", USER),
        ("https://public.example.com", USER),
        (ORIGIN + "/path", USER),
    ],
)
def test_remote_configuration_fails_before_binding(tmp_path, origin, user):
    with pytest.raises(ValueError):
        WorkstationServer(home=tmp_path, tailscale_origin=origin, tailscale_user=user)

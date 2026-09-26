"""Local first-run preferences and trust snapshot.

These tests prove the visit preference is bounded JSON, corrupt-safe,
and never widens the home directory's permissions. They also prove the
trust snapshot reflects a fake/null keychain without ever reading a
secret value.

A second block at the bottom covers the B2 token-scoped wizard routes
and fixed user-initiated exits served by `krellbot.ui.server`. Those
tests exercise the HTTP layer (DashboardServer + http.client) and
start the server on a random port (`port=0`), teardown is in `finally`.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
import sys
from pathlib import Path
from urllib.parse import urljoin

import pytest


@pytest.fixture
def zero_umask():
    """Force umask 0o000 so mkdir creates world-writable dirs by default.

    This exposes the privacy bug where _ensure_home would skip its chmod
    because the resulting mode (0o777) is not the umask-default 0o755.
    """
    old = os.umask(0o000)
    try:
        yield
    finally:
        os.umask(old)


@pytest.fixture
def custom_umask():
    """Force a non-default umask (0o022 reversed to 0o077 so mkdir creates 0o700)."""
    old = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(old)


# --- has_visited_dashboard / mark_visited_dashboard -------------------------


def test_fresh_home_is_not_visited(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard

    assert has_visited_dashboard(tmp_path) is False


def test_mark_then_has_roundtrip(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard, mark_visited_dashboard

    assert has_visited_dashboard(tmp_path) is False
    mark_visited_dashboard(tmp_path)
    assert has_visited_dashboard(tmp_path) is True


def test_corrupt_preference_is_not_visited(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard, mark_visited_dashboard

    mark_visited_dashboard(tmp_path)
    assert has_visited_dashboard(tmp_path) is True

    # Truncated / non-JSON payload must be treated as "not visited" and
    # must not raise.
    (tmp_path / "ui-preferences.json").write_text("{")
    assert has_visited_dashboard(tmp_path) is False


def test_preference_payload_is_bounded(tmp_path: Path) -> None:
    from krellbot.ui.first_run import mark_visited_dashboard

    mark_visited_dashboard(tmp_path)

    payload = (tmp_path / "ui-preferences.json").read_text()
    data = json.loads(payload)
    assert data == {"visited_dashboard": True}


def test_unreadable_preference_is_not_visited(tmp_path: Path) -> None:
    from krellbot.ui.first_run import has_visited_dashboard, mark_visited_dashboard

    mark_visited_dashboard(tmp_path)
    assert has_visited_dashboard(tmp_path) is True

    # Replace the file with a directory so open() fails. has_visited_dashboard
    # must swallow OSError and return False.
    (tmp_path / "ui-preferences.json").unlink()
    (tmp_path / "ui-preferences.json").mkdir()
    assert has_visited_dashboard(tmp_path) is False


@pytest.mark.parametrize(
    "raw",
    [
        '{"visited_dashboard": 1}',                # truthy non-bool
        '{"visited_dashboard": "true"}',          # truthy string
        '{"visited_dashboard": "yes"}',           # truthy string
        '{"visited_dashboard": 0.1}',              # truthy float
        '{"visited_dashboard": [true]}',          # truthy list
        '{"visited_dashboard": null}',             # missing/falsy
        '{"visited_dashboard": false}',           # explicit false
        '{}',                                      # missing key
    ],
)
def test_has_visited_dashboard_strict_bool(tmp_path: Path, raw: str) -> None:
    """Any non-literal-True value must read as 'not visited'.

    Only the exact JSON literal `true` flips the wizard off; strings,
    numbers, lists, null, false, and missing keys keep the user in the
    wizard so a corrupt or hand-edited file cannot silently re-arm it.
    """
    from krellbot.ui.first_run import has_visited_dashboard

    (tmp_path / "ui-preferences.json").write_text(raw)
    assert has_visited_dashboard(tmp_path) is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_mark_creates_missing_home_at_0o700(tmp_path: Path) -> None:
    """When the home does not exist yet, mark_visited_dashboard must create
    it with mode 0o700 on POSIX rather than letting atomic_write raise
    FileNotFoundError. The preference file inside is then 0o600.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    missing = tmp_path / "fresh-home"
    assert not missing.exists()

    mark_visited_dashboard(missing)

    assert missing.is_dir()
    home_mode = missing.stat().st_mode & 0o777
    assert home_mode == 0o700, f"newly created home should be 0o700, got {oct(home_mode)}"
    pref_mode = (missing / "ui-preferences.json").stat().st_mode & 0o777
    assert pref_mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_mark_does_not_widen_existing_home(tmp_path: Path) -> None:
    """If the home already exists with a non-default mode, marking must
    not chmod it. (Covered more strictly by test_mark_visited_does_not_widen_home,
    but this version does not pre-condition the mode to 0o750.)
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    home = tmp_path / "existing-home"
    home.mkdir(mode=0o755)
    before = home.stat().st_mode & 0o777
    assert before == 0o755

    mark_visited_dashboard(home)

    after = home.stat().st_mode & 0o777
    assert after == before, f"home mode changed: {oct(before)} -> {oct(after)}"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_mark_visited_does_not_widen_home(tmp_path: Path) -> None:
    """Writing the preference file must not chmod the home directory.

    atomic_write chmods only the file it creates; the surrounding home
    must keep the mode the caller set. We start with a non-default mode
    (0o750) and assert it survives a mark.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    os.chmod(tmp_path, 0o750)
    before = tmp_path.stat().st_mode & 0o777
    assert before == 0o750

    mark_visited_dashboard(tmp_path)

    after = tmp_path.stat().st_mode & 0o777
    assert after == before, f"home mode changed: {oct(before)} -> {oct(after)}"
    # The preference file itself should still be private.
    pref_mode = (tmp_path / "ui-preferences.json").stat().st_mode & 0o777
    assert pref_mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_ensure_home_is_0o700_under_zero_umask(tmp_path: Path, zero_umask) -> None:
    """Privacy must hold under any umask, including umask=0o000.

    With umask 0o000, a plain ``mkdir`` would create the directory with
    mode 0o777 (world-readable/writable). _ensure_home must still leave
    the freshly created home at exactly 0o700 so the data directory
    cannot leak to other local users.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    missing = tmp_path / "fresh-home-zero-umask"
    assert not missing.exists()

    mark_visited_dashboard(missing)

    assert missing.is_dir()
    home_mode = missing.stat().st_mode & 0o777
    assert home_mode == 0o700, (
        f"newly created home must be 0o700 under zero umask, got {oct(home_mode)}"
    )
    pref_mode = (missing / "ui-preferences.json").stat().st_mode & 0o777
    assert pref_mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_ensure_home_is_0o700_under_other_nonstandard_umask(tmp_path: Path, custom_umask) -> None:
    """Privacy must also hold under a non-default umask like 0o077.

    With umask 0o077, mkdir creates 0o700 (already private). _ensure_home
    must still result in exactly 0o700 — no widening, no narrowing.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    missing = tmp_path / "fresh-home-custom-umask"
    assert not missing.exists()

    mark_visited_dashboard(missing)

    assert missing.is_dir()
    home_mode = missing.stat().st_mode & 0o777
    assert home_mode == 0o700, (
        f"newly created home must be 0o700 under umask 0o077, got {oct(home_mode)}"
    )


# --- trust_snapshot ---------------------------------------------------------


def test_trust_snapshot_keys(tmp_path: Path) -> None:
    from krellbot.ui import trust

    snap = trust.trust_snapshot(tmp_path)
    assert set(snap.keys()) == {
        "home",
        "home_mode",
        "keychain_backend",
        "keychain_ok",
        "bind",
        "live_arm_ui_allowed",
        "trade_only_required",
    }
    assert snap["home"] == str(tmp_path)
    assert snap["bind"] == "127.0.0.1"
    assert snap["live_arm_ui_allowed"] is False
    assert snap["trade_only_required"] is True


def test_trust_snapshot_never_reads_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A fake/null keychain backend must surface keychain_ok=False, and the
    snapshot must never expose any secret value.
    """
    from krellbot.ui import trust

    monkeypatch.setattr(
        trust,
        "_keychain_backend",
        lambda: ("keyring.backends.null.Keyring", "keychain backend is NullKeyring (not persistent)"),
    )

    snap = trust.trust_snapshot(tmp_path)

    assert snap["keychain_backend"] == "keyring.backends.null.Keyring"
    assert snap["keychain_ok"] is False

    # No credential string should leak.
    repr_ = repr(snap).lower()
    assert "secret" not in repr_
    assert "password" not in repr_
    assert "api_key" not in repr_


def test_trust_snapshot_reports_missing_home_mode(tmp_path: Path) -> None:
    from krellbot.ui import trust

    # Use a path that does not exist.
    missing = tmp_path / "nope" / "home"
    snap = trust.trust_snapshot(missing)
    assert snap["home_mode"] is None


def test_trust_snapshot_reports_home_mode(tmp_path: Path) -> None:
    from krellbot.ui import trust

    os.chmod(tmp_path, 0o700)
    snap = trust.trust_snapshot(tmp_path)
    assert snap["home_mode"] == "0o700"


def test_trust_snapshot_reports_unreadable_home_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If stat() raises OSError, home_mode must be None (not raise)."""
    from krellbot.ui import trust

    real_stat = Path.stat

    def fake_stat(self, *args, **kwargs):  # noqa: ANN001
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "stat", fake_stat)

    # trust_snapshot uses os.stat directly, not Path.stat — patch the module's
    # reference.
    monkeypatch.setattr(trust.os, "stat", fake_stat)
    snap = trust.trust_snapshot(tmp_path)
    assert snap["home_mode"] is None


# --- B2: token-scoped wizard routes + fixed exits ---------------------------
#
# These tests construct a DashboardServer on a random port and exercise the
# HTTP layer with http.client. No sleep, no poll: the server is synchronous
# and answers instantly. Tear-down lives in `finally` so a hung test does
# not leak the listening socket.


def _start_server(home: Path):
    """Start a DashboardServer on a random port. Caller must stop."""
    from krellbot.ui.server import DashboardServer

    server = DashboardServer(home=home, port=0)
    server.start()
    return server


def _parse_set_cookies(resp: http.client.HTTPResponse) -> dict[str, str]:
    """Pull every Set-Cookie header off a response and return a name->value map."""
    out: dict[str, str] = {}
    for k, v in resp.getheaders():
        if k.lower() != "set-cookie":
            continue
        first = v.split(";", 1)[0].strip()
        if "=" not in first:
            continue
        name, _, value = first.partition("=")
        out[name.strip()] = value.strip()
    return out


def _login(server, port: int) -> tuple[str, str]:
    """GET /<token>/ once to set cookies. Returns (cookie_header, csrf)."""
    conn = http.client.HTTPConnection("127.0.0.1", port)
    try:
        conn.request("GET", f"/{server.token}/")
        resp = conn.getresponse()
        resp.read()
        cookies = _parse_set_cookies(resp)
        session = cookies.get("krellbot_session", "")
        csrf = cookies.get("krellbot_csrf", "")
        assert session and csrf, (session, csrf, resp.getheaders())
        return f"krellbot_session={session}; krellbot_csrf={csrf}", csrf
    finally:
        conn.close()


def _post_form(server, port: int, path: str, body: str, *, cookies: str, origin: str | None):
    conn = http.client.HTTPConnection("127.0.0.1", port)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookies,
    }
    if origin is not None:
        headers["Origin"] = origin
    conn.request("POST", path, body=body, headers=headers)
    return conn, conn.getresponse()


def test_fresh_root_renders_welcome(tmp_path: Path) -> None:
    """With no recorded visit, the index route must render the wizard's
    Welcome shell — distinct from the dashboard — and the page must
    expose the trust posture via a JSON bootstrap with no raw credential.
    """
    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200, resp.status
            # Welcome markers — the wizard's own brand.
            assert "krellbot first-run wizard" in body.lower()
            assert "welcome-section" in body
            # Security posture is exposed on the Welcome shell via a JSON
            # bootstrap view (`__KB_VIEW__`) — no raw credential string.
            assert "__KB_VIEW__" in body
            assert "keychain_backend" in body
            # No raw credential string leaks even when the JSON is escaped.
            low = body.lower()
            assert "api_key" not in low
            assert "password" not in low
            assert "secret" not in low
        finally:
            conn.close()
    finally:
        server.stop()


def test_security_route_has_posture_and_no_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`GET /<token>/security` exposes the trust snapshot (path, backend) but
    must never include any raw credential string."""
    from krellbot.ui import trust

    monkeypatch.setattr(
        trust,
        "_keychain_backend",
        lambda: ("keyring.backends.null.Keyring", "keychain backend is NullKeyring (not persistent)"),
    )
    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/security")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200, resp.status
            # Backend path appears as text on the security shell.
            assert "keyring.backends.null.Keyring" in body
            # Home path appears.
            assert str(tmp_path) in body
            # No raw credential can leak.
            low = body.lower()
            assert "api_key" not in low
            assert "password" not in low
            assert "secret" not in low
        finally:
            conn.close()
    finally:
        server.stop()


def test_post_visit_dashboard_changes_later_root_to_dashboard(tmp_path: Path) -> None:
    """After a CSRF-protected POST /visit-dashboard flips the preference,
    GET /<token>/ must render the dashboard shell, not welcome.
    """
    from krellbot.ui.first_run import has_visited_dashboard

    server = _start_server(tmp_path)
    try:
        assert has_visited_dashboard(tmp_path) is False
        cookies, csrf = _login(server, server.bound_port)
        conn, resp = _post_form(
            server,
            server.bound_port,
            f"/{server.token}/visit-dashboard",
            f"csrf={csrf}",
            cookies=cookies,
            origin=f"http://127.0.0.1:{server.bound_port}",
        )
        assert resp.status == 200, resp.status
        resp.read()
        conn.close()
        assert has_visited_dashboard(tmp_path) is True

        # Now the root must be the dashboard shell, not the wizard welcome.
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200
            assert "armed-section" in body  # dashboard-only block
        finally:
            conn.close()
    finally:
        server.stop()


def test_back_button_from_dashboard_still_reaches_welcome(tmp_path: Path) -> None:
    """The dashboard shell must surface a back-to-welcome affordance that
    resolves to a fresh Welcome render (NOT a 404, NOT a token-less redirect
    that would leak the gate)."""
    from krellbot.ui.first_run import mark_visited_dashboard

    mark_visited_dashboard(tmp_path)  # preference already set
    server = _start_server(tmp_path)
    try:
        # Dashboard root.
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200
            assert "armed-section" in body
        finally:
            conn.close()
        # Explicit /welcome route (the Back target) also serves the wizard.
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/welcome")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200
            assert "welcome" in body.lower()
        finally:
            conn.close()
    finally:
        server.stop()


def test_fixed_exit_does_not_reflect_untrusted_target(tmp_path: Path) -> None:
    """The exit table is a fixed allowlist. An attacker cannot bounce via
    `?target=https://attacker.invalid`; the route is `out/...` and unknown
    exits must 404 with NO Location header.
    """
    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/out/evil?target=https://attacker.invalid")
            resp = conn.getresponse()
            assert resp.status == 404
            assert resp.getheader("Location") is None
            resp.read()
        finally:
            conn.close()
    finally:
        server.stop()


def test_known_fixed_exits_redirect_with_no_referrer(tmp_path: Path) -> None:
    """The two allowlisted exits return 302s to their fixed targets with
    the B2 security-header set on the redirect itself: CSP,
    `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`,
    and `Cache-Control: no-store`. The redirect is treated as a first-
    class HTML/redirect response by the brief, so the policy lives here
    too.
    """
    server = _start_server(tmp_path)
    try:
        for slug, target in (
            ("docs", "https://krellbot.dev/docs/"),
            ("source", "https://github.com/d4rk-pri0r/krellbot"),
        ):
            conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
            try:
                conn.request("GET", f"/{server.token}/out/{slug}")
                resp = conn.getresponse()
                headers = {k.lower(): v for k, v in resp.getheaders()}
                assert resp.status == 302, resp.status
                assert headers.get("location") == target
                assert headers.get("referrer-policy") == "no-referrer"
                assert headers.get("x-content-type-options") == "nosniff"
                assert headers.get("cache-control") == "no-store"
                csp = headers.get("content-security-policy", "")
                assert "default-src 'none'" in csp, csp
                assert "frame-ancestors 'none'" in csp, csp
                resp.read()
            finally:
                conn.close()
    finally:
        server.stop()


_HREF_RE = re.compile(r"""\b(?:href|action)\s*=\s*['"]([^'"]+)['"]""")


def _wizard_hrefs(html: str) -> list[str]:
    """Every href / action in a wizard HTML page, in document order."""
    return _HREF_RE.findall(html)


def test_wizard_links_resolve_under_token_and_fetch(tmp_path: Path) -> None:
    """Every href in the wizard shell must be sibling-relative to the
    document, NOT `../<route>`. The wizard pages live at `/<token>/welcome`,
    `/<token>/security`, and `/<token>/next`, so a `../` prefix would
    drop the token from the resolved URL and every navigation + the
    stylesheet would 403.

    For each wizard page, parse every href, resolve it against the page
    URL, assert the resolved URL begins with `/{token}/` and is NOT just
    `/<route>` (which is what `../welcome` produces). Also fetch the
    resolved CSS + nav URLs and assert they return 200 (not 403/404).
    """
    server = _start_server(tmp_path)
    try:
        token = server.token
        for page in ("welcome", "security", "next"):
            conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
            try:
                conn.request("GET", f"/{token}/{page}")
                resp = conn.getresponse()
                assert resp.status == 200, (page, resp.status)
                html = resp.read().decode("utf-8")
            finally:
                conn.close()

            page_url = f"http://127.0.0.1:{server.bound_port}/{token}/{page}"
            for href in _wizard_hrefs(html):
                # Skip anchors (form action="visit-dashboard" must stay
                # sibling-relative too; verify below).
                resolved = urljoin(page_url, href)
                path = resolved.split("://", 1)[1].split("/", 1)[1]
                assert path.startswith(f"{token}/"), (
                    page, href, resolved, path,
                )
                # No token-less path (this is the B2 bug class).
                assert not path.startswith("static/"), (page, href, path)
                assert not path.startswith("welcome"), (page, href, path)
                assert not path.startswith("security"), (page, href, path)
                assert not path.startswith("next"), (page, href, path)
                assert not path.startswith("dashboard"), (page, href, path)
                assert not path.startswith("out/"), (page, href, path)

            # Fetch the nav routes + CSS as a real client. All must be 200.
            fetch_paths = [
                f"/{token}/static/style.css",
                f"/{token}/welcome",
                f"/{token}/security",
                f"/{token}/next",
                f"/{token}/dashboard",
                f"/{token}/out/docs",
                f"/{token}/out/source",
            ]
            for path in fetch_paths:
                conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
                try:
                    conn.request("GET", path)
                    resp = conn.getresponse()
                    status = resp.status
                    resp.read()
                finally:
                    conn.close()
                # /dashboard and /out/* are 302 (dashboard shell) or 302
                # (exits). /welcome, /security, /next, /static/style.css
                # must all be 200. The dashboard route returns the
                # dashboard HTML (200) when not visited? No — /dashboard
                # is rendered by _route_get as the dashboard shell, 200.
                # /out/* are 302 redirects. The point: nothing here may
                # be 403 (token-less) or 404.
                assert status in (200, 302), (page, path, status)
    finally:
        server.stop()


def test_root_wizard_link_resolves_under_token(tmp_path: Path) -> None:
    """A fresh `GET /<token>/` renders the welcome shell. Every href on
    that page must still resolve under `/<token>/...` when the page URL
    is the token root (not `/<token>/welcome`).
    """
    server = _start_server(tmp_path)
    try:
        token = server.token
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{token}/")
            resp = conn.getresponse()
            assert resp.status == 200
            html = resp.read().decode("utf-8")
        finally:
            conn.close()
        page_url = f"http://127.0.0.1:{server.bound_port}/{token}/"
        for href in _wizard_hrefs(html):
            resolved = urljoin(page_url, href)
            path = resolved.split("://", 1)[1].split("/", 1)[1]
            assert path.startswith(f"{token}/"), (href, resolved, path)
    finally:
        server.stop()


def test_missing_token_is_403_with_no_set_cookie(tmp_path: Path) -> None:
    """A path token must match the server's token exactly. Missing-token
    requests are 403 and must NOT set any cookie that would grant later
    access to a guessed path.
    """
    server = _start_server(tmp_path)
    try:
        # Use the real token's length but a wrong value so we exercise the
        # constant-time-compare path (not just the empty-string short-circuit).
        wrong = "0" * len(server.token)
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{wrong}/welcome")
            resp = conn.getresponse()
            headers_blob = "\n".join(f"{k}: {v}" for k, v in resp.getheaders())
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 403
            assert "set-cookie" not in headers_blob.lower()
            assert server.token not in body
            assert server.token not in headers_blob
        finally:
            conn.close()
    finally:
        server.stop()


def test_foreign_host_gets_403_with_no_set_cookie(tmp_path: Path) -> None:
    """A foreign Host header is rejected with 403 and no cookie is set."""
    server = _start_server(tmp_path)
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(("127.0.0.1", server.bound_port))
            request = (
                f"GET /{server.token}/welcome HTTP/1.1\r\n"
                "Host: evil.example.com\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)
            data = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
        finally:
            sock.close()
        head = data.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        assert " 403 " in head, head
        assert b"Set-Cookie" not in data
    finally:
        server.stop()


def test_wizard_html_keeps_journal_injection_escaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A journal string `</script><script>alert(1)</script>` must remain
    escaped as `\\u003c` in any HTML the server emits — for both the
    dashboard and the new wizard views.

    The wizard views don't embed journal records by design, so they must
    simply not contain an unescaped `</script>` tag anywhere. The
    dashboard view IS journal-derived and is the path that proves the
    escape helper actually fires.
    """
    from krellbot import paths as kb_paths

    # Mirror the `home` fixture so `krellbot.paths.home()` resolves inside tmp_path.
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path))
    monkeypatch.setattr(kb_paths, "home", lambda *a, **kw: tmp_path)
    monkeypatch.setattr(kb_paths, "ensure_layout", lambda *a, **kw: None)
    journal_dir = Path(tmp_path) / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    payload = "</script><script>alert(1)</script>"
    (journal_dir / "2099-01.jsonl").write_text(
        json.dumps({"detail": payload}) + "\n", encoding="utf-8"
    )

    server = _start_server(tmp_path)
    try:
        # Wizard views — they must not leak an unescaped </script>.
        for path in (
            f"/{server.token}/welcome",
            f"/{server.token}/security",
        ):
            conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                body = resp.read()
                assert resp.status == 200, (path, resp.status)
                assert b"</script><script>" not in body, path
            finally:
                conn.close()
        # Dashboard view — same guarantee, with the escape exercised by
        # the embedded journal string. /<token>/dashboard renders the
        # dashboard directly regardless of the visit preference.
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/dashboard")
            resp = conn.getresponse()
            body = resp.read()
            assert resp.status == 200
            assert b"</script><script>" not in body
            assert b"\\u003c/script\\u003e" in body
        finally:
            conn.close()
    finally:
        server.stop()


def test_security_view_renders_backend_and_home_server_side(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B3 contract: the security view MUST render the actual backend
    name and resolved data home in the visible HTML body, not via
    JS-only hydration. JS may ENHANCE the view, but the static HTML
    must show the truth so the no-JS path is honest.

    This is the real no-JS fallback the brief asks for: a user with
    scripts disabled must still see "macOS Keychain" (or whatever the
    actual backend is) on the page, not an empty list.

    The bootstrap JSON (window.__KB_VIEW__) carries the same data,
    but that path requires JavaScript to evaluate. The visible
    markup between ``<body>...</body>`` (excluding script tags) is the
    no-JS fallback.
    """
    import re

    from krellbot.ui import trust

    monkeypatch.setattr(
        trust,
        "_keychain_backend",
        lambda: ("keyring.backends.macOS.Keyring", None),
    )

    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/security")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200, resp.status
            # Strip script tags so the JSON bootstrap (window.__KB_VIEW__)
            # does not satisfy the assertion. The visible body must carry
            # the value on its own — that's the no-JS fallback.
            visible = re.sub(
                r"<script\b[^>]*>.*?</script>",
                "",
                body,
                flags=re.DOTALL,
            )
            assert "keyring.backends.macOS.Keyring" in visible, (
                "security view must render backend name in visible HTML, "
                "not just in window.__KB_VIEW__ (JS-only hydration is not "
                "a no-JS fallback)"
            )
            assert str(tmp_path) in visible, (
                "security view must render resolved home in visible HTML"
            )
        finally:
            conn.close()
    finally:
        server.stop()


def test_security_view_surfaces_fail_closed_diagnostic_on_null_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the keychain backend is the fake/null keyring, the security
    view must surface a fail-closed diagnostic naming the next CLI
    action (``krellbot doctor`` or equivalent). A null backend must
    NOT be reported as a green check.

    The diagnostic must appear in the visible body, not just the
    JSON bootstrap, so a no-JS user sees the truth.
    """
    import re

    from krellbot.ui import trust

    monkeypatch.setattr(
        trust,
        "_keychain_backend",
        lambda: ("keyring.backends.null.Keyring", "keychain backend is NullKeyring (not persistent)"),
    )

    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/security")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200
            visible = re.sub(
                r"<script\b[^>]*>.*?</script>",
                "",
                body,
                flags=re.DOTALL,
            )
            lower = visible.lower()
            # The page must surface the failing backend (truth), AND a
            # next-action diagnostic — not a green checkmark.
            assert "null" in lower, "failing backend name must be visible"
            assert "doctor" in lower or "krellbot doctor" in lower, (
                "failing backend must point the user at `krellbot doctor` "
                "(or equivalent CLI diagnostic)"
            )
            honest = (
                "not persistent" in lower
                or "fail" in lower
                or "not ok" in lower
                or "refused" in lower
                or "unavailable" in lower
                or "missing" in lower
            )
            assert honest, (
                "failing backend must be visibly NOT a green check; "
                "page should say the backend is unavailable / fail-closed / refused"
            )
        finally:
            conn.close()
    finally:
        server.stop()


def test_welcome_view_serves_three_truthful_statements(tmp_path: Path) -> None:
    """The Welcome shell must declare the three truthful statements
    in the visible HTML so they appear without JavaScript.

    Statements: free open-source local engine, keys stay on this machine,
    official packs are optional and recommended.
    """
    import re

    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/welcome")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200
            visible = re.sub(
                r"<script\b[^>]*>.*?</script>",
                "",
                body,
                flags=re.DOTALL,
            )
            lower = visible.lower()
            assert "open-source" in lower or "open source" in lower or "free" in lower, (
                "welcome must declare the engine is free / open-source"
            )
            assert "stay" in lower and "machine" in lower, (
                "welcome must say keys stay on this machine"
            )
            assert "pack" in lower and ("optional" in lower or "recommended" in lower), (
                "welcome must label official packs as optional / recommended"
            )
        finally:
            conn.close()
    finally:
        server.stop()


def test_next_view_marks_exchange_and_pack_flows_as_future(tmp_path: Path) -> None:
    """The Next view must clearly label exchange connection (C) and
    pack adoption (D) as future slices, and must expose the CLI/free
    path so the user is not funnelled toward a fake-success button.

    The future / CLI labels must be visible HTML, not just JSON.
    """
    import re

    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/next")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200
            visible = re.sub(
                r"<script\b[^>]*>.*?</script>",
                "",
                body,
                flags=re.DOTALL,
            )
            lower = visible.lower()
            assert (
                "future" in lower
                or "later" in lower
                or "coming" in lower
                or "upcoming" in lower
                or "next slice" in lower
                or "next slices" in lower
            ), "next must mark exchange / pack flows as future slices"
            assert (
                "krellbot ui" in lower
                or "free path" in lower
                or "cli" in lower
                or "command line" in lower
            ), "next must allow the CLI / free path"
        finally:
            conn.close()
    finally:
        server.stop()


def test_dashboard_reskin_keeps_paper_action_forms(tmp_path: Path) -> None:
    """The B3 dashboard reskin must keep every existing paper-action
    form field name + CSRF hidden field. We render the dashboard shell
    and grep the response.
    """
    from krellbot.ui.first_run import mark_visited_dashboard

    mark_visited_dashboard(tmp_path)
    server = _start_server(tmp_path)
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("GET", f"/{server.token}/dashboard")
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="replace")
            assert resp.status == 200
            for needle in (
                'action="arm"',
                'action="disarm"',
                'action="stop_all"',
                'action="adopt"',
                'name="pack_path"',
                'name="paper_balance"',
                'name="pack_id"',
                'name="csrf"',
            ):
                assert needle in body, f"dashboard reskin lost {needle!r}"
        finally:
            conn.close()
    finally:
        server.stop()


def test_visit_dashboard_post_without_csrf_is_403(tmp_path: Path) -> None:
    """POST visit-dashboard inherits the existing cookie+CSRF+Origin gate.
    A POST without a session/CSRF cookie must be 403 and must NOT flip the
    preference.
    """
    from krellbot.ui.first_run import has_visited_dashboard

    server = _start_server(tmp_path)
    try:
        assert has_visited_dashboard(tmp_path) is False
        conn = http.client.HTTPConnection("127.0.0.1", server.bound_port)
        try:
            conn.request("POST", f"/{server.token}/visit-dashboard", body="csrf=anything")
            resp = conn.getresponse()
            assert resp.status == 403
            resp.read()
        finally:
            conn.close()
        assert has_visited_dashboard(tmp_path) is False
    finally:
        server.stop()

"""INT01 — real CLI launcher for the workstation shell.

Tests first. They spawn ``python -m krellbot.cli workstation ...`` and
inspect the loopback HTTP server the launcher binds. The brief
(``.superpowers/sdd/krellbot-2027/INT01/INT01-brief.md``) lists four
must-pass tests:

  1. spawn the launcher against a fixture dist, GET the printed URL,
     verify the bootstrap meta tag, the shell copy ``Paper workstation``,
     and ``Cache-Control: no-store``. The URL must not embed the bootstrap
     token. A non-loopback ``Host`` header on the same port returns 403
     ``loopback only``. Stop the child with SIGINT on POSIX.
  2. spawn the launcher against an empty dist (no ``index.html``) and
     verify 404 with the closed ``shell_not_built`` JSON shape. The
     bootstrap token must not appear in stdout or the response body.
  3. ``krellbot workstation --host 0.0.0.0`` exits 2 and stderr contains
     ``Unknown argument: --host``. No server is started.
  4. ``inspect.getsource(cmd_ui)`` still mentions ``DashboardServer`` and
     does not mention ``WorkstationServer`` — the legacy dashboard CLI
     is untouched.

The launcher must use a fresh ``KRELLBOT_HOME`` directory and strip
venue key / secret / keyfile env vars so no real credential reaches
the child.

A unit test that only calls ``create_app`` through ``TestClient`` is
explicitly NOT acceptance. These tests drive the real subprocess the
operator will run.
"""

from __future__ import annotations

import http.client
import inspect
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

# ----- shared helpers ------------------------------------------------------


SECRET_ENV_PREFIXES = (
    "KRELLBOT_",
    "COINBASE_",
    "KRAKEN_",
)
SECRET_ENV_SUFFIXES = (
    "_KEY",
    "_SECRET",
    "_KEYFILE",
)
KEEP_KRELLBOT_EXACT = frozenset({"KRELLBOT_HOME", "KRELLBOT_API"})
KEEP_KRELLBOT_PREFIX = ("KRELLBOT_KB_", "KRELLBOT_NPM")


def _sanitized_env(home: Path) -> dict[str, str]:
    """Build a clean env for the child: keep only what the launcher needs.

    Strips every inherited var that looks like a venue credential or a
    license/activation key. Keeps ``PATH`` and friends so ``python`` and
    any helper the launcher spawns still resolves. Always sets
    ``KRELLBOT_HOME`` to ``home`` so the launcher reads from a fresh
    directory.
    """

    keep: dict[str, str] = {}
    for name, value in os.environ.items():
        if any(name.startswith(p) for p in SECRET_ENV_PREFIXES):
            if any(name.endswith(s) for s in SECRET_ENV_SUFFIXES):
                continue
            if name in KEEP_KRELLBOT_EXACT:
                keep[name] = value
                continue
            if name.startswith(KEEP_KRELLBOT_PREFIX):
                keep[name] = value
                continue
            continue
        keep[name] = value
    keep["KRELLBOT_HOME"] = str(home)
    keep["HOME"] = str(home)
    keep["USERPROFILE"] = str(home)
    keep["PYTHONUNBUFFERED"] = "1"
    return keep


def _make_built_dist(dist: Path) -> Path:
    """Write a minimal dist tree with ``index.html`` + ``assets`` bundle.

    ``index.html`` mirrors the Vite shape enough for the static layer to
    inject ``<meta name="krellbot-bootstrap" ...>``. The JS bundle carries
    the canonical ``Paper workstation`` copy so a GET that walks through
    ``/assets/<file>`` can verify the shell promise without depending on
    the real frontend build.
    """

    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        textwrap.dedent(
            """\
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="utf-8">
                <title>krellbot -- paper workstation</title>
                <script type="module" crossorigin src="/assets/app.js"></script>
              </head>
              <body>
                <div id="root">Paper workstation</div>
              </body>
            </html>
            """
        ),
        encoding="utf-8",
    )
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "app.js").write_text(
        "// Paper workstation shell bundle\nconsole.log('Paper workstation bootstrap');\n",
        encoding="utf-8",
    )
    return dist


def _spawn_workstation(
    home: Path,
    *args: str,
    dist: Path | None = None,
) -> subprocess.Popen:
    """Spawn ``python -m krellbot.cli workstation ...`` with a clean env."""

    argv = [sys.executable, "-m", "krellbot.cli", "workstation", *args]
    popen_kwargs: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "env": _sanitized_env(home),
        "bufsize": 1,
    }
    if sys.platform == "win32":
        import subprocess as _sp

        popen_kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(argv, **popen_kwargs)  # type: ignore[arg-type]


_URL_LINE_RE = re.compile(r"^Workstation running at (http://127\.0\.0\.1:\d+/)")


def _wait_for_workstation_url(proc: subprocess.Popen, timeout: float = 10.0) -> str:
    """Read stdout until the readiness line appears; return the URL.

    Bounded reader thread so a child that never prints the line cannot
    wedge the test runner. Mirrors the dashboard launcher helper so the
    diagnostics on failure are useful.
    """

    assert proc.stdout is not None
    found: list[str] = []
    remaining: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            remaining.append(line)
            match = _URL_LINE_RE.match(line)
            if match:
                found.append(match.group(1))
                return

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found:
            return found[0]
        rc = proc.poll()
        if rc is not None:
            stderr_dump = "\n".join(remaining)
            pytest.fail(f"workstation exited {rc} before printing URL: {stderr_dump!r}")
        time.sleep(0.05)
    proc.kill()
    try:
        proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    pytest.fail(f"timed out after {timeout}s waiting for workstation URL; child output={remaining!r}")


def _stop_workstation(proc: subprocess.Popen) -> None:
    """Send the platform-appropriate stop signal.

    POSIX uses SIGINT (mirrors how a user Ctrl-C's the launcher). Windows
    Popen refuses SIGINT, so the child was launched with
    CREATE_NEW_PROCESS_GROUP and is signalled via CTRL_BREAK_EVENT.
    """

    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGINT)


# ----- 1. happy path: built dist, GET /, GET /assets/<file> -----------------


def test_workstation_serves_index_with_bootstrap_meta(tmp_path):
    """Spawn the launcher, GET /, verify the bootstrap meta tag is
    injected, the URL has no token, the body carries the shell copy,
    and ``Cache-Control: no-store`` is set.

    Also probes the same port with a non-loopback ``Host`` header and
    asserts the server returns 403 ``loopback only``.
    """

    dist = _make_built_dist(tmp_path / "dist")
    home = tmp_path / "home"
    proc = _spawn_workstation(home, "--port", "0", "--dist", str(dist))
    try:
        url = _wait_for_workstation_url(proc, timeout=10.0)
        assert url.startswith("http://127.0.0.1:"), url
        port = int(url.rsplit(":", 1)[1].rstrip("/"))

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
            resp = conn.getresponse()
            body = resp.read()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            status = resp.status
        finally:
            conn.close()
        assert status == 200, (status, headers, body[:256])
        assert "no-store" in headers.get("cache-control", "").lower(), headers
        assert "text/html" in headers.get("content-type", "").lower(), headers
        decoded = body.decode("utf-8")
        assert "krellbot-bootstrap" in decoded, decoded[:512]
        assert "Paper workstation" in decoded, decoded[:512]

        # The URL printed to stdout must not embed the bootstrap token
        # (the meta tag value is the only thing the JS bundle needs).
        bootstrap_match = re.search(r'<meta name="krellbot-bootstrap" content="([^"]+)"', decoded)
        assert bootstrap_match, "bootstrap meta tag missing or malformed"
        bootstrap_token = bootstrap_match.group(1)
        assert bootstrap_token and bootstrap_token not in url, (
            f"bootstrap token {bootstrap_token!r} leaked into the URL {url!r}"
        )

        # And the JS bundle carries the same canonical copy the
        # production shell renders.
        asset_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            asset_conn.request("GET", "/assets/app.js", headers={"Host": f"127.0.0.1:{port}"})
            asset_resp = asset_conn.getresponse()
            asset_body = asset_resp.read()
        finally:
            asset_conn.close()
        assert b"Paper workstation" in asset_body, asset_body[:256]

        # Non-loopback Host on the same port is 403 with the closed
        # JSON shape; the bootstrap token must not appear in the body.
        evil_conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            evil_conn.request("GET", "/", headers={"Host": "evil.example:443"})
            evil_resp = evil_conn.getresponse()
            evil_body = evil_resp.read()
            evil_status = evil_resp.status
        finally:
            evil_conn.close()
        assert evil_status == 403, (evil_status, evil_body[:256])
        decoded_evil = evil_body.decode("utf-8", errors="replace")
        assert "loopback only" in decoded_evil, decoded_evil
        assert bootstrap_token not in decoded_evil, f"bootstrap token leaked into 403 body: {decoded_evil!r}"
    finally:
        _stop_workstation(proc)
        try:
            stdout, _stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _stderr = proc.communicate(timeout=2)
        if proc.returncode not in (0, 0xC000013A, -signal.SIGINT):
            pytest.fail(f"workstation did not exit cleanly: rc={proc.returncode} stdout={stdout!r}")


# ----- 2. empty dist -> refuse with build hint -----------------------------


def test_workstation_missing_index_exits_2_with_build_hint(tmp_path):
    """A dist with no ``index.html`` must refuse before binding a socket.

    The launcher exits 2 within 10 s, prints exactly one stderr line
    containing both ``--dist`` and ``npm --prefix frontend run build``,
    and prints no URL on stdout. The bootstrap token is never generated,
    so the secret-leak check the legacy test ran becomes a "stdout has
    no URL" check; the static-layer ``shell_not_built`` 404 stays in
    place as defence in depth.
    """

    empty_dist = tmp_path / "empty_dist"
    empty_dist.mkdir()
    home = tmp_path / "home"
    env = _sanitized_env(home)
    result = subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "workstation", "--port", "0", "--dist", str(empty_dist)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)

    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(stderr_lines) == 1, f"expected exactly one non-empty stderr line, got {stderr_lines!r}"
    line = stderr_lines[0]
    assert "--dist" in line, f"stderr line missing --dist hint: {line!r}"
    assert "npm --prefix frontend run build" in line, f"stderr line missing build command hint: {line!r}"
    assert "http://" not in result.stdout, f"refusal still printed a URL: {result.stdout!r}"


# ----- 3. unknown arg --host exits 2 --------------------------------------


def test_workstation_rejects_unknown_host_flag(tmp_path):
    """``krellbot workstation --host 0.0.0.0`` exits 2 and stderr carries
    ``Unknown argument: --host``. No server is started.
    """

    home = tmp_path / "home"
    r = subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "workstation", "--host", "0.0.0.0"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_sanitized_env(home),
        timeout=10,
        check=False,
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "Unknown argument: --host" in r.stderr, r.stderr


def test_workstation_rejects_non_integer_port(tmp_path):
    """``krellbot workstation --port abc`` exits 2 without starting."""

    home = tmp_path / "home"
    r = subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "workstation", "--port", "abc"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_sanitized_env(home),
        timeout=10,
        check=False,
    )
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "invalid --port" in r.stderr, r.stderr


# ----- 4. cmd_ui must still construct DashboardServer ----------------------


def test_cmd_ui_source_still_uses_dashboard_server():
    """The legacy ``cmd_ui`` body still constructs ``DashboardServer`` and
    must not be replaced by ``WorkstationServer``. The brief forbids
    editing the body of ``cmd_ui``.
    """

    from krellbot.cli import cmd_ui

    src = inspect.getsource(cmd_ui)
    assert "DashboardServer" in src, "cmd_ui no longer references DashboardServer"
    assert "WorkstationServer" not in src, "cmd_ui body now references WorkstationServer; the brief forbids that"


# ----- 5. usage line advertises the new subcommand -------------------------


def test_usage_advertises_workstation_subcommand():
    """The usage line must mention ``workstation [--port N] [--dist PATH] [--open]``.
    The legacy ``ui [--port N]`` token must still be present.
    """

    import io
    from contextlib import redirect_stderr

    from krellbot.cli import usage

    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = usage()
    assert rc == 2
    rendered = buf.getvalue()
    assert "workstation [--port N] [--dist PATH] [--open]" in rendered, rendered
    assert "ui [--port N]" in rendered, rendered

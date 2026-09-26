"""Tests for scripts/ci_smoke_ui.py.

We can't run the real frozen binary's dashboard in CI without doing
the full PyInstaller build (too slow), so this test suite
exercises the helper with a fake `krellbot` script that prints a
token URL and then opens an http.server on the loopback that
mimics the gate (200 on `/{token}/`, 200 on `/{token}/static/<f>`,
403 on `/deadbeef/`).
"""

from __future__ import annotations

import http.server
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
HELPER = SCRIPTS_DIR / "ci_smoke_ui.py"


class _FakeDashboardHandler(http.server.BaseHTTPRequestHandler):
    """Mimics the real token-gated dashboard's responses."""

    TOKEN = "f" * 64  # 64 hex chars

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = self.path
        if path == "/" or path == f"/{self.TOKEN}/":
            body = b"<html><title>krellbot</title><body>hello</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith(f"/{self.TOKEN}/static/"):
            body = b"// fake static asset " + b"x" * 200
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _spawn_fake_krellbot(home: Path, port: int) -> subprocess.Popen:
    """Spawn a child process that prints the token URL then runs the fake dashboard."""
    # We need to inject the handler class into the child namespace
    # via a sitecustomize-style import. Simpler: write a temp module.
    handler_src = (
        "import http.server\n"
        "class _FakeDashboardHandler(http.server.BaseHTTPRequestHandler):\n"
        f"    TOKEN = '{_FakeDashboardHandler.TOKEN}'\n"
        "    def log_message(self, *a, **k): pass\n"
        "    def do_GET(self):\n"
        "        p = self.path\n"
        "        if p == '/' or p == f'/{self.TOKEN}/':\n"
        "            body = b'<html><title>krellbot</title><body>hello</body></html>'\n"
        "            self.send_response(200)\n"
        "            self.send_header('Content-Type', 'text/html; charset=utf-8')\n"
        "            self.send_header('Content-Length', str(len(body)))\n"
        "            self.end_headers()\n"
        "            self.wfile.write(body)\n"
        "            return\n"
        "        if p.startswith(f'/{self.TOKEN}/static/'):\n"
        "            body = b'// fake static asset ' + b'x' * 200\n"
        "            self.send_response(200)\n"
        "            self.send_header('Content-Type', 'application/javascript')\n"
        "            self.send_header('Content-Length', str(len(body)))\n"
        "            self.end_headers()\n"
        "            self.wfile.write(body)\n"
        "            return\n"
        "        self.send_response(403)\n"
        "        self.send_header('Content-Length', '0')\n"
        "        self.end_headers()\n"
    )
    home.mkdir(parents=True, exist_ok=True)
    handler_path = home / "_fake_handler.py"
    handler_path.write_text(handler_src, encoding="utf-8")
    driver = home / "_fake_driver.py"
    driver.write_text(
        "import sys, threading, http.server, socketserver, signal\n"
        f"sys.path.insert(0, {str(home)!r})\n"
        "from _fake_handler import _FakeDashboardHandler\n"
        f"PORT = {port}\n"
        f"TOKEN = '{_FakeDashboardHandler.TOKEN}'\n"
        "print(f'Dashboard running at http://127.0.0.1:{PORT}/{TOKEN}/', flush=True)\n"
        "print('Open it in your browser. Ctrl-C to stop.', flush=True)\n"
        "class H(_FakeDashboardHandler): pass\n"
        "srv = socketserver.TCPServer(('127.0.0.1', PORT), H)\n"
        "threading.Thread(target=srv.serve_forever, daemon=True).start()\n"
        "stop = threading.Event()\n"
        "def stop_now(*a): stop.set()\n"
        "signal.signal(signal.SIGINT, stop_now)\n"
        "signal.signal(signal.SIGTERM, stop_now)\n"
        "stop.wait()\n",
        encoding="utf-8",
    )
    return subprocess.Popen(
        [sys.executable, str(driver)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
        cwd=str(home),
        text=True,
        bufsize=1,
    )


def _wait_for_dashboard(port: int, deadline: float) -> bool:
    """Spin until 127.0.0.1:port accepts connections or deadline."""
    import socket

    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return True
        except OSError:
            time.sleep(0.05)
    return False


@pytest.fixture
def fake_dashboard(tmp_path):
    """Start a fake dashboard on a free port; yield the port; clean up."""
    import socket

    # Pick a free port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    home = tmp_path / "home"
    log = tmp_path / "dashboard.log"
    proc = _spawn_fake_krellbot(home, port)
    if not _wait_for_dashboard(port, time.time() + 5.0):
        proc.kill()
        pytest.fail("fake dashboard never bound port")
    try:
        yield {"port": port, "home": str(home), "log": str(log), "proc": proc}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def test_ci_smoke_ui_succeeds_against_fake_dashboard(fake_dashboard, tmp_path):
    """End-to-end: ci_smoke_ui.py drives a token-gated dashboard and asserts 200/200/403."""
    # The fake dashboard is already up at fake_dashboard["port"].
    # Spawn a tiny "fake krellbot binary" that prints the URL and
    # delegates to a long-lived http server we control — but the
    # helper only cares about the URL it parses from stdout and
    # the GETs it issues, so we can just point it at the running
    # fake directly. Easier: have the helper launch its OWN child.
    # The cleanest test is to run the helper against a child that
    # mimics the dashboard startup.
    fake_bin = tmp_path / "fake-krellbot"
    fake_bin.write_text(
        "#!/usr/bin/env python3\n"
        "import http.server, socketserver, signal, sys, threading\n"
        f"PORT={fake_dashboard['port']}\n"
        f"TOKEN='{_FakeDashboardHandler.TOKEN}'\n"
        "print(f'Dashboard running at http://127.0.0.1:{PORT}/{TOKEN}/', flush=True)\n"
        "print('Open it in your browser. Ctrl-C to stop.', flush=True)\n"
        "class H(_FakeDashboardHandler): pass\n"
        "from _fake_handler import _FakeDashboardHandler\n"
        "srv = socketserver.TCPServer(('127.0.0.1', PORT), H)\n"
        "threading.Thread(target=srv.serve_forever, daemon=True).start()\n"
        "stop = threading.Event()\n"
        "signal.signal(signal.SIGINT, lambda *a: stop.set())\n"
        "stop.wait()\n",
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)

    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(fake_bin),
            "--port",
            str(fake_dashboard["port"]),
            "--home",
            fake_dashboard["home"],
            "--log",
            fake_dashboard["log"],
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        env={
            **__import__("os").environ,
            "PYTHONPATH": str(fake_dashboard["home"]),
        },
        timeout=30,
    )
    assert rc.returncode == 0, (
        f"ci_smoke_ui exited {rc.returncode}; stderr={rc.stderr[:500]!r}; "
        f"stdout={rc.stdout[:500]!r}"
    )
    assert "ok:" in rc.stdout, rc.stdout


def test_ci_smoke_ui_fails_when_dashboard_does_not_start(tmp_path):
    """If the binary never prints a URL, the helper exits 3."""
    fake_bin = tmp_path / "silent-krellbot"
    fake_bin.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(15)\n",  # never prints a URL within the 10s deadline
        encoding="utf-8",
    )
    fake_bin.chmod(0o755)

    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(fake_bin),
            "--port",
            "18877",
            "--home",
            str(tmp_path / "home"),
            "--log",
            str(tmp_path / "silent.log"),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
        timeout=30,
    )
    assert rc.returncode == 3, (
        f"expected exit 3 (no URL); got {rc.returncode}; "
        f"stderr={rc.stderr[:500]!r}"
    )
    assert "dashboard never printed" in rc.stderr
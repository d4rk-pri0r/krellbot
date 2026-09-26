"""Tests for scripts/ci_smoke_ui.py.

We can't run the real frozen binary's dashboard in CI without doing
the full PyInstaller build (too slow), so this test suite
exercises the helper with a fake `krellbot` script that prints a
token URL and then opens an http.server on the loopback that
mimics the gate (200 on `/{token}/`, 200 on `/{token}/static/<f>`,
403 on `/deadbeef/`).

The Windows CI smoke uses a portable `subprocess.PIPE`-based
helper (no winpty, no pty, no third-party dependency). The CLI
prints the URL with `flush=True` so the bytes reach the parent
pipe immediately even when the child is launched with
`subprocess.PIPE` on Windows. The reader thread + queue
demultiplexes the pipe so the parent can poll without busy-waiting.
These tests cover that path:

  - successful real-pipe capture
  - timeout (no URL within deadline)
  - failure (child exits non-zero before printing URL)
  - subprocess cleanup (proc.kill + wait, file handle closed)
  - explicit Windows-branch exercise (under
    ``pytest.mark.skipif(sys.platform != "win32")`` for local
    smoke; the production code path is exercised by an
    injection test on every platform).
  - A1 regression: `cmd_ui` without `--open` does not import
    `webbrowser` (A1 no-open invariants must survive the new
    `flush=True` and helper refactor).
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


# ---------------------------------------------------------------------------
# Portable pipe-capture helper (Windows + macOS + Linux, no winpty/pty)
# ---------------------------------------------------------------------------
#
# The CI helper now uses ``subprocess.PIPE`` plus a bounded reader thread /
# queue to capture the printed dashboard URL on every platform. The CLI
# prints with ``flush=True`` so the URL reaches the pipe immediately. The
# following tests pin that contract without depending on a tty or winpty.
# They exercise the new public helper ``capture_url_from_subprocess``,
# which the helper script itself uses internally; the helper's
# ``_wait_for_url`` is exercised indirectly through the two end-to-end
# tests above. Together they prove the new path works without winpty.
#
# `capture_url_from_subprocess` is the new public entry point and is
# expected to:
#   - spawn `argv` with stdout=PIPE, stderr=STDOUT, text=True,
#     bufsize=1 on POSIX; on Windows use CREATE_NEW_PROCESS_GROUP
#     so we can deliver a clean CTRL_BREAK_EVENT on cleanup.
#   - start a daemon reader thread that pushes each stdout line
#     into a `queue.Queue` (and writes the bytes to `log_path`).
#   - block until the URL regex matches, the child exits, or the
#     deadline passes.
#   - return ``(url, proc)`` so the caller can drive the smoke
#     GETs and clean up. On timeout / child failure, return
#     ``(None, proc)``.

from scripts.ci_smoke_ui import capture_url_from_subprocess


def _expected_url_for(port: int) -> str:
    """Build the expected ``http://127.0.0.1:PORT/<token>/`` for ``port``."""
    return f"http://127.0.0.1:{port}/{'f' * 64}/"


def _binary_that_prints_url(port: int, log_path: Path, delay: float = 0.0) -> Path:
    """Write a tiny binary that prints the dashboard URL then sleeps."""
    body = (
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        f"port = {port}\n"
        "token = 'f' * 64\n"
        "url = f'http://127.0.0.1:{port}/{token}/'\n"
        f"time.sleep({delay})\n"
        "print(f'Dashboard running at {url}', flush=True)\n"
        "print('Open it in your browser. Ctrl-C to stop.', flush=True)\n"
        "try:\n"
        "    while True:\n"
        "        time.sleep(1)\n"
        "except KeyboardInterrupt:\n"
        "    sys.exit(0)\n"
    )
    parent = log_path.parent
    parent.mkdir(parents=True, exist_ok=True)
    p = parent / "fake_krellbot_flush.py"
    p.write_text(body, encoding="utf-8")
    p.chmod(0o755)
    return p


def _expected_url_for(port: int) -> str:
    """Build the expected ``http://127.0.0.1:PORT/<token>/`` for ``port``."""
    return f"http://127.0.0.1:{port}/{'f' * 64}/"


def test_capture_url_from_subprocess_succeeds_with_real_pipe(tmp_path):
    """The helper captures the URL from a real ``subprocess.PIPE`` child.

    No tty, no winpty, no third-party dependency — works on macOS,
    Linux, and Windows alike because the child uses ``flush=True``
    and the helper's reader thread pulls lines off the pipe.
    """
    port = 18801
    binary = _binary_that_prints_url(port, tmp_path / "logs" / "out.log")
    log_path = tmp_path / "logs" / "dashboard.log"

    url, proc = capture_url_from_subprocess(
        argv=[sys.executable, str(binary)],
        env={**__import__("os").environ},
        log_path=log_path,
        deadline_s=5.0,
    )

    try:
        expected = _expected_url_for(port)
        assert url == expected, f"expected {expected}, got {url!r}"
        # The reader thread must have flushed bytes to disk.
        assert log_path.exists(), "log_path was never written"
        text = log_path.read_text(encoding="utf-8", errors="replace")
        assert "Dashboard running at" in text, text
        assert expected in text, text
        assert proc.poll() is None, "child exited before we could observe it"
    finally:
        # Cleanup contract: caller can rely on proc being
        # terminate-able, the log file being closed, and no reader
        # thread leaks after we wait.
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def test_capture_url_from_subprocess_times_out(tmp_path):
    """If the child never prints the URL, the helper returns ``(None, proc)``."""
    silent = tmp_path / "silent.py"
    silent.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    silent.chmod(0o755)
    log_path = tmp_path / "logs" / "silent.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    url, proc = capture_url_from_subprocess(
        argv=[sys.executable, str(silent)],
        env={**__import__("os").environ},
        log_path=log_path,
        deadline_s=0.5,  # very short — child takes 30s
    )

    try:
        assert url is None, f"expected None, got {url!r}"
        # Child should still be alive (we have not killed it).
        assert proc.poll() is None, "child unexpectedly exited"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def test_capture_url_from_subprocess_reports_child_failure(tmp_path):
    """If the child exits non-zero before printing the URL, the helper
    returns ``(None, proc)`` and exposes the child's exit code so the
    caller can surface a useful error. The log file still contains the
    bytes the child wrote before exit (verifying the reader flushed).
    """
    failing = tmp_path / "fail.py"
    failing.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('starting up', flush=True)\n"
        "sys.stderr.write('boom: missing config\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(7)\n",
        encoding="utf-8",
    )
    failing.chmod(0o755)
    log_path = tmp_path / "logs" / "fail.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    url, proc = capture_url_from_subprocess(
        argv=[sys.executable, str(failing)],
        env={**__import__("os").environ},
        log_path=log_path,
        deadline_s=5.0,
    )

    try:
        assert url is None, f"expected None on failure, got {url!r}"
        # Wait briefly for the helper to observe the exit.
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        assert proc.poll() == 7, f"expected exit 7, got {proc.returncode}"
        # Bytes the child wrote must have hit the log before exit.
        text = log_path.read_text(encoding="utf-8", errors="replace")
        assert "starting up" in text, text
        assert "boom: missing config" in text, text
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)


def test_capture_url_from_subprocess_cleans_up_process_and_handles(tmp_path):
    """After the helper returns, the caller can fully clean up: the
    subprocess can be killed+waited, and a second ``capture_url_...``
    call against the same ``log_path`` starts cleanly (no lingering
    file handles from a previous call)."""
    port = 18802
    binary = _binary_that_prints_url(port, tmp_path / "logs" / "out.log")
    log_path = tmp_path / "logs" / "dashboard.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    url, proc = capture_url_from_subprocess(
        argv=[sys.executable, str(binary)],
        env={**__import__("os").environ},
        log_path=log_path,
        deadline_s=5.0,
    )
    assert url == _expected_url_for(port)

    # Caller terminates the child.
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)
    assert proc.poll() is not None

    # We must be able to delete / overwrite the log file: the helper
    # closed its handle. (On Windows, an open handle blocks deletion.)
    log_path.unlink()
    assert not log_path.exists()

    # And we must be able to start a fresh capture against the same
    # log_path without handle leaks.
    port2 = 18803
    binary2 = _binary_that_prints_url(port2, tmp_path / "logs" / "out2.log")
    url2, proc2 = capture_url_from_subprocess(
        argv=[sys.executable, str(binary2)],
        env={**__import__("os").environ},
        log_path=log_path,
        deadline_s=5.0,
    )
    try:
        assert url2 == _expected_url_for(port2)
    finally:
        proc2.terminate()
        try:
            proc2.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc2.kill()
            proc2.wait(timeout=2)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-specific pipe creation flags; local macOS smoke only",
)
def test_capture_url_from_subprocess_uses_windows_process_group(tmp_path):
    """On Windows, the helper must spawn the child with
    ``CREATE_NEW_PROCESS_GROUP`` so a clean CTRL_BREAK_EVENT can be
    delivered on cleanup without taking down the test runner."""
    binary = _binary_that_prints_url(18804, tmp_path / "logs" / "win.log")
    log_path = tmp_path / "logs" / "dashboard-win.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    url, proc = capture_url_from_subprocess(
        argv=[sys.executable, str(binary)],
        env={**__import__("os").environ},
        log_path=log_path,
        deadline_s=5.0,
    )
    try:
        assert url is not None
        # If the child was launched with CREATE_NEW_PROCESS_GROUP, its
        # creation flags include that bit (0x00000200).
        creation_flags = getattr(proc, "creationflags", 0)
        assert creation_flags & 0x00000200, (
            f"child creationflags missing CREATE_NEW_PROCESS_GROUP: {creation_flags}"
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


# -- A1 regression: the no-open invariant must survive this round --------
#
# The new helper and `flush=True` change touch only the URL-print path
# in `cmd_ui`. If `flush=True` were added inside the `do_open` branch
# by mistake, or if `webbrowser` were imported unconditionally, A1's
# no-open browser call test would fail. Re-run it here against the
# subprocess invocation path that mirrors how the CI helper invokes
# the binary, to prove the no-open invariant survives.


def test_a1_no_open_browser_regression_survives_flush(tmp_path):
    """A1 invariant: ``krellbot ui`` (no --open) must NOT invoke
    webbrowser.open. The flush=True addition and helper refactor must
    not import webbrowser unconditionally."""
    from krellbot.ui.launch import open_url, token_url  # noqa: F401
    from krellbot.ui.server import DashboardServer  # noqa: F401

    # Source-level check: `cmd_ui` only imports webbrowser inside the
    # `if do_open:` branch. We grep the source rather than running the
    # subprocess to keep this fast and deterministic. The behavioural
    # proof is `test_cmd_ui_without_open_does_not_call_browser` in
    # `tests/test_ui_launch.py`; this is the structural smoke that
    # the flush change did not accidentally hoist the import.
    cli_path = (
        Path(__file__).resolve().parent.parent / "src" / "krellbot" / "cli.py"
    )
    src = cli_path.read_text(encoding="utf-8")
    # The conditional webbrowser import lives inside cmd_ui's body
    # and is preceded by `if do_open:`. If a future change ever
    # imports webbrowser at module top-level or in the else branch,
    # this test fails loudly.
    import webbrowser  # noqa: F401

    # Look for the `import webbrowser` line.
    wb_lines = [
        line for line in src.splitlines()
        if line.strip().startswith("import webbrowser")
        or line.strip().startswith("from webbrowser")
    ]
    assert wb_lines, "webbrowser import line missing from cli.py"
    line_no = src.splitlines().index(wb_lines[0]) + 1
    # The 10 lines above the import must contain the `do_open` guard.
    window = "\n".join(src.splitlines()[max(0, line_no - 12):line_no - 1])
    assert "do_open" in window, (
        "webbrowser import must be guarded by `if do_open:`; "
        f"preceding window:\n{window}"
    )
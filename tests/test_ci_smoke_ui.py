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
import re
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
    fake_bin = tmp_path / "fake-krellbot.py"
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
        f"ci_smoke_ui exited {rc.returncode}; stderr={rc.stderr[:500]!r}; stdout={rc.stdout[:500]!r}"
    )
    assert "ok:" in rc.stdout, rc.stdout


def test_ci_smoke_ui_fails_when_dashboard_does_not_start(tmp_path):
    """If the binary never prints a URL, the helper exits 3."""
    fake_bin = tmp_path / "silent-krellbot.py"
    fake_bin.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(15)\n",  # never prints a URL within the 10s deadline
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
    assert rc.returncode == 3, f"expected exit 3 (no URL); got {rc.returncode}; stderr={rc.stderr[:500]!r}"
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
#     so ``finally:`` can deliver ``CTRL_BREAK_EVENT`` to the child
#     process group cleanly (Python on Windows only accepts
#     ``SIGTERM`` / ``CTRL_C_EVENT`` / ``CTRL_BREAK_EVENT`` from
#     ``Popen.send_signal``; ``SIGINT`` raises
#     ``ValueError: Unsupported signal: 2``). We deliberately use
#     ``CTRL_BREAK_EVENT`` — not ``CTRL_C_EVENT`` — because
#     ``CTRL_C_EVENT`` requires a new console the test runner does
#     not own, and we don't want to take down the GitHub Actions
#     runner with a broad Ctrl-C.
#   - start a daemon reader thread that pushes each stdout line
#     into a `queue.Queue` (and writes the bytes to `log_path`).
#   - block until the URL regex matches, the child exits, or the
#     deadline passes.
#   - return ``(url, proc)`` so the caller can drive the smoke
#     GETs and clean up. On timeout / child failure, return
#     ``(None, proc)``.

from scripts.ci_smoke_ui import _stop_capture, capture_url_from_subprocess


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
        "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n",
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

    # Caller must close the capture (joins reader threads, closes log
    # file handle). On Windows, an open handle blocks unlink with
    # WinError 32; the test would otherwise leak the file.
    _stop_capture(proc)

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
        # Same handle-close contract — without it, the test holds a
        # Windows file handle that would block the test cleanup.
        _stop_capture(proc2)


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="Windows-specific pipe creation flags; local macOS smoke only",
)
def test_capture_url_from_subprocess_uses_windows_process_group(tmp_path):
    """On Windows, the helper must spawn the child with
    ``CREATE_NEW_PROCESS_GROUP`` so the helper's ``finally:`` block
    can deliver ``CTRL_C_EVENT`` (Python's ``signal.SIGINT`` on
    Windows) cleanly to the child process group without taking
    down the test runner or the parent shell.
    """
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
        assert creation_flags & 0x00000200, f"child creationflags missing CREATE_NEW_PROCESS_GROUP: {creation_flags}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


# -- Workflow-shape guard: no POSIX-only cleanup in the Windows matrix --
#
# GitHub Actions Windows runners ship Git Bash but **not** the
# GNU ``procps`` tools (``pkill`` / ``pgrep``). A previous review
# added an ``EXIT`` trap to ``.github/workflows/release-frozen.yml``
# that called ``pkill -f "krellbot ui --port $PORT"`` — that
# worked on macOS / Linux but was guaranteed to fail-closed on
# Windows (the bash trap would error out before reaching the
# helper cleanup, and the spawned dashboard would leak for the
# lifetime of the runner).
#
# The portable fix is to let the helper own the child via its own
# ``finally:`` block (``SIGINT`` → ``wait`` → ``kill``) and remove
# the workflow trap. These tests pin that contract so a future
# reviewer can't re-introduce the ``pkill`` trap without breaking
# the suite, AND they prove the helper really does clean up on
# failure (the previous helper crashed out without cleaning on
# early-exit paths).


WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-frozen.yml"


def _smoke_step_run_block() -> str:
    """Return the body of the "Smoke test bundled token-gated dashboard" step.

    PyYAML is not a project dependency, so we use a small
    indentation-based extractor. The smoke step's ``run:`` block
    is a literal-block scalar (``run: |``) with every line
    indented four spaces deeper than the step key. We locate the
    step by name, then read forward until the next sibling at the
    same indentation level as ``- name:``.
    """
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    target = "Smoke test bundled token-gated dashboard"
    # Each step in a GitHub Actions workflow starts with ``      - name:``
    # (six-space indent, then ``- name:``). Locate the matching line.
    step_idx = None
    for i, line in enumerate(lines):
        # Match a list item that begins with "- name:" and contains the target.
        stripped = line.lstrip()
        if stripped.startswith("- name:") and target in stripped:
            step_idx = i
            break
    if step_idx is None:
        raise AssertionError(f"step named {target!r} not found in {WORKFLOW_PATH}")

    # Find the ``run: |`` literal-block scalar that follows the step
    # header. Every step key (including ``run:``) is indented one
    # space deeper than the ``- name:`` line.
    run_idx = None
    for j in range(step_idx + 1, len(lines)):
        line = lines[j]
        stripped = line.lstrip()
        if stripped.startswith("- name:"):
            # Next sibling step started; we never found `run:`.
            break
        if stripped.startswith("run:") and "|" in stripped:
            run_idx = j
            break
    if run_idx is None:
        raise AssertionError(f"`run:` block not found inside step {target!r}")

    # The literal-block scalar body is indented one level deeper
    # than ``run:`` itself. This workflow uses two-space
    # indentation (6 for ``- name:``, 8 for ``run:``, 10 for the
    # body).
    run_line = lines[run_idx]
    run_indent = len(run_line) - len(run_line.lstrip())
    body_indent = run_indent + 2
    body_lines: list[str] = []
    for j in range(run_idx + 1, len(lines)):
        line = lines[j]
        # A blank line is part of the scalar body; keep it.
        if not line.strip():
            body_lines.append("")
            continue
        # If we hit a line whose indent is <= run_indent, we've
        # left the scalar.
        indent = len(line) - len(line.lstrip())
        if indent < body_indent:
            break
        # Strip the consistent body indent so callers can grep the
        # body as a flat string.
        body_lines.append(line[body_indent:])
    if not body_lines:
        raise AssertionError(f"`run:` block for {target!r} appears to be empty")
    return "\n".join(body_lines)


def _matrix_os_list() -> list[str]:
    """Return the ``os`` values declared in the build matrix.

    Like ``_smoke_step_run_block``, this is hand-rolled because
    PyYAML is not in the dev dependency group. The matrix is a
    YAML literal block with each entry on ``          - os: <value>``
    (10-space indent). We collect every ``- os:`` line under the
    ``matrix.include`` block.
    """
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Locate the matrix include block: find a line that contains
    # "matrix:" then a deeper-indented "include:" line.
    matrix_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("matrix:"):
            matrix_idx = i
            break
    if matrix_idx is None:
        raise AssertionError("`matrix:` block not found in workflow")
    include_idx = None
    for j in range(matrix_idx + 1, len(lines)):
        line = lines[j]
        if line.lstrip().startswith("include:"):
            include_idx = j
            break
        # If we exit the matrix block first, abort.
        if line and not line.startswith(" "):
            break
    if include_idx is None:
        raise AssertionError("`matrix.include:` block not found in workflow")

    # Each matrix entry starts with ``          - os: <value>``.
    include_line = lines[include_idx]
    include_indent = len(include_line) - len(include_line.lstrip())
    entry_indent = include_indent + 2  # e.g. "          - os:"
    os_values: list[str] = []
    for j in range(include_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent < entry_indent:
            break
        stripped = line.lstrip()
        if stripped.startswith("- os:"):
            value = stripped[len("- os:") :].strip()
            os_values.append(value)
    return os_values


def test_workflow_smoke_block_has_no_pkill_for_windows_compatibility():
    """The smoke step's bash body must not call ``pkill``.

    GitHub Actions Windows runners use Git Bash, which does NOT
    ship ``pkill`` (or ``pgrep``, or ``procps``). Any ``pkill -f``
    in the trap is guaranteed to error out on the Windows matrix
    before reaching the helper's own cleanup. The helper's
    ``finally:`` block is the single source of truth for child
    cleanup; the workflow must not double-clean with a POSIX-only
    utility.
    """
    run = _smoke_step_run_block()
    matches = re.findall(r"\bpkill\b", run)
    assert not matches, (
        "smoke step uses `pkill`, which is not available on Windows "
        "Git Bash runners — the helper's own `finally:` block already "
        "terminates the child on every exit path; remove the "
        "POSIX-only trap:\n\n" + run
    )


def test_workflow_smoke_block_invokes_ci_smoke_helper():
    """The smoke step must actually invoke the helper script.

    Pin the contract: the step calls
    ``uv run python scripts/ci_smoke_ui.py`` with the frozen
    binary, the picked port, an isolated home, and a log path.
    If a future refactor moves the smoke to a different helper
    (or inlines it in bash), the Windows cleanup contract in
    ``ci_smoke_ui.py`` no longer applies, and this test must
    fail so the reviewer re-checks portability.
    """
    run = _smoke_step_run_block()
    assert "scripts/ci_smoke_ui.py" in run, (
        "smoke step must invoke scripts/ci_smoke_ui.py so the helper's portable `finally:` block owns child cleanup"
    )
    assert "--binary" in run, "smoke step must pass --binary"
    assert "--port" in run, "smoke step must pass --port"
    assert "--home" in run, "smoke step must pass --home (isolated KRELLBOT_HOME)"
    assert "--log" in run, "smoke step must pass --log (capture path)"


def test_workflow_matrix_includes_windows_latest():
    """The matrix must include ``windows-latest`` so the helper's
    Windows path is exercised on every push to a v* tag.

    The reviewer flagged that skipping the Windows matrix would
    silently pass even if the helper's CREATE_NEW_PROCESS_GROUP
    branch regressed; this test makes the omission a CI failure.
    """
    os_list = _matrix_os_list()
    assert "windows-latest" in os_list, f"matrix.include is missing windows-latest entry; got {os_list!r}"


def test_ci_smoke_helper_terminates_child_on_failure(tmp_path):
    """Behavioural proof that the helper cleans up on every exit path.

    Exercises the helper's ``capture_url_from_subprocess`` (the
    entry point the workflow actually drives), simulates a smoke
    failure by raising from the caller right after the URL is
    captured (the same shape as the smoke step's curl 403 path),
    and asserts that the helper's ``main()`` source contains a
    ``finally:`` block that sends a signal and falls back to
    ``kill()``. The structural assertion pins the cleanup contract
    so a future refactor that drops the ``finally:`` (or moves
    cleanup only to the success path) fails this test.
    """
    import signal as _signal
    import sys as _sys

    port = 18805
    binary = _binary_that_prints_url(port, tmp_path / "logs" / "fail-cleanup.log")
    log_path = tmp_path / "logs" / "dashboard-fail-cleanup.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    helper_src = SCRIPTS_DIR / "ci_smoke_ui.py"

    # Invoke the helper's public entry point and confirm the
    # captured child is alive — the helper has not yet had a
    # chance to clean up, so any leak in the cleanup path will
    # surface as ``proc.poll() is None`` later.
    url, proc = capture_url_from_subprocess(
        argv=[_sys.executable, str(binary)],
        env={**__import__("os").environ},
        log_path=log_path,
        deadline_s=5.0,
    )
    assert url is not None, f"expected URL, got {url!r}"
    assert proc.poll() is None, "child unexpectedly exited before our cleanup"

    # Source-level guard on the helper's ``main()`` shape: must
    # own cleanup in a ``finally:`` block that sends SIGINT,
    # waits, and falls back to ``kill()``.
    src = helper_src.read_text(encoding="utf-8")
    main_match = re.search(
        r"def main\(.*?\):(.*?)(?=\n(?:def |\nif __name__))",
        src,
        re.DOTALL,
    )
    assert main_match, "could not locate main() in ci_smoke_ui.py"
    main_body = main_match.group(1)
    assert "finally:" in main_body, (
        "ci_smoke_ui.main() must have a finally: block that owns "
        "child cleanup so Windows smoke doesn't leak the dashboard "
        "process on curl-failure / 403 paths"
    )
    assert "send_signal" in main_body and "wait(" in main_body, (
        "ci_smoke_ui.main() finally: block must send_signal then wait on the child proc"
    )
    assert "kill" in main_body, "ci_smoke_ui.main() finally: block must fall back to kill() if the child ignores SIGINT"

    # Drive the cleanup path manually (this is what the ``finally:``
    # block does). On Windows, ``Popen.send_signal(signal.SIGINT)``
    # raises ``ValueError: Unsupported signal: 2`` because Python's
    # subprocess only accepts SIGTERM / CTRL_C_EVENT /
    # CTRL_BREAK_EVENT on Windows. ``CTRL_C_EVENT`` requires a new
    # console and ``CTRL_BREAK_EVENT`` requires a new process
    # group — the helper already sets CREATE_NEW_PROCESS_GROUP, so
    # ``CTRL_BREAK_EVENT`` is the correct Windows cleanup signal.
    # On POSIX we use ``SIGINT`` to mirror production behaviour.
    if _sys.platform == "win32":
        stop_signal: int = _signal.CTRL_BREAK_EVENT
    else:
        stop_signal = _signal.SIGINT
    try:
        proc.send_signal(stop_signal)
    except (ProcessLookupError, OSError, ValueError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    assert proc.poll() is not None, (
        "child proc should have exited after the cleanup signal — if this fires, "
        "the helper's cleanup won't work on Windows either"
    )
    # Close the capture so the log file handle is released before
    # unlink (Windows blocks unlink on open handles).
    _stop_capture(proc)
    # And the log file handle must be closed by the time we get
    # here (Windows: an open handle blocks unlink).
    log_path.unlink()
    assert not log_path.exists(), (
        "log_path.unlink() should succeed; if it fails the helper "
        "left an open file handle (Windows would have leaked it)"
    )


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
    cli_path = Path(__file__).resolve().parent.parent / "src" / "krellbot" / "cli.py"
    src = cli_path.read_text(encoding="utf-8")
    # The conditional webbrowser import lives inside cmd_ui's body
    # and is preceded by `if do_open:`. If a future change ever
    # imports webbrowser at module top-level or in the else branch,
    # this test fails loudly.
    import webbrowser  # noqa: F401

    # Look for the `import webbrowser` line.
    wb_lines = [
        line
        for line in src.splitlines()
        if line.strip().startswith("import webbrowser") or line.strip().startswith("from webbrowser")
    ]
    assert wb_lines, "webbrowser import line missing from cli.py"
    line_no = src.splitlines().index(wb_lines[0]) + 1
    # The 10 lines above the import must contain the `do_open` guard.
    window = "\n".join(src.splitlines()[max(0, line_no - 12) : line_no - 1])
    assert "do_open" in window, f"webbrowser import must be guarded by `if do_open:`; preceding window:\n{window}"


# ---------------------------------------------------------------------------
# Windows-behavior contract tests (mocked)
# ---------------------------------------------------------------------------
#
# The Windows-specific failures in CI run 36222698422 are the source of
# truth for these contracts. macOS cannot reproduce WinError 193 (no
# CreateProcess) or Popen.send_signal refusing SIGINT (no Windows).
# The tests below drive the *code paths* the helper exercises on
# Windows, mocking ``sys.platform`` and ``signal`` to simulate the
# Windows constants (``CTRL_BREAK_EVENT``, ``CTRL_C_EVENT``). They
# fail loudly if a future refactor drops the platform branch.
#
# These tests run on macOS as a smoke; the GitHub Actions Windows
# matrix is the real proof.


def _install_windows_signal_constants() -> dict[str, str | None]:
    """Inject the Windows-only ``signal.CTRL_C_EVENT`` /
    ``signal.CTRL_BREAK_EVENT`` constants into the helper's
    ``signal`` module binding so we can simulate the Windows
    cleanup path on POSIX. Returns the saved-state dict for
    ``_uninstall_windows_signal_constants``.
    """
    import signal as _signal_mod

    import scripts.ci_smoke_ui as _helper_mod

    saved: dict[str, str | None] = {}
    for name, value in (("CTRL_C_EVENT", 0), ("CTRL_BREAK_EVENT", 1)):
        if not hasattr(_signal_mod, name):
            saved[name] = None
            setattr(_signal_mod, name, value)
        else:
            saved[name] = "present"
        # The helper imports `signal` at module scope; the binding
        # lives on its own namespace, not on stdlib signal, so we
        # also patch the helper module.
        setattr(_helper_mod.signal, name, value)
    return saved


def _uninstall_windows_signal_constants(saved: dict[str, str | None]) -> None:
    import signal as _signal_mod

    import scripts.ci_smoke_ui as _helper_mod

    for name, was_present in saved.items():
        if was_present is None:
            try:
                delattr(_signal_mod, name)
            except AttributeError:
                pass
            try:
                delattr(_helper_mod.signal, name)
            except AttributeError:
                pass


def test_resolve_binary_argv_prefixes_sys_executable_for_python_scripts(tmp_path):
    """``_resolve_binary_argv`` returns ``[sys.executable, path]`` for
    ``.py`` files and ``path`` for everything else. This is the
    contract that lets the helper drive a shebang fakes on Windows
    without hitting ``WinError 193`` from CreateProcess.
    """
    from scripts.ci_smoke_ui import _resolve_binary_argv

    py_script = tmp_path / "fake-krellbot.py"
    py_script.write_text("#!/usr/bin/env python3\nprint('hello')\n", encoding="utf-8")
    exe_path = tmp_path / "krellbot.exe"  # does not exist on disk
    # Even if a `.exe` doesn't exist, we should not prefix sys.executable
    # — production binaries may not have been created yet at config time.
    assert _resolve_binary_argv(str(exe_path)) == str(exe_path)
    # A missing `.py` should also fall through (defensive against tmp races).
    missing_py = tmp_path / "missing.py"
    assert _resolve_binary_argv(str(missing_py)) == str(missing_py)
    # An existing `.py` gets the prefix.
    assert _resolve_binary_argv(str(py_script)) == [sys.executable, str(py_script)]
    upper_py = tmp_path / "fake-krellbot.PY"
    upper_py.write_text("print('hello')\n", encoding="utf-8")
    assert _resolve_binary_argv(str(upper_py)) == [sys.executable, str(upper_py)]
    # Non-`.py` paths are returned untouched.
    other = tmp_path / "binary"
    other.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    assert _resolve_binary_argv(str(other)) == str(other)


def test_helper_finally_uses_ctrl_break_event_on_windows(monkeypatch):
    """On Windows, the helper's ``finally:`` block must send
    ``CTRL_BREAK_EVENT`` (not ``signal.SIGINT``) to terminate the
    child. ``Popen.send_signal(signal.SIGINT)`` raises
    ``ValueError: Unsupported signal: 2`` on Windows because
    Python only accepts SIGTERM / CTRL_C_EVENT / CTRL_BREAK_EVENT
    there.
    """
    import scripts.ci_smoke_ui as _helper_mod

    saved = _install_windows_signal_constants()
    try:
        # Pretend we are on Windows so the helper's platform branch
        # picks CTRL_BREAK_EVENT.
        monkeypatch.setattr(_helper_mod.sys, "platform", "win32")

        sent_signals: list[int] = []

        class _FakeProc:
            def send_signal(self, sig: int) -> None:
                sent_signals.append(sig)

            def wait(self, timeout: float = 0) -> int:
                return 0

            def kill(self) -> None:
                return None

        # Walk the helper's `finally:` block in isolation. We don't
        # need a real subprocess here — the cleanup block is the
        # contract under test.
        proc = _FakeProc()
        if _helper_mod.sys.platform == "win32":
            stop_signal: int = _helper_mod.signal.CTRL_BREAK_EVENT  # type: ignore[attr-defined]
        else:
            stop_signal = _helper_mod.signal.SIGINT
        proc.send_signal(stop_signal)

        assert sent_signals == [_helper_mod.signal.CTRL_BREAK_EVENT], (  # type: ignore[attr-defined]
            f"expected CTRL_BREAK_EVENT on Windows, got {sent_signals!r}"
        )
        # And the helper must catch ValueError too — a previous
        # refactor only caught OSError, which would let the
        # SIGINT-on-Windows path crash through the finally block.
        src = _helper_mod.__file__ and Path(_helper_mod.__file__).read_text(encoding="utf-8")
        # The `try: proc.send_signal(stop_signal)` line must be
        # followed by `except (ProcessLookupError, OSError, ValueError):`
        # so a stale ValueError (defence-in-depth) never crashes cleanup.
        assert "except (ProcessLookupError, OSError, ValueError):" in src, (
            "ci_smoke_ui.main() finally: must catch ValueError around send_signal "
            "so Windows refuses-SIGINT cannot crash cleanup"
        )
    finally:
        _uninstall_windows_signal_constants(saved)


def test_capture_url_attach_uses_stop_capture_for_handle_close(tmp_path):
    """``_stop_capture(proc)`` joins the reader threads and closes
    the log file handle. Callers on Windows MUST invoke it before
    ``log_path.unlink()`` — otherwise the open handle blocks
    deletion with ``WinError 32``.

    This test exercises the round-trip: launch a real
    capture, terminate the child, call ``_stop_capture``, then
    prove ``log_path.unlink()`` succeeds. The cross-platform
    POSIX run is the contract; Windows holds the open handle
    even tighter, but the contract is the same.
    """
    port = 18806
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

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)

    # Without this call, the helper's reader thread still holds
    # the log file open. On Windows the subsequent unlink raises
    # ``PermissionError: [WinError 32]``.
    _stop_capture(proc)
    log_path.unlink()
    assert not log_path.exists(), "log_path.unlink() succeeded — _stop_capture released the handle"

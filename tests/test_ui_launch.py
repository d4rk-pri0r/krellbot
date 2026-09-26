"""Tests for the local UI launch helper.

The launch helper takes a started `DashboardServer` and an injected opener
callable, builds the gated URL, attempts to open it, and returns the URL
whether the open succeeded or not. The token never leaves the function —
no on-disk copy, no env-var side channel.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from krellbot.ui.launch import open_url, token_url
from krellbot.ui.server import DashboardServer

# ---- token_url ---------------------------------------------------------


def test_token_url_matches_gated_format(tmp_path):
    """`token_url` builds the same `http://127.0.0.1:{port}/{token}/`
    string the launcher uses, with no side effects."""
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        assert token_url(server) == f"http://127.0.0.1:{server.bound_port}/{server.token}/"
    finally:
        server.stop()


# ---- open_url ----------------------------------------------------------


def test_open_url_uses_current_server_token(tmp_path):
    """`open_url` must hand the started server's URL to the opener once."""
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        seen: list[str] = []
        url = open_url(server, lambda value: seen.append(value) or True)
        assert seen == [url]
        assert url == token_url(server)
    finally:
        server.stop()


def test_browser_failure_preserves_url(tmp_path):
    """If the opener returns False (or raises), the URL is still returned."""
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        url = open_url(server, lambda _: False)
        assert server.token in url and str(server.bound_port) in url
    finally:
        server.stop()


def test_open_url_swallows_opener_oserror(tmp_path):
    """A browser that raises OSError (e.g. headless, no DISPLAY) must not
    propagate — the URL is still printed so the user can paste it."""
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:

        def boom(_value: str) -> bool:
            raise OSError("no display")

        url = open_url(server, boom)
        assert url == token_url(server)
    finally:
        server.stop()


# ---- CLI flag tests ------------------------------------------------------


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"  # unroutable
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=15,
    )


def test_cmd_ui_rejects_unknown_host_flag(tmp_path):
    """`krellbot ui --host ...` must be refused: the server only binds
    to 127.0.0.1 and there is no host flag."""
    r = _run_cli(tmp_path, "ui", "--host", "0.0.0.0")
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "Unknown argument: --host" in r.stderr


# ---- Behavioral BROWSER-marker test -------------------------------------
#
# Strategy: write a tiny Python "browser" script that records every URL it
# is handed to a marker file, then point `BROWSER` at it and run the CLI
# as a subprocess. Python's stdlib `webbrowser` module honours `BROWSER`
# and instantiates a `GenericBrowser` whose command template includes
# `%s` for the URL. If `cmd_ui` calls `webbrowser.open`, the marker
# script runs and writes the URL to the marker file. If `cmd_ui` does
# NOT call it, the marker file is never created. Readiness is
# deterministic: the test waits on the `Dashboard running at ...`
# stdout line (which is emitted after the server binds and the URL is
# printed) before signalling the process — no sleep-only polling.
_MARKER_SCRIPT = textwrap.dedent(
    """\
    import pathlib, sys
    out = pathlib.Path(sys.argv[1])
    out.write_text(sys.argv[2] if len(sys.argv) > 2 else "", encoding="utf-8")
    """
)


def _spawn_ui_with_browser_marker(
    home: Path,
    marker_path: Path,
    marker_script: Path,
    *args: str,
) -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"
    # GenericBrowser substitutes %s with the URL when launching. Passing
    # %1$s first lets the marker script receive the marker-path and
    # URL as separate argv entries; the trailing %s is the URL
    # substitution webbrowser performs.
    env["BROWSER"] = f'"{sys.executable}" "{marker_script}" "{marker_path}" %s'
    # Flush stdout line-by-line so the parent's reader sees the
    # readiness signal as soon as cmd_ui prints it. Without this,
    # Python's block-buffered stdout keeps the URL line sitting in
    # the child's buffer until the process exits.
    env["PYTHONUNBUFFERED"] = "1"
    popen_kwargs: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "env": env,
    }
    # On Windows, ``Popen.send_signal(signal.SIGINT)`` raises
    # ``ValueError: Unsupported signal: 2``. The portable cleanup
    # signal is ``CTRL_BREAK_EVENT``, which only works when the
    # child was launched with ``CREATE_NEW_PROCESS_GROUP``. POSIX
    # doesn't need this flag (it has its own process group model).
    if sys.platform == "win32":
        import subprocess as _sp  # local import: CREATE_NEW_PROCESS_GROUP only on Windows

        popen_kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen([sys.executable, "-m", "krellbot.cli", *args], **popen_kwargs)  # type: ignore[arg-type]


def _stop_dashboard_proc(proc: subprocess.Popen) -> None:
    """Send the platform-appropriate cleanup signal to a dashboard child.

    On POSIX, ``SIGINT`` is the natural stop signal (matches how a
    user hits Ctrl-C in a terminal). On Windows, ``Popen.send_signal``
    refuses ``SIGINT`` with ``ValueError: Unsupported signal: 2``;
    only ``SIGTERM``, ``CTRL_C_EVENT``, and ``CTRL_BREAK_EVENT`` are
    accepted. ``CTRL_BREAK_EVENT`` is the right choice for a child
    launched with ``CREATE_NEW_PROCESS_GROUP`` (the dashboard child):
    it terminates the group without taking down the test runner.
    """
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGINT)


def _assert_stopped_cleanly(proc: subprocess.Popen, stdout: str, stderr: str) -> None:
    # Windows reports STATUS_CONTROL_C_EXIT after CTRL_BREAK_EVENT; POSIX
    # catches KeyboardInterrupt and exits 0. Both are expected teardown,
    # not a crash. Do not accept arbitrary nonzero exit codes.
    expected = (0, 0xC000013A) if sys.platform == "win32" else (0,)
    assert proc.returncode in expected, f"rc={proc.returncode} stdout={stdout!r} stderr={stderr!r}"


def _wait_for_dashboard_line(proc: subprocess.Popen, timeout: float = 10.0) -> str:
    """Block until `Dashboard running at ...` appears on the child's
    stdout, then return the line. Raises on timeout. This is a
    deterministic readiness signal (the URL line is printed only after
    the server is bound and the URL has been built) — no sleep-only
    polling on process startup."""
    assert proc.stdout is not None
    line_holder: list[str] = []
    exited: list[int | None] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if line.startswith("Dashboard running at "):
                line_holder.append(line)
                return

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if line_holder:
            return line_holder[0]
        rc = proc.poll()
        if rc is not None:
            exited.append(rc)
            break
        time.sleep(0.05)
    if line_holder:
        return line_holder[0]
    if exited:
        stderr = proc.stderr.read() if proc.stderr else ""
        pytest.fail(f"cmd_ui exited before printing the URL line: rc={exited[0]} stderr={stderr!r}")
    # A live child keeps stderr open. Stop it before collecting diagnostics;
    # reading to EOF first would block forever and defeat the deadline.
    proc.kill()
    try:
        stdout, stderr = proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        stdout, stderr = "", "child pipes stayed open after kill"
    pytest.fail(f"timed out after {timeout}s waiting for the Dashboard URL line; stdout={stdout!r} stderr={stderr!r}")


def test_dashboard_readiness_timeout_does_not_block_on_live_stderr():
    """A live child with no URL must fail at the deadline, not wait for EOF."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "import sys,time; print('BOOT_DIAG', file=sys.stderr, flush=True); time.sleep(2)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    started = time.monotonic()
    try:
        with pytest.raises(pytest.fail.Exception, match="timed out.*BOOT_DIAG"):
            _wait_for_dashboard_line(proc, timeout=0.1)
        assert time.monotonic() - started < 1.0
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)


def test_cmd_ui_without_open_does_not_call_browser(tmp_path):
    """`krellbot ui` without `--open` must not invoke any browser opener.

    Behavioral proof, not structural: a tiny marker "browser" is
    pointed at via the `BROWSER` env var (Python's stdlib `webbrowser`
    honours it and instantiates a `GenericBrowser` whose command
    template substitutes `%s` with the URL). After the subprocess
    exits, the marker file must NOT exist — i.e. the real stdlib
    `webbrowser.open` was never reached.
    """
    marker = tmp_path / "browser_marker.txt"
    script = tmp_path / "_marker_browser.py"
    script.write_text(_MARKER_SCRIPT, encoding="utf-8")
    proc = _spawn_ui_with_browser_marker(tmp_path, marker, script, "ui")
    try:
        line = _wait_for_dashboard_line(proc, timeout=10.0)
        assert line.startswith("Dashboard running at http://127.0.0.1:")
        _stop_dashboard_proc(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            pytest.fail(f"cmd_ui did not exit on stop signal; stdout={stdout!r} stderr={stderr!r}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    _assert_stopped_cleanly(proc, stdout, stderr)
    assert not marker.exists(), (
        "webbrowser.open was invoked even though --open was not passed; "
        f"marker contents: {marker.read_text(encoding='utf-8')!r}"
    )


def test_cmd_ui_with_open_invokes_browser(tmp_path):
    """Positive control: `krellbot ui --open` MUST invoke the browser
    opener (here, the marker script), writing the URL to the marker
    file. Pairs with `test_cmd_ui_without_open_does_not_call_browser`
    to prove the BROWSER-marker wiring actually observes what we
    expect it to observe — without this, a silent failure of the
    marker mechanism could make the negative test pass trivially."""
    marker = tmp_path / "browser_marker.txt"
    script = tmp_path / "_marker_browser.py"
    script.write_text(_MARKER_SCRIPT, encoding="utf-8")
    proc = _spawn_ui_with_browser_marker(tmp_path, marker, script, "ui", "--open")
    try:
        line = _wait_for_dashboard_line(proc, timeout=10.0)
        assert line.startswith("Dashboard running at http://127.0.0.1:")
        # The URL line is printed AFTER open_url returns. Inside open_url
        # the GenericBrowser spawns our marker script as a child
        # process; that child's write to disk races against our
        # stop signal of the parent. Bounded poll on the marker
        # file, not a sleep-on-launch — we KNOW the child has been
        # spawned.
        deadline = time.monotonic() + 5.0
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        _stop_dashboard_proc(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            pytest.fail(f"cmd_ui did not exit on stop signal; stdout={stdout!r} stderr={stderr!r}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    _assert_stopped_cleanly(proc, stdout, stderr)
    assert marker.exists(), "marker file not written — webbrowser.open did not run with --open"
    recorded = marker.read_text(encoding="utf-8")
    assert recorded.startswith("http://127.0.0.1:"), recorded

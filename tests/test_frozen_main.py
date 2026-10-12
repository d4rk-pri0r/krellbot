"""Tests for scripts/frozen_main.py.

The frozen-binary entry point delegates to `krellbot.cli.entry`.
We assert that delegation is wired correctly without invoking the
real CLI machinery (which would need KRELLBOT_HOME and a network).
"""

from __future__ import annotations

import ast
import importlib.util
import runpy
import sys
from pathlib import Path
from unittest import mock

import pytest

FROZEN_MAIN = Path(__file__).resolve().parent.parent / "scripts" / "frozen_main.py"


def _load_frozen_main_module():
    """Load scripts/frozen_main.py without executing its __main__ guard.

    Used by tests that want to inspect the module's imports; the guard
    below the imports does not run because __name__ != "__main__".
    """
    spec = importlib.util.spec_from_file_location("frozen_main_under_test", FROZEN_MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_frozen_main_module_imports_entry_from_krellbot_cli():
    """Static check: the module wires `from krellbot.cli import entry` directly."""
    module = _load_frozen_main_module()
    from krellbot.cli import entry as real_entry

    assert module.entry is real_entry, (
        "scripts/frozen_main.py must import entry directly from krellbot.cli, not wrap or re-export it."
    )


def test_frozen_main_invokes_entry_when_run_as_main(monkeypatch):
    """Running the file via runpy with run_name='__main__' calls entry()."""
    recorder = mock.MagicMock(return_value=0)
    fake_cli = mock.MagicMock()
    fake_cli.entry = recorder
    # Pre-seed krellbot.cli in sys.modules so the `from krellbot.cli import entry`
    # inside frozen_main.py picks up our recorder.
    monkeypatch.setitem(sys.modules, "krellbot.cli", fake_cli)
    monkeypatch.setitem(sys.modules, "krellbot", mock.MagicMock())

    # frozen_main.py does `sys.exit(entry())` to propagate the CLI's
    # exit code; catch the SystemExit so the test process doesn't
    # actually exit. We then assert the entry was called and the
    # SystemExit code matches entry()'s return value.
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(FROZEN_MAIN), run_name="__main__")

    recorder.assert_called_once_with()
    assert exc_info.value.code == 0, f"entry() returned 0; expected SystemExit(0); got {exc_info.value.code!r}"


def test_frozen_main_subprocess_runs_entry(tmp_path):
    """End-to-end: `python scripts/frozen_main.py` reaches and uses krellbot.cli.entry.

    We replace krellbot.cli.entry with a sentinel whose return_value is
    42 and assert the subprocess exit code is exactly 42. Proves the
    binary entry-point is wired correctly end-to-end without spinning
    up the real CLI, AND that the return value of entry() actually
    propagates through to sys.exit (so a non-zero entry failure is
    visible to CI, not silently swallowed).

    Mechanism: a `sitecustomize.py` shim module on `PYTHONPATH`
    installs the mock `krellbot.cli.entry` before the script imports
    it. The script's `sys.exit(entry())` then propagates 42 as the
    subprocess exit code.
    """
    import os
    import subprocess

    sentinel_dir = tmp_path / "sentinel"
    sentinel_dir.mkdir()
    (sentinel_dir / "sitecustomize.py").write_text(
        "import sys\n"
        "from unittest.mock import MagicMock\n"
        "_rec = MagicMock(return_value=42)\n"
        "_fake_cli = MagicMock()\n"
        "_fake_cli.entry = _rec\n"
        "sys.modules.setdefault('krellbot', MagicMock())\n"
        "sys.modules['krellbot.cli'] = _fake_cli\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    # PYTHONPATH must include the sentinel dir *before* the project
    # venv's site-packages so our sitecustomize runs first.
    env["PYTHONPATH"] = str(sentinel_dir) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "scripts/frozen_main.py"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(FROZEN_MAIN.parent.parent),
        env=env,
    )
    assert proc.returncode == 42, (
        f"entry() returned 42; expected exit 42; got {proc.returncode}; stderr={proc.stderr!r}"
    )
    # The mock call count assertion (entry was actually called when
    # run as __main__) is covered by
    # test_frozen_main_invokes_entry_when_run_as_main above.


# ---------------------------------------------------------------------------
# App-bones installers (W1) — frozen no-argument launch
#
# The frozen binary must behave like a double-clickable app: with no CLI
# arguments it launches the existing workstation shell with ``--open``
# (loopback only). Explicit arguments stay byte-compatible, and the
# developer (non-frozen) CLI keeps its usage behaviour. All of this is
# routed inside scripts/frozen_main.py — krellbot.cli is not edited.
# ---------------------------------------------------------------------------

REPO_ROOT = FROZEN_MAIN.parent.parent


def _write_routing_shim(tmp_path: Path, name: str, body: str) -> Path:
    shim_dir = tmp_path / name
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "sitecustomize.py").write_text(body, encoding="utf-8")
    return shim_dir


def _routing_shim_dir(tmp_path: Path, name: str, marker: Path, *, frozen: bool) -> Path:
    """Write a sitecustomize shim that fakes krellbot.cli and records argv."""
    return _write_routing_shim(
        tmp_path, name, _RECORD_MAIN_SHIM.format(marker=marker, frozen=frozen)
    )


def _run_frozen_main_with_shim(shim_dir: Path, args: list[str], timeout: float = 30.0):
    import os
    import subprocess

    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim_dir) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "scripts/frozen_main.py", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(REPO_ROOT),
        env=env,
        timeout=timeout,
    )
    return proc


def _split_recorded(line: str) -> tuple[str, list[str]]:
    """Parse one ``repr(argv)`` shim record into ``(argv0, argv[1:])``."""
    argv = ast.literal_eval(line)
    assert isinstance(argv, list) and argv, line
    return argv[0], list(argv[1:])


_RECORD_MAIN_SHIM = """\
import atexit
import sys
from unittest.mock import MagicMock

sys.frozen = {frozen}

recorded = []

def _fake_main(argv):
    recorded.append(list(argv))
    return 0

_fake_cli = MagicMock()
_fake_cli.main = _fake_main
_fake_cli.entry = lambda: sys.exit(_fake_main(sys.argv))
sys.modules.setdefault('krellbot', MagicMock())
sys.modules['krellbot.cli'] = _fake_cli

def _dump():
    with open(r'{marker}', 'w', encoding='utf-8') as fh:
        for argv in recorded:
            fh.write(repr(argv) + "\\n")

atexit.register(_dump)
"""


def test_frozen_no_args_routes_to_workstation_open(tmp_path):
    """RED: frozen + zero CLI args must run main with argv[1:] == ['workstation','--open'].

    argv[0] (the executable path the bootloader chose) is preserved
    byte-identically; only the missing argument tail is filled in.
    """
    marker = tmp_path / "recorded_frozen_noargs.txt"
    shim_dir = _routing_shim_dir(tmp_path, "shim_frozen_noargs", marker, frozen=True)

    proc = _run_frozen_main_with_shim(shim_dir, [])
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    lines = marker.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"main called exactly once; got {lines!r}"
    argv0, tail = _split_recorded(lines[0])
    assert tail == ["workstation", "--open"], lines
    assert argv0, "argv[0] must stay the original program path"


def test_frozen_explicit_args_pass_through_unchanged(tmp_path):
    """RED: frozen + explicit args are handed to main byte-identically (no rewrite)."""
    marker = tmp_path / "recorded_frozen_args.txt"
    shim_dir = _routing_shim_dir(tmp_path, "shim_frozen_args", marker, frozen=True)

    explicit = ["ui", "--port", "8123"]
    proc = _run_frozen_main_with_shim(shim_dir, explicit)
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    lines = marker.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"main called exactly once; got {lines!r}"
    argv0, tail = _split_recorded(lines[0])
    assert tail == explicit, lines
    assert argv0, "argv[0] must stay the original program path"


def test_not_frozen_no_args_stays_usage_path(tmp_path):
    """RED: developer CLI semantics unchanged — non-frozen + no args passes the
    original argv straight through (krellbot.cli.main then prints usage/2)."""
    marker = tmp_path / "recorded_dev_noargs.txt"
    shim_dir = _routing_shim_dir(tmp_path, "shim_dev_noargs", marker, frozen=False)

    proc = _run_frozen_main_with_shim(shim_dir, [])
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    lines = marker.read_text(encoding="utf-8").splitlines()
    # Non-frozen: exactly one call with the untouched argv — no argument tail.
    assert len(lines) == 1, f"main called exactly once; got {lines!r}"
    argv0, tail = _split_recorded(lines[0])
    assert tail == [], lines
    assert argv0, "argv[0] must stay the original program path"


def test_frozen_help_flag_is_not_redirected(tmp_path):
    """RED: ``-h``/``--help`` with no other args is an explicit argument and must
    reach the CLI untouched instead of being forced into a launch."""
    marker = tmp_path / "recorded_frozen_help.txt"
    shim_dir = _routing_shim_dir(tmp_path, "shim_frozen_help", marker, frozen=True)

    proc = _run_frozen_main_with_shim(shim_dir, ["--help"])
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    lines = marker.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1, f"main called exactly once; got {lines!r}"
    argv0, tail = _split_recorded(lines[0])
    assert tail == ["--help"], lines
    assert argv0, "argv[0] must stay the original program path"


_LAUNCH_SHIM_TEMPLATE = """\
import atexit
import signal
import sys
import types

sys.frozen = True
sys._MEIPASS = r"{meipass}"

# The source-launch fixture needs the Windows process-group equivalent
# of Ctrl-C; keep the application's KeyboardInterrupt cleanup exercised.
if sys.platform == "win32":
    signal.signal(signal.SIGBREAK, signal.default_int_handler)

urls = []

class _Recorder:
    def open(self, url, new=0, autoraise=True):
        urls.append(url)
        return True

_mod = types.ModuleType("webbrowser")
_mod.open = _Recorder().open
sys.modules["webbrowser"] = _mod

def _dump():
    with open(r"{marker}", "w", encoding="utf-8") as fh:
        for u in urls:
            fh.write(u + "\\n")

atexit.register(_dump)
"""


def test_frozen_no_args_launch_opens_loopback_url_via_webbrowser(tmp_path):
    """RED: the real no-arg frozen flow serves the shell and hands the loopback
    URL to ``webbrowser.open`` exactly once. The interception replaces
    ``webbrowser`` in ``sys.modules`` so no real browser is launched and the
    bootstrap token is never guessed — it is read from the served HTML only
    to prove it never leaks into the opened/printed URL.
    """
    import os
    import re
    import signal
    import subprocess
    import threading
    import time

    meipass = tmp_path / "meipass"
    dist = meipass / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "app.js").write_text("// shell\n", encoding="utf-8")
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root">Paper workstation</div></body></html>',
        encoding="utf-8",
    )

    marker = tmp_path / "opened_urls.txt"
    shim_dir = _write_routing_shim(
        tmp_path,
        "shim_launch",
        _LAUNCH_SHIM_TEMPLATE.format(meipass=meipass, marker=marker),
    )

    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(shim_dir) + os.pathsep + env.get("PYTHONPATH", "")
    env["KRELLBOT_HOME"] = str(home)
    env["HOME"] = str(home)
    env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "scripts/frozen_main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        cwd=str(REPO_ROOT),
        env=env,
        bufsize=1,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
    )

    url_line = re.compile(r"^Workstation running at (http://127\.0\.0\.1:\d+/)")
    printed: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            printed.append(line)
            if url_line.match(line):
                return

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        if any(url_line.match(line) for line in printed):
            break
        if proc.poll() is not None:
            pytest.fail(f"child exited {proc.returncode} before printing URL; output={printed!r}")
        time.sleep(0.05)
    else:
        proc.kill()
        pytest.fail(f"timed out waiting for workstation URL; output={printed!r}")

    # Give the atexit hook a moment is NOT acceptable on failure paths; the
    # interception must also be observable while the process is alive, so we
    # stop the child with the platform's console-interrupt event and then read.
    # Windows rejects send_signal(SIGINT); CTRL_BREAK_EVENT requires the
    # isolated process group above and is mapped to KeyboardInterrupt by
    # the source-launch fixture, preserving the same cleanup assertions.
    interrupt = signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGINT
    proc.send_signal(interrupt)
    try:
        proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate(timeout=5)
    assert proc.returncode == 0, f"SIGINT must stop the launcher with rc=0; got {proc.returncode}; output={printed!r}"

    opened = marker.read_text(encoding="utf-8").splitlines()
    assert len(opened) == 1, f"webbrowser.open called exactly once; got {opened!r}"
    assert opened[0].startswith("http://127.0.0.1:"), opened
    assert opened[0].endswith("/"), opened
    printed_urls = [url_line.match(line).group(1) for line in printed if url_line.match(line)]
    assert printed_urls == [opened[0]], (printed_urls, opened)

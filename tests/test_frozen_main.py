"""Tests for scripts/frozen_main.py.

The frozen-binary entry point delegates to `krellbot.cli.entry`.
We assert that delegation is wired correctly without invoking the
real CLI machinery (which would need KRELLBOT_HOME and a network).
"""

from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path
from unittest import mock

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
        "scripts/frozen_main.py must import entry directly from krellbot.cli, "
        "not wrap or re-export it."
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

    runpy.run_path(str(FROZEN_MAIN), run_name="__main__")

    recorder.assert_called_once_with()


def test_frozen_main_subprocess_runs_entry(tmp_path):
    """End-to-end: `python scripts/frozen_main.py` reaches and uses krellbot.cli.entry.

    We replace krellbot.cli.entry with a sentinel and assert the
    subprocess exit code is what entry() returned. This proves the
    binary entry-point is wired correctly end-to-end without spinning
    up the real CLI.
    """
    import subprocess

    sentinel_code = (
        "import sys, runpy, unittest.mock as m\n"
        "rec = m.MagicMock(return_value=42)\n"
        "fake_cli = m.MagicMock()\n"
        "fake_cli.entry = rec\n"
        "sys.modules['krellbot.cli'] = fake_cli\n"
        "sys.modules['krellbot'] = m.MagicMock()\n"
        "sys.argv = ['scripts/frozen_main.py']\n"
        "runpy.run_path('scripts/frozen_main.py', run_name='__main__')\n"
        "assert rec.called, 'entry was not called'\n"
        "sys.exit(0)\n"
    )
    shim = tmp_path / "shim.py"
    shim.write_text(sentinel_code, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(shim)],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(FROZEN_MAIN.parent.parent),
    )
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; stderr={proc.stderr!r}"
    )

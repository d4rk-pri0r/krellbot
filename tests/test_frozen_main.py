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

    # frozen_main.py does `sys.exit(entry())` to propagate the CLI's
    # exit code; catch the SystemExit so the test process doesn't
    # actually exit. We then assert the entry was called and the
    # SystemExit code matches entry()'s return value.
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(str(FROZEN_MAIN), run_name="__main__")

    recorder.assert_called_once_with()
    assert exc_info.value.code == 0, (
        f"entry() returned 0; expected SystemExit(0); got {exc_info.value.code!r}"
    )


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
        f"entry() returned 42; expected exit 42; got {proc.returncode}; "
        f"stderr={proc.stderr!r}"
    )
    # The mock call count assertion (entry was actually called when
    # run as __main__) is covered by
    # test_frozen_main_invokes_entry_when_run_as_main above.

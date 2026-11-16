"""Top-level ``krellbot uninstall`` is an honesty pointer, not a product.

Pins that the engine CLI refuses a false top-level uninstall surface and
points at the real paths: installer uninstall for the release install,
and ``krellbot service uninstall`` for the scheduler unit only.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr
from pathlib import Path

from krellbot import cli


def test_uninstall_prints_honest_pointer_and_exits_2(tmp_path: Path, monkeypatch) -> None:
    """``krellbot uninstall`` exits 2 with installer + service pointers."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path / "home"))
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = cli.main(["krellbot", "uninstall"])
    assert rc == 2
    text = buf.getvalue()
    assert "no top-level `krellbot uninstall` product command" in text
    assert "installer's uninstall flow" in text
    assert "krellbot service uninstall" in text


def test_uninstall_does_not_touch_home_or_advertise_in_usage(tmp_path: Path, monkeypatch) -> None:
    """Pointer must not mutate $KRELLBOT_HOME and must not join Usage."""
    home = tmp_path / "home"
    monkeypatch.setenv("KRELLBOT_HOME", str(home))
    assert not home.exists()
    with redirect_stderr(io.StringIO()):
        assert cli.main(["krellbot", "uninstall"]) == 2
    assert not home.exists()

    usage_buf = io.StringIO()
    with redirect_stderr(usage_buf):
        assert cli.usage() == 2
    usage = usage_buf.getvalue()
    assert "service install|uninstall" in usage
    # Do not advertise a top-level uninstall product next to real commands.
    assert " | uninstall " not in usage
    assert not usage.strip().startswith("Usage: krellbot uninstall")

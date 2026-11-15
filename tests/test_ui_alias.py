"""``ui`` is an engine-side alias for ``workstation``.

Pins, without binding a server or touching the network:

  1. ``main(["krellbot", "ui", ...])`` routes to the same handler as
     ``workstation`` with the same argument tail.
  2. Frozen no-arg rewrite fills in ``["ui", "--open"]``.
  3. There is still no legacy ``cmd_ui`` / DashboardServer path.
"""

from __future__ import annotations

import importlib.util
import io
from contextlib import redirect_stderr
from pathlib import Path

from krellbot import cli

FROZEN_MAIN = Path(__file__).resolve().parent.parent / "scripts" / "frozen_main.py"


def _load_frozen_main_module():
    spec = importlib.util.spec_from_file_location("frozen_main_ui_alias", FROZEN_MAIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ui_routes_to_workstation_handler_with_same_args(monkeypatch, tmp_path):
    """``krellbot ui --open --port 8791`` calls ``cmd_workstation`` with the
    same tail as ``krellbot workstation --open --port 8791``. No network.
    """
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path / "home"))
    recorded: list[list[str]] = []

    def _fake_workstation(args):
        recorded.append(list(args))
        return 0

    monkeypatch.setattr(cli, "cmd_workstation", _fake_workstation)

    assert cli.main(["krellbot", "ui", "--open", "--port", "8791"]) == 0
    assert cli.main(["krellbot", "workstation", "--open", "--port", "8791"]) == 0
    assert recorded == [
        ["--open", "--port", "8791"],
        ["--open", "--port", "8791"],
    ]


def test_ui_open_alone_matches_workstation_open(monkeypatch, tmp_path):
    """Bare ``ui --open`` (the site-wrapper default) matches ``workstation --open``."""
    monkeypatch.setenv("KRELLBOT_HOME", str(tmp_path / "home"))
    recorded: list[list[str]] = []

    def _fake_workstation(args):
        recorded.append(list(args))
        return 0

    monkeypatch.setattr(cli, "cmd_workstation", _fake_workstation)

    assert cli.main(["krellbot", "ui", "--open"]) == 0
    assert recorded == [["--open"]]


def test_frozen_no_args_rewrites_to_ui_open(monkeypatch):
    """Frozen + zero CLI args fills ``["ui", "--open"]`` (site-wrapper shape)."""
    module = _load_frozen_main_module()
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    assert module._apply_frozen_default_launch(["/opt/krellbot"]) == [
        "/opt/krellbot",
        "ui",
        "--open",
    ]
    assert module._FROZEN_DEFAULT_ARGS == ["ui", "--open"]


def test_frozen_explicit_ui_args_pass_through(monkeypatch):
    """Explicit ``ui ...`` on a frozen binary is not rewritten again."""
    module = _load_frozen_main_module()
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    argv = ["/opt/krellbot", "ui", "--open", "--port", "8123"]
    assert module._apply_frozen_default_launch(argv) == argv


def test_ui_alias_does_not_revive_legacy_cmd_ui():
    """The alias must not restore the deleted dashboard entry point."""
    assert not hasattr(cli, "cmd_ui")
    assert "DashboardServer" not in Path(cli.__file__).read_text(encoding="utf-8")


def test_usage_advertises_ui_as_workstation_alias():
    """Usage names ``workstation|ui`` with the shared flag set."""
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = cli.usage()
    assert rc == 2
    rendered = buf.getvalue()
    assert "workstation|ui [--port N] [--dist PATH] [--open]" in rendered, rendered

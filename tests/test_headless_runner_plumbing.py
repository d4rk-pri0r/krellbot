"""Headless / always-on runner is existing scheduler plumbing, not a new CLI.

M23.5 pins:

* Docs name the headless always-on entry as ``krellbot service install`` /
  the OS scheduler that fires ``tick`` (``docs/cli.md``, ``docs/service.md``).
* Tailscale / loopback honesty stays documented in ``docs/cli.md``.
* ``service.install`` under an injected write root writes a unit that
  invokes ``tick`` and proves ``krellbot.service.runner`` is importable.
* No new CLI user feature named ``headless``; ``PAPER_ONLY_RELEASE`` stays
  True.
"""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

from krellbot import release_policy

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLI_DOC = _REPO_ROOT / "docs" / "cli.md"
_SERVICE_DOC = _REPO_ROOT / "docs" / "service.md"


def _expected_unit_path(write_root: Path) -> Path | dict[str, Path]:
    if sys.platform == "darwin":
        return write_root / "Library" / "LaunchAgents" / "dev.krellbot.tick.plist"
    if sys.platform.startswith("linux"):
        d = write_root / ".config" / "systemd" / "user"
        return {
            "timer": d / "krellbot-tick.timer",
            "service": d / "krellbot-tick.service",
        }
    if sys.platform == "win32":
        return write_root / "Tasks" / "krellbot-tick.xml"
    raise RuntimeError(f"unsupported test platform: {sys.platform}")


def _unit_blob(path: Path | dict[str, Path]) -> str:
    if isinstance(path, dict):
        return "\n".join(p.read_text(encoding="utf-8") for p in path.values())
    return path.read_text(encoding="utf-8")


def test_docs_name_headless_service_install_and_scheduler() -> None:
    """Accept rg: headless | service install | scheduler in cli + service docs."""
    cli = _CLI_DOC.read_text(encoding="utf-8")
    service = _SERVICE_DOC.read_text(encoding="utf-8")
    combined = f"{cli}\n{service}"
    assert re.search(r"headless", combined, re.IGNORECASE)
    assert "service install" in combined
    assert re.search(r"scheduler", combined, re.IGNORECASE)
    assert re.search(r"headless", cli, re.IGNORECASE)
    assert re.search(r"headless", service, re.IGNORECASE)
    assert "service install" in cli
    assert "service install" in service


def test_cli_doc_pins_tailscale_loopback_honesty() -> None:
    """Always-on remote access stays Tailscale Serve + loopback, not Funnel."""
    text = _CLI_DOC.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "Tailscale" in text
    assert "loopback" in lowered
    assert "--tailscale-origin" in text
    assert "--tailscale-user" in text
    assert "tailscale serve" in lowered
    assert "Funnel" in text
    assert "never expose the backend directly" in lowered


def test_service_doc_names_headless_runner_entry_as_scheduler() -> None:
    """service.md documents the always-on entry as service install / tick."""
    text = _SERVICE_DOC.read_text(encoding="utf-8")
    assert re.search(r"Headless|always-on", text)
    assert "service install" in text
    assert "krellbot tick" in text or "`tick`" in text
    assert "krellbot.service.runner" in text
    assert "workstation" in text.lower()
    assert "loopback" in text.lower()
    assert "Tailscale" in text


def test_service_install_writes_tick_unit_under_injected_root(home: Path) -> None:
    """Headless runner install path writes OS unit invoking tick (fake root)."""
    from krellbot.service import install

    write_root = home / "write-root"
    rc = install(
        home,
        executable="/usr/local/bin/krellbot",
        write_root=write_root,
    )
    assert rc == 0
    unit = _expected_unit_path(write_root)
    if isinstance(unit, dict):
        for p in unit.values():
            assert p.is_file(), f"missing unit file: {p}"
    else:
        assert unit.is_file(), f"missing unit file: {unit}"
    blob = _unit_blob(unit)
    assert "tick" in blob
    assert str(home) in blob
    assert (home / "service" / "owners" / "default.owner").is_file()


def test_runner_is_importable_and_delegates_tick(monkeypatch) -> None:
    """Stable scheduler entry imports; tick argv reaches cli.main."""
    runner = importlib.import_module("krellbot.service.runner")
    assert hasattr(runner, "main")

    captured: list[list[str]] = []

    def _fake_main(argv: list[str]) -> int:
        captured.append(list(argv))
        return 0

    import krellbot.cli as kb_cli

    monkeypatch.setattr(kb_cli, "main", _fake_main)
    assert runner.main(["tick"]) == 0
    assert captured == [["krellbot", "tick"]]
    assert runner.main([]) == 2


def test_no_cli_headless_user_subcommand() -> None:
    """Plumbing only: CLI source must not advertise a headless user command."""
    from krellbot import cli as kb_cli

    source = Path(kb_cli.__file__).read_text(encoding="utf-8")
    assert "headless" not in source.lower()
    # Top-level dispatch stays service/tick plumbing, not a headless product.
    assert 'if cmd == "service"' in source or 'cmd == "service"' in source
    assert 'if cmd == "tick"' in source or 'cmd == "tick"' in source


def test_paper_only_release_stays_true() -> None:
    assert release_policy.PAPER_ONLY_RELEASE is True

"""Getting-started uninstall copy matches CLI honesty (post-M13.8).

Pins that ``docs/getting-started.md`` does not advertise a false top-level
``krellbot uninstall`` product path, and points at the installer uninstall
flow plus ``krellbot service uninstall`` like ``docs/cli.md``.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GETTING_STARTED = REPO_ROOT / "docs" / "getting-started.md"


def test_getting_started_uninstall_matches_cli_honesty() -> None:
    """Uninstall section refuses a fake top-level product command."""
    text = GETTING_STARTED.read_text(encoding="utf-8")
    assert "### Uninstall" in text
    assert "no top-level engine CLI product command named" in text
    assert "`krellbot uninstall`" in text
    assert "installer's" in text and "uninstall flow" in text
    assert "krellbot service uninstall" in text
    # Do not show a copy-paste block that looks like a working product command.
    assert "~/.local/bin/krellbot uninstall" not in text
    assert "# Windows\nkrellbot uninstall" not in text

"""Entry point for the PyInstaller-frozen krellbot binary.

PyInstaller invokes the module specified by `--entry-point` via
`python -m frozen_main` (or `python frozen_main.py`) and we then call
`krellbot.cli.entry()`. Keeping this in a dedicated module — rather
than pointing PyInstaller at `krellbot.cli` directly — means the
frozen build does not depend on `__main__.py` shenanigans inside the
installed package and the entry-point symbol is unambiguous.
"""

from __future__ import annotations

from krellbot.cli import entry

if __name__ == "__main__":
    entry()

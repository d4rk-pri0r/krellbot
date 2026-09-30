"""Entry point for the PyInstaller-frozen krellbot binary.

PyInstaller invokes the module specified by `--entry-point` via
`python -m frozen_main` (or `python frozen_main.py`) and we then call
`krellbot.cli.entry()`. Keeping this in a dedicated module — rather
than pointing PyInstaller at `krellbot.cli` directly — means the
frozen build does not depend on `__main__.py` shenanigans inside the
installed package and the entry-point symbol is unambiguous.

We `sys.exit(entry())` so the CLI's return code propagates as the
frozen binary's exit code. Without this, a non-zero return from
`krellbot.cli.entry` would be silently discarded by the bootloader
and CI would see exit 0 even when the CLI reported a failure.
"""

from __future__ import annotations

import sys

from krellbot.cli import entry

if __name__ == "__main__":
    sys.exit(entry())

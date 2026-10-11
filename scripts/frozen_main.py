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

No-argument launch (installed-app behaviour):

When the PyInstaller bootloader runs us (`sys.frozen` is truthy) and
the user supplied no CLI arguments, the binary behaves like a
double-clicked app: it fills in the argument tail
`["workstation", "--open"]` so the existing launcher starts the
loopback workstation shell and hands its URL to the default browser.
The rewrite happens here — never inside `krellbot.cli` — so the
developer CLI keeps its byte-compatible semantics (`python -m
krellbot.cli` with no arguments still prints usage and exits 2).
Explicit arguments are never rewritten: `krellbot.exe --version`,
`krellbot ui`, `krellbot workstation ...` reach the CLI untouched.
`argv[0]` (the path the bootloader chose) is preserved verbatim.
"""

from __future__ import annotations

import sys

from krellbot.cli import entry

_FROZEN_DEFAULT_ARGS = ["workstation", "--open"]


def _apply_frozen_default_launch(argv: list[str]) -> list[str]:
    """Return the argv to run: frozen + no user arguments -> workstation --open.

    Pure helper (no import of krellbot.cli, no I/O) so tests can pin the
    routing without touching a server. Only the argument tail is filled
    in; `argv[0]` and any explicit user arguments are returned verbatim.
    """
    if not argv:
        return argv
    if len(argv) > 1:
        return argv
    if not getattr(sys, "frozen", False):
        return argv
    return [argv[0], *_FROZEN_DEFAULT_ARGS]


if __name__ == "__main__":
    sys.argv = _apply_frozen_default_launch(sys.argv)
    sys.exit(entry())

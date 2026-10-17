"""Supervised tick runner — the entry point the OS scheduler invokes.

The ``krellbot service install`` command renders a launchd plist (macOS),
a systemd user timer+service pair (Linux), or a Windows task XML that
calls the installed ``executable`` with the ``tick`` argument. This
module is the package the scheduler points at — the executable resolves
``krellbot.service.runner`` and runs ``main()``.

This module is intentionally tiny: it exists so ``install`` can prove
the runner is importable before the scheduler unit is written. A broken
runner fails the install (with a clear traceback), not the scheduled
tick three hours later.

The actual tick loop lives in :mod:`krellbot.run` and is dispatched by
the CLI ``krellbot tick --venue <name>``. The runner here is a stable
entry point so the scheduler unit always points at the same module
path, even if the run-loop internals move.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    """Entry point invoked by the scheduler.

    The scheduler runs ``<executable> tick``. ``argv`` is the argument
    vector after the executable. The runner delegates a ``tick``
    invocation to ``krellbot.cli.main`` (lazy import) so the supervised
    tick path shares the CLI's parsing, fetch, transport, and
    supervision wiring. Any other first argument is a usage error and
    exits 2.

    Returns 0 on a successful invocation; non-zero on refusal. The OS
    scheduler only logs the exit code; the run loop journals per-tick
    outcomes under ``$KRELLBOT_HOME/journal/``.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "tick":
        from krellbot import cli as kb_cli

        rest = list(argv[1:])
        return kb_cli.main(["krellbot", "tick", *rest])
    print("usage: krellbot runner tick", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover — invoked by the scheduler
    raise SystemExit(main())

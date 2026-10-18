"""Test-only Python network guard/audit wrapper for journey tests.

This file is a TEMPLATE: the journey harness copies it into the spec's
temp ``KRELLBOT_HOME/support/`` directory and runs every Python
subprocess (workstation, CLI) through it. It is never imported by the
product.

Guarantees (Phase 2 owner authority, Step 2):
  * ``socket.getaddrinfo`` and ``socket.socket.connect``/``connect_ex``
    refuse non-loopback hosts BEFORE any network syscall is made — a
    refused off-loopback attempt is logged and raises, so the test
    fails on the attempt, not on a later symptom.
  * Every refusal is appended to a per-home audit log
    (``<home>/support/net-guard.log``) so violations are retained in
    artifacts even when the owning test already failed.
  * Loopback traffic (127.0.0.1, ::1, localhost, and the OS-assigned
    ephemeral bind ``127.0.0.1:0``) is untouched.
  * Unix-domain sockets (uv's IPC with its children) are untouched.
"""

from __future__ import annotations

import builtins
import json
import os
import socket
import sys
import time

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", ""})
_GUARD_LOG_ENV = "KRELLBOT_JOURNEY_NET_GUARD_LOG"


def _log(event: dict) -> None:
    path = os.environ.get(_GUARD_LOG_ENV)
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")
    except OSError:
        # The audit log must never crash the guarded program.
        pass


def _is_loopback_host(host) -> bool:
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        try:
            host = host.decode("utf-8", "replace")
        except Exception:
            return False
    text = str(host).strip("[]")
    if text in _LOOPBACK_HOSTS:
        return True
    if text.lower() in ("localhost",):
        return True
    # IPv4-mapped IPv6
    if text.lower().startswith("::ffff:"):
        return _is_loopback_host(text[7:])
    return False


class GuardRefusal(ConnectionRefusedError):
    """Raised when a non-loopback network attempt is refused."""


def install() -> None:
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def getaddrinfo(host, port, *args, **kwargs):
        if not _is_loopback_host(host):
            event = {
                "ts": time.time(),
                "kind": "getaddrinfo_refused",
                "host": str(host),
                "port": str(port),
                "pid": os.getpid(),
            }
            _log(event)
            raise GuardRefusal(
                f"journey network guard: refused off-loopback DNS resolution for {host!r}"
            )
        return real_getaddrinfo(host, port, *args, **kwargs)

    def _check(address):
        # A unix-domain address is a str/bytes path or a 2-tuple-less
        # object; leave everything that is not an AF_INET/AF_INET6
        # 2-tuple alone.
        if not isinstance(address, tuple) or len(address) < 2:
            return
        host, port = address[:2]
        if not _is_loopback_host(host):
            event = {
                "ts": time.time(),
                "kind": "connect_refused",
                "host": str(host),
                "port": str(port),
                "pid": os.getpid(),
            }
            _log(event)
            raise GuardRefusal(
                f"journey network guard: refused off-loopback connect to {host}:{port}"
            )

    def connect(self, address):
        _check(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check(address)
        return real_connect_ex(self, address)

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    socket.socket.connect = connect  # type: ignore[assignment]
    socket.socket.connect_ex = connect_ex  # type: ignore[assignment]


def main() -> int:
    install()
    argv = sys.argv[1:]
    if not argv:
        print("usage: python-socket-guard.py <program> [args...]", file=sys.stderr)
        return 2
    prog = argv[0]
    sys.argv = argv
    import runpy

    if prog == "-c":
        code = argv[1]
        exec(compile(code, "<guard>", "exec"), {"__name__": "__main__"})
        return 0
    if prog.endswith(".py"):
        runpy.run_path(prog, run_name="__main__")
        return 0
    # Module execution (e.g. ``-m krellbot ...`` arrives as
    # ["-m", "krellbot", ...] with prog == "-m"). The krellbot package
    # has no __main__; its entry point is krellbot.cli:entry.
    if prog == "-m":
        module = argv[1]
        if module == "krellbot":
            module = "krellbot.cli"
        sys.argv = ["krellbot"] + argv[2:]
        runpy.run_module(module, run_name="__main__", alter_sys=False)
        return 0
    print(f"journey net guard: unsupported program {prog!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

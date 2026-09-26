"""Tests for the local UI launch helper.

The launch helper takes a started `DashboardServer` and an injected opener
callable, builds the gated URL, attempts to open it, and returns the URL
whether the open succeeded or not. The token never leaves the function —
no on-disk copy, no env-var side channel.
"""

from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from krellbot import cli as kb_cli
from krellbot.ui.launch import open_url
from krellbot.ui.server import DashboardServer


def test_open_url_uses_current_server_token(tmp_path):
    """`open_url` must hand the started server's URL to the opener once."""
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        seen: list[str] = []
        url = open_url(server, lambda value: seen.append(value) or True)
        assert seen == [url]
        assert url == f"http://127.0.0.1:{server.bound_port}/{server.token}/"
    finally:
        server.stop()


def test_browser_failure_preserves_url(tmp_path):
    """If the opener returns False (or raises), the URL is still returned."""
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        url = open_url(server, lambda _: False)
        assert server.token in url and str(server.bound_port) in url
    finally:
        server.stop()


def test_open_url_swallows_opener_oserror(tmp_path):
    """A browser that raises OSError (e.g. headless, no DISPLAY) must not
    propagate — the URL is still printed so the user can paste it."""
    server = DashboardServer(home=tmp_path, port=0)
    server.start()
    try:
        def boom(_value: str) -> bool:
            raise OSError("no display")

        url = open_url(server, boom)
        assert url == f"http://127.0.0.1:{server.bound_port}/{server.token}/"
    finally:
        server.stop()


# ---- CLI flag tests -------------------------------------------------------


def _run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"  # unroutable
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=15,
    )


def test_cmd_ui_rejects_unknown_host_flag(tmp_path):
    """`krellbot ui --host ...` must be refused: the server only binds
    to 127.0.0.1 and there is no host flag."""
    r = _run_cli(tmp_path, "ui", "--host", "0.0.0.0")
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert "Unknown argument: --host" in r.stderr


def test_cmd_ui_without_open_does_not_call_browser(tmp_path):
    """`krellbot ui` without `--open` must not invoke any browser opener.

    Spawn the CLI as a subprocess, send SIGINT to let `cmd_ui` exit 0,
    and assert the URL line is still printed. The behavioral check is
    complemented by a structural AST check on `cli.py` that the only
    call to `webbrowser.open` lives inside the `if do_open` branch of
    `cmd_ui`, so the no-`--open` path is structurally incapable of
    opening a browser.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"
    proc = subprocess.Popen(
        [sys.executable, "-m", "krellbot.cli", "ui"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )
    try:
        time.sleep(1.0)
        proc.send_signal(signal.SIGINT)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            pytest.fail(f"cmd_ui did not exit on SIGINT; stdout={stdout!r} stderr={stderr!r}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert proc.returncode == 0, f"rc={proc.returncode} stdout={stdout!r} stderr={stderr!r}"
    assert "Dashboard running at http://127.0.0.1:" in stdout

    # Structural check: every reference to `webbrowser.open` in cli.py
    # must sit inside cmd_ui's `if do_open` branch. We catch both
    # attribute accesses (the call is open_url(server, webbrowser.open))
    # and Call nodes (defensive — would catch any direct invocation).
    cli_src = Path(kb_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(cli_src)
    refs: list[ast.AST] = []

    class _Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "webbrowser"
                and func.attr == "open"
            ):
                refs.append(node)
            self.generic_visit(node)

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if (
                isinstance(node.value, ast.Name)
                and node.value.id == "webbrowser"
                and node.attr == "open"
            ):
                refs.append(node)
            self.generic_visit(node)

    _Visitor().visit(tree)
    assert refs, "no webbrowser.open reference found in cli.py — the --open wiring is missing"

    parent_map: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parent_map[id(child)] = parent

    def _under_do_open(node: ast.AST) -> bool:
        # Walk the ancestor chain; allow `ast.If` (statement) or
        # `ast.IfExp` (ternary `... if do_open else ...`) as gates.
        current: ast.AST | None = node
        while current is not None:
            current = parent_map.get(id(current))  # type: ignore[assignment]
            if current is None:
                return False
            if isinstance(current, (ast.If, ast.IfExp)):
                test = current.test
                if isinstance(test, ast.Name) and test.id == "do_open":
                    return True
        return False

    for r in refs:
        assert _under_do_open(r), (
            "webbrowser.open is referenced outside the `if do_open:` gate in cmd_ui"
        )


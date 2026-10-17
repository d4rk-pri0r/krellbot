"""M1R-T2 — ``krellbot workstation`` from a clean ``git archive`` export.

Steward finding (M1-VERDICT row 1): from a clean checkout, a bare
``krellbot workstation`` binds and prints a URL, and ``GET /`` returns
``404 {"code":"shell_not_built"}``. The user sees a dead page. The
launcher must refuse up front and tell the operator how to build the
shell.

The two RED tests below export the current tree (matching
``git archive`` semantics: tracked + uncommitted non-ignored files,
``frontend/dist`` excluded by ``.gitignore``) and spawn the CLI
launcher against that export with ``KRELLBOT_HOME`` pointed at a
fresh directory.

* ``test_clean_export_workstation_refuses_with_build_hint`` asserts
  the launcher exits 2 within 15 s, prints one stderr line containing
  both ``--dist`` and ``npm --prefix frontend run build``, and prints
  no URL on stdout. This is the bug from the steward finding.

* ``test_clean_export_with_built_dist_serves_200`` writes a minimal
  ``frontend/dist/index.html`` into the same export, spawns the
  launcher without ``--dist``, parses the URL from stdout, and
  verifies ``GET /`` returns 200 with the ``krellbot-bootstrap`` meta
  tag the static layer injects. This guards the happy path so the
  refusal does not over-refuse.

Hard limits from the brief: no commit, push, tag, or branch change.
No build or commit of ``frontend/dist``. No network. No subagents.
Format only touched files.
"""

from __future__ import annotations

import http.client
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_URL_LINE_RE = re.compile(r"^Workstation running at (http://127\.0\.0\.1:\d+/)")


def _has_git() -> bool:
    """True iff ``git`` is on PATH; otherwise the export helper must skip."""

    return shutil.which("git") is not None


def _export_tree(dst: Path) -> None:
    """Copy every tracked-or-uncommitted-non-ignored file into ``dst``.

    Mirrors ``git archive`` of the current tree including uncommitted
    edits: runs ``git ls-files -z --cached --others --exclude-standard``
    from the repo root and copies each listed path that exists in the
    working tree into ``dst``, keeping the relative layout. Ignored
    paths such as ``frontend/dist`` and ``.venv`` are excluded by
    ``--exclude-standard``; ``pytest.skip`` runs when ``git`` is not
    on PATH.
    """

    if not _has_git():
        pytest.skip("git is not on PATH; cannot reproduce a clean export")
    listed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    ).stdout
    for raw in listed.split("\x00"):
        if not raw:
            continue
        src = REPO_ROOT / raw
        if not src.exists():
            continue
        target = dst / raw
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            shutil.copy2(src, target)
    # Brief: assert that the export did not pull in a built dist.
    assert not (dst / "frontend" / "dist").exists(), f"clean export unexpectedly includes {dst / 'frontend' / 'dist'}"


def _child_env(home: Path, export_root: Path) -> dict[str, str]:
    """Strip venue credentials; point PYTHONPATH at the export's ``src``."""

    keep: dict[str, str] = {}
    for name, value in os.environ.items():
        if name.startswith("KRELLBOT_") and name.endswith(("_KEY", "_SECRET", "_KEYFILE")):
            continue
        if name.startswith(("COINBASE_", "KRAKEN_")):
            continue
        keep[name] = value
    keep["KRELLBOT_HOME"] = str(home)
    keep["HOME"] = str(home)
    keep["USERPROFILE"] = str(home)
    keep["KRELLBOT_ENABLE_LIVE"] = "0"
    keep["PYTHON_KEYRING_BACKEND"] = "tests.fakes.fake_keyring.FakeKeyring"
    keep["PYTHONUNBUFFERED"] = "1"
    # Brief: wire PYTHONPATH at the export so the child imports
    # ``krellbot`` from ``<export>/src`` and not the in-tree checkout.
    keep["PYTHONPATH"] = str(export_root / "src") + os.pathsep + keep.get("PYTHONPATH", "")
    return keep


def _spawn(prog: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> subprocess.CompletedProcess:
    """Run a child to completion with a hard timeout and UTF-8 capture."""

    return subprocess.run(
        prog,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        check=False,
    )


def test_clean_export_workstation_refuses_with_build_hint(tmp_path):
    """A clean ``git archive`` export has no ``frontend/dist``; the launcher
    must refuse with one stderr line telling the operator how to build
    the shell, exit 2, and print nothing useful on stdout.
    """

    export_root = tmp_path / "export"
    export_root.mkdir()
    _export_tree(export_root)

    home = tmp_path / "home"
    home.mkdir()
    env = _child_env(home, export_root)

    # Brief: first prove the child imports ``krellbot`` from the
    # export's ``src/``, not the in-tree checkout.
    probe = _spawn(
        [sys.executable, "-c", "import krellbot,sys;print(krellbot.__file__)"],
        cwd=export_root,
        env=env,
        timeout=15,
    )
    assert probe.returncode == 0, (probe.returncode, probe.stdout, probe.stderr)
    expected = str((export_root / "src" / "krellbot" / "__init__.py").resolve())
    assert probe.stdout.strip() == expected, (
        f"child imported krellbot from {probe.stdout.strip()!r}; expected {expected!r}"
    )

    result = _spawn(
        [sys.executable, "-m", "krellbot.cli", "workstation", "--port", "0"],
        cwd=export_root,
        env=env,
        timeout=15,
    )

    assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)

    stderr_lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(stderr_lines) == 1, f"expected exactly one non-empty stderr line, got {stderr_lines!r}"
    line = stderr_lines[0]
    assert "--dist" in line, f"stderr line missing --dist hint: {line!r}"
    assert "npm --prefix frontend run build" in line, f"stderr line missing build command hint: {line!r}"
    assert "http://" not in result.stdout, f"stdout must not contain a URL on refusal; got {result.stdout!r}"


def test_clean_export_with_built_dist_serves_200(tmp_path):
    """Same export, plus a freshly-built ``frontend/dist/index.html``;
    the launcher binds, prints the URL, and ``GET /`` returns 200 with
    the bootstrap meta tag the static layer injects.
    """

    export_root = tmp_path / "export"
    export_root.mkdir()
    _export_tree(export_root)

    dist_dir = export_root / "frontend" / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(
        "<!doctype html><html><head></head><body>ok</body></html>",
        encoding="utf-8",
    )

    home = tmp_path / "home"
    home.mkdir()
    env = _child_env(home, export_root)

    argv = [sys.executable, "-m", "krellbot.cli", "workstation", "--port", "0"]
    popen_kwargs: dict[str, object] = {
        "cwd": str(export_root),
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "bufsize": 1,
    }
    if sys.platform == "win32":
        import subprocess as _sp

        popen_kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    proc = subprocess.Popen(argv, **popen_kwargs)  # type: ignore[arg-type]

    found: list[str] = []
    remaining: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            remaining.append(line)
            match = _URL_LINE_RE.match(line)
            if match:
                found.append(match.group(1))
                return

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    deadline = time.monotonic() + 15
    try:
        while time.monotonic() < deadline:
            if found:
                break
            rc = proc.poll()
            if rc is not None:
                pytest.fail(f"workstation exited {rc} before printing URL: {remaining!r}")
            time.sleep(0.05)
        if not found:
            pytest.fail(f"timed out after 15s waiting for workstation URL; child output={remaining!r}")
        url = found[0]
        port = int(url.rsplit(":", 1)[1].rstrip("/"))

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
            resp = conn.getresponse()
            body = resp.read()
            status = resp.status
        finally:
            conn.close()
        assert status == 200, (status, body[:256])
        assert b"krellbot-bootstrap" in body, body[:512]
    finally:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
        try:
            stdout, _stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _stderr = proc.communicate(timeout=2)
        if proc.returncode not in (0, 0xC000013A, -signal.SIGINT):
            pytest.fail(f"workstation did not exit cleanly: rc={proc.returncode} stdout={stdout!r}")

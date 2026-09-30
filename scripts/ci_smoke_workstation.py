"""CI helper: smoke-test the bundled workstation shell from a frozen binary.

Used by ``.github/workflows/release-frozen.yml`` to prove the
PyInstaller-frozen binary actually serves the bundled workstation
shell on a loopback socket, the printed URL carries no bootstrap
token (the bootstrap meta tag is the only delivery channel), and
the loopback-host middleware accepts the smoke GET.

This script is the workstation-side counterpart to
``scripts/ci_smoke_ui.py``. Both run in the same workflow step
list; the legacy ``krellbot ui`` dashboard smoke is untouched and
``ci_smoke_ui.py`` is not edited. The brief forbids replacing
``krellbot ui``; this helper exists beside it.

The CLI prints the URL with ``flush=True`` (see
``krellbot.cli.cmd_workstation``) so the URL reaches the child
stdout pipe immediately — even on Windows where a tty is not
available and ``winpty`` is not pre-installed on GitHub Actions
Windows runners. We capture the printed URL via the same portable
``subprocess.PIPE`` + reader-thread + ``queue.Queue`` pattern
``ci_smoke_ui.py`` already uses (``capture_url_from_subprocess``),
so there is no tty, no winpty, no third-party dependency.

The URL is parsed from the captured output, then we:

  1. Confirm the URL path is exactly ``/`` (no token, no nested
     path) — the brief mandates ``http://127.0.0.1:PORT/`` only.
  2. GET the index ``/`` with ``Host: 127.0.0.1:PORT`` — expect
     200 with the ``krellbot-bootstrap`` meta tag in the body, or
     404 with ``shell_not_built``. Anything else exits non-zero.

Exit 0 on full success; non-zero with a clear ``::error::`` line
otherwise. Designed for ``set -euo pipefail`` in CI bash steps.

Venue credentials (``COINBASE_*`` / ``KRAKEN_*`` /
``KRELLBOT_*_KEY`` / ``KRELLBOT_*_SECRET`` /
``KRELLBOT_*_KEYFILE``) are stripped from the child env before the
binary launches, so a real key in the CI runner environment
cannot reach the workstation process. Only ``KRELLBOT_HOME`` is
re-set to the ``--home`` argument; ``KRELLBOT_API`` and the
non-secret ``KRELLBOT_KB_*`` / ``KRELLBOT_NPM*`` namespace stay.
The contract mirrors ``tests/test_int01_workstation_launch.py``.
"""

from __future__ import annotations

import argparse
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# Match ``http://127.0.0.1:PORT/`` exactly — the path is ``/`` only,
# no token segment. A future refactor that accidentally allows a
# token (the dashboard helper's regex) must fail this regex match
# so the brief's "URL path is / only" contract is enforced.
_WORKSTATION_URL_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/(?:\s|$)")

# Windows creation flag — ``subprocess`` exposes this only on
# Windows; on POSIX we simply don't pass it.
try:
    import subprocess as _sp

    _CREATE_NEW_PROCESS_GROUP = _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover — POSIX
    _CREATE_NEW_PROCESS_GROUP = 0


class _SubprocessUrlCapture:
    """Portable URL capture over ``subprocess.PIPE``.

    Mirrors ``scripts.ci_smoke_ui._SubprocessUrlCapture`` so the
    two helpers share the same Windows / POSIX portable pipe
    capture. Re-using the implementation (rather than copy-pasting)
    keeps the helper a single source of truth for child capture.

    The child writes its stdout into a pipe (``stderr`` merged
    into stdout). A daemon reader thread pulls lines off the pipe,
    writes them to ``log_path``, and pushes each line into
    ``line_queue``. The public ``wait_for_url`` polls the queue
    plus the process exit state until the URL regex matches, the
    child exits, or the deadline passes.

    Cleanup contract: ``stop()`` joins the reader thread and
    closes the log file handle. The caller is responsible for
    terminating the ``proc`` (we surface ``proc`` via
    ``self.proc``).
    """

    def __init__(
        self,
        argv: list[str],
        env: dict[str, str],
        log_path: Path,
        *,
        deadline_s: float,
    ) -> None:
        self.log_path = log_path
        self.deadline = time.monotonic() + deadline_s
        self.line_queue: queue.Queue[str] = queue.Queue()
        self.url: str | None = None
        self._log_fh = log_path.open("wb")
        self._stop_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_queue: queue.Queue[str] = queue.Queue()

        popen_kwargs: dict[str, object] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "env": env,
            "close_fds": True,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,  # line-buffered on POSIX
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = _CREATE_NEW_PROCESS_GROUP
        else:
            # POSIX: put the child in its own process group so a
            # SIGINT to the parent doesn't cascade.
            popen_kwargs["preexec_fn"] = os.setsid

        self.proc = subprocess.Popen(argv, **popen_kwargs)  # type: ignore[arg-type]
        self._stdout = self.proc.stdout
        self._stderr = self.proc.stderr
        self._reader_thread = threading.Thread(
            target=self._read_stream,
            args=(self._stdout, self.line_queue, False),
            name="ci-smoke-workstation-stdout-reader",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._read_stream,
            args=(self._stderr, self._stderr_queue, True),
            name="ci-smoke-workstation-stderr-reader",
            daemon=True,
        )
        self._stderr_thread.start()

    def _read_stream(
        self,
        stream,
        out_queue: queue.Queue[str],
        is_stderr: bool,
    ) -> None:
        assert stream is not None
        try:
            for raw in stream:
                if not raw:
                    continue
                try:
                    self._log_fh.write(raw.encode("utf-8", errors="replace"))
                    self._log_fh.flush()
                except (OSError, ValueError):
                    pass
                if is_stderr:
                    try:
                        sys.stderr.write(raw)
                        sys.stderr.flush()
                    except (OSError, ValueError):
                        pass
                for line in raw.splitlines():
                    out_queue.put(line)
        except (OSError, ValueError):
            pass
        finally:
            out_queue.put("")

    def wait_for_url(self) -> str | None:
        """Block until URL appears, child exits, or deadline passes."""
        while time.monotonic() < self.deadline:
            while True:
                try:
                    line = self.line_queue.get_nowait()
                except queue.Empty:
                    break
                if not line:
                    continue
                m = _WORKSTATION_URL_RE.search(line)
                if m:
                    self.url = m.group(0).rstrip()
                    return self.url

            if self.proc.poll() is not None:
                while True:
                    try:
                        line = self.line_queue.get_nowait()
                    except queue.Empty:
                        break
                    if not line:
                        continue
                    m = _WORKSTATION_URL_RE.search(line)
                    if m:
                        self.url = m.group(0).rstrip()
                        return self.url
                return self.url

            time.sleep(0.05)

        return self.url

    def stop(self) -> None:
        """Join reader threads and close the log file handle. Idempotent."""
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        if self._stderr_thread is not None and self._stderr_thread.is_alive():
            self._stderr_thread.join(timeout=2.0)
        try:
            self._log_fh.flush()
            self._log_fh.close()
        except (OSError, ValueError):
            pass


def capture_url_from_subprocess(
    argv: list[str],
    *,
    env: dict[str, str],
    log_path: Path,
    deadline_s: float,
) -> tuple[str | None, subprocess.Popen]:
    """Spawn ``argv`` and capture the workstation URL from its stdout pipe.

    Returns ``(url, proc)``. ``url`` is the first
    ``http://127.0.0.1:PORT/`` the child prints, or ``None`` if
    the deadline passes / the child exits before printing it.
    ``proc`` is the running ``Popen``; the caller owns cleanup
    (terminate, wait, etc.).
    """
    cap = _SubprocessUrlCapture(argv, env, log_path, deadline_s=deadline_s)
    url = cap.wait_for_url()
    cap.proc._ci_smoke_capture = cap  # type: ignore[attr-defined]
    return url, cap.proc


def _resolve_binary_argv(binary: str) -> str | list[str]:
    """Return the first argv token(s) for launching ``binary``.

    Mirrors ``scripts.ci_smoke_ui._resolve_binary_argv`` so the
    production smoke runs a frozen ``.exe`` (or POSIX binary)
    verbatim while tests can pass a shebang Python script and
    have the interpreter launched directly (Windows
    ``CreateProcess`` cannot exec a shebang script — only a real
    PE image — so we prefix ``sys.executable`` for ``.py`` files).
    """
    if binary.lower().endswith(".py"):
        try:
            if Path(binary).is_file():
                return [sys.executable, binary]
        except OSError:
            pass
    return binary


def _stop_capture(proc: subprocess.Popen) -> None:
    cap = getattr(proc, "_ci_smoke_capture", None)
    if cap is not None:
        cap.stop()


def _strip_venue_keys(env: dict[str, str]) -> dict[str, str]:
    """Return ``env`` with venue credentials removed.

    Strips every var matching the workstation convention:
    ``COINBASE_*``, ``KRAKEN_*``, and ``KRELLBOT_*_KEY`` /
    ``KRELLBOT_*_SECRET`` / ``KRELLBOT_*_KEYFILE``. Keeps
    ``KRELLBOT_HOME`` (set by the caller from ``--home``),
    ``KRELLBOT_API``, and the non-secret ``KRELLBOT_KB_*`` /
    ``KRELLBOT_NPM*`` namespaces so the binary can still resolve
    its data home and any non-credential knobs. Mirrors
    ``tests/test_int01_workstation_launch._sanitized_env``.
    """
    keep: dict[str, str] = {}
    for name, value in env.items():
        if name.startswith(("COINBASE_", "KRAKEN_")):
            continue
        if name.startswith("KRELLBOT_"):
            if name in {"KRELLBOT_HOME", "KRELLBOT_API"}:
                keep[name] = value
                continue
            if name.startswith(("KRELLBOT_KB_", "KRELLBOT_NPM")):
                keep[name] = value
                continue
            suffix = name[len("KRELLBOT_") :]
            if suffix.endswith(("_KEY", "_SECRET", "_KEYFILE")):
                continue
            keep[name] = value
            continue
        keep[name] = value
    return keep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, help="path to the frozen krellbot binary")
    parser.add_argument("--port", type=int, required=True, help="port for the workstation to bind")
    parser.add_argument("--home", required=True, help="KRELLBOT_HOME (isolated test home)")
    parser.add_argument("--log", required=True, help="path to write captured workstation output")
    args = parser.parse_args(argv)

    env = _strip_venue_keys(dict(os.environ))
    env["KRELLBOT_HOME"] = args.home
    env["PYTHONKEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    env["PYTHONUNBUFFERED"] = "1"

    Path(args.home).mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log)
    if log_path.exists():
        log_path.unlink()

    binary_argv = _resolve_binary_argv(args.binary)
    cmd = [
        *(binary_argv if isinstance(binary_argv, list) else [binary_argv]),
        "workstation",
        "--port",
        str(args.port),
    ]
    # Portable pipe-based URL capture: matches the
    # ``ci_smoke_ui.py`` helper so the two smokes share the same
    # Windows-friendly path. The CLI prints the URL with
    # ``flush=True`` (see ``cmd_workstation``), so the bytes reach
    # the pipe immediately even on Windows.
    url, proc = capture_url_from_subprocess(cmd, env=env, log_path=log_path, deadline_s=10.0)
    try:
        if not url:
            print(
                "::error::workstation never printed a URL within 10s",
                file=sys.stderr,
            )
            try:
                print(log_path.read_text(errors="replace"), file=sys.stderr)
            except OSError:
                pass
            return 3

        # The brief mandates the URL path is ``/`` only. The
        # ``_WORKSTATION_URL_RE`` already enforces a trailing
        # whitespace or end-of-line after ``/``; double-check
        # defensively so a future regex change cannot regress
        # this contract.
        if not url.endswith("/"):
            print(
                f"::error::workstation URL path is not '/': {url!r}",
                file=sys.stderr,
            )
            return 4
        if len(_WORKSTATION_URL_RE.findall(url)) != 1:
            print(
                f"::error::workstation URL has a token segment: {url!r}",
                file=sys.stderr,
            )
            return 5
        # Pull ``127.0.0.1:PORT`` from the URL for the Host header
        # — the loopback-host middleware checks the bound port.
        host_match = re.match(r"http://(127\.0\.0\.1:\d+)/", url)
        assert host_match, f"URL did not parse as loopback: {url!r}"
        host = host_match.group(1)

        print(f"smoke: workstation URL = {url}")

        # Index GET with the loopback Host header. Accept 200 +
        # ``krellbot-bootstrap`` (built dist) or 404 +
        # ``shell_not_built`` (no dist). Anything else fails.
        index_out = log_path.with_name("smoke_index.html")
        if index_out.exists():
            index_out.unlink()
        index_proc = subprocess.run(
            [
                "curl",
                "-sS",
                "--max-time",
                "10",
                "-H",
                f"Host: {host}",
                "-o",
                str(index_out),
                "-w",
                "%{http_code}",
                url,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        status = index_proc.stdout
        if index_proc.returncode != 0:
            print(
                f"::error::curl failed (rc={index_proc.returncode}): {index_proc.stderr[:500]!r}",
                file=sys.stderr,
            )
            return 6
        if status == "200":
            body = index_out.read_text(errors="replace")
            if "krellbot-bootstrap" not in body:
                print(
                    "::error::index 200 but body lacks krellbot-bootstrap meta tag; body:",
                    file=sys.stderr,
                )
                print(body[:1000], file=sys.stderr)
                return 7
            print(f"ok: workstation served 200 index with krellbot-bootstrap meta tag (URL {url}, log {log_path})")
            return 0
        if status == "404":
            body = index_out.read_text(errors="replace")
            if "shell_not_built" not in body:
                print(
                    "::error::index 404 but body lacks shell_not_built JSON shape; body:",
                    file=sys.stderr,
                )
                print(body[:1000], file=sys.stderr)
                return 8
            print(f"ok: workstation served 404 shell_not_built (URL {url}, log {log_path})")
            return 0
        print(
            f"::error::index GET returned {status!r} (expected 200 or 404); body:",
            file=sys.stderr,
        )
        try:
            print(index_out.read_text(errors="replace")[:1000], file=sys.stderr)
        except OSError:
            pass
        return 9
    finally:
        # Stop the workstation process cleanly. On Windows,
        # ``Popen.send_signal(signal.SIGINT)`` raises
        # ``ValueError: Unsupported signal: 2`` because Python's
        # subprocess only accepts SIGTERM, CTRL_C_EVENT, and
        # CTRL_BREAK_EVENT on Windows. ``CTRL_C_EVENT`` requires
        # a new console the test runner does not own; we use
        # ``CTRL_BREAK_EVENT`` because the child was launched
        # with ``CREATE_NEW_PROCESS_GROUP``, so the break is
        # scoped to the workstation and does not take down the
        # runner. On POSIX, ``SIGINT`` is the right cleanup
        # signal. The brief forbids ``pkill`` (Windows Git Bash
        # has no ``procps``); we never shell out.
        if sys.platform == "win32":
            stop_signal: int = signal.CTRL_BREAK_EVENT
        else:
            stop_signal = signal.SIGINT
        try:
            proc.send_signal(stop_signal)
        except (ProcessLookupError, OSError, ValueError):
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        _stop_capture(proc)


if __name__ == "__main__":
    raise SystemExit(main())

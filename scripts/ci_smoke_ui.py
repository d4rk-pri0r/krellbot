"""CI helper: smoke-test the bundled token-gated dashboard from a frozen binary.

Used by `.github/workflows/release-frozen.yml` to prove the
PyInstaller-frozen binary actually serves the bundled UI assets
(token-gated GET returns 200 with bundled bytes), not just that
the binary exists and `list` exits 0.

The CLI prints the dashboard URL with ``flush=True`` (see
``krellbot.cli.cmd_ui``), so the URL reaches the child stdout pipe
immediately — even on Windows where a tty is not available and
``winpty`` is not pre-installed on GitHub Actions Windows runners.
To capture the printed ``http://127.0.0.1:PORT/<token>/`` URL we
therefore use a portable ``subprocess.PIPE`` + reader-thread +
``queue.Queue`` helper (``capture_url_from_subprocess``) on every
platform. No pty, no winpty, no third-party dependency.

The token URL is parsed from the captured output, then we:

  1. GET the index `/<token>/` — expect 200, body contains
     the bundled dashboard marker (`krellbot`).
  2. GET `/<token>/static/app.js` — expect 200, body non-empty.
  3. GET `/<wrong-token>/` — expect 403, body small (gate
     enforced).

Exit 0 on full success; non-zero with a clear error message
otherwise. Designed for `set -euo pipefail` in CI bash steps.
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

_TOKEN_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/([0-9a-f]{64})/")

# Windows creation flag — ``subprocess`` exposes this only on
# Windows; on POSIX we simply don't pass it.
try:
    import subprocess as _sp
    _CREATE_NEW_PROCESS_GROUP = _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover — POSIX
    _CREATE_NEW_PROCESS_GROUP = 0


class _SubprocessUrlCapture:
    """Portable URL capture over ``subprocess.PIPE``.

    The child writes its stdout into a pipe (``stderr`` merged into
    stdout). A daemon reader thread pulls lines off the pipe, writes
    them to ``log_path``, and pushes each line into ``line_queue``.
    The public ``wait_for_url`` polls the queue plus the process
    exit state until the URL regex matches, the child exits, or the
    deadline passes.

    No pty, no winpty — works on Windows, macOS, and Linux.

    Cleanup contract: ``stop()`` joins the reader thread and closes
    the log file handle. The caller is responsible for terminating
    the ``proc`` (we surface ``proc`` via ``self.proc``).
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

        # ``popen_kwargs`` is built as ``dict[str, object]`` so the
        # Windows / POSIX branches can populate it without ceremony.
        # ``subprocess.Popen`` accepts exactly the keys we set, so the
        # cast is safe and lets Pyright see the call without complaining
        # about the heterogeneous dict literal.
        self.proc = subprocess.Popen(argv, **popen_kwargs)  # type: ignore[arg-type]
        self._stdout = self.proc.stdout
        self._stderr = self.proc.stderr
        self._reader_thread = threading.Thread(
            target=self._read_stream,
            args=(self._stdout, self.line_queue, False),
            name="ci-smoke-stdout-reader",
            daemon=True,
        )
        self._reader_thread.start()
        self._stderr_thread = threading.Thread(
            target=self._read_stream,
            args=(self._stderr, self._stderr_queue, True),
            name="ci-smoke-stderr-reader",
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
                # Write raw bytes to the log so we don't lose ordering
                # between stdout and stderr.
                try:
                    self._log_fh.write(raw.encode("utf-8", errors="replace"))
                    self._log_fh.flush()
                except (OSError, ValueError):
                    pass
                # Echo stderr lines to the parent's stderr too — CI
                # surfaces them in the run log.
                if is_stderr:
                    try:
                        sys.stderr.write(raw)
                        sys.stderr.flush()
                    except (OSError, ValueError):
                        pass
                for line in raw.splitlines():
                    out_queue.put(line)
        except (OSError, ValueError):
            # Pipe closed / file handle closed during shutdown.
            pass
        finally:
            out_queue.put("")  # sentinel — wake any blocked consumer

    def wait_for_url(self) -> str | None:
        """Block until URL appears, child exits, or deadline passes.

        Returns the matched URL on success, else ``None``.
        """
        while time.monotonic() < self.deadline:
            # Drain anything currently buffered in the line queue.
            while True:
                try:
                    line = self.line_queue.get_nowait()
                except queue.Empty:
                    break
                if not line:
                    continue
                m = _TOKEN_RE.search(line)
                if m:
                    self.url = m.group(0)
                    return self.url

            # If the child has exited, drain one final time and stop.
            if self.proc.poll() is not None:
                while True:
                    try:
                        line = self.line_queue.get_nowait()
                    except queue.Empty:
                        break
                    if not line:
                        continue
                    m = _TOKEN_RE.search(line)
                    if m:
                        self.url = m.group(0)
                        return self.url
                return self.url

            time.sleep(0.05)

        return self.url

    def stop(self) -> None:
        """Join reader threads and close the log file handle.

        Idempotent. Safe to call multiple times.
        """
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
    """Spawn ``argv`` and capture the dashboard URL from its stdout pipe.

    Returns ``(url, proc)``. ``url`` is the first ``http://127.0.0.1:PORT/<token>/``
    the child prints, or ``None`` if the deadline passes / the child
    exits before printing it. ``proc`` is the running ``Popen``;
    the caller owns cleanup (terminate, wait, etc.).

    The capture is portable: a single ``subprocess.PIPE`` +
    reader-thread implementation, plus ``flush=True`` on the CLI
    print site, replaces the previous pty (POSIX) / winpty
    (Windows) split that depended on a third-party tool not
    installed on GitHub Actions Windows runners.
    """
    cap = _SubprocessUrlCapture(argv, env, log_path, deadline_s=deadline_s)
    url = cap.wait_for_url()
    # Attach the capture so the caller can stop() us after the smoke
    # GETs run (keeps the log file handle owned by one place).
    cap.proc._ci_smoke_capture = cap  # type: ignore[attr-defined]
    return url, cap.proc


def _stop_capture(proc: subprocess.Popen) -> None:
    cap = getattr(proc, "_ci_smoke_capture", None)
    if cap is not None:
        cap.stop()


def _wait_for_url(proc: subprocess.Popen, deadline: float) -> str | None:
    """Backward-compatible wrapper used by ``main``.

    New code should call ``capture_url_from_subprocess`` directly;
    this wrapper exists so any future caller still using the old
    API gets the same behaviour.
    """
    cap = getattr(proc, "_ci_smoke_capture", None)
    if cap is None:
        return None
    # Reset the deadline relative to ``deadline`` (monotonic).
    cap.deadline = min(cap.deadline, deadline)
    return cap.wait_for_url()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, help="path to the frozen krellbot binary")
    parser.add_argument("--port", type=int, required=True, help="port for the dashboard to bind")
    parser.add_argument("--home", required=True, help="KRELLBOT_HOME (isolated test home)")
    parser.add_argument("--log", required=True, help="path to write captured dashboard output")
    parser.add_argument(
        "--index-marker",
        default="krellbot",
        help="substring expected in the served index body (default: 'krellbot')",
    )
    parser.add_argument(
        "--static-path",
        default="static/app.js",
        help="relative static asset path to GET (default: 'static/app.js')",
    )
    args = parser.parse_args(argv)

    env = dict(os.environ)
    env["KRELLBOT_HOME"] = args.home
    env["PYTHONKEYRING_BACKEND"] = "keyring.backends.fail.Keyring"

    Path(args.home).mkdir(parents=True, exist_ok=True)
    log_path = Path(args.log)
    if log_path.exists():
        log_path.unlink()

    cmd = [args.binary, "ui", "--port", str(args.port)]
    # Portable pipe-based URL capture: replaces the previous pty (POSIX) /
    # winpty (Windows) split that depended on a third-party tool not
    # installed on GitHub Actions Windows runners. The CLI prints the URL
    # with ``flush=True`` (see ``cmd_ui``), so the bytes reach the pipe
    # immediately even on Windows.
    url, proc = capture_url_from_subprocess(
        cmd, env=env, log_path=log_path, deadline_s=10.0
    )
    try:
        if not url:
            print(
                "::error::dashboard never printed a token URL within 10s",
                file=sys.stderr,
            )
            try:
                print(log_path.read_text(errors="replace"), file=sys.stderr)
            except OSError:
                pass
            return 3

        print(f"smoke: dashboard URL = {url}")

        # Index GET — must be 200 and contain the marker.
        index_out = Path(args.log).with_name("smoke_index.html")
        index_proc = subprocess.run(
            ["curl", "-sS", "-o", str(index_out), "-w", "%{http_code}", url],
            capture_output=True,
            text=True,
            check=False,
        )
        if index_proc.returncode != 0 or index_proc.stdout != "200":
            print(
                f"::error::index GET returned {index_proc.stdout!r} "
                f"(curl rc={index_proc.returncode}); body:",
                file=sys.stderr,
            )
            try:
                print(index_out.read_text(errors="replace"), file=sys.stderr)
            except OSError:
                pass
            return 4
        index_body = index_out.read_text(errors="replace")
        if args.index_marker not in index_body:
            print(
                f"::error::index body did not contain {args.index_marker!r}; body:",
                file=sys.stderr,
            )
            print(index_body, file=sys.stderr)
            return 5

        # Static asset GET — must be 200 and non-trivially sized.
        asset_out = Path(args.log).with_name("smoke_static.bin")
        asset_url = url + args.static_path
        asset_proc = subprocess.run(
            ["curl", "-sS", "-o", str(asset_out), "-w", "%{http_code}", asset_url],
            capture_output=True,
            text=True,
            check=False,
        )
        if asset_proc.returncode != 0 or asset_proc.stdout != "200":
            print(
                f"::error::static asset GET returned {asset_proc.stdout!r} "
                f"(curl rc={asset_proc.returncode}); body:",
                file=sys.stderr,
            )
            try:
                print(asset_out.read_text(errors="replace"), file=sys.stderr)
            except OSError:
                pass
            return 6
        asset_bytes = asset_out.stat().st_size
        if asset_bytes < 100:
            print(
                f"::error::bundled static asset is suspiciously small ({asset_bytes} bytes)",
                file=sys.stderr,
            )
            return 7

        # Wrong-token GET — must be 403.
        wrong_url = re.sub(r"/[0-9a-f]{64}/", "/deadbeef/", url)
        wrong_proc = subprocess.run(
            ["curl", "-sS", "-o", os.devnull, "-w", "%{http_code}", wrong_url],
            capture_output=True,
            text=True,
            check=False,
        )
        if wrong_proc.stdout != "403":
            print(
                f"::error::wrong-token GET returned {wrong_proc.stdout!r} (expected 403)",
                file=sys.stderr,
            )
            return 8

        print(
            f"ok: bundled dashboard served 200 index (marker present), "
            f"200 static ({asset_bytes} bytes), 403 wrong-token"
        )
        return 0
    finally:
        # Stop the dashboard process cleanly.
        try:
            proc.send_signal(signal.SIGINT)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
        # Close the capture (joins reader threads, closes log handle).
        _stop_capture(proc)


if __name__ == "__main__":
    raise SystemExit(main())
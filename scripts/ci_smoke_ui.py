"""CI helper: smoke-test the bundled token-gated dashboard from a frozen binary.

Used by `.github/workflows/release-frozen.yml` to prove the
PyInstaller-frozen binary actually serves the bundled UI assets
(token-gated GET returns 200 with bundled bytes), not just that
the binary exists and `list` exits 0.

The frozen binary's stdout is NOT line-buffered by default
(PyInstaller bootloader doesn't propagate `PYTHONUNBUFFERED` to
the embedded interpreter the way a normal `python` invocation
does). To capture the printed `http://127.0.0.1:PORT/<token>/`
URL, we run the binary under a pseudo-tty via the stdlib `pty`
module on POSIX, or via `winpty` on Windows. The token URL is
parsed from the captured output, then we:

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
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

_TOKEN_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/([0-9a-f]{64})/")


def _run_under_pty(argv: list[str], env: dict[str, str], log_path: Path) -> subprocess.Popen:
    """Run the binary attached to a pseudo-tty so its stdout is line-buffered.

    POSIX only. Windows uses the `winpty` fallback below.
    """
    import fcntl
    import pty

    master_fd, slave_fd = pty.openpty()

    # Make master non-blocking so the reader loop can poll.
    flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
    fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    proc = subprocess.Popen(
        argv,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True,
        # Put the child in its own process group so SIGINT to the
        # parent doesn't cascade to the dashboard binary.
        preexec_fn=os.setsid,  # noqa: PLW1509 — intentional in this single-threaded caller
    )
    os.close(slave_fd)

    log_fh = log_path.open("wb")

    captured = bytearray()

    def _drain(deadline: float) -> bytes:
        while time.time() < deadline:
            try:
                chunk = os.read(master_fd, 4096)
            except BlockingIOError:
                time.sleep(0.02)
                continue
            except OSError:
                break
            if not chunk:
                break
            captured.extend(chunk)
            log_fh.write(chunk)
            log_fh.flush()
        return bytes(captured)

    proc._smoke_drain = _drain  # type: ignore[attr-defined]
    proc._smoke_log_fh = log_fh  # type: ignore[attr-defined]
    proc._smoke_master_fd = master_fd  # type: ignore[attr-defined]
    return proc


def _run_under_winpty(argv: list[str], env: dict[str, str], log_path: Path) -> subprocess.Popen:
    """Windows fallback: spawn via `winpty` if available, else fail."""
    import shutil

    winpty = shutil.which("winpty") or shutil.which("winpty.exe")
    if winpty is None:
        raise RuntimeError(
            "winpty is required on Windows to run the frozen dashboard smoke; "
            "install it via 'choco install winpty' or skip this step on Windows"
        )
    log_fh = log_path.open("wb")
    proc = subprocess.Popen(
        [winpty, *argv],
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        env=env,
    )
    proc._smoke_log_fh = log_fh  # type: ignore[attr-defined]
    return proc


def _wait_for_url(proc: subprocess.Popen, deadline: float) -> str | None:
    """Poll the captured output until we see the dashboard URL or hit the deadline."""
    while time.time() < deadline:
        if hasattr(proc, "_smoke_drain"):
            captured = proc._smoke_drain(min(deadline, time.time() + 0.1))  # type: ignore[attr-defined]
            m = _TOKEN_RE.search(captured.decode(errors="replace"))
            if m:
                return m.group(0)
        else:
            # winpty path: just tail the log file
            time.sleep(0.05)
        if proc.poll() is not None:
            break
    return None


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
    if sys.platform == "win32":
        proc = _run_under_winpty(cmd, env, log_path)
    else:
        proc = _run_under_pty(cmd, env, log_path)

    url = _wait_for_url(proc, time.time() + 10.0)
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
        if hasattr(proc, "_smoke_log_fh"):
            proc._smoke_log_fh.close()  # type: ignore[attr-defined]
        if hasattr(proc, "_smoke_master_fd"):
            try:
                os.close(proc._smoke_master_fd)  # type: ignore[attr-defined]
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
"""CI helper: v0.9.6 frozen paper first-use smoke.

This is the release gate's runtime proof: it executes the *actual*
PyInstaller-built binary, relocated outside the checkout, against a fresh
isolated home. Nothing in this helper imports application modules or reads
the checkout's resources at runtime; the binary is copied into a scratch
runtime directory and launched with a stripped environment.

The gate has five phases, all mandatory:

1. ``validate`` — ``krellbot lint <example pack>`` exits 0 and prints
   ``ok``. This reads the bundled ``krellbot/pack/schema.json`` through
   ``importlib.resources``, so a missing package-data file fails here.
2. ``paper arm`` — arm the same pack for paper with a fixed balance.
3. ``paper status`` — the armed record is present with ``mode=paper``.
4. ``disarm`` — the record is removed and a follow-up status is empty.
5. ``workstation`` — launch the built shell on loopback and require a
   ``200`` index carrying the ``krellbot-bootstrap`` meta tag. A ``404``
   with ``shell_not_built`` is a FAILURE; the release must not ship an
   unbuilt shell.
6. ``live refusal`` — with ``KRELLBOT_ENABLE_LIVE=1`` and an operator
   authorization file naming the exact venue/pair, a live arm attempt
   must hard-refuse as paper-only and leave no live arm behind.

The live-refusal phase intentionally depends on the v0.9.6 paper-only
policy implemented in a separate worktree. Until that policy is merged,
this phase is red on the current base and the helper exits non-zero. Do
not weaken it: the release is paper-only regardless of environment.

Environment isolation
---------------------

The child env drops ``PYTHONPATH`` / ``PYTHONHOME`` / ``PYTHONSTARTUP``,
all ``KRELLBOT_*`` variables, venue credential variables (``KRAKEN_*``,
``COINBASE_*``, ``BINANCE_*`` and friends) and anything that looks like a
token/secret/key file. ``HOME``, ``USERPROFILE`` and the XDG directories
point at the fresh home; ``KRELLBOT_HOME`` does too. The keyring backend
is forced to the always-failing backend so a real OS keychain cannot be
read. Only the loopback workstation socket is contacted.

Usage (CI):
    python scripts/ci_smoke_frozen_paper.py \
        --binary dist/krellbot/krellbot \
        --home "$RUNNER_TEMP/frozen-paper-home" \
        --workdir "$RUNNER_TEMP/frozen-paper-work" \
        --pack docs/example-pack.json

Exit 0 only when every phase passes. Every failure prints a ``::error::``
line and preserves captured output under ``--log`` / ``--workdir``.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PAPER_ONLY_RELEASE_MARKER = "paper-only release"
PAPER_ONLY_RELEASE_CODE = "live_disabled_paper_only_release"

_VENUE = "kraken"
_PAIR = "SUIUSD"
_PACK_ID = "trend-follow"
_PAPER_BALANCE = "1000"
_WORKSTATION_URL_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/")
_BOOTSTRAP_MARKER = "krellbot-bootstrap"

# Return codes (kept distinct so CI logs identify the failed phase).
_RC_VALIDATE = 10
_RC_ARM = 11
_RC_STATUS = 12
_RC_DISARM = 13
_RC_WORKSTATION = 14
_RC_LIVE = 15

_CREDENTIAL_PREFIXES = (
    "COINBASE_",
    "KRAKEN_",
    "BINANCE_",
    "BYBIT_",
    "OKX_",
    "KUCOIN_",
    "KRELLBOT_",
)
_CREDENTIAL_SUFFIXES = (
    "_KEY",
    "_SECRET",
    "_KEYFILE",
    "_TOKEN",
    "_PASSWORD",
    "_PASSWD",
    "_API_KEY",
    "_PRIVATE_KEY",
)
_DROP_PYTHON_VARS = frozenset(
    {
        "PYTHONPATH",
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
    }
)


class SmokeFailure(RuntimeError):
    """A release-gate phase failed with a human-readable reason."""

    def __init__(self, message: str, *, returncode: int = 1) -> None:
        super().__init__(message)
        self.returncode = returncode


def _child_env(
    base: Mapping[str, str],
    home: Path,
    *,
    enable_live: str = "0",
) -> dict[str, str]:
    """Return a credential-free environment rooted at ``home``.

    We deliberately drop the *whole* ``KRELLBOT_*`` namespace and rebuild
    only the two knobs this smoke needs. That prevents a developer's real
    ``KRELLBOT_HOME``, API base, key path, or future live switch from
    leaking into the released binary.
    """
    home = Path(home)
    keep: dict[str, str] = {}
    for name, value in base.items():
        upper = name.upper()
        if upper in _DROP_PYTHON_VARS:
            continue
        if upper.startswith(_CREDENTIAL_PREFIXES):
            continue
        if upper.endswith(_CREDENTIAL_SUFFIXES):
            continue
        keep[name] = value

    keep["HOME"] = str(home)
    keep["USERPROFILE"] = str(home)
    keep["XDG_CONFIG_HOME"] = str(home / ".config")
    keep["XDG_DATA_HOME"] = str(home / ".local" / "share")
    keep["XDG_CACHE_HOME"] = str(home / ".cache")
    keep["KRELLBOT_HOME"] = str(home)
    keep["KRELLBOT_ENABLE_LIVE"] = enable_live
    keep["PYTHONKEYRING_BACKEND"] = "keyring.backends.fail.Keyring"
    keep["PYTHONUNBUFFERED"] = "1"
    keep["PYTHONDONTWRITEBYTECODE"] = "1"
    keep["PYTHONNOUSERSITE"] = "1"
    # The only network path is the loopback workstation socket; make sure
    # an inherited proxy cannot intercept it.
    keep["NO_PROXY"] = "127.0.0.1,localhost"
    keep["no_proxy"] = "127.0.0.1,localhost"
    return keep


def _binary_argv(binary: Path) -> list[str]:
    """Return argv tokens for launching ``binary``.

    Production always passes the real PyInstaller executable. Tests pass
    a ``.py`` shim; on Windows ``CreateProcess`` cannot execute a shebang
    script, so we launch it with the current interpreter.
    """
    if binary.suffix.lower() == ".py":
        return [sys.executable, str(binary)]
    return [str(binary)]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _assert_outside_checkout(repo_root: Path, *paths: Path) -> None:
    for path in paths:
        if _is_within(path, repo_root):
            raise SmokeFailure(
                f"refusing to run the frozen smoke inside the checkout: {path} is under {repo_root}. "
                "Pass --home/--workdir/--log paths outside the repository so the runtime cannot borrow "
                "source modules or resources."
            )


def _prepare_fresh_dir(path: Path, *, label: str) -> None:
    path = Path(path)
    if path.exists():
        if not path.is_dir():
            raise SmokeFailure(f"{label} path exists and is not a directory: {path}")
        if any(path.iterdir()):
            raise SmokeFailure(
                f"{label} is not fresh (non-empty): {path}. The frozen first-use smoke requires a "
                "fresh isolated home and workdir; remove it or pick a new path."
            )
    else:
        path.mkdir(parents=True)
    if os.name == "posix":
        try:
            path.chmod(0o700)
        except OSError:
            pass


def _stage_runtime(binary: Path, workdir: Path) -> Path:
    """Relocate the executable/bundle into ``workdir/runtime``.

    A PyInstaller one-dir build is copied wholesale so its ``_internal``
    data travels with it. That makes the runtime self-contained and
    proves it does not resolve package data from the checkout. Test shims
    (``.py``) are copied as a single file for the same reason.
    """
    runtime = workdir / "runtime"
    if runtime.exists():
        raise SmokeFailure(f"runtime staging directory already exists: {runtime}")
    if binary.suffix.lower() == ".py":
        runtime.mkdir()
        staged = runtime / binary.name
        shutil.copy2(binary, staged)
        return staged

    bundle = binary.parent
    if not (bundle / "_internal").is_dir():
        raise SmokeFailure(
            f"not a PyInstaller one-dir bundle: {bundle} has no _internal directory. "
            "Build the release with scripts/freeze.py and pass dist/krellbot/krellbot."
        )
    shutil.copytree(bundle, runtime, symlinks=True)
    staged = runtime / binary.name
    if not staged.is_file():
        raise SmokeFailure(f"staged executable missing after copy: {staged}")
    return staged


def _append_log(log_path: Path, argv: list[str], proc: subprocess.CompletedProcess[str]) -> None:
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n$ {' '.join(argv)}\n")
        if proc.stdout:
            fh.write(proc.stdout)
            if not proc.stdout.endswith("\n"):
                fh.write("\n")
        if proc.stderr:
            fh.write(proc.stderr)
            if not proc.stderr.endswith("\n"):
                fh.write("\n")
        fh.write(f"[exit {proc.returncode}]\n")


@dataclass
class _Context:
    binary: Path
    home: Path
    workdir: Path
    pack: Path
    log_path: Path
    base_env: Mapping[str, str]

    def run(
        self,
        args: list[str],
        *,
        enable_live: str = "0",
        timeout: float = 180.0,
    ) -> subprocess.CompletedProcess[str]:
        argv = [*_binary_argv(self.binary), *args]
        try:
            proc = subprocess.run(
                argv,
                cwd=str(self.workdir),
                env=_child_env(self.base_env, self.home, enable_live=enable_live),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SmokeFailure(f"frozen binary timed out after {timeout:.0f}s: {' '.join(args)}") from exc
        except OSError as exc:
            raise SmokeFailure(f"could not launch frozen binary {self.binary}: {exc}") from exc
        _append_log(self.log_path, argv, proc)
        return proc

    def child_env(self, *, enable_live: str = "0") -> dict[str, str]:
        return _child_env(self.base_env, self.home, enable_live=enable_live)


def _combined(proc: subprocess.CompletedProcess[str]) -> str:
    return (proc.stdout or "") + "\n" + (proc.stderr or "")


def _require_ok(proc: subprocess.CompletedProcess[str], *, phase: str, rc: int) -> None:
    if proc.returncode != 0:
        raise SmokeFailure(
            f"{phase} failed (exit {proc.returncode}; expected 0).\n"
            f"stdout:\n{proc.stdout or ''}\nstderr:\n{proc.stderr or ''}",
            returncode=rc,
        )


def _phase_validate(ctx: _Context) -> None:
    proc = ctx.run(["lint", str(ctx.pack)], timeout=120)
    _require_ok(proc, phase="strategy validate (krellbot lint)", rc=_RC_VALIDATE)
    lines = [line.strip() for line in (proc.stdout or "").splitlines()]
    if "ok" not in lines:
        raise SmokeFailure(
            "strategy validate did not print 'ok'; the bundled pack schema or validator is broken.\n"
            f"stdout:\n{proc.stdout or ''}\nstderr:\n{proc.stderr or ''}",
            returncode=_RC_VALIDATE,
        )
    print("ok: strategy validate -> ok (schema resolved from the bundled runtime)")


def _phase_arm(ctx: _Context) -> None:
    proc = ctx.run(
        [
            "arm",
            str(ctx.pack),
            "--venue",
            _VENUE,
            "--mode",
            "paper",
            "--paper-balance",
            _PAPER_BALANCE,
        ],
        timeout=120,
    )
    _require_ok(proc, phase="paper arm", rc=_RC_ARM)
    out = proc.stdout or ""
    if "armed " not in out or _PACK_ID not in out:
        raise SmokeFailure(
            f"paper arm did not report an armed {_PACK_ID} pack.\nstdout:\n{out}\nstderr:\n{proc.stderr or ''}",
            returncode=_RC_ARM,
        )
    print(f"ok: paper arm -> {_PACK_ID} armed on {_VENUE} {_PAIR}")


def _phase_status(ctx: _Context, *, expect_armed: bool) -> None:
    proc = ctx.run(["status", "--venue", _VENUE], timeout=60)
    _require_ok(proc, phase="paper status", rc=_RC_STATUS)
    out = proc.stdout or ""
    if expect_armed:
        required = (_PACK_ID, "mode=paper", _VENUE, _PAIR)
        missing = [token for token in required if token not in out]
        if missing:
            raise SmokeFailure(
                f"paper status missing {missing!r}.\nstdout:\n{out}\nstderr:\n{proc.stderr or ''}",
                returncode=_RC_STATUS,
            )
        print(f"ok: paper status -> {_PACK_ID} {_VENUE} {_PAIR} mode=paper")
    else:
        if "no armed packs" not in out:
            raise SmokeFailure(
                f"expected no armed packs after disarm/live refusal.\nstdout:\n{out}\nstderr:\n{proc.stderr or ''}",
                returncode=_RC_STATUS,
            )
        print("ok: paper status -> no armed packs")


def _phase_disarm(ctx: _Context) -> None:
    proc = ctx.run(["disarm", "--venue", _VENUE, "--pair", _PAIR], timeout=60)
    _require_ok(proc, phase="disarm", rc=_RC_DISARM)
    if "disarmed" not in (proc.stdout or ""):
        raise SmokeFailure(
            f"disarm did not confirm removal.\nstdout:\n{proc.stdout or ''}\nstderr:\n{proc.stderr or ''}",
            returncode=_RC_DISARM,
        )
    _phase_status(ctx, expect_armed=False)
    print(f"ok: disarm -> {_VENUE} {_PAIR} removed")


def _stop_process(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        stop_signal = signal.CTRL_BREAK_EVENT
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
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _phase_workstation(ctx: _Context) -> None:
    """Launch the bundled workstation and require the built shell."""
    argv = [*_binary_argv(ctx.binary), "workstation", "--port", "0"]
    popen_kwargs: dict[str, object] = {
        "cwd": str(ctx.workdir),
        "env": ctx.child_env(),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "bufsize": 1,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_kwargs["preexec_fn"] = os.setsid

    try:
        proc = subprocess.Popen(argv, **popen_kwargs)  # type: ignore[arg-type]
    except OSError as exc:
        raise SmokeFailure(f"could not launch workstation: {exc}", returncode=_RC_WORKSTATION) from exc

    lines: queue.Queue[str] = queue.Queue()

    def _drain() -> None:
        assert proc.stdout is not None
        try:
            with ctx.log_path.open("a", encoding="utf-8") as fh:
                for line in proc.stdout:
                    fh.write(line)
                    fh.flush()
                    lines.put(line)
        except (OSError, ValueError):
            pass

    reader = threading.Thread(target=_drain, name="frozen-paper-workstation-reader", daemon=True)
    reader.start()

    url: str | None = None
    deadline = time.monotonic() + 25.0
    try:
        while time.monotonic() < deadline:
            try:
                line = lines.get(timeout=0.05)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            match = _WORKSTATION_URL_RE.search(line)
            if match:
                url = match.group(0)
                break

        if url is None:
            raise SmokeFailure(
                "workstation never printed a loopback URL within 25s. The shell is not built or the "
                "launcher refused to bind; a 404 shell_not_built response is never a pass.\n"
                f"See {ctx.log_path}",
                returncode=_RC_WORKSTATION,
            )

        port = int(_WORKSTATION_URL_RE.search(url).group(1))  # type: ignore[union-attr]
        body = ""
        status = 0
        # The launcher prints the URL once its listener is handed to the
        # server runtime. On slower native runners that can still race the
        # first connect; retry briefly on connection errors rather than
        # turning a startup race into a false release failure.
        deadline = time.monotonic() + 15.0
        last_error: OSError | http.client.HTTPException | None = None
        while time.monotonic() < deadline:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}"})
                response = conn.getresponse()
                status = response.status
                body = response.read().decode("utf-8", errors="replace")
                conn.close()
                last_error = None
                break
            except (OSError, http.client.HTTPException) as exc:
                last_error = exc
                time.sleep(0.1)
        if last_error is not None:
            raise SmokeFailure(
                f"workstation loopback GET failed: {last_error}", returncode=_RC_WORKSTATION
            ) from last_error

        if status != 200:
            raise SmokeFailure(
                f"workstation GET / returned HTTP {status}, not 200. The built workstation shell is "
                "required; 404 shell_not_built is a failed release gate.\n"
                f"body:\n{body[:2000]}",
                returncode=_RC_WORKSTATION,
            )
        if _BOOTSTRAP_MARKER not in body:
            raise SmokeFailure(
                "workstation GET / returned 200 but the body lacks the krellbot-bootstrap meta tag; "
                "the shell was not built from the bundled frontend.\n"
                f"body:\n{body[:2000]}",
                returncode=_RC_WORKSTATION,
            )
        print(f"ok: workstation -> 200 built shell with krellbot-bootstrap at {url}")
    finally:
        _stop_process(proc)
        reader.join(timeout=5.0)
        # Close the pipe explicitly: Windows keeps the handle open if the
        # parent leaves it for the GC, which can make pytest's tmp-dir
        # cleanup fail with WinError 32.
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except (OSError, ValueError):
            pass


def _write_live_authorization(home: Path) -> None:
    """Write a valid operator grant for the attempted venue/pair.

    This makes the adversarial live attempt stronger: even with
    ``KRELLBOT_ENABLE_LIVE=1`` and a perfectly valid authorization file,
    the release must refuse. It is removed before the final status check.
    """
    payload = {
        "schema_version": "1",
        "granted_by": "operator",
        "expires_at": int(time.time()) + 3600,
        "grants": [{"venue": _VENUE, "pair": _PAIR}],
    }
    path = home / "live-authorization.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    if os.name == "posix":
        try:
            path.chmod(0o600)
        except OSError:
            pass


def _phase_live_refusal(ctx: _Context) -> None:
    _write_live_authorization(ctx.home)
    proc = ctx.run(
        ["arm", str(ctx.pack), "--venue", _VENUE, "--mode", "live"],
        enable_live="1",
        timeout=90,
    )
    combined = _combined(proc)
    if proc.returncode == 0:
        raise SmokeFailure(
            "adversarial live arm SUCCEEDED with KRELLBOT_ENABLE_LIVE=1. v0.9.6 must hard-refuse "
            "live orders as paper-only.\n"
            f"stdout:\n{proc.stdout or ''}\nstderr:\n{proc.stderr or ''}",
            returncode=_RC_LIVE,
        )
    lowered = combined.lower()
    if PAPER_ONLY_RELEASE_MARKER not in lowered and PAPER_ONLY_RELEASE_CODE not in lowered:
        raise SmokeFailure(
            "live arm was refused, but not with the v0.9.6 paper-only contract. A keyring/key "
            "failure is not a paper-only refusal; the policy must refuse before credentials.\n"
            f"stdout:\n{proc.stdout or ''}\nstderr:\n{proc.stderr or ''}",
            returncode=_RC_LIVE,
        )

    # The refusal must not leave a live (or paper) arm behind.
    status = ctx.run(["status", "--venue", _VENUE], timeout=60)
    if status.returncode != 0 or "no armed packs" not in (status.stdout or ""):
        raise SmokeFailure(
            "live refusal left armed state behind; first-use smoke requires no live arm.\n"
            f"status stdout:\n{status.stdout or ''}\nstatus stderr:\n{status.stderr or ''}",
            returncode=_RC_LIVE,
        )
    # Remove the temporary grant so evidence is not confused with a real one.
    try:
        (ctx.home / "live-authorization.json").unlink()
    except FileNotFoundError:
        pass
    print("ok: live attempt -> hard-refused as paper-only; no live arm persisted")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="v0.9.6 frozen paper first-use release gate")
    parser.add_argument("--binary", required=True, help="path to the PyInstaller-frozen krellbot executable")
    parser.add_argument("--home", required=True, help="fresh isolated KRELLBOT_HOME for the runtime")
    parser.add_argument("--pack", required=True, help="example strategy pack to validate/arm")
    parser.add_argument("--workdir", default=None, help="fresh scratch dir outside the checkout")
    parser.add_argument("--log", default=None, help="smoke log path (default: <workdir>/frozen-paper-smoke.log)")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="checkout that the runtime must not borrow from (default: parent of this script)",
    )
    return parser.parse_args(argv)


def _run(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
    binary = Path(args.binary).resolve()
    home = Path(args.home).resolve()
    workdir = Path(args.workdir).resolve() if args.workdir else home.parent / f"{home.name}-work"
    log_path = Path(args.log).resolve() if args.log else workdir / "frozen-paper-smoke.log"
    pack = Path(args.pack).resolve()

    if not binary.is_file():
        raise SmokeFailure(f"frozen binary not found: {binary}")
    if not pack.is_file():
        raise SmokeFailure(f"example pack not found: {pack}")
    _assert_outside_checkout(repo_root, home, workdir, log_path)
    _prepare_fresh_dir(home, label="home")
    _prepare_fresh_dir(workdir, label="workdir")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        log_path.unlink()

    staged_binary = _stage_runtime(binary, workdir)
    staged_pack = workdir / "pack.json"
    shutil.copyfile(pack, staged_pack)

    ctx = _Context(
        binary=staged_binary,
        home=home,
        workdir=workdir,
        pack=staged_pack,
        log_path=log_path,
        base_env=dict(os.environ),
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(
            f"frozen paper first-use smoke\nbinary source: {binary}\nstaged runtime: {staged_binary}\n"
            f"home: {home}\nworkdir: {workdir}\npack: {pack}\n"
        )

    _phase_validate(ctx)
    _phase_arm(ctx)
    _phase_status(ctx, expect_armed=True)
    _phase_disarm(ctx)
    _phase_workstation(ctx)
    _phase_live_refusal(ctx)
    print(f"PASS: frozen paper first-use gate (evidence: {log_path})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        return _run(args)
    except SmokeFailure as exc:
        print(f"::error::frozen paper first-use smoke failed: {exc}", file=sys.stderr)
        log_path = Path(args.log).resolve() if args.log else None
        if log_path is not None:
            print(f"::error::evidence preserved at {log_path}", file=sys.stderr)
        return exc.returncode or 1


if __name__ == "__main__":
    raise SystemExit(main())

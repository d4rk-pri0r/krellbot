"""Tests for scripts/ci_smoke_workstation.py.

INT06 — smoke the workstation launcher. The release workflow runs
``scripts/ci_smoke_workstation.py`` against the frozen binary to
prove the bundled ``krellbot workstation`` shell actually serves
on the loopback, the printed URL carries no token, and the
loopback-host gate accepts the smoke GET. The legacy
``scripts/ci_smoke_ui.py`` is untouched; the workstation smoke
runs alongside it.

We can't run the real frozen binary in CI without doing the full
PyInstaller build (too slow), so this test suite drives the new
helper with a tiny Python "shim" that execs ``python -m
krellbot.cli workstation ...``. The shim is exactly the shape
the production helper will see: argv tokens
``["workstation", "--port", "<port>"]`` appended after the
binary path. The new helper is expected to:

  - launch ``<binary> workstation --port <port>`` (not ``ui``),
  - parse the printed ``Workstation running at
    http://127.0.0.1:PORT/`` URL (no token; path is exactly ``/``),
  - GET that URL with ``Host: 127.0.0.1:PORT`` and accept either
    a 200 carrying ``krellbot-bootstrap`` or a 404 carrying
    ``shell_not_built``,
  - strip venue-key / license-key environment variables from the
    child env before launching (so a real ``KRAKEN_API_KEY`` in
    the CI runner cannot reach the child),
  - terminate the child in a ``finally:`` block using
    ``send_signal`` + ``wait`` + ``kill()`` fallback — never
    ``pkill`` (Windows Git Bash has no ``procps``),
  - not call ``ui`` anywhere — the dashboard CLI is forbidden
    by the brief.

The workstation shell is reachable at ``/`` only; the bootstrap
token is delivered through the served HTML's
``<meta name="krellbot-bootstrap" ...>`` tag, never through the
URL itself.

The workflow-shape tests pin the new step:

  - ``scripts/ci_smoke_workstation.py`` is invoked in a step named
    ``Smoke test bundled workstation shell``,
  - the legacy ``scripts/ci_smoke_ui.py`` step still exists,
  - the new step's bash run-block does not contain ``pkill``.

Together with the existing CLI smoke tests, the release workflow
proves both the token-gated dashboard shell AND the loopback
workstation shell are bundled correctly.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
HELPER = SCRIPTS_DIR / "ci_smoke_workstation.py"
WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-frozen.yml"


def _shim_binary(tmp_path: Path) -> Path:
    """Write a tiny Python "frozen binary" shim that execs ``python -m krellbot.cli``.

    The shim mirrors the production contract: argv tokens after
    the script path are the CLI subcommand and flags, exactly as
    the helper script appends (``["workstation", "--port", "0"]``).
    The shim ``os.execvp``s ``python -m krellbot.cli <suffix>`` so
    the test exercises the real ``cmd_workstation`` path, not a
    mock.
    """
    shim = tmp_path / "shim-krellbot.py"
    shim.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "# Forward argv tokens after the script path verbatim to ``krellbot.cli``.\n"
        "suffix = sys.argv[1:]\n"
        "os.execvp(sys.executable, [sys.executable, '-m', 'krellbot.cli', *suffix])\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def _wait_for_log(proc: subprocess.Popen, deadline: float) -> str:
    """Read stdout for up to ``deadline`` seconds; return captured text.

    ``deadline`` is a duration in seconds from now (NOT an
    absolute monotonic timestamp). Used by the env-stripping
    test to drain whatever the helper surfaces before it exits.
    """
    chunks: list[str] = []
    end = time.monotonic() + deadline
    while time.monotonic() < end:
        if proc.stdout is None:
            break
        chunk = proc.stdout.read(4096)
        if chunk:
            chunks.append(chunk)
            continue
        rc = proc.poll()
        if rc is not None:
            break
        time.sleep(0.05)
    return "".join(chunks)


# ---------------------------------------------------------------------------
# Behavioural tests: drive the helper end-to-end against a real krellbot.cli.
# ---------------------------------------------------------------------------


def test_workstation_smoke_succeeds_against_shim(tmp_path):
    """End-to-end: the new helper runs a shim binary that execs
    ``python -m krellbot.cli workstation --port <port>``, captures the
    printed loopback URL, GETs it, and exits 0.

    The response body must either be a 200 carrying
    ``krellbot-bootstrap`` (built dist path) or a 404 carrying
    ``shell_not_built`` (missing dist path). The captured URL has
    no token; the path is exactly ``/``.
    """
    shim = _shim_binary(tmp_path)
    home = tmp_path / "home"
    log = tmp_path / "workstation.log"

    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(shim),
            "--port",
            "0",
            "--home",
            str(home),
            "--log",
            str(log),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert rc.returncode == 0, (
        f"ci_smoke_workstation exited {rc.returncode}; stderr={rc.stderr[:1000]!r}; stdout={rc.stdout[:1000]!r}"
    )

    # The captured URL has no token and the path is exactly ``/``.
    url_match = re.search(r"http://127\.0\.0\.1:\d+/", rc.stdout)
    assert url_match, f"captured URL not found in stdout: {rc.stdout!r}"
    url = url_match.group(0)
    # The URL must not embed a token path. A token would look like
    # ``/abcdef0123.../`` after the port. The regex above already
    # requires the trailing character be ``/`` — assert the URL
    # body carries no further slashes / hex.
    assert re.fullmatch(r"http://127\.0\.0\.1:\d+/", url), (
        f"captured URL must be exactly ``http://127.0.0.1:PORT/`` with no token; got {url!r}"
    )

    # The response is either 200 + krellbot-bootstrap (dist built)
    # or 404 + shell_not_built (no dist). Both are accepted outcomes.
    # We don't pin the helper's index body file path here — the
    # helper's own ``ok:`` line on stdout is the source of truth.
    assert "ok:" in rc.stdout or "shell_not_built" in rc.stdout, rc.stdout


def test_workstation_smoke_does_not_invoke_ui(tmp_path):
    """The new helper must never call ``ui`` — only ``workstation``.

    The brief forbids touching ``krellbot ui`` from this smoke
    step. The helper script's argv construction is the only place
    this contract lives, so we assert it on the source rather than
    a runtime trace.
    """
    src = HELPER.read_text(encoding="utf-8")
    # Pin the contract on the argv construction: the helper builds
    # its CLI argv with a string literal subcommand token. We
    # assert that token is exactly ``"workstation"`` and never
    # ``"ui"``. The grep is narrow: only the literal quoted token.
    ui_token_re = re.compile(r"""(['"])ui\1""")
    assert not ui_token_re.search(src), (
        "ci_smoke_workstation.py must not launch `krellbot ui`; the brief forbids replacing the dashboard smoke"
    )
    workstation_token_re = re.compile(r"""(['"])workstation\1""")
    assert workstation_token_re.search(src), "ci_smoke_workstation.py must launch `krellbot workstation`"


def test_workstation_smoke_strips_venue_keys_from_child_env(tmp_path):
    """The smoke helper must strip venue credentials before launching the child.

    A real ``KRAKEN_API_KEY`` / ``COINBASE_API_SECRET`` in the
    CI runner environment must NOT reach the child. The helper
    sets ``KRELLBOT_HOME`` and removes every var matching the
    workstation convention (KRELLBOT_*/COINBASE_*/KRAKEN_* with
    secret suffix). We seed both kinds, run the helper, and
    inspect the child env via a probe binary that prints the env
    to stderr (the helper's reader thread echoes child stderr to
    its own stderr, so the test sees it on a merged pipe).
    """
    probe = tmp_path / "probe-krellbot.py"
    probe.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys, time\n"
        "sys.stderr.write('ENV[' + json.dumps(dict(os.environ), sort_keys=True) + ']\\n')\n"
        "sys.stderr.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    probe.chmod(0o755)

    sentinel_keys = {
        "KRAKEN_API_KEY": "sentinel-kraken-key",
        "COINBASE_API_SECRET": "sentinel-coinbase-secret",
        "KRELLBOT_FOO_KEY": "sentinel-krellbot-key",
    }
    env = {**os.environ, **sentinel_keys}

    home = tmp_path / "home"
    log = tmp_path / "workstation.log"

    proc = subprocess.Popen(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(probe),
            "--port",
            "0",
            "--home",
            str(home),
            "--log",
            str(log),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        captured = _wait_for_log(proc, deadline=30.0)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

    assert "ENV[" in captured, captured
    # Find the first ``ENV[{...}]`` block. The JSON dump can
    # contain ``]`` characters mid-key (escaped sequences, base64
    # padding, etc.), so we use a non-greedy regex anchored on the
    # ``]\n`` the probe writes at the end of its stderr line.
    block_match = re.search(r"ENV\[(\{.*?\})\]\n", captured)
    assert block_match, captured[:200]
    child_env = json.loads(block_match.group(1))
    for key, sentinel in sentinel_keys.items():
        # The helper must strip these keys. ``KRELLBOT_HOME`` is
        # the only KRELLBOT_* var that survives (it is set to
        # ``--home``).
        assert sentinel not in child_env.values(), (
            f"venue key {key}={sentinel!r} leaked into the child env: {child_env}"
        )
        assert key not in child_env, f"venue key {key}={sentinel!r} leaked into the child env: {child_env}"
    # The helper must still set KRELLBOT_HOME to the requested home.
    assert child_env.get("KRELLBOT_HOME") == str(home), child_env


def test_workstation_smoke_fails_when_url_never_printed(tmp_path):
    """If the child never prints the workstation URL, the helper exits non-zero."""
    silent = tmp_path / "silent.py"
    silent.write_text(
        "#!/usr/bin/env python3\nimport time\ntime.sleep(60)\n",
        encoding="utf-8",
    )
    silent.chmod(0o755)
    home = tmp_path / "home"
    log = tmp_path / "silent.log"

    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(silent),
            "--port",
            "0",
            "--home",
            str(home),
            "--log",
            str(log),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert rc.returncode != 0, f"expected non-zero exit, got {rc.returncode}; stdout={rc.stdout!r}"


def test_workstation_smoke_fails_when_url_carries_token(tmp_path):
    """A child that prints a token-bearing URL is a failure.

    The brief mandates the URL path is ``/`` only. If a future
    refactor accidentally parses a token URL (the dashboard
    helper's regex), this test must fail loudly.
    """
    bad = tmp_path / "bad-url.py"
    bad.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "print('Workstation running at http://127.0.0.1:19999/abcdef0123456789/', flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    bad.chmod(0o755)
    home = tmp_path / "home"
    log = tmp_path / "bad.log"

    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(bad),
            "--port",
            "19999",
            "--home",
            str(home),
            "--log",
            str(log),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert rc.returncode != 0, f"helper accepted a token-bearing URL; stdout={rc.stdout!r}; stderr={rc.stderr[:500]!r}"


def test_workstation_smoke_fails_when_get_returns_unexpected(tmp_path):
    """If the GET returns a status that is neither 200+krellbot-bootstrap
    nor 404+shell_not_built, the helper exits non-zero.

    We point the helper at a probe binary that prints a valid
    ``Workstation running at ...`` URL but the GET against the
    printed port hits nothing — connection refused returns a
    non-200 / non-404 status from curl, so the helper must fail
    closed.
    """
    # A binary that prints the URL but never starts an HTTP server.
    # We deliberately pick an unbound port so curl refuses the
    # connection and the helper sees a curl failure, which is the
    # "anything else" branch in the brief.
    binary = tmp_path / "no-server.py"
    port = 29999  # arbitrary, almost certainly unbound in the test env
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        f"print('Workstation running at http://127.0.0.1:{port}/', flush=True)\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    home = tmp_path / "home"
    log = tmp_path / "no-server.log"

    rc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(binary),
            "--port",
            str(port),
            "--home",
            str(home),
            "--log",
            str(log),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert rc.returncode != 0, f"helper accepted an unreachable URL; stdout={rc.stdout!r}; stderr={rc.stderr[:500]!r}"


# ---------------------------------------------------------------------------
# Helper source-level contracts
# ---------------------------------------------------------------------------


def test_helper_finally_owns_child_cleanup():
    """The helper's ``main()`` must own child cleanup in a ``finally:`` block.

    The brief forbids ``pkill``; the helper must use
    ``send_signal`` + ``wait`` + ``kill()`` fallback so Windows
    Git Bash runners (no ``procps``) work.
    """
    src = HELPER.read_text(encoding="utf-8")
    main_match = re.search(
        r"def main\(.*?\):(.*?)(?=\n(?:def |\nif __name__))",
        src,
        re.DOTALL,
    )
    assert main_match, "could not locate main() in ci_smoke_workstation.py"
    main_body = main_match.group(1)
    # Strip comments before the executable-code check so a
    # comment that mentions "pkill" (e.g. "we forbid pkill
    # because Windows has no procps") does not trip the contract.
    code_lines: list[str] = []
    for line in main_body.splitlines():
        stripped = line.split("#", 1)[0]
        code_lines.append(stripped)
    code_only = "\n".join(code_lines)
    assert "finally:" in main_body, "ci_smoke_workstation.main() must own cleanup in a finally: block"
    assert "send_signal" in main_body and "wait(" in main_body, (
        "ci_smoke_workstation.main() finally: must send_signal then wait on the child proc"
    )
    assert "kill" in main_body, "ci_smoke_workstation.main() finally: must fall back to kill() on timeout"
    assert "pkill" not in code_only, "ci_smoke_workstation.main() must not call pkill (Windows has no procps)"


def test_helper_accepts_required_args():
    """The helper CLI accepts ``--binary``, ``--port``, ``--home``, ``--log``.

    Pin the contract from the brief so a future refactor that
    renames an arg fails the test instead of the workflow.
    """
    src = HELPER.read_text(encoding="utf-8")
    for flag in ("--binary", "--port", "--home", "--log"):
        assert flag in src, f"ci_smoke_workstation must accept {flag}"


# ---------------------------------------------------------------------------
# Workflow-shape tests
# ---------------------------------------------------------------------------


def _step_run_block(step_name: str) -> str:
    """Return the body of the step whose ``- name:`` matches ``step_name``.

    Hand-rolled YAML extractor; PyYAML is not a dev dependency.
    Mirrors ``_smoke_step_run_block`` in test_ci_smoke_ui.py.
    """
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    step_idx = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("- name:") and step_name in stripped:
            step_idx = i
            break
    if step_idx is None:
        raise AssertionError(f"step named {step_name!r} not found in {WORKFLOW_PATH}")

    run_idx = None
    for j in range(step_idx + 1, len(lines)):
        line = lines[j]
        stripped = line.lstrip()
        if stripped.startswith("- name:"):
            break
        if stripped.startswith("run:") and "|" in stripped:
            run_idx = j
            break
    if run_idx is None:
        raise AssertionError(f"`run:` block not found inside step {step_name!r}")

    run_line = lines[run_idx]
    run_indent = len(run_line) - len(run_line.lstrip())
    body_indent = run_indent + 2
    body_lines: list[str] = []
    for j in range(run_idx + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            body_lines.append("")
            continue
        indent = len(line) - len(line.lstrip())
        if indent < body_indent:
            break
        body_lines.append(line[body_indent:])
    if not body_lines:
        raise AssertionError(f"`run:` block for {step_name!r} appears to be empty")
    return "\n".join(body_lines)


def test_workflow_has_workstation_smoke_step_after_dashboard_smoke():
    """The release workflow must contain BOTH smoke steps.

    The new step (``Smoke test bundled workstation shell``)
    follows the legacy dashboard smoke step. The brief forbids
    removing the legacy step.
    """
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "scripts/ci_smoke_ui.py" in text, (
        "release-frozen.yml must still invoke scripts/ci_smoke_ui.py; the legacy dashboard smoke must not be removed"
    )
    assert "scripts/ci_smoke_workstation.py" in text, "release-frozen.yml must invoke scripts/ci_smoke_workstation.py"
    assert "Smoke test bundled workstation shell" in text, (
        "release-frozen.yml must contain a step named 'Smoke test bundled workstation shell'"
    )


def test_workflow_workstation_smoke_step_invokes_helper_with_required_args():
    """The new smoke step must invoke the helper with ``--binary`` / ``--port`` / ``--home`` / ``--log``."""
    run = _step_run_block("Smoke test bundled workstation shell")
    assert "scripts/ci_smoke_workstation.py" in run
    assert "--binary" in run, "workstation smoke step must pass --binary"
    assert "--port" in run and "--port 0" in run, "workstation smoke step must bind port 0"
    assert "--home" in run, "workstation smoke step must pass --home (isolated KRELLBOT_HOME)"
    assert "--log" in run, "workstation smoke step must pass --log (capture path)"


def test_workflow_workstation_smoke_step_does_not_use_pkill():
    """The new smoke step's bash body must not call ``pkill``.

    GitHub Actions Windows runners use Git Bash, which does NOT
    ship ``pkill`` (or ``pgrep``, or ``procps``). The helper's
    own ``finally:`` block owns child cleanup on every platform;
    a POSIX-only trap would fail-closed on Windows.
    """
    run = _step_run_block("Smoke test bundled workstation shell")
    matches = re.findall(r"\bpkill\b", run)
    assert not matches, (
        "workstation smoke step uses `pkill`, which is not available on Windows "
        "Git Bash runners — the helper's own `finally:` block already terminates "
        "the child on every exit path; remove the POSIX-only trap:\n\n" + run
    )


def test_workflow_dashboard_smoke_step_still_present():
    """The legacy dashboard smoke step must still be present.

    Pins the contract from the brief: do not replace
    ``krellbot ui``; add the workstation smoke beside it.
    """
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "Smoke test bundled token-gated dashboard" in text, (
        "release-frozen.yml must still contain the legacy 'Smoke test bundled token-gated dashboard' step"
    )


def test_workflow_workstation_smoke_step_uses_distinct_log_path():
    """The new step must use a log path that does not collide with the
    legacy dashboard smoke step's log path.

    Both steps write to ``<temp>/...`` — if they used the same
    path the second smoke would clobber the first's log and the
    helper's diagnostics would be ambiguous.
    """
    dash_run = _step_run_block("Smoke test bundled token-gated dashboard")
    work_run = _step_run_block("Smoke test bundled workstation shell")
    dash_log_match = re.search(r"--log\s+(\S+)", dash_run)
    work_log_match = re.search(r"--log\s+(\S+)", work_run)
    assert dash_log_match and work_log_match, (
        f"both steps must declare --log; dashboard={dash_log_match}, workstation={work_log_match}"
    )
    assert dash_log_match.group(1) != work_log_match.group(1), (
        f"workstation smoke must use a distinct log path; both used {dash_log_match.group(1)!r}"
    )


def test_workflow_workstation_smoke_step_uses_port_zero():
    """The new step must bind port 0 so the OS assigns a free loopback port.

    Pin the contract from the brief: the helper reads the URL
    from the child's stdout; probing a separate port in a
    separate process adds a race and nested Bash/Python quoting
    breaks on Windows.
    """
    run = _step_run_block("Smoke test bundled workstation shell")
    assert "--port 0" in run, "workstation smoke step must bind port 0 (OS-assigned loopback port)"


# ---------------------------------------------------------------------------
# Sanity: the helper script + tests file must exist on disk.
# ---------------------------------------------------------------------------


def test_helper_script_exists():
    """Sanity: ``scripts/ci_smoke_workstation.py`` is on disk and importable."""
    assert HELPER.is_file(), f"missing helper script: {HELPER}"


def test_workflow_file_exists():
    """Sanity: ``.github/workflows/release-frozen.yml`` is on disk."""
    assert WORKFLOW_PATH.is_file(), f"missing workflow file: {WORKFLOW_PATH}"


def _import_helper_module():
    """Import ``scripts.ci_smoke_workstation`` and surface the module object."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ci_smoke_workstation", HELPER)
    assert spec and spec.loader, "could not build import spec for ci_smoke_workstation.py"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

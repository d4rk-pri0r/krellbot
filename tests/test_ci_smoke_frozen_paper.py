"""Tests for the v0.9.6 three-platform frozen paper first-use smoke.

The release gate must run the *actual* PyInstaller-built binary outside
the checkout, with a fresh isolated home, stripped credential /
``PYTHONPATH`` environment, and no real venue requests. It then has to
prove the frozen runtime can:

1. validate a supplied example strategy pack (reads bundled
   ``krellbot/pack/schema.json`` through ``importlib.resources``),
2. arm that pack for paper,
3. report it through ``status``, and
4. disarm it.

It must also require the built workstation shell (a 404
``shell_not_built`` is a failure, not a pass) and attempt a live arm
with ``KRELLBOT_ENABLE_LIVE=1`` that must hard-refuse as paper-only.

The live-refusal assertion is deliberately red on the current base:
the v0.9.6 paper-only policy is being implemented by a different
writer/worktree and is not merged here. We do not weaken the gate to
make this suite green on the wrong tree.

These tests drive the helper with small Python shims. They do not run
PyInstaller and never touch a real key, keyring, or network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
HELPER = SCRIPTS_DIR / "ci_smoke_frozen_paper.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "release-frozen.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"

PAPER_ONLY_MESSAGE = (
    "v0.9.6 is a paper-only release: live order send is disabled regardless of "
    "environment, stored keys, or authorization. This is temporary; an "
    "owner-approved code change can re-enable live trading."
)


def _load_helper():
    """Import ``scripts.ci_smoke_frozen_paper`` for unit-level checks."""
    spec = importlib.util.spec_from_file_location("ci_smoke_frozen_paper_under_test", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve string annotations through sys.modules; register
    # the module before executing it so ``@dataclass`` can find itself.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_bundle(
    tmp_path: Path,
    *,
    live_policy: str = "paper_only",
    workstation: str = "built",
    live_exit: int = 1,
) -> Path:
    """Write a portable Python shim that behaves like the frozen CLI.

    ``live_policy='paper_only'`` models the merged v0.9.6 policy. The
    ``'current_base'`` variant models today's gate, which falls through
    to the keyring and reports ``no key stored`` — exactly the shape the
    smoke must reject as "not a paper-only refusal".
    """
    bundle = tmp_path / "fake-dist" / "krellbot"
    bundle.mkdir(parents=True)
    shim = bundle / "krellbot.py"
    shim.write_text(
        f"""
import json
import os
import sys
from pathlib import Path

POLICY = {live_policy!r}
WORKSTATION = {workstation!r}
LIVE_EXIT = {live_exit!r}

args = sys.argv[1:]
cmd = args[0] if args else ""
HOME = Path(os.environ["KRELLBOT_HOME"])

def _diag():
    rec = {{
        "argv": args,
        "cwd": os.getcwd(),
        "bundle_dir": str(Path(__file__).resolve().parent),
        "home": os.environ.get("KRELLBOT_HOME"),
        "pythonpath": os.environ.get("PYTHONPATH"),
        "enable_live": os.environ.get("KRELLBOT_ENABLE_LIVE"),
        "kraken_key": os.environ.get("KRAKEN_API_KEY"),
        "krellbot_key": os.environ.get("KRELLBOT_KRAKEN_KEY"),
    }}
    with (HOME / "diag.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\\n")

if cmd == "lint":
    _diag()
    print("ok")
    raise SystemExit(0)

if cmd == "arm":
    _diag()
    mode = args[args.index("--mode") + 1]
    if mode == "live":
        if os.environ.get("KRELLBOT_ENABLE_LIVE") == "1":
            if POLICY == "paper_only" and LIVE_EXIT == 0:
                print("armed trend-follow 1.0.0 on kraken SUIUSD")
                raise SystemExit(0)
            if POLICY == "paper_only":
                print("live refused: " + {PAPER_ONLY_MESSAGE!r})
            else:
                print("live refused: no key stored for kraken")
            raise SystemExit(1)
        print("live is off; set KRELLBOT_ENABLE_LIVE=1 to arm a live pack")
        raise SystemExit(1)
    (HOME / "armed.txt").write_text(mode, encoding="utf-8")
    print("armed trend-follow 1.0.0 on kraken SUIUSD")
    print("armed trend-follow 1.0.0 on kraken SUIUSD")
    raise SystemExit(0)

if cmd == "status":
    _diag()
    armed = HOME / "armed.txt"
    if armed.exists():
        print("trend-follow 1.0.0 kraken SUIUSD cap=25 stop=5 mode=" + armed.read_text() + " requires_license=False")
    else:
        print("no armed packs")
    raise SystemExit(0)

if cmd == "disarm":
    _diag()
    armed = HOME / "armed.txt"
    if not armed.exists():
        print("not armed: kraken SUIUSD")
        raise SystemExit(1)
    armed.unlink()
    print("disarmed kraken SUIUSD")
    raise SystemExit(0)

if cmd == "workstation":
    _diag()
    port = int(args[args.index("--port") + 1])
    built = WORKSTATION == "built"
    import socket

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(5)
    actual = srv.getsockname()[1]
    print(f"Workstation running at http://127.0.0.1:{{actual}}/", flush=True)
    while True:
        conn, _ = srv.accept()
        try:
            conn.recv(4096)
            if built:
                body = b'<!doctype html><html><head><meta name="krellbot-bootstrap" content="t"></head></html>'
                status = b"200 OK"
                ctype = b"text/html"
            else:
                body = b'{{"code":"shell_not_built"}}'
                status = b"404 Not Found"
                ctype = b"application/json"
            head = (
                b"HTTP/1.1 " + status + b"\\r\\nContent-Type: " + ctype
                + b"\\r\\nContent-Length: " + str(len(body)).encode()
                + b"\\r\\nConnection: close\\r\\n\\r\\n"
            )
            conn.sendall(head + body)
        finally:
            conn.close()

print("unexpected command: " + cmd)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim


def _run_helper(tmp_path: Path, shim: Path, *, home: Path | None = None, workdir: Path | None = None):
    home = home or (tmp_path / "fresh-home")
    workdir = workdir or (tmp_path / "work")
    pack = tmp_path / "example-pack.json"
    pack.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "trend-follow",
                "version": "1.0.0",
                "label": "Trend follow",
                "author": "krellbot",
                "origin": "Written on this machine.",
                "timeframe": "1h",
                "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
                "entry": ["close", ">", "sma20"],
                "exit": ["close", "<", "sma20"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
                "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
            }
        ),
        encoding="utf-8",
    )
    return subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--binary",
            str(shim),
            "--home",
            str(home),
            "--workdir",
            str(workdir),
            "--pack",
            str(pack),
        ],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Environment isolation
# ---------------------------------------------------------------------------


def test_child_env_strips_credentials_pythonpath_and_real_home(tmp_path):
    module = _load_helper()
    home = tmp_path / "home"
    base = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": "/home/real-user",
        "USERPROFILE": "C:\\Users\\real-user",
        "PYTHONPATH": "/repo/src",
        "PYTHONHOME": "/usr",
        "PYTHONSTARTUP": "/repo/start.py",
        "KRAKEN_API_KEY": "real-kraken-key",
        "KRAKEN_API_SECRET": "real-kraken-secret",
        "COINBASE_SECRET": "real-coinbase",
        "KRELLBOT_KRAKEN_KEY": "real-krellbot-key",
        "KRELLBOT_KRAKEN_SECRET": "real-krellbot-secret",
        "KRELLBOT_KRAKEN_KEYFILE": "/home/real-user/keyfile",
        "KRELLBOT_ENABLE_LIVE": "1",
        "KRELLBOT_HOME": "/home/real-user/.krellbot",
        "KRELLBOT_API": "https://api.example",
        "LANG": "C.UTF-8",
    }

    env = module._child_env(base, home, enable_live="0")

    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
    assert "PYTHONSTARTUP" not in env
    for name in (
        "KRAKEN_API_KEY",
        "KRAKEN_API_SECRET",
        "COINBASE_SECRET",
        "KRELLBOT_KRAKEN_KEY",
        "KRELLBOT_KRAKEN_SECRET",
        "KRELLBOT_KRAKEN_KEYFILE",
        "KRELLBOT_API",
    ):
        assert name not in env, f"{name} must be stripped from the frozen child env"
    assert env["KRELLBOT_HOME"] == str(home)
    assert env["HOME"] == str(home)
    assert env["USERPROFILE"] == str(home)
    assert env["KRELLBOT_ENABLE_LIVE"] == "0"
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.fail.Keyring"
    assert env["PATH"] == base["PATH"]
    assert env["LANG"] == "C.UTF-8"


def test_child_env_forces_fail_backend_selected_by_keyring(tmp_path, monkeypatch):
    import keyring.core

    module = _load_helper()
    for inherited in (None, "keyring.backends.null.Keyring"):
        base = {"PYTHONKEYRING_BACKEND": "keyring.backends.null.Keyring"}
        if inherited is not None:
            base["PYTHON_KEYRING_BACKEND"] = inherited
        env = module._child_env(base, tmp_path / "home")
        # Exercise the installed library's actual environment selection, not
        # get_keyring(), which could discover a real OS keychain on failure.
        with monkeypatch.context() as scoped:
            scoped.setattr(os, "environ", env)
            backend = keyring.core.load_env()
        assert backend is not None, "keyring ignored the helper's backend override"
        assert type(backend).__module__ == "keyring.backends.fail"
        assert "PYTHONKEYRING_BACKEND" not in env


def test_workflow_forces_fail_keyring_for_every_build_step():
    text = WORKFLOW.read_text(encoding="utf-8")
    build_env = re.search(r"^    env:\n(?:^      .*\n)+", text, re.MULTILINE)
    assert build_env is not None
    assert "      PYTHON_KEYRING_BACKEND: keyring.backends.fail.Keyring\n" in build_env.group()
    assert "PYTHONKEYRING_BACKEND:" not in text


def test_child_env_enables_live_only_when_explicitly_requested(tmp_path):
    module = _load_helper()
    env = module._child_env({"PATH": "/bin"}, tmp_path / "home", enable_live="1")
    assert env["KRELLBOT_ENABLE_LIVE"] == "1"


# ---------------------------------------------------------------------------
# Fresh-home / outside-checkout contract
# ---------------------------------------------------------------------------


def test_non_empty_home_is_refused_before_launch(tmp_path):
    shim = _fake_bundle(tmp_path)
    home = tmp_path / "fresh-home"
    home.mkdir()
    (home / "state.json").write_text("{}", encoding="utf-8")

    result = _run_helper(tmp_path, shim, home=home)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "not fresh" in combined.lower() or "non-empty" in combined.lower(), combined


def test_workdir_inside_checkout_is_refused(tmp_path):
    shim = _fake_bundle(tmp_path)
    inside = REPO_ROOT / ".ci-smoke-tmp-should-not-exist"
    result = _run_helper(tmp_path, shim, workdir=inside)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "checkout" in combined.lower() or "repo" in combined.lower(), combined
    assert not inside.exists(), "helper must not create a workdir inside the checkout"


# ---------------------------------------------------------------------------
# Full first-use path
# ---------------------------------------------------------------------------


def test_full_first_use_passes_and_uses_copied_bundle_outside_checkout(tmp_path):
    shim = _fake_bundle(tmp_path)
    result = _run_helper(tmp_path, shim)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "validate" in combined.lower()
    assert "paper arm" in combined.lower()
    assert "paper status" in combined.lower()
    assert "disarm" in combined.lower()
    assert "workstation" in combined.lower()
    assert "paper-only" in combined.lower()

    diag_path = tmp_path / "fresh-home" / "diag.jsonl"
    rows = [json.loads(line) for line in diag_path.read_text(encoding="utf-8").splitlines() if line]
    assert rows, "the frozen shim must have been executed"
    expected_home = (tmp_path / "fresh-home").resolve()
    expected_cwd = (tmp_path / "work").resolve()
    expected_runtime = (tmp_path / "work" / "runtime").resolve()
    for row in rows:
        assert Path(row["home"]).resolve() == expected_home
        assert row["pythonpath"] is None, "PYTHONPATH must not reach the frozen runtime"
        assert row["kraken_key"] is None
        assert row["krellbot_key"] is None
        assert Path(row["cwd"]).resolve() == expected_cwd
        assert Path(row["bundle_dir"]).resolve().is_relative_to(expected_runtime), (
            f"runtime must execute from the copied bundle, got {row['bundle_dir']!r}"
        )

    # The live attempt is the only row with ENABLE_LIVE=1, and it must not arm.
    live_rows = [row for row in rows if row["enable_live"] == "1"]
    assert len(live_rows) == 1, f"expected one live attempt, got {live_rows!r}"
    assert not (tmp_path / "fresh-home" / "armed.txt").exists()


def test_live_attempt_is_checked_for_paper_only_refusal(tmp_path):
    """A live arm that merely says 'no key stored' is not a paper-only refusal."""
    shim = _fake_bundle(tmp_path, live_policy="current_base")
    result = _run_helper(tmp_path, shim)
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "paper-only" in combined.lower(), combined
    assert "live attempt" in combined.lower() or "live arm" in combined.lower(), combined


def test_live_attempt_that_succeeds_is_refused(tmp_path):
    # A policy that returns 0 on a live arm must still fail the smoke.
    shim = _fake_bundle(tmp_path, live_policy="paper_only", live_exit=0)

    result = _run_helper(tmp_path, shim)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "live" in combined.lower(), combined
    assert "succeeded" in combined.lower() or "succeed" in combined.lower(), combined


# ---------------------------------------------------------------------------
# Workstation must be genuinely built
# ---------------------------------------------------------------------------


def test_workstation_404_shell_not_built_fails(tmp_path):
    shim = _fake_bundle(tmp_path, workstation="not_built")
    result = _run_helper(tmp_path, shim)
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "shell_not_built" in combined, combined
    assert "workstation" in combined.lower()


def test_workstation_200_without_bootstrap_marker_fails(tmp_path):
    shim = _fake_bundle(tmp_path)
    text = shim.read_text(encoding="utf-8")
    text = text.replace('meta name="krellbot-bootstrap"', 'meta name="not-bootstrap"')
    shim.write_text(text, encoding="utf-8")

    result = _run_helper(tmp_path, shim)
    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "bootstrap" in combined.lower(), combined


# ---------------------------------------------------------------------------
# Workflow gate: every native build runs the smoke; publish waits for all
# ---------------------------------------------------------------------------


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_runs_frozen_paper_smoke_on_all_three_native_platforms():
    text = _workflow_text()
    assert "scripts/ci_smoke_frozen_paper.py" in text, "release workflow must invoke the new frozen first-use smoke"
    assert re.search(r"os:\s*windows-latest", text)
    assert re.search(r"os:\s*ubuntu-latest", text)
    assert re.search(r"os:\s*macos-latest", text)
    assert "--binary" in text
    assert "--home" in text
    assert "--workdir" in text
    assert "--pack" in text


def test_workflow_smoke_step_cannot_be_bypassed():
    text = _workflow_text()
    assert "continue-on-error" not in text, "a failed frozen first-use smoke must never be tolerated"
    # publish must depend on the complete build matrix, and only the tag
    # condition may gate it (no smoke-specific bypass).
    publish = text.split("  publish:", 1)[1]
    assert re.search(r"^\s*needs:\s*build\s*$", publish, re.MULTILINE), "publish must need the build matrix"
    assert "startsWith(github.ref, 'refs/tags/v')" in publish
    assert "if:" not in publish.replace("if: startsWith(github.ref, 'refs/tags/v')", ""), (
        "publish must not add a second conditional that can bypass the native smoke"
    )


def test_workflow_preserves_failure_evidence():
    text = _workflow_text()
    assert "if: always()" in text or "if: ${{ always() }}" in text
    assert "frozen-paper" in text.lower()
    assert "upload-artifact" in text


def test_workflow_version_env_is_096():
    text = _workflow_text()
    match = re.search(r'^\s*KRELLBOT_VERSION:\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert match.group(1) == "0.9.6", f"release workflow KRELLBOT_VERSION must be 0.9.6; got {match.group(1)!r}"


def test_pyproject_version_is_096():
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert match.group(1) == "0.9.6"

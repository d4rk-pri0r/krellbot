"""Site installer wrapper default/`ui` matches an engine command that serves `/`.

Fetches ``https://krellbot.dev/api/install?os=linux`` (or a pinned fixture of
the launcher wrapper) into an isolated temp HOME, extracts the wrapper the
site installer would write, and asserts that the wrapper's no-arg / ``ui``
invocation matches an engine command that exits 0 while serving ``/``.

No secrets, no exchange credentials, no signing. Loud failure if the cloud
wrapper still invokes a dead command the engine no longer accepts.
"""

from __future__ import annotations

import http.client
import os
import re
import signal
import subprocess
import sys
import textwrap
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

INSTALL_URL = "https://krellbot.dev/api/install?os=linux"
FIXTURE_WRAPPER = Path(__file__).resolve().parent / "fixtures" / "installer" / "linux_launcher_wrapper.sh"
REPO_ROOT = Path(__file__).resolve().parent.parent

# Wrapper heredoc body inside the rendered POSIX installer.
_WRAPPER_HEREDOC_RE = re.compile(
    r"<<'WRAPPER_EOF'\n(?P<body>.*?)\nWRAPPER_EOF",
    re.DOTALL,
)
# Default argv the wrapper injects on a bare invocation.
_DEFAULT_SET_RE = re.compile(
    r'^\s*if\s+\[\s+"\$#"\s+-eq\s+0\s+\]\s*;\s*then\s*\n'
    r"\s*set\s+--\s+(?P<args>.+?)\s*\n"
    r"\s*fi\s*$",
    re.MULTILINE,
)
_URL_LINE_RE = re.compile(r"^Workstation running at (http://127\.0\.0\.1:\d+/)")

SECRET_ENV_PREFIXES = ("KRELLBOT_", "COINBASE_", "KRAKEN_")
SECRET_ENV_SUFFIXES = ("_KEY", "_SECRET", "_KEYFILE")
KEEP_KRELLBOT_EXACT = frozenset({"KRELLBOT_HOME", "KRELLBOT_API"})
KEEP_KRELLBOT_PREFIX = ("KRELLBOT_KB_", "KRELLBOT_NPM")

# Accepted engine-side commands for the site-wrapper default.
_COMPATIBLE_HEADS = frozenset({"ui", "workstation"})


def _sanitized_env(home: Path) -> dict[str, str]:
    """Env for child processes: isolated home, no venue/license secrets."""

    keep: dict[str, str] = {}
    for name, value in os.environ.items():
        if any(name.startswith(p) for p in SECRET_ENV_PREFIXES):
            if any(name.endswith(s) for s in SECRET_ENV_SUFFIXES):
                continue
            if name in KEEP_KRELLBOT_EXACT:
                keep[name] = value
                continue
            if name.startswith(KEEP_KRELLBOT_PREFIX):
                keep[name] = value
                continue
            continue
        keep[name] = value
    keep["KRELLBOT_HOME"] = str(home)
    keep["HOME"] = str(home)
    keep["USERPROFILE"] = str(home)
    keep["PYTHONUNBUFFERED"] = "1"
    keep["KRELLBOT_ENABLE_LIVE"] = "0"
    keep.setdefault("PYTHON_KEYRING_BACKEND", "tests.fakes.fake_keyring.FakeKeyring")
    return keep


def _make_built_dist(dist: Path) -> Path:
    """Minimal Vite-shaped dist so the workstation static layer can serve `/`."""

    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        textwrap.dedent(
            """\
            <!doctype html>
            <html lang="en">
              <head>
                <meta charset="utf-8">
                <title>krellbot -- paper workstation</title>
                <script type="module" crossorigin src="/assets/app.js"></script>
              </head>
              <body>
                <div id="root">Paper workstation</div>
              </body>
            </html>
            """
        ),
        encoding="utf-8",
    )
    assets = dist / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "app.js").write_text(
        "// Paper workstation shell bundle\nconsole.log('Paper workstation');\n",
        encoding="utf-8",
    )
    return dist


def _fetch_linux_installer(*, timeout: float = 30.0) -> str:
    """Download the live POSIX installer script. Fail loudly on any error."""

    req = urllib.request.Request(
        INSTALL_URL,
        headers={"User-Agent": "krellbot-ci-installer-wrapper-check/1.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = "utf-8"
            ctype = resp.headers.get_content_charset()
            if ctype:
                charset = ctype
    except urllib.error.HTTPError as exc:
        pytest.fail(f"cloud installer fetch failed loudly: HTTP {exc.code} from {INSTALL_URL}: {exc.reason}")
    except urllib.error.URLError as exc:
        pytest.fail(f"cloud installer fetch failed loudly: could not reach {INSTALL_URL}: {exc.reason}")
    except TimeoutError:
        pytest.fail(f"cloud installer fetch failed loudly: timed out fetching {INSTALL_URL}")

    if not raw:
        pytest.fail(f"cloud installer fetch failed loudly: empty body from {INSTALL_URL}")
    try:
        text = raw.decode(charset)
    except UnicodeDecodeError as exc:
        pytest.fail(f"cloud installer fetch failed loudly: non-text body from {INSTALL_URL}: {exc}")
    if "WRAPPER_EOF" not in text and "set --" not in text:
        pytest.fail(
            "cloud installer fetch failed loudly: response is not a recognizable "
            f"POSIX installer wrapper script (url={INSTALL_URL}, bytes={len(raw)})"
        )
    return text


def _load_installer_source() -> tuple[str, str]:
    """Return ``(source_label, installer_or_wrapper_text)``.

    Default: fetch the live cloud installer. Set
    ``KRELLBOT_INSTALLER_SOURCE=fixture`` to use the pinned wrapper fixture
    instead (offline / hermetic). Live fetch remains the CI default so a
    broken cloud wrapper fails the job loudly.
    """

    mode = os.environ.get("KRELLBOT_INSTALLER_SOURCE", "fetch").strip().lower()
    if mode in {"fixture", "pinned", "local"}:
        if not FIXTURE_WRAPPER.is_file():
            pytest.fail(f"pinned installer wrapper fixture missing: {FIXTURE_WRAPPER}")
        return "fixture", FIXTURE_WRAPPER.read_text(encoding="utf-8")
    return "fetch", _fetch_linux_installer()


def _extract_wrapper_body(installer_text: str) -> str:
    """Pull the launcher wrapper heredoc (or accept a bare wrapper fixture)."""

    match = _WRAPPER_HEREDOC_RE.search(installer_text)
    if match:
        return match.group("body").strip() + "\n"
    # Pinned fixture is already just the wrapper body.
    if installer_text.lstrip().startswith("#!/bin/sh") and "set --" in installer_text:
        return installer_text if installer_text.endswith("\n") else installer_text + "\n"
    pytest.fail(
        "installer wrapper extraction failed loudly: no WRAPPER_EOF heredoc and "
        "body is not a recognizable launcher wrapper"
    )


def _default_argv_from_wrapper(wrapper_body: str) -> list[str]:
    """Parse the bare-invocation ``set -- ...`` default from the wrapper."""

    match = _DEFAULT_SET_RE.search(wrapper_body)
    if not match:
        pytest.fail(
            'cloud/fixture wrapper is broken: no bare-invocation `if [ "$#" -eq 0 ]; then set -- ...; fi` block found'
        )
    tokens = match.group("args").split()
    if not tokens:
        pytest.fail("cloud/fixture wrapper is broken: bare-invocation `set --` has no arguments")
    return tokens


def _materialize_wrapper(
    *,
    home: Path,
    wrapper_body: str,
    version: str = "ci-test",
    binary_path: Path,
) -> Path:
    """Write the site launcher under ``home/.local/bin/krellbot``.

    The wrapper computes the staged binary as
    ``$HOME/.local/share/krellbot/versions/<VERSION>/krellbot``. We place a
    stub (or shim) there and substitute the version sentinel.
    """

    versions_dir = home / ".local" / "share" / "krellbot" / "versions" / version
    versions_dir.mkdir(parents=True, exist_ok=True)
    staged = versions_dir / "krellbot"
    if binary_path.resolve() != staged.resolve():
        staged.write_bytes(binary_path.read_bytes())
        staged.chmod(0o755)

    launcher_bin = home / ".local" / "bin"
    launcher_bin.mkdir(parents=True, exist_ok=True)
    launcher = launcher_bin / "krellbot"
    body = wrapper_body.replace("%%KRELLBOT_VERSION%%", version)
    if "%%KRELLBOT_VERSION%%" in body:
        pytest.fail("wrapper still contains unsubstituted %%KRELLBOT_VERSION%% sentinel")
    launcher.write_text(body, encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def _write_argv_recorder(path: Path) -> Path:
    """POSIX shim that records argv to ``$KRELLBOT_HOME/wrapper-argv.txt``."""

    path.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            # Test-only argv recorder. No network. No secrets.
            mkdir -p -- "${KRELLBOT_HOME}" || exit 1
            out="${KRELLBOT_HOME}/wrapper-argv.txt"
            : > "$out"
            for arg in "$@"; do
                printf '%s\\n' "$arg" >> "$out"
            done
            exit 0
            """
        ),
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _wait_for_url(proc: subprocess.Popen[str], timeout: float = 15.0) -> str:
    assert proc.stdout is not None
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
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found:
            return found[0]
        if proc.poll() is not None:
            pytest.fail(f"engine exited {proc.returncode} before printing URL: {remaining!r}")
        time.sleep(0.05)
    proc.kill()
    try:
        proc.communicate(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    pytest.fail(f"timed out waiting for workstation URL; child output={remaining!r}")


def _stop(proc: subprocess.Popen[str]) -> None:
    if sys.platform == "win32":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGINT)


def _spawn_engine(home: Path, argv_tail: list[str], *, dist: Path) -> subprocess.Popen[str]:
    """Spawn the in-tree engine CLI with the wrapper's default argv plus bind flags."""

    argv = [
        sys.executable,
        "-m",
        "krellbot.cli",
        *argv_tail,
        "--port",
        "0",
        "--dist",
        str(dist),
    ]
    popen_kwargs: dict[str, object] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "encoding": "utf-8",
        "env": _sanitized_env(home),
        "bufsize": 1,
    }
    if sys.platform == "win32":
        import subprocess as _sp

        popen_kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    return subprocess.Popen(argv, **popen_kwargs)  # type: ignore[arg-type]


def _assert_serves_root(url: str) -> None:
    assert url.startswith("http://127.0.0.1:"), url
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
    decoded = body.decode("utf-8", errors="replace")
    assert "krellbot-bootstrap" in decoded, decoded[:512]


# ----- tests -----------------------------------------------------------------


@pytest.fixture(scope="module")
def installer_source() -> tuple[str, str]:
    """Fetch (or pin) the installer once per module to keep CI quiet and fast."""

    return _load_installer_source()


def test_fetched_installer_wrapper_defaults_to_compatible_ui(tmp_path: Path, installer_source: tuple[str, str]) -> None:
    """Fetch (or pin) the installer, materialize the wrapper under a temp HOME,
    and assert bare invocation yields an engine-compatible ``ui``/``workstation``
    ``--open`` argv. No secrets in the fixture or logs.
    """

    source, text = installer_source
    wrapper = _extract_wrapper_body(text)
    default_argv = _default_argv_from_wrapper(wrapper)
    assert default_argv[0] in _COMPATIBLE_HEADS, (
        f"{source} wrapper default head {default_argv[0]!r} is not engine-compatible "
        f"(expected one of {sorted(_COMPATIBLE_HEADS)}); cloud wrapper still broken?"
    )
    assert "--open" in default_argv, (
        f"{source} wrapper default argv {default_argv!r} is missing --open; cloud wrapper still broken?"
    )

    # No credentials may appear in the installer text we consume.
    lowered = text.lower()
    for needle in ("api_key", "api-secret", "private_key", "authorization: bearer"):
        assert needle not in lowered, f"installer source unexpectedly contains {needle!r}"

    if sys.platform == "win32":
        # Shell wrapper execution is POSIX; parsing above is the Windows pin.
        return

    home = tmp_path / "home"
    home.mkdir()
    recorder = _write_argv_recorder(tmp_path / "recorder.sh")
    launcher = _materialize_wrapper(home=home, wrapper_body=wrapper, binary_path=recorder)

    env = _sanitized_env(home / "data")
    env["HOME"] = str(home)
    # Wrapper defaults KRELLBOT_HOME to $HOME/.krellbot when unset.
    env.pop("KRELLBOT_HOME", None)
    result = subprocess.run(
        [str(launcher)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    recorded_path = home / ".krellbot" / "wrapper-argv.txt"
    assert recorded_path.is_file(), (
        f"wrapper did not invoke staged binary; stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    recorded = [line for line in recorded_path.read_text(encoding="utf-8").splitlines() if line]
    assert recorded == default_argv, (
        f"bare wrapper argv {recorded!r} != parsed default {default_argv!r} (source={source})"
    )


def test_wrapper_default_argv_serves_index(tmp_path: Path, installer_source: tuple[str, str]) -> None:
    """Engine command matching the wrapper default exits cleanly while serving `/`."""

    source, text = installer_source
    wrapper = _extract_wrapper_body(text)
    default_argv = _default_argv_from_wrapper(wrapper)
    assert default_argv[0] in _COMPATIBLE_HEADS, (
        f"{source} wrapper default {default_argv!r} is not engine-compatible; cloud wrapper still broken?"
    )

    dist = _make_built_dist(tmp_path / "dist")
    home = tmp_path / "engine-home"
    home.mkdir()
    proc = _spawn_engine(home, default_argv, dist=dist)
    try:
        url = _wait_for_url(proc, timeout=15.0)
        _assert_serves_root(url)
    finally:
        _stop(proc)
        try:
            stdout, _ = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, _ = proc.communicate(timeout=2)
        if proc.returncode not in (0, 0xC000013A, -signal.SIGINT):
            pytest.fail(
                f"engine did not exit cleanly after wrapper-compatible argv "
                f"{default_argv!r}: rc={proc.returncode} stdout={stdout!r}"
            )


def test_pinned_wrapper_fixture_is_engine_compatible() -> None:
    """Pinned fixture stays aligned with the engine ``ui`` alias contract."""

    assert FIXTURE_WRAPPER.is_file(), FIXTURE_WRAPPER
    body = FIXTURE_WRAPPER.read_text(encoding="utf-8")
    argv = _default_argv_from_wrapper(body)
    assert argv == ["ui", "--open"], argv
    # Fixture must not embed secrets or absolute install-time user paths.
    assert "sk-" not in body
    assert "/home/" not in body
    assert "%%KRELLBOT_VERSION%%" in body

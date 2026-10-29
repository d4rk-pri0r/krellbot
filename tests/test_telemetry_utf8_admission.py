"""Issue 341: invalid-UTF-8 telemetry.json is absorbed like torn JSON.

`telemetry._load` reads ``$KRELLBOT_HOME/telemetry.json`` as UTF-8. Torn
JSON, an unreadable (chmod 000) file, and a directory named telemetry.json
are absorbed by ``_load`` today. A file holding invalid UTF-8 bytes instead
escaped as a raw ``UnicodeDecodeError`` traceback, so every
``krellbot telemetry enable | disable | show`` invocation exited rc 1.

These tests pin the fixed typing with real subprocess CLI runs against an
isolated ``KRELLBOT_HOME``: invalid UTF-8 is absorbed exactly like torn
JSON (enable/disable proceed from defaults, show reports the empty state,
rc 0, no traceback), every control keeps its byte-existing behavior, and
the opt-in consent gate never opens without an explicit ``y``.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid as uuid_mod
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
KNOWN_ID = "11111111-2222-3333-4444-555555555555"
DEFAULT_URL = "https://krellbot.dev/api/telemetry"

PAYLOAD_KEYS = {
    "install_id",
    "pack_id",
    "pack_version",
    "venue",
    "pair",
    "side",
    "bar_ts",
    "modeled_px",
    "fill_px",
    "qty_bucket",
    "fee_bps",
}


def _cli(home: Path, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    """Run ``python -m krellbot.cli`` in a scrubed subprocess environment.

    The environment is built from scratch, not inherited: no exchange
    credential variables can leak in, every live flag is pinned to 0, and
    the fake keyring backend is selected before any ``import keyring``.
    """
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "KRELLBOT_HOME": str(home),
        "KRELLBOT_ENABLE_LIVE": "0",
        "KRELLBOT_LIVE": "0",
        "KRELLBOT_API_LIVE": "0",
        "PYTHON_KEYRING_BACKEND": "tests.fakes.fake_keyring.FakeKeyring",
        "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)]),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TMPDIR": str(home),
    }
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        input=stdin,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        cwd=str(REPO),
    )


def _write_invalid_utf8(home: Path) -> None:
    home.joinpath("telemetry.json").write_bytes(b'{"enabled": true, "install_id": "\xff\xfe\x80"}')


def _write_torn(home: Path) -> None:
    home.joinpath("telemetry.json").write_bytes(b'{"enabled": true, "install_i')


def _write_healthy(home: Path) -> None:
    record = {"enabled": True, "install_id": KNOWN_ID, "url": DEFAULT_URL}
    home.joinpath("telemetry.json").write_text(json.dumps(record), encoding="utf-8")


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path


class SpyTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, dict]] = []

    def post(self, url: str, body: bytes, headers: dict) -> object:
        self.calls.append((url, body, headers))
        return b"{}"


# ------------------------- invalid UTF-8: the regression ----------------------


def test_invalid_utf8_show_reports_empty_state(home: Path) -> None:
    """`telemetry show` over invalid UTF-8: rc 0, `{}`, empty stderr."""
    _write_invalid_utf8(home)
    proc = _cli(home, "telemetry", "show")
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stdout == "{}\n"
    assert proc.stderr == ""
    home.joinpath("telemetry.json").read_bytes()  # file untouched, not deleted


def test_invalid_utf8_disable_proceeds_from_defaults(home: Path) -> None:
    """`telemetry disable` over invalid UTF-8 rewrites a fresh valid config."""
    _write_invalid_utf8(home)
    proc = _cli(home, "telemetry", "disable")
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stdout == "telemetry disabled\n"
    assert proc.stderr == ""
    stored = json.loads(home.joinpath("telemetry.json").read_text(encoding="utf-8"))
    assert stored == {"enabled": False}
    assert not home.joinpath("telemetry.json.tmp").exists()


def test_invalid_utf8_enable_with_y_writes_fresh_valid_config(home: Path) -> None:
    """`telemetry enable` answering y over invalid UTF-8: rc 0, fresh install."""
    _write_invalid_utf8(home)
    proc = _cli(home, "telemetry", "enable", stdin="y\n")
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stderr == ""
    assert proc.stdout.endswith("telemetry enabled\n")
    payload = json.loads(proc.stdout[: proc.stdout.rindex("telemetry enabled")])
    assert set(payload) == PAYLOAD_KEYS
    assert UUID_RE.fullmatch(payload["install_id"])
    stored = json.loads(home.joinpath("telemetry.json").read_text(encoding="utf-8"))
    assert stored["enabled"] is True
    assert stored["install_id"] == payload["install_id"]
    assert stored["url"] == DEFAULT_URL
    assert not home.joinpath("telemetry.json.tmp").exists()


def test_invalid_utf8_enable_with_n_keeps_gate_closed(home: Path) -> None:
    """Answering n never enables, never rewrites the file, never posts."""
    from krellbot import telemetry as kb_telemetry

    _write_invalid_utf8(home)
    before = home.joinpath("telemetry.json").read_bytes()
    proc = _cli(home, "telemetry", "enable", stdin="n\n")
    assert proc.returncode == 0, f"stderr={proc.stderr!r}"
    assert proc.stdout.endswith("telemetry not enabled\n")
    assert proc.stderr == ""
    assert home.joinpath("telemetry.json").read_bytes() == before
    spy = SpyTransport()
    kb_telemetry.maybe_send(home, _sample_fill(), transport=spy)
    assert spy.calls == []
    assert kb_telemetry.resolve_transport(home, None) is None


def _sample_fill() -> dict:
    return {
        "pack_id": "free-trend",
        "pack_version": "1.0.0",
        "venue": "kraken",
        "pair": "XBT/USD",
        "side": "buy",
        "bar_ts": 1770000000,
        "modeled_px": "50000.00",
        "fill_px": "50001.00",
        "qty_bucket": 6,
        "fee_bps": 10,
    }


def test_invalid_utf8_absorbed_exactly_like_torn_json(tmp_path: Path) -> None:
    """Byte-identical typing: invalid UTF-8 == torn JSON for all 3 subcommands."""
    torn_home = tmp_path / "torn"
    utf8_home = tmp_path / "utf8"
    torn_home.mkdir()
    utf8_home.mkdir()
    _write_torn(torn_home)
    _write_invalid_utf8(utf8_home)
    for args, stdin in (
        (("telemetry", "show"), ""),
        (("telemetry", "disable"), ""),
        (("telemetry", "enable"), "y\n"),
    ):
        torn = _cli(torn_home, *args, stdin=stdin)
        raw = _cli(utf8_home, *args, stdin=stdin)
        assert raw.returncode == torn.returncode == 0, f"args={args} torn={torn.stderr!r} raw={raw.stderr!r}"
        assert raw.stderr == torn.stderr == ""
        assert UUID_RE.sub("<uuid>", raw.stdout) == UUID_RE.sub("<uuid>", torn.stdout)
    for h in (torn_home, utf8_home):
        stored = json.loads(h.joinpath("telemetry.json").read_text(encoding="utf-8"))
        assert stored["enabled"] is True
        assert UUID_RE.fullmatch(stored["install_id"])
        assert stored["url"] == DEFAULT_URL
        assert set(stored) == {"enabled", "install_id", "url"}


def test_consent_gate_stays_opt_in_across_absorbed_states(tmp_path: Path) -> None:
    """No absorbed state posts anything or resolves a real transport."""
    from krellbot import telemetry as kb_telemetry

    states: list[Path] = []
    for name, writer in (
        ("fresh", lambda h: None),
        ("torn", _write_torn),
        ("invalid", _write_invalid_utf8),
        ("disabled", lambda h: h.joinpath("telemetry.json").write_text('{"enabled": false}', encoding="utf-8")),
    ):
        h = tmp_path / name
        h.mkdir()
        writer(h)
        states.append(h)
    for h in states:
        assert kb_telemetry.is_enabled(h) is False
        assert kb_telemetry.resolve_transport(h, None) is None
        spy = SpyTransport()
        kb_telemetry.maybe_send(h, _sample_fill(), transport=spy)
        assert spy.calls == []
    enabled = tmp_path / "enabled"
    enabled.mkdir()
    _write_healthy(enabled)
    assert kb_telemetry.is_enabled(enabled) is True
    spy = SpyTransport()
    kb_telemetry.maybe_send(enabled, _sample_fill(), transport=spy)
    assert len(spy.calls) == 1
    body = json.loads(spy.calls[0][1])
    assert set(body) == PAYLOAD_KEYS
    assert body["install_id"] == KNOWN_ID


# --------------------------------- controls -----------------------------------


def test_control_torn_json_behavior_unchanged(home: Path) -> None:
    """Torn JSON: show `{}`, disable rc 0, enable-y rc 0, no stderr."""
    _write_torn(home)
    show = _cli(home, "telemetry", "show")
    assert show.returncode == 0 and show.stdout == "{}\n" and show.stderr == ""
    disable = _cli(home, "telemetry", "disable")
    assert disable.returncode == 0
    assert disable.stdout == "telemetry disabled\n"
    assert disable.stderr == ""
    assert json.loads(home.joinpath("telemetry.json").read_text(encoding="utf-8")) == {"enabled": False}


def test_control_chmod000_absorbed(home: Path) -> None:
    """chmod 000 telemetry.json: read failure is absorbed (non-root POSIX)."""
    target = home.joinpath("telemetry.json")
    target.write_text('{"enabled": true}', encoding="utf-8")
    os.chmod(target, 0)
    show = _cli(home, "telemetry", "show")
    if os.name == "posix" and os.geteuid() != 0:
        assert show.returncode == 0, f"stderr={show.stderr!r}"
        assert show.stdout == "{}\n"
        assert show.stderr == ""
        disable = _cli(home, "telemetry", "disable")
        assert disable.returncode == 0
        assert disable.stdout == "telemetry disabled\n"
        assert disable.stderr == ""
        assert json.loads(target.read_text(encoding="utf-8")) == {"enabled": False}
    else:
        assert show.returncode == 0, f"stderr={show.stderr!r}"
        assert json.loads(show.stdout)["enabled"] is True
    os.chmod(target, 0o600)


def test_control_directory_telemetry_json(home: Path) -> None:
    """A directory named telemetry.json: load absorbed; save path preserved."""
    home.joinpath("telemetry.json").mkdir()
    show = _cli(home, "telemetry", "show")
    assert show.returncode == 0, f"stderr={show.stderr!r}"
    assert show.stdout == "{}\n"
    assert show.stderr == ""
    decline = _cli(home, "telemetry", "enable", stdin="n\n")
    assert decline.returncode == 0
    assert decline.stdout.endswith("telemetry not enabled\n")
    assert decline.stderr == ""
    disable = _cli(home, "telemetry", "disable")
    assert disable.returncode == 1
    assert "Traceback" in disable.stderr
    if os.name == "posix":
        assert "IsADirectoryError" in disable.stderr
    accept = _cli(home, "telemetry", "enable", stdin="y\n")
    assert accept.returncode == 1
    assert "Traceback" in accept.stderr
    if os.name == "posix":
        assert "IsADirectoryError" in accept.stderr
    assert not home.joinpath("telemetry.json.tmp").exists()


def test_control_healthy_show_byte_exact(home: Path) -> None:
    _write_healthy(home)
    proc = _cli(home, "telemetry", "show")
    assert proc.returncode == 0
    assert proc.stderr == ""
    expected = json.dumps({"enabled": True, "install_id": KNOWN_ID, "url": DEFAULT_URL}, indent=2, sort_keys=True)
    assert proc.stdout == expected + "\n"


def test_control_healthy_disable_preserves_install_id(home: Path) -> None:
    _write_healthy(home)
    proc = _cli(home, "telemetry", "disable")
    assert proc.returncode == 0
    assert proc.stdout == "telemetry disabled\n"
    assert proc.stderr == ""
    stored = json.loads(home.joinpath("telemetry.json").read_text(encoding="utf-8"))
    assert stored == {"enabled": False, "install_id": KNOWN_ID, "url": DEFAULT_URL}


def test_control_healthy_enable_reuses_install_id(home: Path) -> None:
    _write_healthy(home)
    proc = _cli(home, "telemetry", "enable", stdin="y\n")
    assert proc.returncode == 0
    assert proc.stderr == ""
    payload = {
        "install_id": KNOWN_ID,
        "pack_id": "",
        "pack_version": "",
        "venue": "",
        "pair": "",
        "side": "buy",
        "bar_ts": 0,
        "modeled_px": "0",
        "fill_px": "0",
        "qty_bucket": 0,
        "fee_bps": 0,
    }
    expected = json.dumps(payload, indent=2, sort_keys=True) + "\ntelemetry enabled\n"
    assert proc.stdout == expected
    stored = json.loads(home.joinpath("telemetry.json").read_text(encoding="utf-8"))
    assert stored == {"enabled": True, "install_id": KNOWN_ID, "url": DEFAULT_URL}


def test_control_healthy_enable_with_n_changes_nothing(home: Path) -> None:
    _write_healthy(home)
    before = home.joinpath("telemetry.json").read_bytes()
    proc = _cli(home, "telemetry", "enable", stdin="n\n")
    assert proc.returncode == 0
    assert proc.stdout.endswith("telemetry not enabled\n")
    assert proc.stderr == ""
    assert home.joinpath("telemetry.json").read_bytes() == before


def test_control_fresh_install_enable_with_y_is_valid_utf8_json(home: Path) -> None:
    """Fresh home (no telemetry.json at all): enable-y writes a valid config."""
    proc = _cli(home, "telemetry", "enable", stdin="y\n")
    assert proc.returncode == 0
    assert proc.stderr == ""
    stored = json.loads(home.joinpath("telemetry.json").read_text(encoding="utf-8"))
    assert stored["enabled"] is True
    assert uuid_mod.UUID(stored["install_id"])
    assert stored["url"] == DEFAULT_URL

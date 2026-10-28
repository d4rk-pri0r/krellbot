"""An unreadable `$KRELLBOT_HOME/config.json` is refused, never a raw traceback.

BASE on main (b592ed3): `krellbot status` and `krellbot doctor` crashed with a
raw PermissionError traceback when config.json was chmod 000, and a raw
IsADirectoryError when config.json was a directory — both rc1. These tests are
the regression pin: `load_config` raises the typed `ConfigUnreadableError`
(an OSError subclass naming config.json) and every CLI surface that does not
catch OSError renders the one-line typed refusal with rc 1 (no traceback, no
process exit from library code), while missing / torn / non-dict config keeps
the silent empty-Config fallback (rc0) and healthy load/save stays
byte-identical. The workstation API keeps serving typed responses instead of
dying, and `/paper/history` keeps its OSError/ValueError fallback. The CLI
runs in real subprocesses with a tmp KRELLBOT_HOME, the fake keyring, no
network, and no live flags.

No skip markers are used anywhere in this file: chmod-000 rows probe the
machine's actual capability (`chmod_blocks_read`) and assert the typed
refusal only when the bytes are genuinely unreadable, asserting the healthy
path otherwise, so every row runs on every platform.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from krellbot.config import ArmedPack, Config, ConfigUnreadableError, load_config, save_config

_ON_WINDOWS = sys.platform == "win32"


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_API"] = "http://127.0.0.1:9"  # unroutable; any accidental call fails fast
    env["KRELLBOT_HOME"] = str(home / "krellbot-home")
    return subprocess.run(
        [sys.executable, "-m", "krellbot.cli", *args],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=30,
    )


def kh(home: Path) -> Path:
    krellbot_home = home / "krellbot-home"
    krellbot_home.mkdir(parents=True, exist_ok=True)
    return krellbot_home


def write_config(krellbot_home: Path, payload) -> None:
    (krellbot_home / "config.json").write_text(payload, encoding="utf-8")


def chmod_blocks_read(path: Path) -> bool:
    """Capability probe: can the current process still read these bytes?

    chmod 000 only forbids reads for unprivileged POSIX processes; root and
    some ACL setups read anyway, and Windows does not map the mode to a read
    denial. Rows below assert the typed refusal only when this probe proves
    the bytes are genuinely unreadable, and assert the healthy path
    otherwise — no platform is excluded and no marker is required.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return True
    os.close(fd)
    return False


def assert_refusal(proc: subprocess.CompletedProcess, exc_name: str) -> None:
    assert proc.returncode == 1
    assert "config.json" in proc.stderr
    assert "config load refused" in proc.stderr
    assert exc_name in proc.stderr
    assert "Traceback" not in proc.stderr


# ---- typed refusal: unreadable config.json (chmod 000) ----------------------


def test_status_unreadable_config_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    proc = run_cli(tmp_path, "status")
    if chmod_blocks_read(krellbot_home / "config.json"):
        assert_refusal(proc, "PermissionError")
    else:
        assert proc.returncode == 0
        assert proc.stdout == "no armed packs\n"
        assert "config load refused" not in proc.stderr


def test_doctor_unreadable_config_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    proc = run_cli(tmp_path, "doctor", "--skip-clock")
    if chmod_blocks_read(krellbot_home / "config.json"):
        assert_refusal(proc, "PermissionError")
    else:
        assert proc.returncode in {0, 1}
        assert "config load refused" not in proc.stderr
        assert "Traceback" not in proc.stderr


# ---- typed refusal: config.json is a directory -------------------------------


def test_status_config_directory_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    proc = run_cli(tmp_path, "status")
    exc_name = "IsADirectoryError" if not _ON_WINDOWS else "PermissionError"
    assert_refusal(proc, exc_name)


def test_doctor_config_directory_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    proc = run_cli(tmp_path, "doctor", "--skip-clock")
    exc_name = "IsADirectoryError" if not _ON_WINDOWS else "PermissionError"
    assert_refusal(proc, exc_name)


# ---- load_config-level typed refusal -----------------------------------------


def test_load_config_unreadable_raises_typed_error(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    if chmod_blocks_read(krellbot_home / "config.json"):
        with pytest.raises(ConfigUnreadableError) as exc_info:
            load_config(krellbot_home)
        assert isinstance(exc_info.value, OSError)
        message = str(exc_info.value)
        assert "config.json" in message
        assert "config load refused" in message
        assert "PermissionError" in message
        assert isinstance(exc_info.value.read_error, PermissionError)
    else:
        assert load_config(krellbot_home) == Config()


def test_load_config_directory_raises_typed_error(tmp_path):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    with pytest.raises(ConfigUnreadableError) as exc_info:
        load_config(krellbot_home)
    assert isinstance(exc_info.value, OSError)
    message = str(exc_info.value)
    assert "config.json" in message
    assert "config load refused" in message


# ---- disarm / stop CLI rows share the same typed refusal ---------------------


def test_disarm_unreadable_config_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    proc = run_cli(tmp_path, "disarm", "--venue", "kraken", "--pair", "XBT/USD")
    if chmod_blocks_read(krellbot_home / "config.json"):
        assert_refusal(proc, "PermissionError")
    else:
        assert proc.returncode == 1
        assert proc.stdout == "not armed: kraken XBT/USD\n"
        assert "config load refused" not in proc.stderr


def test_stop_unreadable_config_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    proc = run_cli(tmp_path, "stop", "--venue", "kraken", "--pair", "XBT/USD", "--price", "100")
    if chmod_blocks_read(krellbot_home / "config.json"):
        assert_refusal(proc, "PermissionError")
    else:
        assert proc.returncode == 1
        assert proc.stdout == "not armed: kraken XBT/USD\n"
        assert "config load refused" not in proc.stderr


def test_disarm_config_directory_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    proc = run_cli(tmp_path, "disarm", "--venue", "kraken", "--pair", "XBT/USD")
    exc_name = "IsADirectoryError" if not _ON_WINDOWS else "PermissionError"
    assert_refusal(proc, exc_name)


def test_stop_config_directory_refusal(tmp_path):
    krellbot_home = kh(tmp_path)
    (krellbot_home / "config.json").mkdir()
    proc = run_cli(tmp_path, "stop", "--venue", "kraken", "--pair", "XBT/USD", "--price", "100")
    exc_name = "IsADirectoryError" if not _ON_WINDOWS else "PermissionError"
    assert_refusal(proc, exc_name)


# ---- paper service routes disarm/stop/pause/resume/arm/export ----------------


def test_paper_service_commands_route_typed_refusal(tmp_path):
    """Every PaperService method that reads the config refuses typed, in-process.

    disarm / stop (raise_stop) / pause_entries / resume_entries / arm /
    export all read the armed-pack config through `_revision` first; an
    unreadable config.json must surface as the same typed
    ConfigUnreadableError `load_config` raises — never a raw OSError
    traceback and never a process exit — so API/UI callers keep their
    existing OSError handlers.
    """
    from krellbot.application.paper import PaperService

    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    service = PaperService(home=krellbot_home)
    if chmod_blocks_read(krellbot_home / "config.json"):
        with pytest.raises(ConfigUnreadableError):
            service.disarm(venue="kraken", pair="XBT/USD")
        with pytest.raises(ConfigUnreadableError):
            service.raise_stop(venue="kraken", pair="XBT/USD", new_stop=Decimal(10500))
        with pytest.raises(ConfigUnreadableError):
            service.pause_entries(venue="kraken", pair="XBT/USD")
        with pytest.raises(ConfigUnreadableError):
            service.resume_entries(venue="kraken", pair="XBT/USD")
        with pytest.raises(ConfigUnreadableError):
            service.export(venue="kraken", pair="XBT/USD")
        with pytest.raises(ConfigUnreadableError):
            service.arm(
                tmp_path / "pack.json",
                venue="kraken",
                mode="paper",
                paper_balance=Decimal(100),
            )
    else:
        results = [
            service.disarm(venue="kraken", pair="XBT/USD"),
            service.raise_stop(venue="kraken", pair="XBT/USD", new_stop=Decimal(10500)),
            service.pause_entries(venue="kraken", pair="XBT/USD"),
            service.resume_entries(venue="kraken", pair="XBT/USD"),
            service.export(venue="kraken", pair="XBT/USD"),
        ]
        for result in results:
            assert result.ok is False
            assert result.effect == "refused"


# ---- workstation API keeps serving typed responses ---------------------------


def _http_get(port: int, path: str, headers: dict[str, str]) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


def _workstation_session(port: int) -> dict[str, str]:
    """Bootstrap a workstation session on a live server; return auth headers."""

    status, body = _http_get(port, "/", {"Host": f"127.0.0.1:{port}"})
    assert status == 200, (status, body[:200])
    match = re.search(rb'name="krellbot-bootstrap" content="([^"]+)"', body)
    assert match, body[:200]
    token = match.group(1).decode("ascii")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    payload = json.dumps({"token": token})
    try:
        conn.request(
            "POST",
            "/api/v1/session/bootstrap",
            body=payload,
            headers={
                "Host": f"127.0.0.1:{port}",
                "Origin": f"http://127.0.0.1:{port}",
                "Content-Type": "application/json",
                "Content-Length": str(len(payload)),
            },
        )
        response = conn.getresponse()
        response.read()
        assert response.status == 200, response.status
        cookie = response.getheader("Set-Cookie")
    finally:
        conn.close()
    assert cookie and cookie.startswith("krellbot_session="), cookie
    return {
        "Host": f"127.0.0.1:{port}",
        "Origin": f"http://127.0.0.1:{port}",
        "Cookie": cookie.split(";", 1)[0],
    }


def test_workstation_api_keeps_serving_typed_response_with_unreadable_config(tmp_path):
    """A chmod-000 config.json must not wedge the real workstation server.

    On the rejected candidate, `load_config` raised SystemExit: the first
    config-reading request wedged the event loop and every later request
    timed out — the workstation API died instead of serving typed
    responses. On the repaired head the server answers every probe: the
    `/paper/history` OSError/ValueError fallback serves its typed JSON
    body, `/api/v1/capabilities` stays available, and the config-reading
    `/api/v1/paper/status` route returns a definitive HTTP answer (500
    with the bytes genuinely unreadable, 200 `armed:false` where the
    platform can still read them) instead of hanging the server.
    """
    from tests.test_int01_workstation_launch import (
        _make_built_dist,
        _spawn_workstation,
        _stop_workstation,
        _wait_for_workstation_url,
    )

    home = kh(tmp_path)
    dist = _make_built_dist(tmp_path / "dist")
    proc = _spawn_workstation(home, "--dist", str(dist))
    try:
        url = _wait_for_workstation_url(proc)
        port = int(re.match(r"http://127\.0\.0\.1:(\d+)/", url).group(1))
        headers = _workstation_session(port)

        write_config(home, '{"armed": [], "live_first_armed": false}')
        os.chmod(home / "config.json", 0o000)
        blocked = chmod_blocks_read(home / "config.json")

        status, _body = _http_get(port, "/api/v1/paper/status", headers)
        assert status in {200, 500}, status
        if blocked:
            assert status == 500, status

        history_status, history_body = _http_get(port, "/api/v1/paper/history", headers)
        assert history_status == 200, history_status
        history = json.loads(history_body)
        assert history["schema_version"] == "1"
        assert "runs" in history

        caps_status, caps_body = _http_get(port, "/api/v1/capabilities", headers)
        assert caps_status == 200, caps_status
        caps = json.loads(caps_body)
        assert caps["schema_version"] == "1"

        assert proc.poll() is None, "workstation server died on an unreadable config.json"
    finally:
        _stop_workstation(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()


def test_workstation_api_history_fallback_with_directory_config(tmp_path):
    """A directory-shaped config.json also keeps the server serving typed rows.

    This unreadable shape blocks reads on every platform, so the row needs
    no capability branch: `/paper/history` serves its fallback JSON, the
    config-reading route answers 500 instead of wedging the loop, and the
    server stays alive for later requests.
    """
    from tests.test_int01_workstation_launch import (
        _make_built_dist,
        _spawn_workstation,
        _stop_workstation,
        _wait_for_workstation_url,
    )

    home = kh(tmp_path)
    (home / "config.json").mkdir()
    dist = _make_built_dist(tmp_path / "dist")
    proc = _spawn_workstation(home, "--dist", str(dist))
    try:
        url = _wait_for_workstation_url(proc)
        port = int(re.match(r"http://127\.0\.0\.1:(\d+)/", url).group(1))
        headers = _workstation_session(port)

        status, _body = _http_get(port, "/api/v1/paper/status", headers)
        assert status == 500, status

        history_status, history_body = _http_get(port, "/api/v1/paper/history", headers)
        assert history_status == 200, history_status
        history = json.loads(history_body)
        assert history["schema_version"] == "1"
        assert "runs" in history

        caps_status, _caps_body = _http_get(port, "/api/v1/capabilities", headers)
        assert caps_status == 200, caps_status

        assert proc.poll() is None, "workstation server died on a directory config.json"
    finally:
        _stop_workstation(proc)
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()


# ---- controls: surfaces that do not read config.json stay rc0 ----------------


def test_controls_unaffected_by_unreadable_config(tmp_path):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, '{"armed": [], "live_first_armed": false}')
    os.chmod(krellbot_home / "config.json", 0o000)
    journal = run_cli(tmp_path, "journal", "--tail", "2")
    assert journal.returncode == 0
    assert "no journal" in journal.stdout
    telemetry = run_cli(tmp_path, "telemetry", "show")
    assert telemetry.returncode == 0
    version = run_cli(tmp_path, "--version")
    assert version.returncode == 0
    listed = run_cli(tmp_path, "list")
    assert listed.returncode == 0


# ---- silent empty-Config fallback stays byte-identical (rc0) -----------------


@pytest.mark.parametrize("payload", ['{"armed": [', "[1, 2]", '"nope"', "null"])
def test_torn_and_nondict_config_silent_fallback(tmp_path, payload):
    krellbot_home = kh(tmp_path)
    write_config(krellbot_home, payload)
    status = run_cli(tmp_path, "status")
    assert status.returncode == 0
    assert status.stdout == "no armed packs\n"
    assert status.stderr == ""
    doctor = run_cli(tmp_path, "doctor", "--skip-clock")
    assert doctor.returncode in {0, 1}  # doctor reports health; it must not crash
    assert "Traceback" not in doctor.stderr
    assert "config load refused" not in doctor.stderr
    assert load_config(krellbot_home) == Config()


def test_missing_config_keeps_empty_fallback(tmp_path):
    krellbot_home = kh(tmp_path)
    assert load_config(krellbot_home) == Config()
    status = run_cli(tmp_path, "status")
    assert status.returncode == 0
    assert status.stdout == "no armed packs\n"


# ---- healthy config load/save stays byte-identical ---------------------------


def _healthy_config() -> Config:
    return Config(
        armed=[
            ArmedPack(
                pack_path="/tmp/packs/breakout.json",
                pack_sha256="a" * 64,
                pack_id="breakout",
                pack_version="1.2.3",
                venue="kraken",
                pair="XBT/USD",
                cap=Decimal(25),
                stop=Decimal("10500.5"),
                mode="paper",
                starting_cash=Decimal("10000.00"),
                requires_license=False,
                armed_at_ts=1_700_000_000,
                owned_qty=Decimal("0.5"),
                pending_version="1.3.0",
                entries_paused=True,
            )
        ],
        live_first_armed=True,
    )


def test_healthy_config_round_trip_byte_identical(tmp_path):
    first = tmp_path / "h1"
    second = tmp_path / "h2"
    first.mkdir()
    second.mkdir()
    save_config(first, _healthy_config())
    loaded = load_config(first)
    assert loaded == _healthy_config()
    save_config(second, loaded)
    assert (first / "config.json").read_bytes() == (second / "config.json").read_bytes()
    payload = json.loads((first / "config.json").read_text(encoding="utf-8"))
    assert payload == json.loads((second / "config.json").read_text(encoding="utf-8"))
    assert payload["live_first_armed"] is True
    assert payload["armed"][0]["cap"] == "25"


def test_healthy_status_prints_armed_line(tmp_path):
    krellbot_home = kh(tmp_path)
    save_config(krellbot_home, _healthy_config())
    proc = run_cli(tmp_path, "status")
    assert proc.returncode == 0
    assert proc.stderr == ""
    assert proc.stdout == "breakout 1.2.3 kraken XBT/USD cap=25 stop=10500.5 mode=paper requires_license=False\n"

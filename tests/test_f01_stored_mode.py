"""F01 — paper commands must refuse to mutate a stored live deployment.

The defect: ``paper.disarm``, ``paper.pause_entries``, ``paper.resume_entries``,
and ``paper.raise_stop`` locate the stored armed record by ``(venue, pair)``
without inspecting its ``mode``. A caller that omits ``mode`` (the frontend
sends only venue + pair) or sends ``mode: paper`` was able to mutate a
``mode: live`` record through the versioned API.

The fix lives in the application service: every paper command reads the
stored record, returns a typed ``stored_mode_not_paper`` refusal when the
record's mode is not ``paper``, and leaves ``config.json`` byte-identical.
The caller payload does not influence the stored-mode check. ``paper.arm``
with ``mode: live`` stays refused; live arm authority remains the legacy
CLI path.

Tests cover:

  1. The service refuses each of the four mutation commands when the stored
     record is ``mode: live``. ``config.json`` bytes are unchanged before
     and after the refused call.
  2. The same four commands succeed against a stored ``mode: paper``
     record. A paper pause still persists ``entries_paused``.
  3. The versioned API reflects the same refusal: omitting ``mode`` from
     the payload does not override the stored live mode, and sending
     ``mode: paper`` does not override either.
  4. ``paper.arm`` with ``mode: live`` remains refused before any command
     runs; the live path stays in the legacy CLI.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from tests.test_ns06_api import (
    TEST_PORT,
    _bootstrap_token,
    _build_app,
    _config_bytes,
    _default_origin_header,
    _post_json,
    _run_paper_arm,
    _session_from_cookies,
)

# ---- helpers ---------------------------------------------------------------


def _seed_stored_record(
    home: Path,
    *,
    mode: str,
    paused: bool = False,
    stop: Decimal = Decimal(1),
    pair: str = "SUIUSD",
    venue: str = "kraken",
    pack_id: str = "reconciliation-fixture",
) -> None:
    """Write a single armed-pack record under ``<home>/config.json``.

    Mirrors the synthetic fixture the parent reconciliation probe uses.
    The mode is whatever the test wants to exercise; no engine call runs.
    """

    from krellbot import config as cfg

    record = cfg.ArmedPack(
        pack_path=str(home / "synthetic-pack.json"),
        pack_sha256="0" * 64,
        pack_id=pack_id,
        pack_version="1.0.0",
        venue=venue,
        pair=pair,
        cap=Decimal(10),
        stop=stop,
        mode=mode,
        starting_cash=Decimal(100) if mode == "paper" else None,
        requires_license=False,
        armed_at_ts=1,
        entries_paused=paused,
    )
    cfg.save_config(home, cfg.Config(armed=[record]))


def _bootstrap_headers(app, token: str) -> tuple[str, str]:
    """Redeem ``token`` on ``app`` and return ``(session_value, csrf_token)``."""

    status, _h, body, cookies = _post_json(
        app,
        "/api/v1/session/bootstrap",
        {"token": token},
        headers=_default_origin_header(),
    )
    assert status == 200, (status, body, cookies)
    csrf_token = json.loads(body)["csrf_token"]
    session_value = _session_from_cookies(cookies)
    return session_value, csrf_token


def _command_headers(session_value: str, csrf_token: str) -> list[tuple[str, str]]:
    """Loopback-origin auth headers for ``POST /api/v1/commands``."""

    return [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("X-Krellbot-CSRF", csrf_token),
        ("Cookie", f"krellbot_session={session_value}"),
    ]


# ---- 1. service-level refusal on stored live -------------------------------


def test_paper_service_disarm_refuses_stored_live_record(home: Path) -> None:
    """``paper.disarm`` refuses a stored live record with code
    ``stored_mode_not_paper`` and leaves ``config.json`` byte-identical.
    """

    from krellbot.application.paper import PaperService

    _seed_stored_record(home, mode="live", paused=False)
    before = _config_bytes(home)

    service = PaperService(home=home)
    result = service.disarm(venue="kraken", pair="SUIUSD", correlation_id="svc-disarm-live")

    assert result.ok is False, result
    assert result.code == "stored_mode_not_paper", result
    assert result.effect == "refused", result
    assert result.revision_before == result.revision_after, result
    assert _config_bytes(home) == before, "refused disarm must not touch config bytes"


def test_paper_service_pause_entries_refuses_stored_live_record(home: Path) -> None:
    """``paper.pause_entries`` refuses a stored live record and does not
    flip ``entries_paused``."""

    from krellbot.application.paper import PaperService

    _seed_stored_record(home, mode="live", paused=False)
    before = _config_bytes(home)

    service = PaperService(home=home)
    result = service.pause_entries(venue="kraken", pair="SUIUSD", correlation_id="svc-pause-live")

    assert result.ok is False, result
    assert result.code == "stored_mode_not_paper", result
    assert result.effect == "refused", result
    assert result.revision_before == result.revision_after, result
    assert _config_bytes(home) == before, "refused pause must not touch config bytes"

    # Reload and prove ``entries_paused`` stayed False.
    from krellbot import config as cfg

    config = cfg.load_config(home)
    assert config.armed[0].entries_paused is False, config.armed[0]


def test_paper_service_resume_entries_refuses_stored_live_record(home: Path) -> None:
    """``paper.resume_entries`` refuses a stored live record that is
    somehow marked ``entries_paused``. The resume must not run.
    """

    from krellbot.application.paper import PaperService

    _seed_stored_record(home, mode="live", paused=True)
    before = _config_bytes(home)

    service = PaperService(home=home)
    result = service.resume_entries(venue="kraken", pair="SUIUSD", correlation_id="svc-resume-live")

    assert result.ok is False, result
    assert result.code == "stored_mode_not_paper", result
    assert result.effect == "refused", result
    assert result.revision_before == result.revision_after, result
    assert _config_bytes(home) == before

    from krellbot import config as cfg

    config = cfg.load_config(home)
    assert config.armed[0].entries_paused is True, "refused resume must not flip the flag"


def test_paper_service_raise_stop_refuses_stored_live_record(home: Path) -> None:
    """``paper.raise_stop`` refuses a stored live record; the stop price
    on disk must stay at the seeded value.
    """

    from krellbot.application.paper import PaperService

    _seed_stored_record(home, mode="live", paused=False, stop=Decimal(1))
    before = _config_bytes(home)

    service = PaperService(home=home)
    result = service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(10), correlation_id="svc-stop-live")

    assert result.ok is False, result
    assert result.code == "stored_mode_not_paper", result
    assert result.effect == "refused", result
    assert result.revision_before == result.revision_after, result
    assert _config_bytes(home) == before

    from krellbot import config as cfg

    config = cfg.load_config(home)
    assert config.armed[0].stop == Decimal(1), "refused raise_stop must not move the stop"


# ---- 2. positive paper cases still pass ------------------------------------


def test_paper_service_disarm_succeeds_against_stored_paper_record(home: Path) -> None:
    """Sanity: paper disarm still removes a stored paper record."""

    from krellbot.application.paper import PaperService

    _seed_stored_record(home, mode="paper", paused=False)
    service = PaperService(home=home)
    result = service.disarm(venue="kraken", pair="SUIUSD", correlation_id="svc-disarm-paper")

    assert result.ok is True, result
    assert result.code == "disarmed", result
    assert result.effect == "changed", result

    from krellbot import config as cfg

    config = cfg.load_config(home)
    assert config.armed == [], config.armed


def test_paper_service_pause_persists_entries_paused(home: Path) -> None:
    """Paper pause against a stored paper record persists
    ``entries_paused``; reload still sees the flag.
    """

    from krellbot.application.paper import PaperService

    _run_paper_arm(home)
    service = PaperService(home=home)
    result = service.pause_entries(venue="kraken", pair="SUIUSD", correlation_id="svc-pause-paper")
    assert result.ok is True, result
    assert result.code == "entries_paused", result
    assert result.effect == "changed", result

    from krellbot import config as cfg

    config = cfg.load_config(home)
    assert config.armed[0].entries_paused is True

    config2 = cfg.load_config(home)
    assert config2.armed[0].entries_paused is True


def test_paper_service_resume_and_raise_stop_succeed_against_stored_paper(home: Path) -> None:
    """Sanity: paper resume + paper raise-stop succeed against a stored
    paper record.
    """

    from krellbot.application.paper import PaperService

    _run_paper_arm(home)
    service = PaperService(home=home)

    service.pause_entries(venue="kraken", pair="SUIUSD", correlation_id="seed-pause")
    resume = service.resume_entries(venue="kraken", pair="SUIUSD", correlation_id="seed-resume")
    assert resume.ok and resume.code == "entries_resumed", resume

    raise_result = service.raise_stop(venue="kraken", pair="SUIUSD", new_stop=Decimal(10), correlation_id="seed-stop")
    assert raise_result.ok and raise_result.code == "stop_raised", raise_result


# ---- 3. caller payload must not override stored mode ----------------------


def test_api_pause_entries_with_no_mode_refuses_stored_live(home: Path) -> None:
    """The versioned API: omitting ``mode`` from the payload (the
    frontend's shape) still refuses a stored live record. The stored
    mode is the authority.
    """

    _seed_stored_record(home, mode="live", paused=False)
    before = _config_bytes(home)

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap_headers(app, token)

    payload = {
        "schema_version": "1",
        "command": "paper.pause_entries",
        "payload": {"venue": "kraken", "pair": "SUIUSD"},
    }
    status, _h, body, _c = _post_json(
        app, "/api/v1/commands", payload, headers=_command_headers(session_value, csrf_token)
    )

    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded.get("ok") is False, decoded
    assert decoded.get("code") == "stored_mode_not_paper", decoded
    assert decoded.get("effect") == "refused", decoded
    assert _config_bytes(home) == before, "refusal must leave config bytes untouched"


def test_api_pause_entries_with_mode_paper_refuses_stored_live(home: Path) -> None:
    """The versioned API: sending ``mode: paper`` in the payload does
    not override the stored live mode.
    """

    _seed_stored_record(home, mode="live", paused=False)
    before = _config_bytes(home)

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap_headers(app, token)

    payload = {
        "schema_version": "1",
        "command": "paper.pause_entries",
        "payload": {"venue": "kraken", "pair": "SUIUSD", "mode": "paper"},
    }
    status, _h, body, _c = _post_json(
        app, "/api/v1/commands", payload, headers=_command_headers(session_value, csrf_token)
    )

    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded.get("ok") is False, decoded
    assert decoded.get("code") == "stored_mode_not_paper", decoded
    assert decoded.get("effect") == "refused", decoded
    assert _config_bytes(home) == before


def test_api_resume_entries_refuses_stored_live(home: Path) -> None:
    """``paper.resume_entries`` refuses a stored live record via the API."""

    _seed_stored_record(home, mode="live", paused=True)
    before = _config_bytes(home)

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap_headers(app, token)

    payload = {
        "schema_version": "1",
        "command": "paper.resume_entries",
        "payload": {"venue": "kraken", "pair": "SUIUSD"},
    }
    status, _h, body, _c = _post_json(
        app, "/api/v1/commands", payload, headers=_command_headers(session_value, csrf_token)
    )

    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded.get("code") == "stored_mode_not_paper", decoded
    assert _config_bytes(home) == before


def test_api_disarm_refuses_stored_live(home: Path) -> None:
    """``paper.disarm`` refuses a stored live record via the API."""

    _seed_stored_record(home, mode="live", paused=False)
    before = _config_bytes(home)

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap_headers(app, token)

    payload = {
        "schema_version": "1",
        "command": "paper.disarm",
        "payload": {"venue": "kraken", "pair": "SUIUSD"},
    }
    status, _h, body, _c = _post_json(
        app, "/api/v1/commands", payload, headers=_command_headers(session_value, csrf_token)
    )

    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded.get("code") == "stored_mode_not_paper", decoded
    assert _config_bytes(home) == before


def test_api_raise_stop_refuses_stored_live(home: Path) -> None:
    """``paper.raise_stop`` refuses a stored live record via the API."""

    _seed_stored_record(home, mode="live", paused=False, stop=Decimal(1))
    before = _config_bytes(home)

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap_headers(app, token)

    payload = {
        "schema_version": "1",
        "command": "paper.raise_stop",
        "payload": {"venue": "kraken", "pair": "SUIUSD", "new_stop": "10"},
    }
    status, _h, body, _c = _post_json(
        app, "/api/v1/commands", payload, headers=_command_headers(session_value, csrf_token)
    )

    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded.get("code") == "stored_mode_not_paper", decoded
    assert _config_bytes(home) == before


# ---- 4. paper.arm with mode=live stays refused -----------------------------


def test_paper_service_arm_with_mode_live_is_refused(home: Path) -> None:
    """``paper.arm`` with ``mode: live`` is refused by the service
    before any command runs. No live-order command is added.
    """

    from krellbot.application.paper import PaperService
    from tests.test_ns06_api import _write_dsl_pack

    pack_path = _write_dsl_pack(home)
    before = _config_bytes(home)

    service = PaperService(home=home)
    result = service.arm(
        pack_path, venue="kraken", mode="live", paper_balance=Decimal(1000), correlation_id="svc-arm-live"
    )

    assert result.ok is False, result
    assert result.code == "invalid_request", result
    assert result.effect == "refused", result
    assert _config_bytes(home) == before


def test_api_paper_arm_with_mode_live_returns_403_and_leaves_config(home: Path) -> None:
    """The API refuses ``paper.arm`` with ``mode: live`` and leaves the
    config unchanged. This is the existing M1 surface; F01 does not
    weaken it.
    """

    from tests.test_ns06_api import _write_dsl_pack

    _write_dsl_pack(home)
    before = _config_bytes(home)

    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap_headers(app, token)
    pack_path = _write_dsl_pack(home)

    payload = {
        "schema_version": "1",
        "command": "paper.arm",
        "payload": {
            "pack_path": str(pack_path),
            "venue": "kraken",
            "mode": "live",
            "paper_balance": "1000",
        },
    }
    status, _h, body, _c = _post_json(
        app, "/api/v1/commands", payload, headers=_command_headers(session_value, csrf_token)
    )

    assert status == 403, (status, body)
    assert _config_bytes(home) == before


# ---- 5. the legacy CLI live path is unchanged ------------------------------


def test_legacy_cli_live_protection_path_is_untouched(home: Path) -> None:
    """The CLI live risk-reduction path is out of scope for F01. The
    existing CLI refuses ``arm --mode live`` via the legacy guard. This
    test is the contract the brief calls out: ``src/krellbot/cli.py``
    is not edited.
    """

    import os
    import subprocess
    import sys

    from tests.test_ns06_api import _write_dsl_pack

    pack_path = _write_dsl_pack(home)

    env = {k: v for k, v in os.environ.items() if not k.startswith("KRELLBOT_")}
    env["KRELLBOT_HOME"] = str(home)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env["KRELLBOT_ENABLE_LIVE"] = "0"

    # Without the typed live confirmation / key check, the CLI refuses
    # ``--mode live``. The exact return code is owned by the legacy CLI
    # path and is not part of F01.
    r = subprocess.run(
        [sys.executable, "-m", "krellbot.cli", "arm", str(pack_path), "--venue", "kraken", "--mode", "live"],
        capture_output=True,
        check=False,
        text=True,
        env=env,
        timeout=30,
    )
    assert r.returncode != 0, (r.returncode, r.stdout, r.stderr)


# ---- 6. paper commands end-to-end against a stored paper record -----------


def test_api_paper_commands_succeed_against_stored_paper_record(home: Path) -> None:
    """End-to-end: pause / resume / raise-stop / disarm against a stored
    paper record all return success through the API. This is the
    positive control for the refusal tests above.
    """

    _run_paper_arm(home)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value, csrf_token = _bootstrap_headers(app, token)
    headers = _command_headers(session_value, csrf_token)

    pause = _post_json(
        app,
        "/api/v1/commands",
        {"schema_version": "1", "command": "paper.pause_entries", "payload": {"venue": "kraken", "pair": "SUIUSD"}},
        headers=headers,
    )
    assert pause[0] == 200, pause
    assert json.loads(pause[2])["code"] == "entries_paused"

    resume = _post_json(
        app,
        "/api/v1/commands",
        {"schema_version": "1", "command": "paper.resume_entries", "payload": {"venue": "kraken", "pair": "SUIUSD"}},
        headers=headers,
    )
    assert resume[0] == 200, resume
    assert json.loads(resume[2])["code"] == "entries_resumed"

    raise_stop = _post_json(
        app,
        "/api/v1/commands",
        {
            "schema_version": "1",
            "command": "paper.raise_stop",
            "payload": {"venue": "kraken", "pair": "SUIUSD", "new_stop": "10"},
        },
        headers=headers,
    )
    assert raise_stop[0] == 200, raise_stop
    assert json.loads(raise_stop[2])["code"] == "stop_raised"

    disarm = _post_json(
        app,
        "/api/v1/commands",
        {"schema_version": "1", "command": "paper.disarm", "payload": {"venue": "kraken", "pair": "SUIUSD"}},
        headers=headers,
    )
    assert disarm[0] == 200, disarm
    assert json.loads(disarm[2])["code"] == "disarmed"


# ---- 7. stop_raised order smoke (no other paper-control mutation) ----------


def test_paper_status_path_unchanged_for_stored_live(home: Path) -> None:
    """F01 only restricts mutation. The status route may still surface a
    stored live record's mode (the route itself does not refuse live;
    the route is read-only). This test pins the read-only behaviour.
    """

    from tests.test_ns10_paper_status import (
        _bootstrap_session_cookie,
        _get_paper_status,
    )

    _seed_stored_record(home, mode="live", paused=False)
    token = _bootstrap_token(home)
    app = _build_app(home, bootstrap_token=token)
    session_value = _bootstrap_session_cookie(app, token)
    headers = [
        ("Origin", f"http://127.0.0.1:{TEST_PORT}"),
        ("Cookie", f"krellbot_session={session_value}"),
    ]
    status, _h, body, _c = _get_paper_status(app, headers=headers)
    assert status == 200, (status, body)
    decoded = json.loads(body)
    assert decoded.get("armed") is True, decoded
    assert decoded.get("mode") == "live", decoded

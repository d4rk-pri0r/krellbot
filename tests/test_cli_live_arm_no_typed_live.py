"""CLI live arm never blocks on ``Type LIVE to arm:`` stdin (M13.5).

Pins:

* Default release: ``arm --mode live`` refuses as paper-only before any
  stdin prompt; ``builtins.input`` is never called.
* When the paper-only fence is lifted in tests, CLI live arm still refuses
  with an honest workstation-grant message and never prompts Type LIVE;
  web ``skip_confirm`` remains the successful live-arm seam.
"""

from __future__ import annotations

import json
from pathlib import Path

from fakes.live_grant import write_grant

from krellbot.application import live_gate
from krellbot.release_policy import PAPER_ONLY_RELEASE

VENUE = "kraken"
PAIR = "SUIUSD"
KRAKEN_TEST_KEY = "FAKE_KEY_FOR_KRAKEN_TESTS"
KRAKEN_TEST_SECRET_B64 = "kQH5HW/8p1uGOVjbgWA7FunAmGO8lsSUXNsu3eow76sz84Q18fWxnyRzBHCd3pd5nE9qa99HAZtuZuj6F1huXg=="


def _write_pack(home: Path, *, pack_id: str = "cli-live-arm") -> Path:
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": "CLI live arm",
        "author": "krellbot tests",
        "timeframe": "1h",
        "indicators": {"sma2": {"fn": "sma", "src": "close", "len": 2}},
        "entry": ["close", "crosses_above", "sma2"],
        "exit": ["close", "crosses_below", "sma2"],
        "risk": {"max_account_pct": 100, "stop": {"type": "pct", "pct": 50}},
        "markets": [{"venue": VENUE, "pair": PAIR}],
    }
    target = home / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _must_not_prompt(*_args, **_kwargs) -> str:
    raise AssertionError("must not prompt Type LIVE to arm: on stdin")


def test_paper_only_release_stays_true() -> None:
    assert PAPER_ONLY_RELEASE is True


def test_cli_live_arm_paper_only_never_prompts_typed_live(home, monkeypatch, capsys) -> None:
    """Default release: CLI live arm is paper-only; stdin is untouched."""
    from krellbot.cli import cmd_arm

    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    pack_path = _write_pack(home)
    monkeypatch.setattr("builtins.input", _must_not_prompt)

    rc = cmd_arm([str(pack_path), "--venue", VENUE, "--mode", "live"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "paper-only" in out.lower() or live_gate.CODE_PAPER_ONLY_RELEASE in out
    assert "Type LIVE to arm:" not in out


def test_cli_live_arm_refuses_workstation_grant_without_stdin(
    home,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
    capsys,
) -> None:
    """Live-capable release: CLI still refuses without Type LIVE stdin."""
    from krellbot import secrets
    from krellbot.cli import cmd_arm
    from krellbot.config import load_config
    from krellbot.venues.base import KeyPerms

    del live_capable_release
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    secrets.store(VENUE, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)
    pack_path = _write_pack(home)

    monkeypatch.setattr("builtins.input", _must_not_prompt)
    monkeypatch.setattr(
        "krellbot.cli_keys._probe",
        lambda venue, key, secret: type(
            "Probe",
            (),
            {"to_key_perms": staticmethod(lambda: KeyPerms(can_trade=True, can_withdraw=False))},
        )(),
    )

    rc = cmd_arm([str(pack_path), "--venue", VENUE, "--mode", "live"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "workstation grant" in out.lower()
    assert "Type LIVE to arm:" not in out
    assert load_config(home).armed == []


def test_arm_pack_without_skip_confirm_never_calls_confirm_fn(
    home,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
    capsys,
) -> None:
    """Engine seam: missing skip_confirm refuses; confirm_fn is never called."""
    from krellbot import secrets
    from krellbot.run import arm_pack
    from krellbot.venues.base import KeyPerms

    del live_capable_release
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    secrets.store(VENUE, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)
    pack_path = _write_pack(home)
    monkeypatch.setattr("builtins.input", _must_not_prompt)

    def must_not_call() -> str:
        raise AssertionError("confirm_fn must not run for CLI Type LIVE")

    rc = arm_pack(
        pack_path,
        venue=VENUE,
        mode="live",
        home=home,
        skip_confirm=False,
        confirm_fn=must_not_call,
        key_check=lambda _v: KeyPerms(can_trade=True, can_withdraw=False),
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "workstation grant" in out.lower()


def test_arm_pack_skip_confirm_still_arms_without_stdin(
    home,
    fresh_keyring,
    live_capable_release,
    monkeypatch,
) -> None:
    """Web seam unchanged: skip_confirm arms without stdin / confirm_fn."""
    from krellbot import secrets
    from krellbot.config import load_config
    from krellbot.run import arm_pack
    from krellbot.venues.base import KeyPerms

    del live_capable_release
    monkeypatch.setenv("KRELLBOT_ENABLE_LIVE", "1")
    write_grant(home, venue=VENUE, pair=PAIR)
    secrets.store(VENUE, KRAKEN_TEST_KEY, KRAKEN_TEST_SECRET_B64)
    pack_path = _write_pack(home)
    monkeypatch.setattr("builtins.input", _must_not_prompt)

    def must_not_call() -> str:
        raise AssertionError("confirm_fn must not run when skip_confirm=True")

    rc = arm_pack(
        pack_path,
        venue=VENUE,
        mode="live",
        home=home,
        skip_confirm=True,
        confirm_fn=must_not_call,
        key_check=lambda _v: KeyPerms(can_trade=True, can_withdraw=False),
    )
    assert rc == 0
    cfg = load_config(home)
    assert len(cfg.armed) == 1
    assert cfg.armed[0].mode == "live"
    assert cfg.live_first_armed is True

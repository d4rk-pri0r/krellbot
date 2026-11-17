"""Opt-in local demo/fixture seed for preview honesty (M18.5).

Populates a clearly labeled rehearsal/demo marker under ``KRELLBOT_HOME``
so local preview can show fixture rows without inventing live P&L, fills,
market performance, or soak PASS. Default fresh homes stay empty.

Honesty invariants:

* Fixture metrics are never presented as live or soak proof.
* Enabling requires an explicit opt-in confirm flag.
* Clearing restores the empty/honest default.
* Does not arm paper packs, place orders, or touch risk-path engine state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from krellbot.paths import atomic_write

SCHEMA_VERSION = "1"
STATE_FILENAME = "demo_fixture.json"

FIXTURE_LABEL = "Fixture / demo rehearsal — not live performance"
FIXTURE_BADGE = "Fixture demo"
HONESTY_NOTE = (
    "Opt-in local preview seed only. Labeled fixture/demo/rehearsal — never live P&L, market performance, or soak PASS."
)

# Closed-shape demo rows for local preview surfaces. Not journal fills.
_DEMO_DEPLOYMENTS: tuple[dict[str, Any], ...] = (
    {
        "id": "fixture-demo-paper-1",
        "label": "Demo paper deployment (fixture)",
        "venue": "kraken",
        "pair": "SUIUSD",
        "mode": "paper",
        "pack_id": "fixture-demo-sma",
        "status": "rehearsal_idle",
        "is_fixture": True,
        "live_performance": False,
        "soak_proof": False,
    },
)


def _state_path(home: Path) -> Path:
    return Path(home) / STATE_FILENAME


def _empty_status() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": False,
        "label": None,
        "badge": None,
        "honesty_note": HONESTY_NOTE,
        "is_fixture": False,
        "live_performance": False,
        "soak_proof": False,
        "deployments": [],
        "message": "Demo fixture seed is off. Fresh home stays empty and honest.",
    }


def _enabled_status() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "enabled": True,
        "label": FIXTURE_LABEL,
        "badge": FIXTURE_BADGE,
        "honesty_note": HONESTY_NOTE,
        "is_fixture": True,
        "live_performance": False,
        "soak_proof": False,
        "deployments": [dict(row) for row in _DEMO_DEPLOYMENTS],
        "message": "Demo fixture seed enabled — labeled fixture/demo only.",
    }


def get_status(home: Path) -> dict[str, Any]:
    """Return closed-shape fixture seed status for ``home``."""
    path = _state_path(home)
    if not path.is_file():
        return _empty_status()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _empty_status()
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return _empty_status()
    # Re-project honesty fields from code so a tampered file cannot claim
    # live_performance or soak_proof.
    status = _enabled_status()
    status["message"] = str(raw.get("message") or status["message"])
    return status


def seed(home: Path, *, confirm: bool) -> dict[str, Any]:
    """Opt-in enable the demo fixture seed.

    Requires ``confirm=True``. Refuses otherwise so a bare POST cannot
    silently populate fixture rows. Never sets live_performance/soak_proof.
    """
    if confirm is not True:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "code": "confirm_required",
            "message": (
                "Opt-in confirm required to enable the demo fixture seed. Fixture metrics are never live or soak proof."
            ),
            "enabled": False,
            "is_fixture": False,
            "live_performance": False,
            "soak_proof": False,
        }

    Path(home).mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": SCHEMA_VERSION,
        "enabled": True,
        "label": FIXTURE_LABEL,
        "badge": FIXTURE_BADGE,
        "is_fixture": True,
        "live_performance": False,
        "soak_proof": False,
        "deployments": [dict(row) for row in _DEMO_DEPLOYMENTS],
        "message": "Demo fixture seed enabled — labeled fixture/demo only.",
    }
    atomic_write(
        _state_path(home),
        (json.dumps(body, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    status = get_status(home)
    return {
        "ok": True,
        "code": "demo_fixture_seeded",
        **status,
    }


def clear(home: Path) -> dict[str, Any]:
    """Remove the demo fixture seed; restore empty/honest default."""
    path = _state_path(home)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "code": "clear_failed",
            "message": "Could not clear demo fixture seed file.",
            **_empty_status(),
        }
    status = get_status(home)
    return {
        "ok": True,
        "code": "demo_fixture_cleared",
        **status,
    }


def assert_not_live_or_soak(status: dict[str, Any]) -> None:
    """Raise AssertionError if status claims live performance or soak proof."""
    if status.get("live_performance") is True:
        raise AssertionError("fixture seed must not claim live_performance")
    if status.get("soak_proof") is True:
        raise AssertionError("fixture seed must not claim soak_proof")
    if status.get("enabled") is True and status.get("is_fixture") is not True:
        raise AssertionError("enabled fixture seed must set is_fixture")
    for row in status.get("deployments") or []:
        if not isinstance(row, dict):
            raise TypeError("deployment rows must be objects")
        if row.get("live_performance") is True or row.get("soak_proof") is True:
            raise AssertionError("fixture deployment must not claim live/soak")
        if row.get("is_fixture") is not True:
            raise AssertionError("fixture deployment must be labeled is_fixture")


__all__ = [
    "FIXTURE_BADGE",
    "FIXTURE_LABEL",
    "HONESTY_NOTE",
    "SCHEMA_VERSION",
    "assert_not_live_or_soak",
    "clear",
    "get_status",
    "seed",
]

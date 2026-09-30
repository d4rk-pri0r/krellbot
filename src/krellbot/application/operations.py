"""Read-only ``GET /api/v1/operations`` body builder.

The view aggregates three read-only sources for the workstation:

  * ``live_gate.live_status`` — the closed-shape snapshot of the live
    authorization gate, kill switch, and promotion status.
  * The list of armed records from ``krellbot.config.load_config`` —
    projected to a closed shape that never carries ``cap``, ``stop``,
    ``starting_cash``, ``owned_qty``, ``pack_path``, ``pack_sha256``,
    or any balance / key material.
  * The deduped, severity-sorted alert list from
    ``krellbot.application.alerts.collect``.

Each deployment's ``promotion.code`` is what ``live_gate.check_promotion``
returns when run against that deployment, with ``revision_id`` fixed to
the literal ``"deployment"``. Promotion never succeeds; the field is the
typed refusal code so the UI can render the same message the API
returns when the operator clicks Promote.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from krellbot import config as kb_config
from krellbot.application import alerts, live_gate

SCHEMA_VERSION = "1"
PROMOTION_REVISION_ID = "deployment"


def _deployment_projection(home: Path, *, env: Mapping[str, str] | None, now: int) -> list[dict]:
    """Project every armed record to a closed shape.

    ``mode`` is the stored mode, verbatim — a seeded live row stays
    ``"live"`` and is never rewritten into ``"paper"``.
    """

    config = kb_config.load_config(home)
    out: list[dict] = []
    for armed in config.armed:
        promo = live_gate.check_promotion(
            home,
            venue=armed.venue,
            pair=armed.pair,
            revision_id=PROMOTION_REVISION_ID,
            env=env,
            now=now,
        )
        out.append(
            {
                "venue": armed.venue,
                "pair": armed.pair,
                "pack_id": armed.pack_id,
                "pack_version": armed.pack_version,
                "mode": armed.mode,
                "entries_paused": bool(armed.entries_paused),
                "promotion": {
                    "available": False,
                    "code": promo.code,
                },
            }
        )
    return out


def operations_view(home: Path, *, env: Mapping[str, str] | None = None, now: int) -> dict:
    """Return the closed-shape operations view.

    The body never includes ``cap``, ``stop``, ``starting_cash``,
    ``owned_qty``, ``pack_path``, ``pack_sha256``, any balance, or any
    key material. ``promotion_available`` is always ``False``; the
    brief documents that promotion is owner-deferred in this build.
    """

    home = Path(home)
    return {
        "schema_version": SCHEMA_VERSION,
        "live": live_gate.live_status(home, env=env, now=now),
        "deployments": _deployment_projection(home, env=env, now=now),
        "alerts": [a.to_dict() for a in alerts.collect(home, now=now)],
    }


__all__ = ["operations_view"]

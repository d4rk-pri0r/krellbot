"""Seed unresolved-order ledger rows for the Operations e2e spec.

Writes committed-not-sent outbox rows, needs_reconcile audits (with
``ts`` so age is computable), and one reconcile lookup outcome into
``<home>/ops.sqlite``. Used by
``frontend/e2e/operations-unresolved-orders.spec.ts``.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

COID_ABSENT = "coid-e2e-absent"
COID_NONE = "coid-e2e-none"


def seed(home: Path, *, now: int | None = None) -> None:
    # Ensure the package is importable when launched via uv run.
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))

    from krellbot.storage.database import OperationalStore

    stamp = int(now if now is not None else time.time())
    store = OperationalStore(home / "ops.sqlite")
    store.connect()

    older = stamp - 125
    newer = stamp - 45

    with store.transaction() as conn:
        for coid, body_ts in ((COID_ABSENT, older), (COID_NONE, newer)):
            outbox = json.dumps(
                {
                    "coid": coid,
                    "body": json.dumps(
                        {"kind": "entry", "qty": "1", "stop": "1", "pair": "BTCUSD"},
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    "sent": False,
                    "mode": "live",
                    "venue": "kraken",
                    "ts": body_ts,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
                (outbox,),
            )
            audit = json.dumps(
                {"coid": coid, "ts": body_ts},
                sort_keys=True,
                separators=(",", ":"),
            )
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('needs_reconcile', ?)",
                (audit,),
            )
        lookup = json.dumps(
            {"coid": COID_ABSENT, "result": "absent"},
            sort_keys=True,
            separators=(",", ":"),
        )
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('reconcile_absent', ?)",
            (lookup,),
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <home>", file=sys.stderr)
        return 2
    home = Path(argv[1])
    home.mkdir(parents=True, exist_ok=True)
    seed(home)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

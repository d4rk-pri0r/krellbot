"""Seed a paper deployment and two live_refused tick records.

Writes a paper pack JSON to ``<home>/packs/<pack_id>.json`` and arms it
via ``krellbot.config.save_config`` + ``ArmedPack`` (mode ``paper``,
venue ``kraken``, pair ``SUIUSD``).

Then appends two ``live_refused`` tick records to
``<home>/journal/<YYYY-MM>.jsonl`` using the same UTC month naming
``krellbot.journal`` uses.

Used by ``frontend/e2e/m3-operations.spec.ts`` through ``spawnSync``
of ``uv run python frontend/e2e/m3_seed.py <home>``. The spec runs
the rest of the flow; this module only writes the seed state.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

# Repo root is computed from this file's location: frontend/e2e/m3_seed.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PACK_ID = "m3-ops-pack"
VENUE = "kraken"
PAIR = "SUIUSD"


def _write_pack(home: Path) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    pack_path = packs / f"{PACK_ID}.json"
    pack_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": PACK_ID,
                "version": "1.0.0",
                "label": "M3 ops seed pack",
                "author": "m3-operations e2e",
                "timeframe": "1h",
                "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
                "entry": ["close", ">", "sma20"],
                "exit": ["close", "<", "sma20"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
                "markets": [{"venue": VENUE, "pair": PAIR}],
            }
        ),
        encoding="utf-8",
    )
    return pack_path


def _arm_pack(home: Path, pack_path: Path) -> None:
    from krellbot import config as kb_config  # noqa: WPS433 — runtime import.

    config = kb_config.load_config(home)
    config.armed.append(
        kb_config.ArmedPack(
            pack_path=str(pack_path),
            pack_sha256="0" * 64,
            pack_id=PACK_ID,
            pack_version="1.0.0",
            venue=VENUE,
            pair=PAIR,
            cap=Decimal("25"),
            stop=Decimal("0"),
            mode="paper",
            starting_cash=Decimal("1000"),
            requires_license=False,
            armed_at_ts=0,
        )
    )
    kb_config.save_config(home, config)


def _append_journal(home: Path, ts: int, payload: dict) -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    utc = _dt.datetime.fromtimestamp(int(ts), tz=_dt.timezone.utc)
    file_path = journal_dir / f"{utc:%Y-%m}.jsonl"
    record = {
        "ts": ts,
        "kind": "tick",
        "venue": VENUE,
        "pack": PACK_ID,
        "bar_ts": ts,
        "detail": payload,
    }
    fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        line = json.dumps(record, separators=(",", ":")) + "\n"
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    if os.name != "nt":
        os.chmod(file_path, 0o600)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <home>", file=sys.stderr)
        return 2
    home = Path(argv[1])
    home.mkdir(parents=True, exist_ok=True)
    pack_path = _write_pack(home)
    _arm_pack(home, pack_path)
    # Two live_refused tick records, two different timestamps so the
    # spec sees a count of ×2.
    _append_journal(
        home,
        1_700_000_000,
        {"reason": "live_refused", "code": "live_disabled", "pair": PAIR},
    )
    _append_journal(
        home,
        1_700_000_060,
        {"reason": "live_refused", "code": "live_disabled", "pair": PAIR},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
"""Reconcile journal state with venue state for one pack.

The pack's "owned" quantity is `min(base balance on the venue for the pair,
qty this pack's journal says it filled)`. Anything else is the user's other
holdings and is never touched. This module reads the journal for prior tick
records and computes the canonical owned_qty for a pack.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


def _journal_dir(home: Path) -> Path:
    return Path(home) / "journal"


def _cumulative_owned_from_journal(home: Path, *, pack_id: str, pair: str) -> Decimal:
    """Sum entry qty - sum exit qty for this pack across all journal files.

    Only the `kind=tick` records are inspected. Each `tick` record's detail
    carries the actions taken: `entry_qty`, `exit_qty`, `stop_qty`.
    """
    journal_dir = _journal_dir(home)
    if not journal_dir.is_dir():
        return Decimal(0)
    owned = Decimal(0)
    for path in sorted(journal_dir.glob("*.jsonl")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("kind") != "tick":
                continue
            if rec.get("pack") != pack_id:
                continue
            detail = rec.get("detail", {})
            if not isinstance(detail, dict):
                continue
            if rec.get("venue") and detail.get("pair") and detail["pair"] != pair:
                continue
            entry_qty = _to_decimal(detail.get("entry_qty"))
            exit_qty = _to_decimal(detail.get("exit_qty"))
            stop_qty = _to_decimal(detail.get("stop_qty"))
            owned += entry_qty - exit_qty - stop_qty
    return owned


def _to_decimal(raw: object) -> Decimal:
    if raw is None:
        return Decimal(0)
    if isinstance(raw, Decimal):
        return raw
    try:
        return Decimal(str(raw))
    except (ValueError, TypeError):
        return Decimal(0)


def reconcile_owned_qty(
    home: Path,
    *,
    pack_id: str,
    pair: str,
    venue_owned_qty: Decimal,
) -> Decimal:
    """Return the canonical owned qty for this pack on this pair.

    The pack owns `min(venue_owned_qty, sum-of-fills-in-journal)`. Extra coins
    the user holds are not touched.
    """
    journal_qty = _cumulative_owned_from_journal(home, pack_id=pack_id, pair=pair)
    return min(venue_owned_qty, journal_qty)

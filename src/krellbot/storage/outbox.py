"""Commit an order intent before a fake send. Do not resubmit blindly.

The Outbox is the paper-mode boundary for order sends. ``ModeError`` is
raised by paper-only helpers (used from ``run.tick``) when invoked for a
non-paper arm; live arms bypass the Outbox entirely. The ``audit_*``
helpers record fault-fill observations in the same ledger so an operator
can reconcile a partial fill, a late fill, or an unknown ack against the
venue's report.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from krellbot.storage.database import OperationalStore


class ModeError(RuntimeError):
    """A paper-only code path was invoked for a non-paper arm."""


class Outbox:
    def __init__(self, store: OperationalStore) -> None:
        self._store = store

    def dispatch(
        self,
        client_order_id: str,
        body: str,
        send: Callable[[str, str], None],
        *,
        mode: str | None = None,
        venue: str | None = None,
    ) -> str:
        state = self._state(client_order_id)
        if state == "sent":
            return "already_sent"
        if state == "committed":
            return "needs_reconcile"
        self._commit(client_order_id, body, mode=mode, venue=venue)
        send(client_order_id, body)
        self._mark_sent(client_order_id)
        return "sent"

    def _state(self, client_order_id: str) -> str | None:
        for _row_id, _kind, payload in self._store.read_ledger():
            if _kind != "outbox":
                continue
            record = json.loads(payload)
            if record.get("coid") == client_order_id:
                return "sent" if record.get("sent") is True else "committed"
        return None

    def _commit(
        self,
        client_order_id: str,
        body: str,
        *,
        mode: str | None = None,
        venue: str | None = None,
    ) -> None:
        record_obj: dict = {"coid": client_order_id, "body": body, "sent": False}
        if mode is not None:
            record_obj["mode"] = mode
        if venue is not None:
            record_obj["venue"] = venue
        record = json.dumps(record_obj, sort_keys=True, separators=(",", ":"))
        with self._store.transaction() as conn:
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
                (record,),
            )

    def _mark_sent(self, client_order_id: str) -> None:
        with self._store.transaction() as conn:
            rows = conn.execute("SELECT id, payload FROM ledger WHERE kind = 'outbox'").fetchall()
            for row in rows:
                record = json.loads(row["payload"])
                if record.get("coid") != client_order_id:
                    continue
                record["sent"] = True
                conn.execute(
                    "UPDATE ledger SET payload = ? WHERE id = ?",
                    (json.dumps(record), row["id"]),
                )
                return


def audit_partial_fill(
    store: OperationalStore,
    *,
    coid: str,
    requested: str,
    filled: str,
) -> None:
    payload = json.dumps(
        {"coid": coid, "requested": requested, "filled": filled},
        sort_keys=True,
        separators=(",", ":"),
    )
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('partial_fill', ?)",
            (payload,),
        )


def audit_late_fill(
    store: OperationalStore,
    *,
    coid: str,
    qty: str,
    price: str,
    ts_ms: int,
) -> None:
    """Record a late fill: a fill that arrived after the position was exited."""
    payload = json.dumps(
        {"coid": coid, "qty": qty, "price": price, "ts_ms": ts_ms},
        sort_keys=True,
        separators=(",", ":"),
    )
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('late_fill', ?)",
            (payload,),
        )


def audit_unknown_ack(
    store: OperationalStore,
    *,
    coid: str,
    qty: str,
    price: str,
    ts_ms: int,
) -> None:
    """Record an unknown coid: a fill the engine never dispatched."""
    payload = json.dumps(
        {"coid": coid, "qty": qty, "price": price, "ts_ms": ts_ms},
        sort_keys=True,
        separators=(",", ":"),
    )
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('unknown_ack', ?)",
            (payload,),
        )


def audit_needs_reconcile(
    store: OperationalStore,
    *,
    coid: str,
) -> None:
    """Record an outbox state: send committed-but-not-sent; reconcile next tick."""
    payload = json.dumps({"coid": coid}, sort_keys=True, separators=(",", ":"))
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('needs_reconcile', ?)",
            (payload,),
        )


def dispatched_coids(store: OperationalStore) -> set[str]:
    out: set[str] = set()
    for _row_id, _kind, payload in store.read_ledger():
        if _kind != "outbox":
            continue
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            continue
        coid = record.get("coid")
        if isinstance(coid, str) and coid:
            out.add(coid)
    return out


def audited_coids(store: OperationalStore, *, kinds: tuple[str, ...]) -> set[str]:
    out: set[str] = set()
    for _row_id, kind, payload in store.read_ledger():
        if kind not in kinds:
            continue
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            continue
        coid = record.get("coid")
        if isinstance(coid, str) and coid:
            out.add(coid)
    return out

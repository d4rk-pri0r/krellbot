"""Commit an order intent before a fake send. Do not resubmit blindly."""

from __future__ import annotations

import json
from collections.abc import Callable

from krellbot.storage.database import OperationalStore


class Outbox:
    def __init__(self, store: OperationalStore) -> None:
        self._store = store

    def dispatch(
        self,
        client_order_id: str,
        body: str,
        send: Callable[[str, str], None],
    ) -> str:
        state = self._state(client_order_id)
        if state == "sent":
            return "already_sent"
        if state == "committed":
            return "needs_reconcile"
        self._commit(client_order_id, body)
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

    def _commit(self, client_order_id: str, body: str) -> None:
        record = json.dumps({"coid": client_order_id, "body": body, "sent": False})
        with self._store.transaction() as conn:
            conn.execute(
                "INSERT INTO ledger (kind, payload) VALUES ('outbox', ?)",
                (record,),
            )

    def _mark_sent(self, client_order_id: str) -> None:
        with self._store.transaction() as conn:
            rows = conn.execute(
                "SELECT id, payload FROM ledger WHERE kind = 'outbox'"
            ).fetchall()
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

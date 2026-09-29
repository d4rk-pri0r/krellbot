"""An intent is committed before a fake send, and a restart does not resubmit it."""

from __future__ import annotations

from krellbot.storage.database import OperationalStore
from krellbot.storage.outbox import Outbox


def test_send_happens_only_after_the_intent_is_committed(tmp_path) -> None:
    store = OperationalStore(tmp_path / "ops.sqlite")
    seen: list[str] = []

    def send(coid: str, body: str) -> None:
        rows = store.read_ledger()
        assert rows, "send ran before the intent commit"
        assert "coid-1" in rows[0][2]
        seen.append(coid)
        assert body == "buy"

    assert Outbox(store).dispatch("coid-1", "buy", send) == "sent"
    assert seen == ["coid-1"]
    assert Outbox(store).dispatch("coid-1", "buy", send) == "already_sent"
    assert seen == ["coid-1"]


def test_restart_after_commit_does_not_send_again(tmp_path) -> None:
    path = tmp_path / "ops.sqlite"
    store = OperationalStore(path)

    def die(_coid: str, _body: str) -> None:
        raise RuntimeError("died after commit")

    try:
        Outbox(store).dispatch("coid-2", "buy", die)
    except RuntimeError as exc:
        assert str(exc) == "died after commit"
    else:
        raise AssertionError("the send must fail after the commit")
    calls: list[str] = []
    reopened = Outbox(OperationalStore(path))
    assert (
        reopened.dispatch("coid-2", "buy", lambda coid, _body: calls.append(coid))
        == "needs_reconcile"
    )
    assert calls == []

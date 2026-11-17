"""Operator supervision alert classes (M16.3).

Pins typed alert kinds beyond the M2.5 / M9 baseline:

  * ``tick_failure`` — durable scheduler ``last_error``
  * ``scheduler_stale`` — armed venue last tick older than
    ``doctor.TICK_STALE_SECONDS``
  * ``unresolved_order_aging`` — unresolved order age ≥
    ``alerts.UNRESOLVED_AGING_SECONDS``
  * ``restore_fence`` — kill switch engaged by home restore

Each kind acknowledges through the existing ``alerts.acknowledge`` path.
``metadata_refusal`` alerts remain (M2.5). Collect is read-only: no
silent drops and no new files on an empty home.
"""

from __future__ import annotations

import datetime
import json
import os
from decimal import Decimal
from pathlib import Path

from krellbot.application import alerts, live_gate
from krellbot.data.instruments import METADATA_UNAVAILABLE
from krellbot.doctor import TICK_STALE_SECONDS


def _append_journal_record(home: Path, record: dict) -> None:
    journal_dir = home / "journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    utc = datetime.datetime.fromtimestamp(int(record["ts"]), tz=datetime.timezone.utc)
    file_path = journal_dir / f"{utc:%Y-%m}.jsonl"
    fd = os.open(str(file_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        line = json.dumps(record, separators=(",", ":")) + "\n"
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)


def _write_pack(home: Path, *, pack_id: str, venue: str, pair: str) -> Path:
    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    body = {
        "schema_version": 1,
        "id": pack_id,
        "version": "1.0.0",
        "label": pack_id,
        "author": "krellbot operator alert tests",
        "timeframe": "1h",
        "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
        "entry": ["close", ">", "sma20"],
        "exit": ["close", "<", "sma20"],
        "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
        "markets": [{"venue": venue, "pair": pair}],
    }
    target = packs / f"{pack_id}.json"
    target.write_text(json.dumps(body), encoding="utf-8")
    return target


def _arm_paper(home: Path, pack_path: Path, *, venue: str) -> None:
    from krellbot.application.paper import PaperService

    result = PaperService(home=home).arm(
        pack_path,
        venue=venue,
        mode="paper",
        paper_balance=Decimal(1000),
        correlation_id="seed-operator-alerts",
    )
    assert result.ok, result.message


def _seed_unresolved(home: Path, *, coid: str, ts: int) -> None:
    from krellbot.storage.database import OperationalStore

    store = OperationalStore(home / "ops.sqlite")
    store.connect()
    with store.transaction() as conn:
        payload = json.dumps({"coid": coid, "ts": ts}, separators=(",", ":"))
        conn.execute(
            "INSERT INTO ledger (kind, payload) VALUES ('needs_reconcile', ?)",
            (payload,),
        )


# ---- tick failure / scheduler stale --------------------------------------


def test_tick_failure_alert_from_scheduler_last_error(home: Path) -> None:
    from krellbot.service import supervise as kb_supervise

    now = 1_700_000_000
    kb_supervise.set_last_error(home, "tick exited rc=1")
    before = {p for p in home.rglob("*") if p.is_file()}
    result = alerts.collect(home, now=now)
    after = {p for p in home.rglob("*") if p.is_file()}
    assert before == after, (before, after)

    failures = [a for a in result if a.kind == alerts.KIND_TICK_FAILURE]
    assert len(failures) == 1, result
    alert = failures[0]
    assert alert.severity == "critical", alert
    assert alert.code == "tick exited rc=1", alert
    assert alert.acknowledged is False, alert

    acked = alerts.acknowledge(home, alert.id, now=now + 1)
    assert acked.kind == alerts.KIND_TICK_FAILURE
    assert acked.acknowledged is True
    again = alerts.collect(home, now=now + 1)
    assert next(a for a in again if a.id == alert.id).acknowledged is True


def test_scheduler_stale_alert_for_armed_venue_past_threshold(home: Path) -> None:
    pack = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    _arm_paper(home, pack, venue="kraken")
    last_ts = 1_700_000_000
    _append_journal_record(
        home,
        {
            "ts": last_ts,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": last_ts,
            "detail": {"pair": "SUIUSD", "decision": "hold"},
        },
    )
    now = last_ts + TICK_STALE_SECONDS
    result = alerts.collect(home, now=now)
    stale = [a for a in result if a.kind == alerts.KIND_SCHEDULER_STALE]
    assert len(stale) == 1, result
    alert = stale[0]
    assert alert.severity == "warning", alert
    assert alert.code == "tick_stale", alert
    assert alert.venue == "kraken", alert
    assert alert.first_ts == last_ts, alert
    assert alert.last_ts == now, alert
    assert alert.acknowledged is False, alert

    # Below threshold: no stale alert.
    fresh = alerts.collect(home, now=last_ts + TICK_STALE_SECONDS - 1)
    assert [a for a in fresh if a.kind == alerts.KIND_SCHEDULER_STALE] == []


def test_scheduler_stale_skips_armed_venue_with_no_ticks(home: Path) -> None:
    pack = _write_pack(home, pack_id="trend-follow", venue="kraken", pair="SUIUSD")
    _arm_paper(home, pack, venue="kraken")
    result = alerts.collect(home, now=1_700_000_000 + TICK_STALE_SECONDS)
    assert [a for a in result if a.kind == alerts.KIND_SCHEDULER_STALE] == []


# ---- unresolved order aging ----------------------------------------------


def test_unresolved_order_aging_alert_and_ack(home: Path) -> None:
    started = 1_700_000_000
    now = started + alerts.UNRESOLVED_AGING_SECONDS
    _seed_unresolved(home, coid="aged-coid-1", ts=started)

    result = alerts.collect(home, now=now)
    aging = [a for a in result if a.kind == alerts.KIND_UNRESOLVED_ORDER_AGING]
    assert len(aging) == 1, result
    alert = aging[0]
    assert alert.code == "aged-coid-1", alert
    assert alert.severity == "warning", alert
    assert alert.acknowledged is False, alert

    # Young unresolved order does not alert.
    young_home_ts = started + alerts.UNRESOLVED_AGING_SECONDS - 1
    young = alerts.collect(home, now=young_home_ts)
    # Same coid still aged relative to started? age = young_home_ts - started
    # which is UNRESOLVED_AGING_SECONDS - 1 → should not alert.
    assert [a for a in young if a.kind == alerts.KIND_UNRESOLVED_ORDER_AGING] == []

    acked = alerts.acknowledge(home, alert.id, now=now + 5)
    assert acked.acknowledged is True
    assert acked.kind == alerts.KIND_UNRESOLVED_ORDER_AGING


# ---- restore fence -------------------------------------------------------


def test_restore_fence_alert_alongside_kill_switch(home: Path) -> None:
    now = 1_700_000_500
    live_gate.engage_kill(
        home,
        reason="home restored; release entries pause and kill switch before live sends",
        now=now,
    )
    result = alerts.collect(home, now=now + 10)
    kinds = {a.kind for a in result}
    assert "kill_switch" in kinds, result
    assert alerts.KIND_RESTORE_FENCE in kinds, result
    fence = next(a for a in result if a.kind == alerts.KIND_RESTORE_FENCE)
    assert fence.severity == "critical", fence
    assert fence.code == "restore_fence_engaged", fence
    assert fence.acknowledged is False, fence

    acked = alerts.acknowledge(home, fence.id, now=now + 20)
    assert acked.acknowledged is True
    again = alerts.collect(home, now=now + 20)
    assert next(a for a in again if a.id == fence.id).acknowledged is True


def test_plain_kill_switch_is_not_restore_fence(home: Path) -> None:
    now = 1_700_000_600
    live_gate.engage_kill(home, reason="operator engaged kill", now=now)
    result = alerts.collect(home, now=now)
    assert [a for a in result if a.kind == alerts.KIND_RESTORE_FENCE] == []
    assert any(a.kind == "kill_switch" for a in result)


# ---- metadata_refusal preserved + empty home hygiene ---------------------


def test_metadata_refusal_still_surfaces(home: Path) -> None:
    ts = 1_700_000_700
    _append_journal_record(
        home,
        {
            "ts": ts,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": ts,
            "detail": {
                "pair": "BTCUSD",
                "reason": "no_signal",
                "metadata_refusal": METADATA_UNAVAILABLE,
                "intent_refused": None,
            },
        },
    )
    result = alerts.collect(home, now=ts + 1)
    meta = [a for a in result if a.kind == "metadata_refusal"]
    assert len(meta) == 1, result
    assert meta[0].code == METADATA_UNAVAILABLE
    assert meta[0].acknowledged is False


def test_empty_home_collect_creates_no_files(home: Path) -> None:
    before = {p for p in home.rglob("*") if p.is_file()} if home.exists() else set()
    assert alerts.collect(home, now=1_700_000_000) == []
    after = {p for p in home.rglob("*") if p.is_file()} if home.exists() else set()
    assert before == after

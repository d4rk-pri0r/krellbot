"""M3-GUI — alerts collection and acknowledgement.

Tests-first. ``krellbot.application.alerts`` does not exist before this
leaf lands; the import lines below must fail with ``ModuleNotFoundError``
in the RED phase.

The contract documented in the brief (M3-GUI/brief.md):

  * ``collect(home, now=...)`` reads the kill switch, the
    ``<home>/ops.sqlite`` ledger, and the journal files, and returns a
    deduped list of alerts. Sources are read-only; ``collect`` must
    never create any file. An empty home returns ``[]`` and leaves the
    filesystem untouched.
  * Kill switch engaged produces a critical ``kill_switch`` alert.
  * A ``needs_reconcile`` ledger row produces a critical
    ``needs_reconcile`` alert. A corrupt ``ops.sqlite`` produces a
    single ``store_fault`` alert without mutating the file.
  * Journal tick records whose ``detail.reason`` is ``live_refused``,
    ``store_refused``, or carries an ``intent_refused`` key produce
    warning alerts keyed by the same tuple. Three occurrences for the
    same (code, venue, pair) collapse to a single alert with
    ``count=3``.
  * ``acknowledge`` writes ``<home>/run/alerts-ack.json`` with
    ``mode 0o600``. A later occurrence with a greater ``last_ts``
    un-acknowledges the alert. The ack persists across a fresh
    ``collect`` (a restart). A corrupt ack file does not raise.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path

from krellbot.application import alerts

# ---- helpers ---------------------------------------------------------------


def _seed_paper_pack(home: Path) -> None:
    from krellbot import config as kb_config

    packs = home / "packs"
    packs.mkdir(parents=True, exist_ok=True)
    (packs / "p.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "trend-follow",
                "version": "1.0.0",
                "label": "Trend follow",
                "author": "alerts tests",
                "timeframe": "1h",
                "indicators": {"sma20": {"fn": "sma", "src": "close", "len": 20}},
                "entry": ["close", ">", "sma20"],
                "exit": ["close", "<", "sma20"],
                "risk": {"max_account_pct": 25, "stop": {"type": "pct", "pct": 5}},
                "markets": [{"venue": "kraken", "pair": "SUIUSD"}],
            }
        ),
        encoding="utf-8",
    )

    config = kb_config.load_config(home)
    config.armed.append(
        kb_config.ArmedPack(
            pack_path=str(packs / "p.json"),
            pack_sha256="0" * 64,
            pack_id="trend-follow",
            pack_version="1.0.0",
            venue="kraken",
            pair="SUIUSD",
            cap=Decimal(25),
            stop=Decimal(0),
            mode="paper",
            starting_cash=Decimal(1000),
            requires_license=False,
            armed_at_ts=0,
        )
    )
    kb_config.save_config(home, config)


def _home_files(home: Path) -> set[str]:
    out: set[str] = set()
    if not home.exists():
        return out
    for root, _dirs, files in os.walk(home):
        rel = Path(root).relative_to(home)
        for f in files:
            out.add(str(rel / f))
    return out


# ---------------------------------------------------------------------------
# 6. Empty home: collect returns [] and never creates any file.
# ---------------------------------------------------------------------------


def test_collect_on_empty_home_returns_empty_and_creates_nothing(home: Path) -> None:
    before = _home_files(home)
    result = alerts.collect(home, now=1_700_000_000)
    assert result == [], result
    after = _home_files(home)
    assert before == after, (before, after)
    # Defensive: ops.sqlite, run/, run/alerts-ack.json must all be absent.
    assert not (home / "ops.sqlite").exists()
    assert not (home / "run").exists()


# ---------------------------------------------------------------------------
# 7. Journal tick records dedupe by (kind, code, venue, pair).
# ---------------------------------------------------------------------------


def _append_journal_record(home: Path, record: dict) -> None:
    """Append one journal record using the same month-naming scheme as
    ``krellbot.journal``.

    The journal module appends via ``open(..., os.O_APPEND)``; we use the
    same UTC month file so a journal reader can find it.
    """
    import datetime

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
    if not file_path.exists() or os.name != "nt":
        os.chmod(file_path, 0o600)


def test_journal_live_refused_dedupes_by_kind_code_venue_pair(home: Path) -> None:
    base_ts = 1_700_000_000
    # Three identical live_refused for (kraken, SUIUSD) + one for SUI/EUR.
    for offset in (0, 60, 120):
        _append_journal_record(
            home,
            {
                "ts": base_ts + offset,
                "kind": "tick",
                "venue": "kraken",
                "pack": "trend-follow",
                "bar_ts": base_ts + offset,
                "detail": {
                    "reason": "live_refused",
                    "code": "live_disabled",
                    "pair": "SUIUSD",
                },
            },
        )
    _append_journal_record(
        home,
        {
            "ts": base_ts + 200,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": base_ts + 200,
            "detail": {
                "reason": "live_refused",
                "code": "live_disabled",
                "pair": "SUIEUR",
            },
        },
    )
    result = alerts.collect(home, now=base_ts + 1000)
    assert len(result) == 2, result
    by_pair = {a.pair: a for a in result}
    sui = by_pair["SUIUSD"]
    eur = by_pair["SUIEUR"]
    assert sui.kind == "live_refused", sui
    assert sui.code == "live_disabled", sui
    assert sui.venue == "kraken", sui
    assert sui.count == 3, sui
    assert sui.first_ts == base_ts, sui
    assert sui.last_ts == base_ts + 120, sui
    assert eur.count == 1, eur


# ---------------------------------------------------------------------------
# 8. needs_reconcile ledger row is critical; corrupt ops.sqlite is store_fault.
# ---------------------------------------------------------------------------


def test_needs_reconcile_alert_is_critical(home: Path) -> None:
    from krellbot.storage.database import OperationalStore
    from krellbot.storage.outbox import audit_needs_reconcile

    store = OperationalStore(home / "ops.sqlite")
    audit_needs_reconcile(store, coid="stuck-coid-1")

    # Also seed a journal live_refused so we can check ordering (critical first).
    _append_journal_record(
        home,
        {
            "ts": 1_700_000_000,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": 1_700_000_000,
            "detail": {"reason": "live_refused", "code": "live_disabled", "pair": "SUIUSD"},
        },
    )

    result = alerts.collect(home, now=1_700_001_000)
    kinds = [a.kind for a in result]
    assert "needs_reconcile" in kinds, kinds
    assert "live_refused" in kinds, kinds
    # Critical first.
    severities = [a.severity for a in result]
    assert severities[0] == "critical", severities
    nr = next(a for a in result if a.kind == "needs_reconcile")
    assert nr.severity == "critical", nr
    assert nr.code == "stuck-coid-1", nr


def test_corrupt_ops_sqlite_yields_store_fault(home: Path) -> None:
    """A non-sqlite ops.sqlite produces a single store_fault alert with
    code ``store_corrupt`` and the file bytes are unchanged."""

    ops_path = home / "ops.sqlite"
    original_bytes = b"definitely not a sqlite database\n"
    ops_path.write_bytes(original_bytes)

    result = alerts.collect(home, now=1_700_000_000)
    assert len(result) == 1, result
    alert = result[0]
    assert alert.kind == "store_fault", alert
    assert alert.severity == "critical", alert
    assert alert.code == "store_corrupt", alert
    # File bytes are unchanged.
    assert ops_path.read_bytes() == original_bytes


# ---------------------------------------------------------------------------
# 9. Ack persists across restart; later occurrence un-acknowledges;
#    corrupt ack file does not raise.
# ---------------------------------------------------------------------------


def test_ack_persists_and_later_occurrence_unacknowledges(home: Path) -> None:
    ts1 = 1_700_000_000
    _append_journal_record(
        home,
        {
            "ts": ts1,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": ts1,
            "detail": {"reason": "live_refused", "code": "live_disabled", "pair": "SUIUSD"},
        },
    )
    first = alerts.collect(home, now=ts1 + 5)
    assert len(first) == 1, first
    alert_id = first[0].id
    assert first[0].acknowledged is False

    acked = alerts.acknowledge(home, alert_id, now=ts1 + 10)
    assert acked.acknowledged is True, acked

    # The ack file must exist with mode 0o600 and the alert_id keyed.
    ack_file = home / "run" / "alerts-ack.json"
    assert ack_file.exists(), ack_file
    mode = ack_file.stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)
    raw = json.loads(ack_file.read_text(encoding="utf-8"))
    assert raw.get(alert_id) == ts1 + 10, raw

    # A fresh collect (restart) keeps the ack.
    second = alerts.collect(home, now=ts1 + 20)
    assert len(second) == 1, second
    assert second[0].acknowledged is True, second[0]

    # A new occurrence with a greater ts must un-acknowledge the alert.
    ts2 = ts1 + 1_000
    _append_journal_record(
        home,
        {
            "ts": ts2,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": ts2,
            "detail": {"reason": "live_refused", "code": "live_disabled", "pair": "SUIUSD"},
        },
    )
    third = alerts.collect(home, now=ts2 + 5)
    assert len(third) == 1, third
    assert third[0].acknowledged is False, third[0]
    assert third[0].count == 2, third[0]
    assert third[0].last_ts == ts2, third[0]


def test_corrupt_ack_file_does_not_raise(home: Path) -> None:
    """A non-jsonable alerts-ack.json is treated as empty; the next ack
    overwrites it without raising."""

    _append_journal_record(
        home,
        {
            "ts": 1_700_000_000,
            "kind": "tick",
            "venue": "kraken",
            "pack": "trend-follow",
            "bar_ts": 1_700_000_000,
            "detail": {"reason": "live_refused", "code": "live_disabled", "pair": "SUIUSD"},
        },
    )
    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    ack_file = run_dir / "alerts-ack.json"
    ack_file.write_bytes(b"\xff\xfe garbage \x00 \x01")

    result = alerts.collect(home, now=1_700_000_500)
    assert len(result) == 1, result
    assert result[0].acknowledged is False, result[0]

    acked = alerts.acknowledge(home, result[0].id, now=1_700_000_600)
    assert acked.acknowledged is True, acked

    # File is now valid JSON.
    reloaded = json.loads(ack_file.read_text(encoding="utf-8"))
    assert reloaded.get(result[0].id) == 1_700_000_600, reloaded

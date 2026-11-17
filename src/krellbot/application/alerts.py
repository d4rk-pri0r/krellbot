"""Persisted alerts surface for the live-operations view.

Sources (all read-only):

  1. ``live_gate.kill_state`` — kill switch engaged ⇒ one critical
     ``kill_switch`` alert.
  2. ``<home>/ops.sqlite`` ledger rows of kind ``needs_reconcile`` —
     one critical ``needs_reconcile`` alert per ``coid`` (i.e. the
     payload's ``coid`` is the alert code). The store is opened only
     when ``path.exists()`` is true so collecting alerts never creates
     the database.
  3. Journal tick records whose ``detail.reason`` is
     ``live_refused`` or ``store_refused``, or whose ``detail`` carries
     an ``intent_refused`` or ``metadata_refusal`` key — one warning
     alert per ``(kind, code, venue, pair)`` triple, deduped with a
     count and ``first_ts`` / ``last_ts``. A ``metadata_refusal`` tick
     must never be a silent skip: it surfaces as an unacknowledged
     Operations alert.
  4. Scheduler / tick supervision (M16.3): durable ``service/last_error``
     ⇒ ``tick_failure``; armed venues whose last journal tick is older
     than ``doctor.TICK_STALE_SECONDS`` ⇒ ``scheduler_stale``.
  5. Unresolved order aging (M16.3): operational ledger orders awaiting
     reconcile whose age is at least ``UNRESOLVED_AGING_SECONDS`` ⇒
     ``unresolved_order_aging``.
  6. Restore fence (M16.3): kill switch engaged with the home-restore
     reason ⇒ typed ``restore_fence`` (in addition to ``kill_switch``).

Alerts are deduped, severity-sorted (critical first), and ordered by
``last_ts`` descending inside each severity band. Acknowledgements
persist in ``<home>/run/alerts-ack.json`` keyed by alert id; a new
occurrence with a greater ``last_ts`` un-acknowledges the alert. A
corrupt ack file is treated as empty and overwritten on the next ack.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Mapping as _Mapping
from dataclasses import dataclass
from pathlib import Path

from krellbot import paths as kb_paths
from krellbot.application import live_gate
from krellbot.doctor import TICK_STALE_SECONDS

SCHEMA_VERSION = "1"
ACK_FILE = "alerts-ack.json"

REASON_LIVE_REFUSED = "live_refused"
REASON_STORE_REFUSED = "store_refused"
INTENT_REFUSED_KEY = "intent_refused"
METADATA_REFUSAL_KEY = "metadata_refusal"

KIND_TICK_FAILURE = "tick_failure"
KIND_SCHEDULER_STALE = "scheduler_stale"
KIND_UNRESOLVED_ORDER_AGING = "unresolved_order_aging"
KIND_RESTORE_FENCE = "restore_fence"

# Unresolved orders older than this surface as operator-supervision alerts.
UNRESOLVED_AGING_SECONDS = 3600

RESTORE_FENCE_REASON_PREFIX = "home restored"

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"

OPS_DB_FILENAME = "ops.sqlite"


@dataclass(frozen=True)
class Alert:
    """One deduped alert row."""

    id: str
    kind: str
    severity: str
    code: str | None
    venue: str | None
    pair: str | None
    count: int
    first_ts: int
    last_ts: int
    acknowledged: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity,
            "code": self.code,
            "venue": self.venue,
            "pair": self.pair,
            "count": self.count,
            "first_ts": self.first_ts,
            "last_ts": self.last_ts,
            "acknowledged": self.acknowledged,
        }


def _alert_id(kind: str, code: str | None, venue: str | None, pair: str | None) -> str:
    seed = json.dumps([kind, code, venue, pair], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _ack_path(home: Path) -> Path:
    return Path(home) / "run" / ACK_FILE


def _load_acks(home: Path) -> dict[str, int]:
    """Read the ack map. A missing or corrupt file yields {} so a corrupt
    file does not raise and the next ack overwrites it cleanly."""

    path = _ack_path(home)
    if not path.exists():
        return {}
    try:
        raw = path.read_bytes()
        decoded = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(decoded, dict):
        return {}
    out: dict[str, int] = {}
    for k, v in decoded.items():
        if isinstance(k, str) and isinstance(v, int):
            out[k] = v
    return out


def _save_acks(home: Path, acks: dict[str, int]) -> None:
    run_dir = Path(home) / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(acks, sort_keys=True, separators=(",", ":")).encode("utf-8")
    kb_paths.atomic_write(_ack_path(home), payload, mode=0o600)


def _collect_kill_switch(home: Path, *, now: int) -> list[Alert]:
    state = live_gate.kill_state(home)
    if not state.engaged:
        return []
    ts = state.engaged_at if state.engaged_at is not None else now
    return [
        Alert(
            id=_alert_id("kill_switch", "kill_switch_engaged", None, None),
            kind="kill_switch",
            severity=SEVERITY_CRITICAL,
            code="kill_switch_engaged",
            venue=None,
            pair=None,
            count=1,
            first_ts=ts,
            last_ts=ts,
            acknowledged=False,
        )
    ]


def _collect_needs_reconcile(home: Path) -> list[Alert]:
    """Read ``<home>/ops.sqlite`` for ``needs_reconcile`` ledger rows.

    The store is opened only when the file exists; collecting alerts
    never creates the database. Any read failure yields a single
    ``store_fault`` critical alert; the file bytes are not modified
    (the helper only opens an existing file in read mode through
    :class:`OperationalStore`).
    """

    path = Path(home) / OPS_DB_FILENAME
    if not path.exists():
        return []
    # Imported lazily so the cold-path does not pull sqlite3 for tests
    # that never touch the database.
    from krellbot.storage.database import (
        OperationalStore,
        StoreBusy,
        StoreCorrupt,
    )

    store = OperationalStore(path)
    try:
        rows = store.read_ledger()
    except (StoreBusy, StoreCorrupt, sqlite3.Error, OSError) as exc:
        code = getattr(exc, "code", "store_error")
        code = code if isinstance(code, str) else "store_error"
        return [
            Alert(
                id=_alert_id("store_fault", code, None, None),
                kind="store_fault",
                severity=SEVERITY_CRITICAL,
                code=code,
                venue=None,
                pair=None,
                count=1,
                first_ts=0,
                last_ts=0,
                acknowledged=False,
            )
        ]

    out: list[Alert] = []
    for _id, kind, payload in rows:
        if kind != "needs_reconcile":
            continue
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        coid = record.get("coid")
        if not isinstance(coid, str) or not coid:
            continue
        out.append(
            Alert(
                id=_alert_id("needs_reconcile", coid, None, None),
                kind="needs_reconcile",
                severity=SEVERITY_CRITICAL,
                code=coid,
                venue=None,
                pair=None,
                count=1,
                first_ts=0,
                last_ts=0,
                acknowledged=False,
            )
        )
    return out


def _iter_journal_records(home: Path) -> list[tuple[int, str, dict]]:
    """Read every line of every ``<home>/journal/*.jsonl`` file.

    Unparseable lines are skipped silently; the file must not be
    created on a missing home. Returns ``(ts, venue, detail_dict)``
    tuples in the order the journal wrote them.
    """

    journal_dir = Path(home) / "journal"
    if not journal_dir.exists():
        return []
    out: list[tuple[int, str, dict]] = []
    files = sorted(p for p in journal_dir.iterdir() if p.is_file() and p.suffix == ".jsonl")
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            ts_raw = record.get("ts")
            kind = record.get("kind")
            venue = record.get("venue")
            detail = record.get("detail")
            if not isinstance(ts_raw, int):
                continue
            if kind != "tick":
                continue
            if not isinstance(venue, str):
                continue
            if not isinstance(detail, dict):
                continue
            out.append((ts_raw, venue, detail))
    return out


def _bucket_journal_refusal(
    buckets: dict[tuple[str, str | None, str | None, str | None], dict[str, object]],
    *,
    kind: str,
    code: str | None,
    venue: str,
    pair: str | None,
    ts: int,
) -> None:
    key = (kind, code, venue, pair)
    bucket = buckets.get(key)
    if bucket is None:
        bucket = {"count": 0, "first_ts": ts, "last_ts": ts}
        buckets[key] = bucket
    bucket["count"] = int(bucket["count"]) + 1
    first_ts = int(bucket["first_ts"])
    last_ts = int(bucket["last_ts"])
    if ts < first_ts:
        bucket["first_ts"] = ts
    if ts > last_ts:
        bucket["last_ts"] = ts


def _collect_journal_refusals(home: Path) -> list[Alert]:
    """Group ``live_refused`` / ``store_refused`` / ``intent_refused`` /
    ``metadata_refusal`` records by ``(kind, code, venue, pair)``.

    A tick may carry more than one refusal key (for example
    ``intent_refused`` and ``metadata_refusal``); each non-null string
    key produces its own alert so a ``metadata_refusal`` is never a
    silent skip.
    """

    buckets: dict[tuple[str, str | None, str | None, str | None], dict[str, object]] = {}
    for ts, venue, detail in _iter_journal_records(home):
        reason = detail.get("reason")
        raw_pair = detail.get("pair")
        pair = raw_pair if isinstance(raw_pair, str) else None
        if reason == REASON_LIVE_REFUSED:
            raw_code = detail.get("code")
            code = raw_code if isinstance(raw_code, str) else None
            _bucket_journal_refusal(
                buckets,
                kind=REASON_LIVE_REFUSED,
                code=code,
                venue=venue,
                pair=pair,
                ts=ts,
            )
        elif reason == REASON_STORE_REFUSED:
            raw_code = detail.get("code")
            code = raw_code if isinstance(raw_code, str) else None
            _bucket_journal_refusal(
                buckets,
                kind=REASON_STORE_REFUSED,
                code=code,
                venue=venue,
                pair=pair,
                ts=ts,
            )
        intent_code = detail.get(INTENT_REFUSED_KEY)
        if isinstance(intent_code, str) and intent_code:
            _bucket_journal_refusal(
                buckets,
                kind=INTENT_REFUSED_KEY,
                code=intent_code,
                venue=venue,
                pair=pair,
                ts=ts,
            )
        metadata_code = detail.get(METADATA_REFUSAL_KEY)
        if isinstance(metadata_code, str) and metadata_code:
            _bucket_journal_refusal(
                buckets,
                kind=METADATA_REFUSAL_KEY,
                code=metadata_code,
                venue=venue,
                pair=pair,
                ts=ts,
            )

    out: list[Alert] = []
    for (kind, code, venue, pair), bucket in buckets.items():
        out.append(
            Alert(
                id=_alert_id(kind, code, venue, pair),
                kind=kind,
                severity=SEVERITY_WARNING,
                code=code,
                venue=venue,
                pair=pair,
                count=int(bucket["count"]),
                first_ts=int(bucket["first_ts"]),
                last_ts=int(bucket["last_ts"]),
                acknowledged=False,
            )
        )
    return out


def _apply_acks(alerts: list[Alert], acks: _Mapping[str, int]) -> list[Alert]:
    """Mark each alert acknowledged when the ack ts is ``>= last_ts``.

    A new occurrence (greater ``last_ts``) un-acknowledges the alert,
    so the comparison uses ``>=`` so the alert stays acknowledged
    until a strictly later event arrives.
    """

    if not acks:
        return alerts
    out: list[Alert] = []
    for alert in alerts:
        ack_ts = acks.get(alert.id)
        acknowledged = ack_ts is not None and ack_ts >= alert.last_ts
        out.append(
            Alert(
                id=alert.id,
                kind=alert.kind,
                severity=alert.severity,
                code=alert.code,
                venue=alert.venue,
                pair=alert.pair,
                count=alert.count,
                first_ts=alert.first_ts,
                last_ts=alert.last_ts,
                acknowledged=acknowledged,
            )
        )
    return out


def _order(alerts: list[Alert]) -> list[Alert]:
    return sorted(
        alerts,
        key=lambda a: (
            0 if a.severity == SEVERITY_CRITICAL else 1,
            -a.last_ts,
            a.kind,
        ),
    )


def _collect_tick_failure(home: Path, *, now: int) -> list[Alert]:
    """Surface a durable scheduler ``last_error`` as ``tick_failure``."""

    from krellbot.service import supervise as kb_supervise

    message = kb_supervise.get_last_error(home)
    if message is None:
        return []
    code = message if len(message) <= 64 else message[:61] + "..."
    return [
        Alert(
            id=_alert_id(KIND_TICK_FAILURE, code, None, None),
            kind=KIND_TICK_FAILURE,
            severity=SEVERITY_CRITICAL,
            code=code,
            venue=None,
            pair=None,
            count=1,
            first_ts=now,
            last_ts=now,
            acknowledged=False,
        )
    ]


def _collect_scheduler_stale(home: Path, *, now: int) -> list[Alert]:
    """Warn when an armed venue's last tick is older than the stale threshold.

    Uses the same journal scan as scheduler supervision
    (``supervise.last_tick_ts``) and ``doctor.TICK_STALE_SECONDS``. A
    venue that has never ticked is not treated as stale here — that is
    a just-armed fleet state, not a missed scheduler wake.
    """

    from krellbot import config as kb_config
    from krellbot.service import supervise as kb_supervise

    try:
        cfg = kb_config.load_config(home)
    except (OSError, ValueError):
        return []
    venues = sorted({record.venue for record in cfg.armed})
    out: list[Alert] = []
    for venue in venues:
        last = kb_supervise.last_tick_ts(home, venue)
        if last is None:
            continue
        age = int(now) - int(last)
        if age < int(TICK_STALE_SECONDS):
            continue
        out.append(
            Alert(
                id=_alert_id(KIND_SCHEDULER_STALE, "tick_stale", venue, None),
                kind=KIND_SCHEDULER_STALE,
                severity=SEVERITY_WARNING,
                code="tick_stale",
                venue=venue,
                pair=None,
                count=1,
                first_ts=int(last),
                last_ts=int(now),
                acknowledged=False,
            )
        )
    return out


def _collect_unresolved_order_aging(home: Path, *, now: int) -> list[Alert]:
    """Warn for each unresolved order whose age meets the aging threshold."""

    from krellbot.application import operations as operations_view_app

    rows = operations_view_app.list_unresolved_orders(home, now=now)
    out: list[Alert] = []
    for row in rows:
        age = row.get("age_seconds")
        if not isinstance(age, int) or age < UNRESOLVED_AGING_SECONDS:
            continue
        coid = row.get("client_order_id")
        if not isinstance(coid, str) or not coid:
            continue
        out.append(
            Alert(
                id=_alert_id(KIND_UNRESOLVED_ORDER_AGING, coid, None, None),
                kind=KIND_UNRESOLVED_ORDER_AGING,
                severity=SEVERITY_WARNING,
                code=coid,
                venue=None,
                pair=None,
                count=1,
                first_ts=int(now) - int(age),
                last_ts=int(now),
                acknowledged=False,
            )
        )
    return out


def _collect_restore_fence(home: Path, *, now: int) -> list[Alert]:
    """Typed alert when the kill switch was engaged by a home restore fence."""

    state = live_gate.kill_state(home)
    if not state.engaged:
        return []
    reason = state.reason or ""
    if not reason.startswith(RESTORE_FENCE_REASON_PREFIX):
        return []
    ts = state.engaged_at if state.engaged_at is not None else now
    return [
        Alert(
            id=_alert_id(KIND_RESTORE_FENCE, "restore_fence_engaged", None, None),
            kind=KIND_RESTORE_FENCE,
            severity=SEVERITY_CRITICAL,
            code="restore_fence_engaged",
            venue=None,
            pair=None,
            count=1,
            first_ts=ts,
            last_ts=ts,
            acknowledged=False,
        )
    ]


def collect(home: Path, *, now: int) -> list[Alert]:
    """Collect alerts from every read-only source and return them in a
    stable order.

    Sources:

      * ``live_gate.kill_state`` (kill_switch)
      * ``<home>/ops.sqlite`` ``needs_reconcile`` rows (and one
        ``store_fault`` alert on a read failure)
      * ``<home>/journal/*.jsonl`` tick records with a refusal reason
        (``live_refused``, ``store_refused``, ``intent_refused``, or
        ``metadata_refusal``)
      * scheduler ``last_error`` (``tick_failure``) and stale last-tick
        gaps (``scheduler_stale``)
      * aged unresolved orders (``unresolved_order_aging``)
      * restore-fence kill reason (``restore_fence``)

    The function never creates any file. An empty home yields ``[]``
    and leaves the filesystem untouched.
    """

    alerts: list[Alert] = []
    alerts.extend(_collect_kill_switch(Path(home), now=now))
    alerts.extend(_collect_restore_fence(Path(home), now=now))
    alerts.extend(_collect_needs_reconcile(Path(home)))
    alerts.extend(_collect_journal_refusals(Path(home)))
    alerts.extend(_collect_tick_failure(Path(home), now=now))
    alerts.extend(_collect_scheduler_stale(Path(home), now=now))
    alerts.extend(_collect_unresolved_order_aging(Path(home), now=now))
    acks = _load_acks(Path(home))
    alerts = _apply_acks(alerts, acks)
    return _order(alerts)


def acknowledge(home: Path, alert_id: str, *, now: int) -> Alert:
    """Record an ack for ``alert_id`` at ``now`` and return the alert.

    A :class:`KeyError` is raised when ``alert_id`` is not in the
    current ``collect(...)`` output — callers cannot ack a phantom id.
    The ack file is written atomically with mode ``0o600``; a corrupt
    existing file is treated as empty and overwritten on this call.
    """

    home = Path(home)
    alerts = collect(home, now=now)
    for alert in alerts:
        if alert.id == alert_id:
            acks = _load_acks(home)
            acks[alert_id] = now
            _save_acks(home, acks)
            return Alert(
                id=alert.id,
                kind=alert.kind,
                severity=alert.severity,
                code=alert.code,
                venue=alert.venue,
                pair=alert.pair,
                count=alert.count,
                first_ts=alert.first_ts,
                last_ts=alert.last_ts,
                acknowledged=True,
            )
    raise KeyError(alert_id)


__all__ = [
    "ACK_FILE",
    "KIND_RESTORE_FENCE",
    "KIND_SCHEDULER_STALE",
    "KIND_TICK_FAILURE",
    "KIND_UNRESOLVED_ORDER_AGING",
    "SEVERITY_CRITICAL",
    "SEVERITY_WARNING",
    "UNRESOLVED_AGING_SECONDS",
    "Alert",
    "acknowledge",
    "collect",
]

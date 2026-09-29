"""Bounded research jobs and the SSE event buffer.

This module owns the queue, cancellation, and event buffer that the
v1 API exposes at:

  * ``POST /api/v1/research/jobs``
  * ``GET  /api/v1/jobs/{id}``
  * ``POST /api/v1/jobs/{id}/cancel``
  * ``GET  /api/v1/events``

Shape and behavior follow ``.superpowers/sdd/krellbot-2027/contracts/jobs.md``.
Job and Event dataclasses are versioned and stable. The buffer is bounded
because events are a notification channel, not the ledger — authoritative
state lives on disk and a client that misses a window may receive a
``resync_required`` marker and re-query the snapshot endpoints.
"""

from __future__ import annotations

import copy
import datetime as _dt
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"

JOB_KIND_RESEARCH_BACKTEST = "research.backtest"
JOB_KIND_EXPORT_REPRODUCIBILITY = "export.reproducibility"

JOB_STATE_QUEUED = "queued"
JOB_STATE_RUNNING = "running"
JOB_STATE_CANCELLING = "cancelling"
JOB_STATE_CANCELLED = "cancelled"
JOB_STATE_SUCCEEDED = "succeeded"
JOB_STATE_FAILED = "failed"

JOB_STATES_TERMINAL = frozenset({JOB_STATE_SUCCEEDED, JOB_STATE_FAILED, JOB_STATE_CANCELLED})
JOB_STATES_CANCEL = frozenset({JOB_STATE_RUNNING, JOB_STATE_CANCELLING})

JOB_ERROR_QUEUE_FULL = "queue_full"
JOB_ERROR_JOB_FAILED = "job_failed"
JOB_ERROR_MISSING_RESULT_REF = "missing_result_ref"
JOB_ERROR_NOT_FOUND = "not_found"
JOB_ERROR_RESULT_UNAVAILABLE = "result_unavailable"

# Allowed concurrency per the brief: one running + up to four queued.
MAX_RUNNING_JOBS = 1
MAX_QUEUED_JOBS = 4

# Bounded event buffer; per the contract, "events are not the ledger".
EVENT_BUFFER_LIMIT = 256

EVENT_KIND_JOB_CHANGED = "job.changed"
EVENT_KIND_RESYNC_REQUIRED = "resync_required"


@dataclass
class JobV1:
    """Versioned snapshot of a single job's state."""

    schema_version: str = SCHEMA_VERSION
    id: str = ""
    kind: str = JOB_KIND_RESEARCH_BACKTEST
    state: str = JOB_STATE_QUEUED
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    progress: dict | None = None
    result_ref: str | None = None
    error: dict | None = None
    correlation_id: str = ""

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "result_ref": self.result_ref,
            "error": self.error,
            "correlation_id": self.correlation_id,
        }


@dataclass
class EventV1:
    """Versioned event emitted by the manager."""

    schema_version: str = SCHEMA_VERSION
    seq: int = 0
    event_id: str = ""
    kind: str = ""
    occurred_at: str = ""
    subject_id: str = ""
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "seq": self.seq,
            "event_id": self.event_id,
            "kind": self.kind,
            "occurred_at": self.occurred_at,
            "subject_id": self.subject_id,
            "payload": dict(self.payload),
        }


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_job_id() -> str:
    return secrets.token_urlsafe(12)


def _extract_result(outcome: dict) -> dict:
    """Build the stored result object from a successful runner outcome.

    Returns a dict with ``legacy_receipt`` and ``trace`` keys. The bytes
    are kept exactly as the runner returned them — no key injection, no
    zero-substitution for missing fee / equity / drawdown values. The
    contract is that the receipt is byte-identical to the runner's view.
    """

    receipt = outcome.get("legacy_receipt")
    trace = outcome.get("trace")
    out: dict = {}
    if isinstance(receipt, dict):
        out["legacy_receipt"] = receipt
    if isinstance(trace, list):
        out["trace"] = trace
    return out


# ---------------------------------------------------------------------------
# Event buffer
# ---------------------------------------------------------------------------


class EventBuffer:
    """Thread-safe bounded ring buffer of :class:`EventV1`.

    The buffer is the M1 source for SSE replay. It is not the ledger:
    authoritative state lives on disk, and a client that misses a window
    may receive a ``resync_required`` and a fresh snapshot query.

    A separate asyncio lock is used inside the buffer; callers that hold
    the :class:`JobManager` lock must not re-enter the buffer's lock from
    elsewhere in a way that would invert the order. The manager itself
    only acquires the buffer lock *while already holding* the manager
    lock, so no cycle is possible.
    """

    def __init__(self, limit: int = EVENT_BUFFER_LIMIT) -> None:
        self._limit = int(limit)
        self._events: list[EventV1] = []
        self._lock = threading.Lock()
        self._seq = 0

    def append(self, *, kind: str, subject_id: str, payload: dict) -> EventV1:
        with self._lock:
            self._seq += 1
            event = EventV1(
                schema_version=SCHEMA_VERSION,
                seq=self._seq,
                event_id=str(self._seq),
                kind=kind,
                occurred_at=_now_iso(),
                subject_id=subject_id,
                payload=dict(payload),
            )
            self._events.append(event)
            if len(self._events) > self._limit:
                self._events = self._events[-self._limit :]
            return event

    def replay(self, last_event_id: int | None) -> list[EventV1]:
        """Return the events to replay for ``last_event_id``.

        With ``last_event_id=None`` every retained event is returned. With
        an integer, only events with ``seq > last_event_id`` are returned.
        """

        with self._lock:
            events = list(self._events)
        if last_event_id is None:
            return events
        return [e for e in events if e.seq > int(last_event_id)]

    def oldest_seq(self) -> int | None:
        """Return the smallest seq still retained, or ``None`` if empty."""

        with self._lock:
            return self._events[0].seq if self._events else None

    def is_gap(self, last_event_id: int) -> bool:
        """Return True if ``last_event_id`` is older than the oldest retained event."""

        with self._lock:
            if not self._events:
                return False
            return int(last_event_id) < self._events[0].seq

    def is_empty(self) -> bool:
        with self._lock:
            return not self._events


# ---------------------------------------------------------------------------
# Job manager
# ---------------------------------------------------------------------------


RunnerFn = Callable[[dict], Any]


class QueueFull(Exception):
    """Raised when the manager cannot accept a new job."""

    def __init__(self, code: str = JOB_ERROR_QUEUE_FULL, message: str | None = None) -> None:
        self.code = code
        self.message = message or "queue is full"
        super().__init__(self.message)


@dataclass
class _InternalJob:
    """Mutable internal record for one in-flight or terminal job."""

    id: str
    kind: str
    correlation_id: str
    created_at: str
    request: dict = field(default_factory=dict)
    job: JobV1 = field(default_factory=lambda: JobV1(state=JOB_STATE_QUEUED))
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # Stored only on success. ``None`` for queued, running, cancelling,
    # cancelled, and failed jobs. The result route reads this directly.
    result: dict | None = None

    def snapshot(self) -> JobV1:
        return copy.deepcopy(self.job)

    def is_cancel_requested(self) -> bool:
        return self.cancel_event.is_set()

    def result_snapshot(self) -> dict | None:
        """Return a deep copy of the stored result, or ``None``."""

        if self.result is None:
            return None
        return copy.deepcopy(self.result)


class JobManager:
    """Owns the bounded queue and the worker thread for one FastAPI app.

    The default runner delegates to ``ResearchService(home=home).run(request)``;
    tests inject their own runner so queue, cancel, and concurrency proofs
    do not need a network or a real backtest.
    """

    def __init__(
        self,
        *,
        home: Path,
        runner: RunnerFn | None = None,
        events: EventBuffer | None = None,
    ) -> None:
        self._home = Path(home)
        self._events = events if events is not None else EventBuffer()
        self._runner = runner
        self._jobs: dict[str, _InternalJob] = {}
        self._queue_order: list[str] = []
        self._running_id: str | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._worker_started = False

    # ---- public ----------------------------------------------------------

    def event_buffer(self) -> EventBuffer:
        return self._events

    def submit(self, *, kind: str, correlation_id: str, request: dict | None = None) -> JobV1:
        """Create a new job, enqueue it, and return its JobV1.

        Raises :class:`QueueFull` if one job is already running and four
        are queued. The exception path creates no job and emits no event.

        When no other job is running, the freshly submitted job is
        transitioned to ``running`` synchronously inside this call so the
        returned snapshot reflects the post-submit state immediately.
        The worker thread picks up the runner afterwards.
        """

        with self._lock:
            if self._running_id is not None and len(self._queue_order) >= MAX_QUEUED_JOBS:
                raise QueueFull()
            job_id = _new_job_id()
            created_at = _now_iso()
            internal = _InternalJob(
                id=job_id,
                kind=kind,
                correlation_id=correlation_id,
                created_at=created_at,
                request=dict(request or {}),
            )
            internal.job = JobV1(
                id=job_id,
                kind=kind,
                state=JOB_STATE_QUEUED,
                created_at=created_at,
                correlation_id=correlation_id,
            )
            self._jobs[job_id] = internal

            if self._running_id is None:
                # Claim the running slot synchronously so the response
                # already reflects ``running`` instead of a transient
                # ``queued``. The worker thread will invoke the runner.
                self._running_id = job_id
                internal.job.state = JOB_STATE_RUNNING
                internal.job.started_at = _now_iso()
                self._events.append(
                    kind=EVENT_KIND_JOB_CHANGED,
                    subject_id=job_id,
                    payload={"state": JOB_STATE_QUEUED, "kind": kind},
                )
                self._events.append(
                    kind=EVENT_KIND_JOB_CHANGED,
                    subject_id=job_id,
                    payload={"state": JOB_STATE_RUNNING, "kind": kind},
                )
                if self._worker is None:
                    self._worker = threading.Thread(
                        target=self._worker_loop,
                        name="krellbot-jobs",
                        daemon=True,
                    )
                    self._worker.start()
            else:
                self._queue_order.append(job_id)
                self._events.append(
                    kind=EVENT_KIND_JOB_CHANGED,
                    subject_id=job_id,
                    payload={"state": JOB_STATE_QUEUED, "kind": kind},
                )

            snapshot = internal.snapshot()

        self._wake.set()
        return snapshot

    def get(self, job_id: str) -> JobV1 | None:
        with self._lock:
            internal = self._jobs.get(job_id)
            if internal is None:
                return None
            return internal.snapshot()

    def result_for(self, job_id: str) -> dict | None:
        """Return the stored result for ``job_id`` or ``None``.

        Returns ``None`` when the job is unknown, or when no result has
        been stored yet (queued, running, cancelling, cancelled, failed).
        The caller can distinguish those by combining this with
        :meth:`get`: a known job with ``state == "succeeded"`` and a
        ``None`` value indicates a missing receipt, which the contract
        treats as a 500-class internal failure.
        """

        with self._lock:
            internal = self._jobs.get(job_id)
            if internal is None:
                return None
            return internal.result_snapshot()

    def cancel(self, job_id: str) -> JobV1 | None:
        """Cancel ``job_id`` if known and not already terminal. Idempotent.

        Cancelling a queued job removes it from the queue and finalizes
        the state as ``cancelled``. Cancelling a running job flips the
        state to ``cancelling`` and sets the cancel flag; the worker
        finalizes the state as ``cancelled`` when the runner returns.
        A cancel issued after the job has reached a terminal state is a
        no-op and returns the existing snapshot.
        """

        with self._lock:
            internal = self._jobs.get(job_id)
            if internal is None:
                return None
            if internal.job.state in JOB_STATES_TERMINAL:
                return internal.snapshot()

            internal.cancel_event.set()

            if internal.job.state == JOB_STATE_QUEUED:
                try:
                    self._queue_order.remove(internal.id)
                except ValueError:
                    pass
                internal.job.state = JOB_STATE_CANCELLED
                internal.job.finished_at = _now_iso()
                internal.job.result_ref = None
                self._events.append(
                    kind=EVENT_KIND_JOB_CHANGED,
                    subject_id=internal.id,
                    payload={"state": JOB_STATE_CANCELLED, "kind": internal.job.kind},
                )
                # A queue slot opened up; nudge the worker in case the
                # job was dequeued and about to be claimed.
                self._wake.set()
                return internal.snapshot()

            if internal.job.state == JOB_STATE_RUNNING:
                internal.job.state = JOB_STATE_CANCELLING
                self._events.append(
                    kind=EVENT_KIND_JOB_CHANGED,
                    subject_id=internal.id,
                    payload={"state": JOB_STATE_CANCELLING, "kind": internal.job.kind},
                )
                return internal.snapshot()

            # Already cancelling — idempotent, return the current snapshot.
            return internal.snapshot()

    # ---- worker ----------------------------------------------------------

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            job_id = self._pick_or_claim()
            if job_id is None:
                self._wake.wait(timeout=0.1)
                self._wake.clear()
                continue
            self._run_job(job_id)

    def _pick_or_claim(self) -> str | None:
        """Return the running job id, or claim the next queued job.

        Honors cancel-by-queue: a queued job whose cancel flag was set
        while it sat in the queue is finalized as ``cancelled`` and never
        runs. The next queued job is then claimed if any remain.
        """

        with self._lock:
            if self._stop.is_set():
                return None
            if self._running_id is None and not self._queue_order:
                return None

            if self._running_id is not None:
                return self._running_id

            # Skip already-cancelled queued entries; finalize them and
            # return None so the loop waits for the next live job.
            while self._queue_order:
                next_id = self._queue_order[0]
                internal = self._jobs.get(next_id)
                if internal is None:
                    self._queue_order.pop(0)
                    continue
                if internal.is_cancel_requested() and internal.job.state == JOB_STATE_QUEUED:
                    self._queue_order.pop(0)
                    internal.job.state = JOB_STATE_CANCELLED
                    internal.job.finished_at = _now_iso()
                    self._events.append(
                        kind=EVENT_KIND_JOB_CHANGED,
                        subject_id=internal.id,
                        payload={"state": JOB_STATE_CANCELLED, "kind": internal.job.kind},
                    )
                    continue
                break

            if not self._queue_order:
                return None

            next_id = self._queue_order.pop(0)
            internal = self._jobs.get(next_id)
            if internal is None:
                return None
            self._running_id = next_id
            internal.job.state = JOB_STATE_RUNNING
            internal.job.started_at = _now_iso()
            self._events.append(
                kind=EVENT_KIND_JOB_CHANGED,
                subject_id=internal.id,
                payload={"state": JOB_STATE_RUNNING, "kind": internal.job.kind},
            )
            return next_id

    def _run_job(self, job_id: str) -> None:
        with self._lock:
            internal = self._jobs.get(job_id)
            if internal is None:
                self._running_id = None
                self._wake.set()
                return
            cancel_event = internal.cancel_event
            request_payload = dict(internal.request)
            request_payload["id"] = internal.id
            request_payload["kind"] = internal.job.kind
            request_payload["correlation_id"] = internal.job.correlation_id

        outcome: Any = None
        runner_error: Exception | None = None

        try:
            runner = self._runner if self._runner is not None else self._default_runner
            outcome = runner(request_payload)
        except Exception:  # noqa: BLE001 — coerced to a closed JobV1 error code
            runner_error = RuntimeError("runner raised")
        finally:
            with self._lock:
                cancel_requested = cancel_event.is_set()
                if cancel_requested and internal.job.state in JOB_STATES_CANCEL:
                    self._finalize_cancelled(internal)
                elif runner_error is not None:
                    self._finalize_failed(internal, code=JOB_ERROR_JOB_FAILED, message="job failed")
                elif isinstance(outcome, dict) and outcome.get("ok") is True:
                    ref = outcome.get("result_ref")
                    if isinstance(ref, str) and ref:
                        internal.job.result_ref = ref
                        # Store the receipt + trace exactly as the runner
                        # returned them. We deliberately do not add keys
                        # and do not coerce missing fields to ``0``. The
                        # contract keeps the receipt bytes identical to
                        # the runner's output. The result route reads
                        # this object verbatim.
                        internal.result = _extract_result(outcome)
                        self._finalize_state(internal, JOB_STATE_SUCCEEDED)
                    else:
                        self._finalize_failed(
                            internal,
                            code=JOB_ERROR_MISSING_RESULT_REF,
                            message="runner returned no result_ref",
                        )
                else:
                    code = outcome.get("code") if isinstance(outcome, dict) else None
                    message = outcome.get("message") if isinstance(outcome, dict) else None
                    if isinstance(code, str) and code:
                        self._finalize_failed(
                            internal,
                            code=code,
                            message=str(message) if isinstance(message, str) else "job failed",
                        )
                    else:
                        self._finalize_failed(internal, code=JOB_ERROR_JOB_FAILED, message="job failed")

                if self._running_id == internal.id:
                    self._running_id = None

        # Outside the lock: wake any waiters so the next queued job gets
        # its turn on the worker thread.
        self._wake.set()

    # ---- finalize helpers ------------------------------------------------

    def _finalize_state(self, internal: _InternalJob, state: str) -> None:
        internal.job.state = state
        internal.job.finished_at = _now_iso()
        self._events.append(
            kind=EVENT_KIND_JOB_CHANGED,
            subject_id=internal.id,
            payload={"state": state, "kind": internal.job.kind},
        )

    def _finalize_cancelled(self, internal: _InternalJob) -> None:
        internal.job.state = JOB_STATE_CANCELLED
        internal.job.finished_at = _now_iso()
        internal.job.result_ref = None
        internal.job.error = None
        self._events.append(
            kind=EVENT_KIND_JOB_CHANGED,
            subject_id=internal.id,
            payload={"state": JOB_STATE_CANCELLED, "kind": internal.job.kind},
        )

    def _finalize_failed(self, internal: _InternalJob, *, code: str, message: str) -> None:
        internal.job.state = JOB_STATE_FAILED
        internal.job.finished_at = _now_iso()
        internal.job.result_ref = None
        internal.job.error = {"code": code, "message": message}
        self._events.append(
            kind=EVENT_KIND_JOB_CHANGED,
            subject_id=internal.id,
            payload={"state": JOB_STATE_FAILED, "kind": internal.job.kind},
        )

    # ---- default runner --------------------------------------------------

    def _default_runner(self, request_payload: dict) -> dict:
        """Default runner for the production path.

        Translates the API request dict into a :class:`ResearchRequest`
        and runs it through :class:`ResearchService`. Raises any
        exception the service raises; the worker captures it as a closed
        JobV1 error code.
        """

        from krellbot.application.research import ResearchRequest, ResearchService

        pack_path = request_payload.get("pack_path", "")
        revision_id = request_payload.get("revision_id")
        if not pack_path and isinstance(revision_id, str) and revision_id:
            from krellbot.application.strategy import RevisionNotFound, StrategyDraftService

            try:
                pack_path = str(StrategyDraftService(home=self._home).revision_path(revision_id))
            except RevisionNotFound:
                return {
                    "ok": False,
                    "code": JOB_ERROR_NOT_FOUND,
                    "message": "revision not found",
                }
        venue = request_payload.get("venue") or "kraken"
        pair = request_payload.get("pair")
        timeframe = request_payload.get("timeframe")
        dataset_csv = request_payload.get("dataset_csv")
        starting_cash = request_payload.get("starting_cash")
        fee_bps = request_payload.get("fee_bps")
        slippage_bps = request_payload.get("slippage_bps")
        slippage_mult = request_payload.get("slippage_mult")
        from_ms = request_payload.get("from_ms")
        to_ms = request_payload.get("to_ms")
        allow_gaps = bool(request_payload.get("allow_gaps", False))
        holdout_from_ms_raw = request_payload.get("holdout_from_ms")
        holdout_to_ms_raw = request_payload.get("holdout_to_ms")

        from decimal import Decimal

        kwargs: dict = {
            "pack_path": Path(str(pack_path)) if pack_path else Path("."),
            "venue": str(venue),
            "pair": str(pair) if isinstance(pair, str) else None,
            "timeframe": str(timeframe) if isinstance(timeframe, str) else None,
            "dataset_csv": Path(str(dataset_csv)) if dataset_csv else None,
            "starting_cash": Decimal(str(starting_cash)) if starting_cash is not None else Decimal(10000),
            "fee_bps": int(fee_bps) if fee_bps is not None else None,
            "slippage_bps": int(slippage_bps) if slippage_bps is not None else None,
            "slippage_mult": float(slippage_mult) if slippage_mult is not None else None,
            "from_ms": int(from_ms) if from_ms is not None else None,
            "to_ms": int(to_ms) if to_ms is not None else None,
            "allow_gaps": allow_gaps,
        }
        if "holdout_from_ms" in request_payload:
            kwargs["holdout_from_ms"] = holdout_from_ms_raw
        if "holdout_to_ms" in request_payload:
            kwargs["holdout_to_ms"] = holdout_to_ms_raw
        if "nodes" in request_payload:
            kwargs["nodes"] = request_payload.get("nodes")
        request = ResearchRequest(**kwargs)
        service = ResearchService(home=self._home)
        result = service.run(request)
        if not result.ok:
            refusal = result.refusal if isinstance(result.refusal, dict) else {}
            code = refusal.get("code") if isinstance(refusal.get("code"), str) else None
            message = refusal.get("message") if isinstance(refusal.get("message"), str) else "job failed"
            payload: dict = {"ok": False}
            if code is not None:
                payload["code"] = code
            payload["message"] = message
            return payload
        correlation_id = str(request_payload.get("correlation_id") or "")
        job_id = str(request_payload.get("id") or "unknown")
        # Pass the receipt + trace back to the worker verbatim. The worker
        # stores them under ``_InternalJob.result`` and the result route
        # reads them back. We do not add keys and do not coerce missing
        # fields to ``0``; the contract keeps the receipt bytes
        # byte-identical to the runner's view.
        detail = result.detail if isinstance(result.detail, dict) else {}
        trace = detail.get("trace")
        return {
            "ok": True,
            "result_ref": f"backtest:{correlation_id}:{job_id}",
            "legacy_receipt": result.legacy_receipt,
            "trace": trace,
        }

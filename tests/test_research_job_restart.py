"""Research job history survives restart without resubmitting work."""

import threading
import time
from unittest.mock import Mock

import pytest

from krellbot.api.jobs import JOB_KIND_RESEARCH_BACKTEST, JobManager


def submit(manager):
    return manager.submit(kind=JOB_KIND_RESEARCH_BACKTEST, correlation_id="synthetic-restart")


def stop_worker(manager):
    manager._stop.set()
    manager._wake.set()
    if manager._worker:
        manager._worker.join(timeout=3)
        assert not manager._worker.is_alive()


def test_restart_retains_running_queued_and_cancelling_without_replaying(tmp_path):
    release = threading.Event()
    started = threading.Event()

    def runner(_request):
        started.set()
        release.wait(timeout=10)
        return {"ok": False, "code": "synthetic", "message": "test complete"}

    original = JobManager(home=tmp_path, runner=runner)
    try:
        running = submit(original)
        assert started.wait(timeout=3)
        queued = submit(original)
        cancelled = submit(original)
        original.cancel(cancelled.id)
        replay = Mock()
        restored = JobManager(home=tmp_path, runner=replay)
        assert {j.id for j in restored.list_jobs()} == {running.id, queued.id, cancelled.id}
        for snapshot in (running, queued):
            job = restored.get(snapshot.id)
            assert job.state == "interrupted"
            assert job.created_at == snapshot.created_at
            assert job.finished_at is not None
            assert job.error["code"] == "interrupted"
            assert restored.result_for(job.id) is None
            assert restored.cancel(job.id).state == "interrupted"
        assert restored.get(cancelled.id).state == "cancelled"
        assert restored._worker is None
        replay.assert_not_called()
        again = JobManager(home=tmp_path, runner=replay)
        assert again.get(running.id).to_dict() == restored.get(running.id).to_dict()
        original.cancel(running.id)
        cancelling = JobManager(home=tmp_path, runner=replay)
        assert cancelling.get(running.id).state == "interrupted"
    finally:
        original._stop.set()
        release.set()
        stop_worker(original)


@pytest.mark.parametrize("succeeded", [True, False])
def test_finished_history_and_results_remain_exact_after_restart(tmp_path, succeeded):
    # Explicit synthetic runner output, not market returns.
    evidence = {"legacy_receipt": {"fee_bps": 10, "fixture": "synthetic"}, "trace": []}
    outcome = (
        {"ok": True, "result_ref": "synthetic-result", **evidence}
        if succeeded
        else {"ok": False, "code": "synthetic_refusal", "message": "fixture refused"}
    )
    manager = JobManager(home=tmp_path, runner=lambda _: outcome)
    try:
        job = submit(manager)
        deadline = time.monotonic() + 3
        while manager.get(job.id).state in {"queued", "running"}:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        expected = manager.get(job.id).to_dict()
        restored = JobManager(home=tmp_path, runner=Mock())
        assert restored.get(job.id).to_dict() == expected
        assert restored.result_for(job.id) == (evidence if succeeded else None)
        assert restored._worker is None
    finally:
        stop_worker(manager)

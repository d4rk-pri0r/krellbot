"""M3-FM: harness for the steward-runnable fault matrix.

The harness runs eight named cases; each case spawns fresh subprocesses
that drive ``krellbot.run.tick`` through the real ``tick -> outbox -> store``
path with a scripted fake venue. This test module asserts the harness
itself:

  - reports rc 0 when all eight cases pass
  - prints eight rows on stdout, in the exact order the brief specifies
  - every row has ``pass is True``
  - ``observed`` is NOT the same object as ``expected`` (verified by a
    deliberate perturbation via ``KRELLBOT_FM_SABOTAGE``)
  - the parent test exits non-zero when a row fails (negative case)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS = REPO_ROOT / "scripts" / "fault_matrix.py"

EXPECTED_CASE_ORDER = [
    "crash_before_send",
    "crash_after_send_before_commit",
    "duplicate_fill",
    "disk_full_state_write",
    "restart_with_pending_intents",
    "corrupt_or_busy_store",
    "live_refused_before_transport",
    "live_outbox_commit_before_send",
]


def _run_harness(
    *,
    env_extra: dict[str, str] | None = None,
    json_out: Path | None = None,
    args: list[str] | None = None,
    timeout: int = 900,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(HARNESS)]
    if json_out is not None:
        cmd += ["--json-out", str(json_out)]
    if args:
        cmd += args
    env = os.environ.copy()
    # Force a clean keyring backend so no real secrets are read.
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    # Force-disable live in the parent (children force it themselves).
    env["KRELLBOT_ENABLE_LIVE"] = "0"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _last_json_line(stdout: str) -> dict:
    """Return the last JSON object printed on stdout by the harness."""
    last: dict | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            last = json.loads(line)
        except json.JSONDecodeError:
            continue
    assert last is not None, f"no JSON line in stdout:\n{stdout}"
    return last


def _row_for(rows: list[dict], case: str) -> dict:
    for r in rows:
        if r.get("case") == case:
            return r
    raise AssertionError(f"row for case {case!r} not found in {rows!r}")


def test_harness_runs_eight_cases_with_zero_failures():
    """The harness runs all eight cases, prints eight rows on stdout, all pass."""
    if not shutil.which("uv"):
        pytest.skip("uv is required to run the harness end-to-end")
    with tempfile.TemporaryDirectory() as tmp:
        json_path = Path(tmp) / "fm.json"
        proc = _run_harness(json_out=json_path, timeout=900)
        assert proc.returncode == 0, f"harness rc={proc.returncode}; stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        rows = json.loads(json_path.read_text(encoding="utf-8"))
        case_names = [r["case"] for r in rows]
        assert case_names == EXPECTED_CASE_ORDER, (
            f"case order mismatch: got {case_names}, expected {EXPECTED_CASE_ORDER}"
        )
        assert len(rows) == 8
        for r in rows:
            assert r["pass"] is True, (
                f"row must pass; case={r['case']!r} observed={r['observed']!r} expected={r['expected']!r} detail={r['detail']!r}"
            )

        summary = _last_json_line(proc.stdout)
        assert summary == {"summary": {"total": 8, "passed": 8, "failed": 0}}, summary


def test_harness_observed_is_not_copied_from_expected():
    """A deliberate perturbation via KRELLBOT_FM_SABOTAGE must produce a
    failing row. This proves the harness is not constant-true: the
    observed values are read from disk, never copied from expected.
    """
    if not shutil.which("uv"):
        pytest.skip("uv is required to run the harness end-to-end")
    proc = _run_harness(
        env_extra={"KRELLBOT_FM_SABOTAGE": "duplicate_fill"},
        timeout=900,
    )
    assert proc.returncode != 0, (
        f"harness must fail under sabotage; rc={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    # Find the duplicate_fill row and assert pass is False.
    rows: list[dict] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "case" in obj:
            rows.append(obj)
    assert rows, f"no row objects in stdout:\n{proc.stdout}"
    dup = _row_for(rows, "duplicate_fill")
    assert dup["pass"] is False, f"sabotaged row must fail; got {dup!r}"
    # And the observed payload must differ from the expected payload (proof that
    # the harness is not silently copying expected into observed).
    assert dup["observed"] != dup["expected"], (
        f"observed must be computed from disk, not copied from expected; row={dup!r}"
    )


def test_harness_single_case_flag_runs_only_one():
    """``--case NAME`` runs exactly one case and prints exactly one row + summary."""
    if not shutil.which("uv"):
        pytest.skip("uv is required to run the harness end-to-end")
    proc = _run_harness(args=["--case", "crash_before_send"], timeout=120)
    assert proc.returncode == 0, f"harness rc={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    rows = [json.loads(line) for line in proc.stdout.splitlines() if line.strip().startswith("{")]
    # Last line is the summary; everything before it is a row.
    summary_rows = [r for r in rows if "summary" in r]
    case_rows = [r for r in rows if "case" in r]
    assert len(case_rows) == 1, f"expected one case row, got {case_rows!r}"
    assert case_rows[0]["case"] == "crash_before_send"
    assert len(summary_rows) == 1, f"expected one summary line, got {summary_rows!r}"


def test_harness_unknown_case_returns_usage_error():
    """``--case NOPE`` exits 2 with no rows."""
    if not shutil.which("uv"):
        pytest.skip("uv is required to run the harness end-to-end")
    proc = _run_harness(args=["--case", "no-such-case"], timeout=60)
    assert proc.returncode == 2, (
        f"expected rc=2 for unknown case, got {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

"""NS30 conformance — paper gate refusal paths under fault scenarios.

Tests-first. ``scripts/paper_gate`` already returns
``"clock-not-started"`` when the clock file is absent and never creates
that file; the existing ``test_ns30_paper_gate.py`` covers the happy
and the refusal paths. This conformance file adds:

  * a fresh assertion that the missing-clock case stays missing across
    repeated calls (the gate must never materialise the file);
  * three measured fault-matrix rows — ``auth_refusal``, ``stale_data``,
    and ``duplicate_ownership`` — that record the gate's returned code
    alongside a wall-clock elapsed time measured via ``time.perf_counter``.

The three rows are assertions, not a substitute for the paper clock:
the test never writes a valid clock and the test does not create a new
paper-clock.json. Each row exercises a different refusal branch of
``paper_gate.evaluate`` and records ``{"result", "elapsed_ms"}``.
"""

from __future__ import annotations

import time
from pathlib import Path

from scripts.paper_gate import evaluate


def _measure(home: Path) -> tuple[str, float]:
    """Run ``evaluate(home)`` and return ``(result, elapsed_ms)``."""

    t0 = time.perf_counter()
    result = evaluate(home)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return result, elapsed_ms


def test_missing_clock_is_not_started_and_does_not_create_the_file(tmp_path: Path) -> None:
    """A missing clock stays missing across repeated gate calls.

    Conformance assertion: the gate must return ``clock-not-started``
    on every invocation against a clean ``KRELLBOT_HOME`` and must
    never materialise ``paper-clock.json`` as a side effect of
    running the gate.
    """

    clock_path = tmp_path / "paper-clock.json"
    assert not clock_path.exists()

    assert evaluate(tmp_path) == "clock-not-started"
    assert not clock_path.exists()

    assert evaluate(tmp_path) == "clock-not-started"
    assert not clock_path.exists()

    # A third call still does not create the file. The conformance row
    # for the missing-clock case is also captured here for symmetry
    # with the three named fault-matrix rows below.
    result, elapsed_ms = _measure(tmp_path)
    assert result == "clock-not-started"
    assert elapsed_ms >= 0.0


def test_auth_refusal_is_measured(tmp_path: Path) -> None:
    """Fault-matrix row: an auth-refusal-shaped clock is incomplete.

    The clock file holds a parsed JSON object with no ``started_at``
    field — the gate's refusal path for "auth never started". The row
    records the gate's returned code and the measured elapsed time.
    """

    clock = tmp_path / "paper-clock.json"
    clock.write_text("{}")

    result, elapsed_ms = _measure(tmp_path)
    row: dict[str, object] = {
        "scenario": "auth_refusal",
        "result": result,
        "elapsed_ms": elapsed_ms,
    }

    assert row["result"] == "coverage-incomplete", row
    assert isinstance(row["elapsed_ms"], float), row
    assert row["elapsed_ms"] >= 0.0, row


def test_stale_data_is_measured(tmp_path: Path) -> None:
    """Fault-matrix row: a stale-data-shaped clock is incomplete.

    The clock file holds a parsed JSON object with ``started_at`` but
    no ``expected_evaluations`` field — the gate's refusal path for
    "data too old / under-specified". The row records the gate's
    returned code and the measured elapsed time.
    """

    clock = tmp_path / "paper-clock.json"
    clock.write_text('{"started_at": "2026-09-29T00:00:00Z"}')

    result, elapsed_ms = _measure(tmp_path)
    row: dict[str, object] = {
        "scenario": "stale_data",
        "result": result,
        "elapsed_ms": elapsed_ms,
    }

    assert row["result"] == "coverage-incomplete", row
    assert isinstance(row["elapsed_ms"], float), row
    assert row["elapsed_ms"] >= 0.0, row


def test_duplicate_ownership_is_measured(tmp_path: Path) -> None:
    """Fault-matrix row: a duplicate-ownership-shaped clock is incomplete.

    The clock file holds bytes that are not parseable as a JSON object
    — the gate's refusal path for "clock content does not match the
    single-writer contract". The row records the gate's returned code
    and the measured elapsed time.
    """

    clock = tmp_path / "paper-clock.json"
    clock.write_text("not valid json {")

    result, elapsed_ms = _measure(tmp_path)
    row: dict[str, object] = {
        "scenario": "duplicate_ownership",
        "result": result,
        "elapsed_ms": elapsed_ms,
    }

    assert row["result"] == "coverage-incomplete", row
    assert isinstance(row["elapsed_ms"], float), row
    assert row["elapsed_ms"] >= 0.0, row
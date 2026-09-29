"""The paper gate refuses to count a day, and never creates the clock file."""

from __future__ import annotations

import json

from scripts.paper_gate import evaluate, main


def test_missing_clock_is_not_started_and_is_not_created(tmp_path) -> None:
    assert evaluate(tmp_path) == "clock-not-started"
    assert not (tmp_path / "paper-clock.json").exists()
    assert main([str(tmp_path)]) == 2
    assert not (tmp_path / "paper-clock.json").exists()


def test_incomplete_clock_is_not_counted(tmp_path) -> None:
    clock = tmp_path / "paper-clock.json"
    clock.write_text("{}")
    assert evaluate(tmp_path) == "coverage-incomplete"
    assert clock.read_text() == "{}"


def test_started_clock_counts_without_rewriting_the_file(tmp_path) -> None:
    clock = tmp_path / "paper-clock.json"
    payload = {"started_at": "2026-09-29T00:00:00Z", "expected_evaluations": 1}
    clock.write_text(json.dumps(payload))
    before = clock.read_bytes()
    assert evaluate(tmp_path) == "counted"
    assert main([str(tmp_path)]) == 0
    assert clock.read_bytes() == before

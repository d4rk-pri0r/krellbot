"""Tests for the jobs ERROR-CODE axis label mapper.

The closed set of job error codes lives in ``krellbot.api.jobs``; these
tests pin the mapping to stable, human-readable labels and the fallback
literal for anything outside the set.
"""

from __future__ import annotations

from krellbot.api.jobs import (
    JOB_ERROR_JOB_FAILED,
    JOB_ERROR_MISSING_RESULT_REF,
    JOB_ERROR_NOT_FOUND,
    JOB_ERROR_QUEUE_FULL,
    JOB_ERROR_RESULT_UNAVAILABLE,
)
from krellbot.application.jobs_error_label import JOBS_ERROR_LABELS, jobs_error_label

UNKNOWN = "Job error unknown"


def test_queue_full_label() -> None:
    assert jobs_error_label(JOB_ERROR_QUEUE_FULL) == "Queue full"


def test_job_failed_label() -> None:
    assert jobs_error_label(JOB_ERROR_JOB_FAILED) == "Job failed"


def test_missing_result_ref_label() -> None:
    assert jobs_error_label(JOB_ERROR_MISSING_RESULT_REF) == "Missing result reference"


def test_not_found_label() -> None:
    assert jobs_error_label(JOB_ERROR_NOT_FOUND) == "Job not found"


def test_result_unavailable_label() -> None:
    assert jobs_error_label(JOB_ERROR_RESULT_UNAVAILABLE) == "Result unavailable"


def test_none_falls_back_to_unknown() -> None:
    assert jobs_error_label(None) == UNKNOWN


def test_unknown_string_falls_back_to_unknown() -> None:
    assert jobs_error_label("UNKNOWN") == UNKNOWN


def test_non_string_falls_back_to_unknown() -> None:
    assert jobs_error_label(42) == UNKNOWN


def test_dict_is_closed_set_of_source_of_truth_constants() -> None:
    assert set(JOBS_ERROR_LABELS) == {
        JOB_ERROR_QUEUE_FULL,
        JOB_ERROR_JOB_FAILED,
        JOB_ERROR_MISSING_RESULT_REF,
        JOB_ERROR_NOT_FOUND,
        JOB_ERROR_RESULT_UNAVAILABLE,
    }
    assert JOBS_ERROR_LABELS[JOB_ERROR_QUEUE_FULL] == "Queue full"
    assert JOBS_ERROR_LABELS[JOB_ERROR_JOB_FAILED] == "Job failed"
    assert JOBS_ERROR_LABELS[JOB_ERROR_MISSING_RESULT_REF] == "Missing result reference"
    assert JOBS_ERROR_LABELS[JOB_ERROR_NOT_FOUND] == "Job not found"
    assert JOBS_ERROR_LABELS[JOB_ERROR_RESULT_UNAVAILABLE] == "Result unavailable"


def test_lookup_is_deterministic() -> None:
    first = jobs_error_label(JOB_ERROR_QUEUE_FULL)
    second = jobs_error_label(JOB_ERROR_QUEUE_FULL)
    assert first == second == "Queue full"
    assert jobs_error_label(None) == jobs_error_label(None) == UNKNOWN

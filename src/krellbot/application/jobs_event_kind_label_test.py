"""Tests for the jobs event-kind label mapper."""

from __future__ import annotations

from krellbot.api.jobs import EVENT_KIND_JOB_CHANGED, EVENT_KIND_RESYNC_REQUIRED
from krellbot.application.jobs_event_kind_label import (
    JOBS_EVENT_KIND_LABELS,
    JOBS_EVENT_KIND_UNKNOWN_LABEL,
    jobs_event_kind_label,
)


def test_job_changed_label() -> None:
    assert jobs_event_kind_label(EVENT_KIND_JOB_CHANGED) == "Job changed"


def test_resync_required_label() -> None:
    assert jobs_event_kind_label(EVENT_KIND_RESYNC_REQUIRED) == "Resync required"


def test_none_is_unknown() -> None:
    assert jobs_event_kind_label(None) == JOBS_EVENT_KIND_UNKNOWN_LABEL


def test_unknown_string_is_unknown() -> None:
    assert jobs_event_kind_label("UNKNOWN") == JOBS_EVENT_KIND_UNKNOWN_LABEL


def test_non_string_is_unknown() -> None:
    assert jobs_event_kind_label(42) == JOBS_EVENT_KIND_UNKNOWN_LABEL


def test_labels_pinned_to_source_of_truth_constants() -> None:
    assert set(JOBS_EVENT_KIND_LABELS) == {EVENT_KIND_JOB_CHANGED, EVENT_KIND_RESYNC_REQUIRED}


def test_deterministic_repeated_calls() -> None:
    first = jobs_event_kind_label(EVENT_KIND_JOB_CHANGED)
    second = jobs_event_kind_label(EVENT_KIND_JOB_CHANGED)
    assert first == second == "Job changed"


def test_empty_string_is_unknown() -> None:
    assert jobs_event_kind_label("") == JOBS_EVENT_KIND_UNKNOWN_LABEL


def test_arbitrary_object_is_unknown() -> None:
    assert jobs_event_kind_label(object()) == JOBS_EVENT_KIND_UNKNOWN_LABEL

"""Tests for the jobs validation-code label mapper."""

from __future__ import annotations

from krellbot.api.jobs import (
    CODE_INVALID_DATASET,
    CODE_INVALID_STARTING_CASH,
    CODE_NO_DATASET_AND_NO_FETCH,
)
from krellbot.application.jobs_validation_code_label import (
    JOBS_VALIDATION_CODE_LABELS,
    JOBS_VALIDATION_CODE_UNKNOWN_LABEL,
    jobs_validation_code_label,
)


def test_invalid_dataset_label() -> None:
    assert jobs_validation_code_label(CODE_INVALID_DATASET) == "Invalid dataset"


def test_no_dataset_and_no_fetch_label() -> None:
    assert jobs_validation_code_label(CODE_NO_DATASET_AND_NO_FETCH) == (
        "No dataset and no fetch"
    )


def test_invalid_starting_cash_label() -> None:
    assert jobs_validation_code_label(CODE_INVALID_STARTING_CASH) == (
        "Invalid starting cash"
    )


def test_none_is_unknown() -> None:
    assert jobs_validation_code_label(None) == JOBS_VALIDATION_CODE_UNKNOWN_LABEL


def test_unknown_string_is_unknown() -> None:
    assert jobs_validation_code_label("UNKNOWN") == JOBS_VALIDATION_CODE_UNKNOWN_LABEL


def test_non_string_is_unknown() -> None:
    assert jobs_validation_code_label(42) == JOBS_VALIDATION_CODE_UNKNOWN_LABEL


def test_closed_set_matches_source_of_truth() -> None:
    assert set(JOBS_VALIDATION_CODE_LABELS) == {
        CODE_INVALID_DATASET,
        CODE_NO_DATASET_AND_NO_FETCH,
        CODE_INVALID_STARTING_CASH,
    }


def test_deterministic_output() -> None:
    first = jobs_validation_code_label(CODE_INVALID_STARTING_CASH)
    second = jobs_validation_code_label(CODE_INVALID_STARTING_CASH)
    assert first == second == "Invalid starting cash"


def test_empty_string_is_unknown() -> None:
    assert jobs_validation_code_label("") == JOBS_VALIDATION_CODE_UNKNOWN_LABEL


def test_arbitrary_object_is_unknown() -> None:
    assert jobs_validation_code_label(object()) == JOBS_VALIDATION_CODE_UNKNOWN_LABEL

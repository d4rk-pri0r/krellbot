"""Jobs ERROR-CODE axis label mapper.

``krellbot.api.jobs`` defines the closed set of job error codes used by
``JobsError`` subclasses and HTTP-style error payloads. The UI renders the
raw ``code`` strings verbatim today; this mapper presents stable, human-
readable labels instead. Anything outside the closed set -- ``None``, a
non-string, an unknown string -- maps to the ``"Job error unknown"`` literal
so callers never have to guard against missing or malformed values.

This covers only the ERROR-CODE axis; the KIND and STATE axes are handled
separately by ``jobs_kind_label`` and ``research_job_state_label``.
"""

from __future__ import annotations

from krellbot.api.jobs import (
    JOB_ERROR_JOB_FAILED,
    JOB_ERROR_MISSING_RESULT_REF,
    JOB_ERROR_NOT_FOUND,
    JOB_ERROR_QUEUE_FULL,
    JOB_ERROR_RESULT_UNAVAILABLE,
)

JOBS_ERROR_LABELS: dict[str, str] = {
    JOB_ERROR_QUEUE_FULL: "Queue full",
    JOB_ERROR_JOB_FAILED: "Job failed",
    JOB_ERROR_MISSING_RESULT_REF: "Missing result reference",
    JOB_ERROR_NOT_FOUND: "Job not found",
    JOB_ERROR_RESULT_UNAVAILABLE: "Result unavailable",
}

JOBS_ERROR_UNKNOWN_LABEL = "Job error unknown"


def jobs_error_label(code: object) -> str:
    """Map a job error ``code`` to its human-readable label.

    Never raises and never returns ``None``: values outside the closed set
    fall back to ``JOBS_ERROR_UNKNOWN_LABEL``.
    """
    if isinstance(code, str):
        return JOBS_ERROR_LABELS.get(code, JOBS_ERROR_UNKNOWN_LABEL)
    return JOBS_ERROR_UNKNOWN_LABEL

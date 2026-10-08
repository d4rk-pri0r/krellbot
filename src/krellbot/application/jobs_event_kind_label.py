"""Pure label mapping for jobs event-kind codes."""

from __future__ import annotations

from krellbot.api.jobs import EVENT_KIND_JOB_CHANGED, EVENT_KIND_RESYNC_REQUIRED

JOBS_EVENT_KIND_UNKNOWN_LABEL = "Job event kind unknown"

JOBS_EVENT_KIND_LABELS: dict[str, str] = {
    EVENT_KIND_JOB_CHANGED: "Job changed",
    EVENT_KIND_RESYNC_REQUIRED: "Resync required",
}


def jobs_event_kind_label(kind: object) -> str:
    """Return the human-readable label for a jobs event-kind code.

    Pure lookup: returns ``JOBS_EVENT_KIND_UNKNOWN_LABEL`` for None,
    non-strings, or unrecognized codes. Never raises or mutates state.
    """
    if isinstance(kind, str) and kind in JOBS_EVENT_KIND_LABELS:
        return JOBS_EVENT_KIND_LABELS[kind]
    return JOBS_EVENT_KIND_UNKNOWN_LABEL

"""Jobs validation-code axis label mapper.

``krellbot.api.jobs`` defines a closed set of three request-validation
refusal codes (``CODE_*``) surfaced when arming/disarming paper or fetching
datasets. This mapper presents stable, human-readable labels for that axis
so CLI, audit log, or future renderers share identical wording. Anything
outside the closed set -- ``None``, a non-string, an unknown string --
falls back to the ``"Job validation code unknown"`` literal.

This covers only the VALIDATION-CODE axis; the KIND axis is handled by
``jobs_kind_label``, the ERROR-CODE axis by ``jobs_error_label``, and the
STATE axis by ``research_job_state_label``.
"""

from __future__ import annotations

from krellbot.api.jobs import (
    CODE_INVALID_DATASET,
    CODE_INVALID_STARTING_CASH,
    CODE_NO_DATASET_AND_NO_FETCH,
)

JOBS_VALIDATION_CODE_UNKNOWN_LABEL = "Job validation code unknown"

JOBS_VALIDATION_CODE_LABELS: dict[str, str] = {
    CODE_INVALID_DATASET: "Invalid dataset",
    CODE_NO_DATASET_AND_NO_FETCH: "No dataset and no fetch",
    CODE_INVALID_STARTING_CASH: "Invalid starting cash",
}


def jobs_validation_code_label(code: object) -> str:
    """Map a jobs validation ``code`` to its human-readable label.

    Never raises and never returns ``None``: values outside the closed set
    fall back to ``JOBS_VALIDATION_CODE_UNKNOWN_LABEL``.
    """
    if isinstance(code, str):
        return JOBS_VALIDATION_CODE_LABELS.get(code, JOBS_VALIDATION_CODE_UNKNOWN_LABEL)
    return JOBS_VALIDATION_CODE_UNKNOWN_LABEL

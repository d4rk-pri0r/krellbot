"""Trial record log.

A `record_trial(log, *, experiment_id, trial_id, state, config_sha256)`
call appends one record to `log`. `state` must be one of the three
literals `"succeeded"`, `"failed"`, or `"cancelled"`; any other value
raises `ValueError` and does not mutate `log`. A `failed` or
`cancelled` trial is recorded verbatim: it is never dropped, never
rewritten as `"succeeded"`, and the record carries no `equity`,
`return_pct`, or `pnl` field (the module does not invent a return).

A second call with the same `trial_id` raises `DuplicateTrial` and
leaves `log` at its prior length with the first record byte-identical.

`log` is a `MutableSequence[dict]`. The function performs no IO, no
clock reads, no keyring calls, and no network calls. It does not import
`krellbot.venues` or any other venue-aware module.
"""

from __future__ import annotations

from collections.abc import MutableSequence
from typing import Final

_ALLOWED_STATES: Final[frozenset[str]] = frozenset({"succeeded", "failed", "cancelled"})


class DuplicateTrial(Exception):
    """A second `record_trial` call with an already-recorded `trial_id`.

    The first record is preserved byte-identical: the log length is
    unchanged and the original entry is not overwritten.
    """

    def __init__(self, trial_id: str) -> None:
        self.trial_id = trial_id
        super().__init__(f"trial_id {trial_id!r} is already recorded")


def _validate_state(state: object) -> str:
    """Return `state` as a string if it is one of the allowed literals.

    Any other value (including non-strings) raises `ValueError` so the
    caller has a single failure mode for invalid states.
    """
    if not isinstance(state, str) or state not in _ALLOWED_STATES:
        allowed = ", ".join(sorted(_ALLOWED_STATES))
        raise ValueError(f"state must be one of {{{allowed}}}; got {state!r}")
    return state


def _already_recorded(log: MutableSequence[dict], trial_id: str) -> bool:
    """Return `True` if `trial_id` already appears in `log`.

    The lookup is a linear scan; the log is an in-memory list of
    records. The function does not index by `trial_id`: the brief makes
    no claim about lookup performance, only about uniqueness.
    """
    for entry in log:
        if entry.get("trial_id") == trial_id:
            return True
    return False


def record_trial(
    log: MutableSequence[dict],
    *,
    experiment_id: str,
    trial_id: str,
    state: str,
    config_sha256: str,
) -> dict:
    """Append one trial record to `log`.

    The record has four fields, exactly:
        - `experiment_id`:   the caller's experiment identifier
        - `trial_id`:        the caller's per-trial identifier
        - `state`:           one of `"succeeded"`, `"failed"`, `"cancelled"`
        - `config_sha256`:   the caller's hex digest string, stored verbatim

    No `equity`, `return_pct`, or `pnl` field is added. The function
    never invents a return for a `failed` or `cancelled` trial.

    `state` is validated first; an invalid `state` raises `ValueError`
    before any duplicate check, so a caller cannot probe whether a
    `trial_id` is taken by passing a bad state. On `DuplicateTrial`,
    the log is left at its prior length and the first record is not
    overwritten.

    Returns the appended record (the same `dict` instance now in `log`).
    """
    normalized_state = _validate_state(state)
    if _already_recorded(log, trial_id):
        raise DuplicateTrial(trial_id)

    record: dict[str, str] = {
        "experiment_id": experiment_id,
        "trial_id": trial_id,
        "state": normalized_state,
        "config_sha256": config_sha256,
    }
    log.append(record)
    return record


__all__ = ["DuplicateTrial", "record_trial"]

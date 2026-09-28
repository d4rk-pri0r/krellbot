"""NS17a: trial record log.

`record_trial(log, *, experiment_id, trial_id, state, config_sha256)`
appends one record to `log`. `state` must be `"succeeded"`, `"failed"`,
or `"cancelled"`; any other value raises `ValueError` and does not
mutate `log`. A `failed` or `cancelled` trial is recorded verbatim: it
is never dropped and never rewritten as `"succeeded"`. The record
carries `config_sha256` exactly as the caller passed it and does not
contain `equity`, `return_pct`, or `pnl` (the brief forbids invented
returns). A second call with the same `trial_id` raises `DuplicateTrial`
and leaves `log` at its prior length.

The module does not import `krellbot.venues` or open a network
connection.
"""

from __future__ import annotations

import pytest

from krellbot.research.experiments import DuplicateTrial, record_trial

# ---------------------------------------------------------------------------
# 1. record_trial appends one record; state must be one of three literals.
# ---------------------------------------------------------------------------


def test_record_trial_appends_one_record_for_succeeded():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    assert len(log) == 1


def test_record_trial_appends_one_record_for_failed():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="failed",
        config_sha256="a" * 64,
    )
    assert len(log) == 1


def test_record_trial_appends_one_record_for_cancelled():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="cancelled",
        config_sha256="a" * 64,
    )
    assert len(log) == 1


@pytest.mark.parametrize("bad_state", ["", "Succeeded", "SUCCESS", "done", "skipped", "running"])
def test_record_trial_rejects_unknown_state(bad_state: str):
    """Any `state` outside the three brief-allowed literals raises
    `ValueError` and does not mutate the log."""
    log: list[dict] = []
    with pytest.raises(ValueError):
        record_trial(
            log,
            experiment_id="exp-001",
            trial_id="trial-1",
            state=bad_state,
            config_sha256="a" * 64,
        )
    assert log == []


def test_record_trial_unknown_state_is_value_error_subclass():
    assert issubclass(ValueError, Exception)
    log: list[dict] = []
    with pytest.raises(ValueError) as excinfo:
        record_trial(
            log,
            experiment_id="exp-001",
            trial_id="trial-1",
            state="running",
            config_sha256="a" * 64,
        )
    assert "running" in str(excinfo.value)


def test_record_trial_rejects_non_string_state():
    """States that are not even strings raise `ValueError` (not `TypeError`):
    the brief requires a single failure mode for any invalid state."""
    log: list[dict] = []
    with pytest.raises(ValueError):
        record_trial(
            log,
            experiment_id="exp-001",
            trial_id="trial-1",
            state=42,  # type: ignore[arg-type]
            config_sha256="a" * 64,
        )
    assert log == []


# ---------------------------------------------------------------------------
# 2. failed and cancelled trials stay in the log; never dropped, never rewritten.
# ---------------------------------------------------------------------------


def test_record_trial_failed_trial_stays_in_log():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="failed",
        config_sha256="a" * 64,
    )
    assert len(log) == 1
    assert log[0]["state"] == "failed"


def test_record_trial_cancelled_trial_stays_in_log():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="cancelled",
        config_sha256="a" * 64,
    )
    assert len(log) == 1
    assert log[0]["state"] == "cancelled"


def test_record_trial_failed_state_is_not_rewritten_as_succeeded():
    """Recording a `failed` trial never silently upgrades it to
    `succeeded`. The stored `state` is exactly the caller's value."""
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="failed",
        config_sha256="a" * 64,
    )
    assert log[0]["state"] != "succeeded"


def test_record_trial_cancelled_state_is_not_rewritten_as_succeeded():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="cancelled",
        config_sha256="a" * 64,
    )
    assert log[0]["state"] != "succeeded"


def test_record_trial_mixed_states_all_remain_in_log():
    """A log with all three states keeps each entry exactly as recorded."""
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-2",
        state="failed",
        config_sha256="b" * 64,
    )
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-3",
        state="cancelled",
        config_sha256="c" * 64,
    )
    assert [entry["state"] for entry in log] == ["succeeded", "failed", "cancelled"]
    assert len(log) == 3


# ---------------------------------------------------------------------------
# 3. config_sha256 is stored exactly; no equity/return_pct/pnl field.
# ---------------------------------------------------------------------------


def test_record_trial_stores_config_sha256_exactly():
    digest = "0123456789abcdef" * 4  # 64 hex chars
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256=digest,
    )
    assert log[0]["config_sha256"] == digest
    assert log[0]["config_sha256"] is digest


def test_record_trial_stores_config_sha256_for_failed():
    digest = "deadbeef" * 8
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="failed",
        config_sha256=digest,
    )
    assert log[0]["config_sha256"] == digest


def test_record_trial_stores_config_sha256_for_cancelled():
    digest = "feedface" * 8
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="cancelled",
        config_sha256=digest,
    )
    assert log[0]["config_sha256"] == digest


@pytest.mark.parametrize("forbidden_field", ["equity", "return_pct", "pnl"])
def test_record_trial_record_has_no_forbidden_field(forbidden_field: str):
    """The record does not invent `equity`, `return_pct`, or `pnl`.
    These are return-narrative fields; the brief forbids inventing a
    return when a trial failed or was cancelled."""
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="failed",
        config_sha256="a" * 64,
    )
    assert forbidden_field not in log[0]


def test_record_trial_record_keys_are_exactly_brief_fields():
    """The record exposes the brief-required fields and nothing else
    invented. No return-narrative field, no timestamp the brief did not
    ask for. The exact key set is an implementation choice made by the
    module; the test only pins what the brief forbids."""
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    forbidden = {"equity", "return_pct", "pnl"}
    assert forbidden.isdisjoint(log[0].keys())


def test_record_trial_records_experiment_id_and_trial_id():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-007",
        trial_id="trial-42",
        state="succeeded",
        config_sha256="a" * 64,
    )
    assert log[0]["experiment_id"] == "exp-007"
    assert log[0]["trial_id"] == "trial-42"


# ---------------------------------------------------------------------------
# 4. Two trials with the same trial_id raise DuplicateTrial; log unchanged.
# ---------------------------------------------------------------------------


def test_record_trial_duplicate_trial_id_raises_duplicate_trial():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    with pytest.raises(DuplicateTrial):
        record_trial(
            log,
            experiment_id="exp-001",
            trial_id="trial-1",
            state="succeeded",
            config_sha256="b" * 64,
        )


def test_record_trial_duplicate_trial_id_leaves_log_length_unchanged():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    before = len(log)
    with pytest.raises(DuplicateTrial):
        record_trial(
            log,
            experiment_id="exp-001",
            trial_id="trial-1",
            state="failed",
            config_sha256="b" * 64,
        )
    assert len(log) == before


def test_record_trial_duplicate_trial_id_does_not_overwrite_first_entry():
    """A refused duplicate must leave the first record byte-identical."""
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    first_entry = log[0]
    first_sha = log[0]["config_sha256"]
    first_state = log[0]["state"]
    with pytest.raises(DuplicateTrial):
        record_trial(
            log,
            experiment_id="exp-001",
            trial_id="trial-1",
            state="failed",
            config_sha256="b" * 64,
        )
    assert log[0] is first_entry
    assert log[0]["config_sha256"] == first_sha
    assert log[0]["config_sha256"] is first_sha
    assert log[0]["state"] == first_state


def test_duplicate_trial_is_an_exception_subclass():
    assert issubclass(DuplicateTrial, Exception)


def test_record_trial_duplicate_across_different_experiments_is_allowed():
    """`trial_id` uniqueness is global, not per-experiment. Two different
    `experiment_id`s may not reuse the same `trial_id`."""
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-A",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    with pytest.raises(DuplicateTrial):
        record_trial(
            log,
            experiment_id="exp-B",
            trial_id="trial-1",
            state="succeeded",
            config_sha256="b" * 64,
        )
    assert len(log) == 1


def test_record_trial_different_trial_ids_same_experiment_id_are_allowed():
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-2",
        state="failed",
        config_sha256="b" * 64,
    )
    assert len(log) == 2


def test_record_trial_duplicate_check_runs_after_state_validation():
    """An invalid `state` raises `ValueError`, not `DuplicateTrial`. The
    state validation is a precondition for the duplicate check, so a
    caller cannot accidentally learn that a `trial_id` is already
    taken by passing a bad state."""
    log: list[dict] = []
    record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    with pytest.raises(ValueError):
        record_trial(
            log,
            experiment_id="exp-001",
            trial_id="trial-1",
            state="running",
            config_sha256="b" * 64,
        )
    assert len(log) == 1


# ---------------------------------------------------------------------------
# 5. Keyword-only signature; returns the appended record.
# ---------------------------------------------------------------------------


def test_record_trial_arguments_are_keyword_only():
    """The brief pins the signature as keyword-only (`*,`). Positional
    arguments must not be accepted."""
    log: list[dict] = []
    with pytest.raises(TypeError):
        record_trial(log, "exp-001", "trial-1", "succeeded", "a" * 64)  # type: ignore[misc]


def test_record_trial_returns_appended_record():
    """The caller receives the record that was appended, so the same
    `dict` instance appears in `log` and as the return value."""
    log: list[dict] = []
    returned = record_trial(
        log,
        experiment_id="exp-001",
        trial_id="trial-1",
        state="succeeded",
        config_sha256="a" * 64,
    )
    assert returned is log[0]


# ---------------------------------------------------------------------------
# 6. Network isolation.
# ---------------------------------------------------------------------------


def test_record_trial_does_not_import_venues():
    """`krellbot.research.experiments` must not import `krellbot.venues`."""
    import ast
    import inspect

    import krellbot.research.experiments as experiments_mod

    source = inspect.getsource(experiments_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "venues" not in alias.name, f"krellbot.research.experiments imports {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "krellbot.venues", (
                "krellbot.research.experiments does a from-import from krellbot.venues"
            )
            for alias in node.names:
                assert "venues" not in alias.name, (
                    f"krellbot.research.experiments imports {alias.name!r} from {node.module!r}"
                )

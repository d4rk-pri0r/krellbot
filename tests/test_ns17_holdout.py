"""NS17b: holdout disjointness check.

`assert_disjoint(scored_from_ms, scored_to_ms, holdout_from_ms,
holdout_to_ms)` returns `None` when the scored window ends strictly
before the holdout starts, or starts strictly after the holdout ends.
Any other configuration — including a single shared endpoint, a partial
overlap on either side, or a scored window entirely inside the
holdout — raises `HoldoutOverlap`. The exception carries the four
timestamps as attributes; it does not carry `equity`, `return_pct`, or
`pnl`, because an overlapping score is not a return: the brief refuses
to score a window that touches the holdout.

The module does not import `krellbot.venues` or `krellbot.backtest`.
"""

from __future__ import annotations

import pytest

from krellbot.research.holdout import HoldoutOverlap, assert_disjoint

# ---------------------------------------------------------------------------
# 1. Disjoint windows return None and never raise.
# ---------------------------------------------------------------------------


def test_assert_disjoint_returns_none_when_scored_ends_before_holdout_starts():
    """The scored window ends strictly before the holdout begins; the
    call must return `None` and not raise."""
    result = assert_disjoint(
        scored_from_ms=0,
        scored_to_ms=1_000,
        holdout_from_ms=2_000,
        holdout_to_ms=3_000,
    )
    assert result is None


def test_assert_disjoint_returns_none_when_scored_starts_after_holdout_ends():
    """The scored window starts strictly after the holdout ends; the
    call must return `None` and not raise."""
    result = assert_disjoint(
        scored_from_ms=4_000,
        scored_to_ms=5_000,
        holdout_from_ms=1_000,
        holdout_to_ms=3_000,
    )
    assert result is None


def test_assert_disjoint_returns_none_with_one_ms_gap_on_left():
    """A scored window that ends one millisecond before the holdout
    starts is still disjoint. Shared endpoints are the boundary, not
    a one-ms gap."""
    result = assert_disjoint(
        scored_from_ms=0,
        scored_to_ms=999,
        holdout_from_ms=1_000,
        holdout_to_ms=2_000,
    )
    assert result is None


def test_assert_disjoint_returns_none_with_one_ms_gap_on_right():
    """A scored window that starts one millisecond after the holdout
    ends is still disjoint."""
    result = assert_disjoint(
        scored_from_ms=2_001,
        scored_to_ms=3_000,
        holdout_from_ms=0,
        holdout_to_ms=2_000,
    )
    assert result is None


def test_assert_disjoint_returns_none_for_empty_gap():
    """Two distant windows with a large gap are disjoint."""
    result = assert_disjoint(
        scored_from_ms=1_700_000_000_000,
        scored_to_ms=1_700_003_600_000,
        holdout_from_ms=1_800_000_000_000,
        holdout_to_ms=1_800_003_600_000,
    )
    assert result is None


# ---------------------------------------------------------------------------
# 2. Shared endpoints are overlap (requirement 2).
# ---------------------------------------------------------------------------


def test_assert_disjoint_raises_on_shared_endpoint_at_left():
    """When `scored_to_ms == holdout_from_ms`, the windows share a
    single endpoint. Per the brief, a shared endpoint is overlap, so
    the call must raise `HoldoutOverlap`."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=0,
            scored_to_ms=1_000,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


def test_assert_disjoint_raises_on_shared_endpoint_at_right():
    """When `scored_from_ms == holdout_to_ms`, the windows share a
    single endpoint. The call must raise `HoldoutOverlap`."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=2_000,
            scored_to_ms=3_000,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


def test_assert_disjoint_raises_on_identical_windows():
    """Two identical windows overlap entirely; the call must raise."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=1_000,
            scored_to_ms=2_000,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


# ---------------------------------------------------------------------------
# 3. Partial overlap on either side raises.
# ---------------------------------------------------------------------------


def test_assert_disjoint_raises_on_partial_overlap_left():
    """The scored window starts before the holdout and ends inside it."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=0,
            scored_to_ms=1_500,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


def test_assert_disjoint_raises_on_partial_overlap_right():
    """The scored window starts inside the holdout and ends after it."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=1_500,
            scored_to_ms=3_000,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


# ---------------------------------------------------------------------------
# 4. Scored window entirely inside the holdout (requirement 3).
# ---------------------------------------------------------------------------


def test_assert_disjoint_raises_when_scored_inside_holdout():
    """A scored window strictly inside the holdout must raise."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=1_100,
            scored_to_ms=1_900,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


def test_assert_disjoint_raises_when_scored_is_a_single_point_inside_holdout():
    """A degenerate single-point scored window `[x, x]` inside the
    holdout is still overlap: the point lies inside the holdout."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=1_500,
            scored_to_ms=1_500,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


def test_assert_disjoint_raises_when_holdout_inside_scored():
    """The holdout is entirely inside the scored window; the brief
    forbids any overlap, so this case is also refused."""
    with pytest.raises(HoldoutOverlap):
        assert_disjoint(
            scored_from_ms=0,
            scored_to_ms=3_000,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )


# ---------------------------------------------------------------------------
# 5. HoldoutOverlap carries the four timestamps as attributes.
# ---------------------------------------------------------------------------


def test_holdout_overlap_carries_the_four_timestamps():
    """The exception exposes `scored_from_ms`, `scored_to_ms`,
    `holdout_from_ms`, and `holdout_to_ms` as attributes so the caller
    can identify the offending windows."""
    with pytest.raises(HoldoutOverlap) as excinfo:
        assert_disjoint(
            scored_from_ms=0,
            scored_to_ms=1_500,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )
    assert excinfo.value.scored_from_ms == 0
    assert excinfo.value.scored_to_ms == 1_500
    assert excinfo.value.holdout_from_ms == 1_000
    assert excinfo.value.holdout_to_ms == 2_000


def test_holdout_overlap_attributes_are_exact_int_values():
    """The carried timestamps are the integer values the caller passed;
    no normalization, no float coercion."""
    with pytest.raises(HoldoutOverlap) as excinfo:
        assert_disjoint(
            scored_from_ms=1_700_000_000_000,
            scored_to_ms=1_700_003_600_000,
            holdout_from_ms=1_700_003_600_000,
            holdout_to_ms=1_700_007_200_000,
        )
    assert excinfo.value.scored_from_ms == 1_700_000_000_000
    assert excinfo.value.scored_to_ms == 1_700_003_600_000
    assert excinfo.value.holdout_from_ms == 1_700_003_600_000
    assert excinfo.value.holdout_to_ms == 1_700_007_200_000


def test_holdout_overlap_message_mentions_overlap():
    """The exception message is informative enough that a caller can
    tell the overlap was detected (not silently dropped)."""
    with pytest.raises(HoldoutOverlap) as excinfo:
        assert_disjoint(
            scored_from_ms=0,
            scored_to_ms=1_500,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )
    text = str(excinfo.value)
    assert "overlap" in text.lower() or "holdout" in text.lower()


def test_holdout_overlap_message_mentions_the_timestamps():
    """The four timestamps are visible in the message so a log line is
    enough to diagnose the violation."""
    with pytest.raises(HoldoutOverlap) as excinfo:
        assert_disjoint(
            scored_from_ms=0,
            scored_to_ms=1_500,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )
    text = str(excinfo.value)
    assert "0" in text
    assert "1500" in text or "1,500" in text
    assert "1000" in text or "1,000" in text
    assert "2000" in text or "2,000" in text


# ---------------------------------------------------------------------------
# 6. HoldoutOverlap carries no equity/return_pct/pnl (no invented return).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden_attr", ["equity", "return_pct", "pnl"])
def test_holdout_overlap_has_no_forbidden_attribute(forbidden_attr: str):
    """`HoldoutOverlap` is a refusal of a score, not a return-narrative
    record. The brief forbids inventing a return; the exception must
    not expose `equity`, `return_pct`, or `pnl`."""
    with pytest.raises(HoldoutOverlap) as excinfo:
        assert_disjoint(
            scored_from_ms=0,
            scored_to_ms=1_500,
            holdout_from_ms=1_000,
            holdout_to_ms=2_000,
        )
    assert not hasattr(excinfo.value, forbidden_attr), f"HoldoutOverlap must not carry a {forbidden_attr!r} attribute"


def test_holdout_overlap_class_does_not_define_forbidden_attributes():
    """The class itself never declares `equity`, `return_pct`, or `pnl`
    as instance attributes. The check is on the class, not just the
    instance, so a subclass cannot quietly add them either."""
    forbidden = {"equity", "return_pct", "pnl"}
    declared = set(HoldoutOverlap.__init__.__code__.co_names)
    assert forbidden.isdisjoint(declared)


# ---------------------------------------------------------------------------
# 7. HoldoutOverlap is a regular Exception subclass.
# ---------------------------------------------------------------------------


def test_holdout_overlap_is_an_exception_subclass():
    assert issubclass(HoldoutOverlap, Exception)


# ---------------------------------------------------------------------------
# 8. Network / module isolation.
# ---------------------------------------------------------------------------


def test_holdout_does_not_import_venues_or_backtest():
    """`krellbot.research.holdout` must not import `krellbot.venues`
    or `krellbot.backtest`. The disjointness check is a pure predicate
    over four timestamps; it does not own market data, keyring, or
    pack evaluation."""
    import ast
    import inspect

    import krellbot.research.holdout as holdout_mod

    source = inspect.getsource(holdout_mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "venues" not in alias.name, f"krellbot.research.holdout imports {alias.name!r}"
                assert "backtest" not in alias.name, f"krellbot.research.holdout imports {alias.name!r}"
        elif isinstance(node, ast.ImportFrom):
            assert node.module != "krellbot.venues", "krellbot.research.holdout does a from-import from krellbot.venues"
            assert node.module != "krellbot.backtest", (
                "krellbot.research.holdout does a from-import from krellbot.backtest"
            )
            assert not node.module.startswith("krellbot.venues."), (
                "krellbot.research.holdout does a from-import from krellbot.venues.*"
            )
            assert not node.module.startswith("krellbot.backtest."), (
                "krellbot.research.holdout does a from-import from krellbot.backtest.*"
            )

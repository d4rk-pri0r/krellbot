"""Holdout disjointness check.

A `assert_disjoint(scored_from_ms, scored_to_ms, holdout_from_ms,
holdout_to_ms)` call returns `None` when the scored window ends
strictly before the holdout starts, or starts strictly after the
holdout ends. Any other configuration — including a single shared
endpoint, a partial overlap on either side, a scored window entirely
inside the holdout, or a holdout entirely inside the scored window —
raises `HoldoutOverlap`. The exception carries the four timestamps as
attributes so the caller can identify the offending windows; it does
not carry `equity`, `return_pct`, or `pnl`, because an overlapping
score is not a return: the brief refuses to score a window that
touches the holdout.

The module is a pure predicate over four integers. It does not import
`krellbot.venues`, `krellbot.backtest`, the OS keyring, the network
stack, or any clock.
"""

from __future__ import annotations


class HoldoutOverlap(Exception):
    """The scored window overlaps the holdout window.

    Overlap is defined as any non-empty intersection between the two
    windows, including a single shared endpoint. The exception carries
    the four timestamps as attributes; it does not carry `equity`,
    `return_pct`, or `pnl`, because a refused score is not a return.
    """

    def __init__(
        self,
        scored_from_ms: int,
        scored_to_ms: int,
        holdout_from_ms: int,
        holdout_to_ms: int,
    ) -> None:
        self.scored_from_ms = scored_from_ms
        self.scored_to_ms = scored_to_ms
        self.holdout_from_ms = holdout_from_ms
        self.holdout_to_ms = holdout_to_ms
        super().__init__(
            f"holdout overlap refused: "
            f"scored=[{scored_from_ms}, {scored_to_ms}] "
            f"holdout=[{holdout_from_ms}, {holdout_to_ms}]"
        )


def _overlaps(
    scored_from_ms: int,
    scored_to_ms: int,
    holdout_from_ms: int,
    holdout_to_ms: int,
) -> bool:
    """Return `True` when the two closed intervals `[scored_from_ms,
    scored_to_ms]` and `[holdout_from_ms, holdout_to_ms]` share at
    least one timestamp, including a shared endpoint.

    The disjoint condition is `scored_to_ms < holdout_from_ms` (the
    scored window ends strictly before the holdout starts) **or**
    `scored_from_ms > holdout_to_ms` (the scored window starts strictly
    after the holdout ends). The overlap condition is the negation.
    """
    return scored_to_ms >= holdout_from_ms and scored_from_ms <= holdout_to_ms


def assert_disjoint(
    scored_from_ms: int,
    scored_to_ms: int,
    holdout_from_ms: int,
    holdout_to_ms: int,
) -> None:
    """Refuse a score whose window overlaps the holdout window.

    Returns `None` when the scored window is strictly disjoint from
    the holdout window: it ends strictly before the holdout starts
    (`scored_to_ms < holdout_from_ms`) or it starts strictly after the
    holdout ends (`scored_from_ms > holdout_to_ms`).

    Raises `HoldoutOverlap` when the two windows share at least one
    timestamp. A shared endpoint counts as overlap: the brief refuses
    any score that touches the holdout.

    The four arguments are interpreted as closed integer endpoints.
    The function is a pure predicate over the four timestamps; it
    performs no IO, no clock reads, no keyring calls, and no network
    calls, and does not import `krellbot.venues` or
    `krellbot.backtest`.
    """
    if _overlaps(
        scored_from_ms,
        scored_to_ms,
        holdout_from_ms,
        holdout_to_ms,
    ):
        raise HoldoutOverlap(
            scored_from_ms,
            scored_to_ms,
            holdout_from_ms,
            holdout_to_ms,
        )


__all__ = ["HoldoutOverlap", "assert_disjoint"]

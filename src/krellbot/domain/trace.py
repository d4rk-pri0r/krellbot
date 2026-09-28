"""NS18a — decision trace keeps `unknown` as `unknown`.

`decision_trace(*, source_ts_ms, rule_value, intent)` builds a
`DecisionTrace` carrying exactly three fields: `source_ts_ms`,
`rule_value`, and `intent`. The function is pure: it does not read a
clock, touch the keyring, open a network connection, or look at a
venue. `source_ts_ms` is stored as the caller passed it (an `int`,
including `0`); `rule_value` is stored verbatim, including the literal
string `"unknown"`, which the engine never coerces to `0`, `0.0`,
`None`, or `""`.

The record carries no `fill_price` and no `venue_fill` field. The
engine does not claim a modeled fill equals a venue fill, and the
module exposes no helper that would. The trace only records what the
rule decided; venue confirmations belong in the adapter layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DecisionTrace:
    """The three-field decision record.

    Fields:
        source_ts_ms: the caller's source timestamp in milliseconds. Stored
            as the caller passed it; `0` is a legal value (no source
            timestamp yet) and is preserved.
        rule_value:   the value the rule produced for this decision.
            Stored verbatim. The literal string `"unknown"` is stored
            as `"unknown"`, never coerced to `0`, `0.0`, `None`, or
            `""`. The type is `Any` because the rule may emit a string,
            a number, or another marker; the module does not pretend to
            know the rule's value type.
        intent:       the caller's intent string (e.g. `"entry"`,
            `"exit"`, `"stop"`).

    The record carries no `fill_price` and no `venue_fill` field. A
    decision trace never asserts a venue-side confirmation.
    """

    source_ts_ms: int
    rule_value: Any
    intent: str


def decision_trace(*, source_ts_ms: int, rule_value: Any, intent: str) -> DecisionTrace:
    """Build a `DecisionTrace` from the caller's three inputs.

    The function does not coerce `rule_value`: a literal `"unknown"`
    stays `"unknown"`, and a numeric value stays numeric. `source_ts_ms`
    is stored as the caller passed it, including `0`. The function
    performs no IO and does not consult any venue or run state.
    """
    return DecisionTrace(
        source_ts_ms=source_ts_ms,
        rule_value=rule_value,
        intent=intent,
    )


__all__ = ["DecisionTrace", "decision_trace"]

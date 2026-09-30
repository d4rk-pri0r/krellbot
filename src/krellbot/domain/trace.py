"""NS18a/b — decision trace keeps `unknown` as `unknown`.

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

NS18b adds `shared_decision_trace(pack, candles)` — the one builder
used by both replay (`ResearchService._build_trace`) and paper
(`paper_decision_trace`). Replay and paper take the same pack shape
and the same candle list; they call the same function; they return
equal lists. A warmup condition outcome stays the string `"unknown"`,
never `0`, `0.0`, `False`, or `None`. The builder imports
`krellbot.pack.evaluate` and `krellbot.pack.model` (the pure pack
math and the `Candle` type) and imports nothing from
`krellbot.venues` or `krellbot.run`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from krellbot.pack import evaluate as kb_evaluate
from krellbot.pack.model import Candle


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


def shared_decision_trace(pack: dict, candles: list[Candle]) -> list[dict]:
    """Build the per-bar decision trace shared by replay and paper.

    For every bar we emit one entry with: `bar_ts`, the closed candle
    values used, the pack indicators at this bar, the entry/exit
    condition outcomes, the per-bar Target, and whether the bar is
    warmup. Indicator values that are still warming up are emitted as
    `None`; condition outcomes whose operands include `None` are
    emitted as the literal string `"unknown"` so they are distinct
    from `false` and from numeric zero. The function takes the same
    pack shape `krellbot.pack.evaluate.run_series` already accepts and
    performs no IO; it is pure over `(pack, candles)`.

    `ResearchService._build_trace` (replay) and `paper_decision_trace`
    (paper) both call this function and return its output. For one
    pack and one candle list, the two paths return equal lists.
    """
    computed, _atr_series = kb_evaluate._compute_all(pack, candles)
    targets = kb_evaluate.run_series(pack, candles)
    used = kb_evaluate._used_indicators(pack.get("entry")) | kb_evaluate._used_indicators(pack.get("exit"))

    out: list[dict] = []
    for t, candle in enumerate(candles):
        target = targets[t]
        warmup = target.reason == "warmup"
        entry_path = _condition_outcomes(pack.get("entry"), computed, candles, t)
        exit_path = _condition_outcomes(pack.get("exit"), computed, candles, t)
        conditions = [
            {"path": f"entry{ep['path']}", "outcome": ep["outcome"], "operands": ep["operands"]} for ep in entry_path
        ]
        conditions.extend(
            {"path": f"exit{ep['path']}", "outcome": ep["outcome"], "operands": ep["operands"]} for ep in exit_path
        )

        indicators_map: dict[str, float | None] = {}
        for name in sorted(used):
            series = computed.get(name)
            v = series[t] if series is not None else None
            indicators_map[name] = v

        out.append(
            {
                "bar_ts": candle.ts_ms,
                "warmup": warmup,
                "input": {
                    "ts_ms": candle.ts_ms,
                    "open": float(candle.open),
                    "high": float(candle.high),
                    "low": float(candle.low),
                    "close": float(candle.close),
                    "volume": float(candle.volume),
                },
                "indicators": indicators_map,
                "conditions": conditions,
                "target": {
                    "long": target.long,
                    "stop_price": None if target.stop_price is None else float(target.stop_price),
                    "reason": target.reason,
                },
            }
        )
    return out


def paper_decision_trace(pack: dict, candles: list[Candle]) -> list[dict]:
    """Paper mode's decision trace. Delegates to `shared_decision_trace`.

    Paper mode takes the same pack shape and the same candle list as
    replay; the trace is the same function's output, so the two paths
    cannot drift. The brief pins `paper_decision_trace(pack, candles)`
    as the paper entry point.
    """
    return shared_decision_trace(pack, candles)


def _condition_outcomes(condition: Any, computed: dict, candles: list[Candle], i: int) -> list[dict]:
    """Walk a condition tree and return a flat list of {path, outcome, operands} per leaf.

    Outcomes are `True`, `False`, or the literal string `"unknown"`. The
    string marker is required so warmup/unavailable is distinct from
    `false` and from numeric zero — see
    `.superpowers/sdd/krellbot-2027/contracts/strategy-compatibility.md`.
    """

    out: list[dict] = []

    def _walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key in ("all", "any"):
                for j, sub in enumerate(node.get(key, [])):
                    _walk(sub, f"{path}.{key}[{j}]")
            return
        if isinstance(node, list) and len(node) == 3:
            left, op, right = node
            lv = _operand_value(left, computed, candles, i)
            rv = _operand_value(right, computed, candles, i)
            outcome = _outcome_for(op, left, right, computed, candles, i, lv, rv)
            out.append(
                {
                    "path": path,
                    "outcome": outcome,
                    "operands": {
                        "left": _operand_token(left),
                        "op": op,
                        "right": _operand_token(right),
                        "left_value": lv,
                        "right_value": rv,
                    },
                }
            )
            return
        out.append({"path": path, "outcome": "unknown", "operands": {}})

    _walk(condition, "")
    return out


def _operand_token(token: Any) -> Any:
    """Return a JSON-friendly token shape for an operand in a trace.

    Strings are kept as strings; numeric literals are kept as numbers;
    indicator references are the bare name. The shape is identical
    between operands that resolve and operands that do not, so the
    trace is uniform.
    """
    return token


def _operand_value(token: Any, computed: dict, candles: list[Candle], i: int) -> float | None:
    if isinstance(token, (int, float)):
        return float(token)
    if isinstance(token, str):
        if token == "open":
            return float(candles[i].open)
        if token == "high":
            return float(candles[i].high)
        if token == "low":
            return float(candles[i].low)
        if token == "close":
            return float(candles[i].close)
        if token == "volume":
            return float(candles[i].volume)
        series = computed.get(token)
        if series is None:
            return None
        return series[i]
    return None


def _outcome_for(
    op: str,
    left: Any,
    right: Any,
    computed: dict,
    candles: list[Candle],
    i: int,
    lv: float | None,
    rv: float | None,
) -> bool | str:
    if op == "crosses_above":
        if i == 0 or lv is None or rv is None:
            return "unknown" if lv is None or rv is None else False
        l1 = _operand_value(left, computed, candles, i - 1)
        r1 = _operand_value(right, computed, candles, i - 1)
        if l1 is None or r1 is None:
            return "unknown"
        return l1 <= r1 and lv > rv
    if op == "crosses_below":
        if i == 0 or lv is None or rv is None:
            return "unknown" if lv is None or rv is None else False
        l1 = _operand_value(left, computed, candles, i - 1)
        r1 = _operand_value(right, computed, candles, i - 1)
        if l1 is None or r1 is None:
            return "unknown"
        return l1 >= r1 and lv < rv
    if lv is None or rv is None:
        return "unknown"
    if op == ">":
        return lv > rv
    if op == "<":
        return lv < rv
    if op == ">=":
        return lv >= rv
    if op == "<=":
        return lv <= rv
    return "unknown"


__all__ = [
    "DecisionTrace",
    "decision_trace",
    "paper_decision_trace",
    "shared_decision_trace",
]

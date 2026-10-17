"""NS19h — stateful operators require a checkpoint.

``require_checkpoint(operator)`` returns ``None`` when the operator's
``fn`` is *not* in the stateful set ``{"ema", "atr",
"roofing_filter"}``. When ``fn`` *is* in that set, the operator must
carry a ``checkpoint`` field, and the field must be a ``dict``. A
missing key, ``None``, the integer ``0``, the float ``0.0``, or the
boolean ``True`` all raise ``MissingCheckpoint`` — each of those
values is a tempting "no state" sentinel that hides the absence of
cross-evaluation state, and the brief explicitly forbids storing any
of them as a checkpoint.

The stateful set is exactly three names — ``ema``, ``atr``, and
``roofing_filter`` — the three whitelist operators that hold state
across evaluations (the exponential moving average's seed, the average
true range's running window, and the roofing filter's two-stage
state). Operators outside the set (``sma``, ``wma``, ``vwma``,
``stdev``, ``roc``, ``efficiency_ratio``, ``power_mean``, ``hma``,
``highest``, ``lowest``) never carry a checkpoint, and the function
returns ``None`` without inspecting one.

``MissingCheckpoint`` carries the offending ``fn`` as an attribute so
the caller can identify which operator failed the check. It carries
no ``equity``, ``return_pct``, or ``pnl`` attribute — a refused
checkpoint check is not a return, and the brief forbids inventing one.

The module is a pure predicate over the operator shape. It does not
import ``krellbot.venues``, ``krellbot.run``, or
``krellbot.pack.evaluate``; it does not read the clock, touch the
keyring, or open a network transport. The strategy IR owns the
checkpoint check; venues, the evaluator, and runtime orchestration
consume the verified operator later.
"""

from __future__ import annotations

from typing import Any

# The stateful set is pinned by the brief: exactly ``{"ema", "atr",
# "roofing_filter"}``. No other names are added or removed. ``frozenset``
# is used so the policy cannot be mutated at runtime — the check is
# the contract, not a suggestion.
STATEFUL_FNS: frozenset[str] = frozenset({"ema", "atr", "roofing_filter"})


class MissingCheckpoint(Exception):
    """A stateful operator does not carry a ``dict`` checkpoint.

    The exception carries the offending operator's ``fn`` (``"ema"``,
    ``"atr"``, or ``"roofing_filter"``) as the ``fn`` attribute so the
    caller can identify which operator failed the check. It carries no
    ``equity``, ``return_pct``, or ``pnl`` attribute — a refused
    checkpoint check is not a return, and the brief forbids inventing
    one.
    """

    def __init__(self, fn: str) -> None:
        self.fn = fn
        super().__init__(
            f"checkpoint refusal: stateful operator {fn!r} requires a dict "
            f"checkpoint (the operator must materialise a dict, not None / "
            f"0 / 0.0 / True or any other sentinel)"
        )


def _require_mapping(operator: Any) -> None:
    """Refuse a non-mapping input.

    The brief pins the operator as a mapping that carries ``fn`` and
    ``checkpoint`` keys. ``None``, a string, a list, a tuple, a number,
    or a boolean are not operators and the function refuses them with
    ``TypeError`` rather than silently coercing. The check is the same
    shape rule the other NS19 leaves apply — a pure predicate over a
    known mapping shape does not guess at intent.
    """
    if not isinstance(operator, dict):
        raise TypeError(f"operator must be a mapping, got {type(operator).__name__}")


def _require_fn(operator: dict) -> str:
    """Return ``operator["fn"]`` or raise ``TypeError`` when missing.

    The brief pins the operator's identity in the ``fn`` key. The
    function reads it once and surfaces a missing key as ``TypeError``
    — the checkpoint rule is a check on a known operator shape, and
    an operator without ``fn`` is not a known operator.
    """
    if "fn" not in operator:
        raise TypeError("operator must carry an 'fn' field")
    fn = operator["fn"]
    if not isinstance(fn, str):
        raise TypeError(f"operator['fn'] must be a string, got {type(fn).__name__}")
    return fn


def require_checkpoint(operator: Any) -> None:
    """Refuse a stateful operator that does not carry a ``dict`` checkpoint.

    Returns ``None`` when ``operator["fn"]`` is *not* in the stateful
    set ``{"ema", "atr", "roofing_filter"}`` — non-stateful operators
    never carry a checkpoint and the function does not inspect the
    ``checkpoint`` field at all. Returns ``None`` when ``fn`` *is* in
    the stateful set *and* the operator carries a ``checkpoint`` field
    whose value is a ``dict``.

    Raises ``MissingCheckpoint`` when ``fn`` is in the stateful set
    *and* the operator's ``checkpoint`` field is missing, ``None``,
    the integer ``0``, the float ``0.0``, the boolean ``True``, or
    any other non-``dict`` value. The ``MissingCheckpoint`` exception
    carries the offending ``fn`` so the caller can identify the
    failing operator.

    A non-mapping input raises ``TypeError`` rather than
    ``MissingCheckpoint`` — the brief pins the rule for known
    operator shapes, and the function refuses to guess at intent. A
    mapping without ``fn`` also raises ``TypeError`` for the same
    reason. The function is a pure predicate over the operator
    shape; it does not import ``krellbot.venues``, ``krellbot.run``,
    or ``krellbot.pack.evaluate``, and it does not read the clock,
    touch the keyring, or open a network transport.
    """
    _require_mapping(operator)
    fn = _require_fn(operator)
    if fn not in STATEFUL_FNS:
        return
    # The stateful branch: the operator must carry a ``dict``
    # checkpoint. ``operator.get("checkpoint")`` returns ``None`` for a
    # missing key — a sentinel the brief explicitly refuses. The
    # ``isinstance(..., dict)`` check rejects every other type: ``None``,
    # ``0``, ``0.0``, ``True``, ``False``, strings, lists, tuples, and
    # any custom mapping that is not a ``dict`` (``OrderedDict`` is a
    # subclass of ``dict`` and passes; ``MappingProxyType`` does not).
    checkpoint = operator.get("checkpoint")
    if not isinstance(checkpoint, dict):
        raise MissingCheckpoint(fn)
    return


__all__ = ["STATEFUL_FNS", "MissingCheckpoint", "require_checkpoint"]

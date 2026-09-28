"""NS19e — typed v1 clock.

``require_v1_clock(graph)`` returns ``None`` only when ``graph`` is a
mapping whose ``schema_version`` is the integer ``1`` AND whose
``timeframe`` is exactly one of the three strings the locked pack
schema enumerates: ``"1h"``, ``"4h"``, ``"1d"``. Anything else raises
``InvalidGraph`` carrying the offending ``field`` and ``value``. The
exception carries no ``equity``, ``return_pct``, or ``pnl``: a refused
clock check is not a return, and the brief forbids inventing one.

The schema (``src/krellbot/pack/schema.json``) is the source of truth
for the legal values. The check uses ``type(value) is int`` rather than
``isinstance(value, int)`` — a ``bool`` is a subclass of ``int`` in
Python, so ``isinstance(True, int)`` is ``True`` and would let a
boolean ``schema_version`` through. The check uses string equality on
``timeframe`` rather than any coercion — the integer ``1`` and the
string ``"1H"`` are both refused, and a missing timeframe is refused
rather than defaulted to ``"1h"``.

The module is a pure predicate over the graph shape. It does not
import ``krellbot.venues``, ``krellbot.pack.evaluate``, or
``krellbot.run``; it does not read the clock, touch the keyring, or
open a network transport. The strategy IR owns the clock check;
venues, the evaluator, and runtime orchestration consume the
verified graph later.
"""

from __future__ import annotations

from typing import Any

# Allowed schema_version: the integer 1. The schema's ``const`` field
# pins it; the module mirrors that exactly. ``type(value) is int`` is
# used (not ``isinstance``) so ``True`` does not pass.
_LEGAL_SCHEMA_VERSION = 1

# Allowed timeframes: the schema's ``enum`` for ``timeframe`` is
# ``["1h", "4h", "1d"]``. Listed as a frozenset for O(1) membership
# tests; the module does not invent extra timeframes.
_LEGAL_TIMEFRAMES = frozenset({"1h", "4h", "1d"})


class InvalidGraph(Exception):
    """The graph failed the v1 clock check.

    Carries ``field`` (``"schema_version"`` or ``"timeframe"``) and
    ``value`` (the raw value that was supplied, verbatim — ``True`` is
    not coerced to ``1``, ``1.0`` is not coerced to ``1``, and a
    missing key is reported as ``None``). The brief forbids
    ``equity``, ``return_pct``, or ``pnl`` attributes: a refused clock
    check is not a return.
    """

    def __init__(self, field: str, value: Any, reason: str) -> None:
        self.field = field
        self.value = value
        self.reason = reason
        super().__init__(f"v1 clock refusal: {field}={value!r} ({reason})")


def _check_schema_version(graph: dict) -> None:
    """Verify ``graph["schema_version"]`` is the integer ``1``.

    Missing, ``True``, ``False``, ``1.0``, ``"1"``, or any other value
    raises ``InvalidGraph`` with ``field="schema_version"``. The
    check is deliberately strict: ``type(value) is int`` rules out the
    ``bool`` subclass of ``int``, and no coercion is applied. The
    missing case reports ``value=None``.
    """
    if "schema_version" not in graph:
        raise InvalidGraph(
            "schema_version",
            None,
            "schema_version missing; the v1 clock requires the integer 1",
        )
    raw = graph["schema_version"]
    if type(raw) is not int:
        raise InvalidGraph(
            "schema_version",
            raw,
            "schema_version must be the integer 1 (not coerced)",
        )
    if raw != _LEGAL_SCHEMA_VERSION:
        raise InvalidGraph(
            "schema_version",
            raw,
            f"schema_version must be the integer {_LEGAL_SCHEMA_VERSION}",
        )


def _check_timeframe(graph: dict) -> None:
    """Verify ``graph["timeframe"]`` is exactly one of the legal v1
    timeframes.

    Missing, the integer ``1``, the string ``"1H"``, the string
    ``"1m"``, or any value outside the schema's enum raises
    ``InvalidGraph`` with ``field="timeframe"``. The check uses
    membership in the legal set; it does not coerce an int to a
    string, normalise case, or default a missing value to ``"1h"``.
    """
    if "timeframe" not in graph:
        raise InvalidGraph(
            "timeframe",
            None,
            'timeframe missing; the v1 clock requires one of "1h", "4h", "1d"',
        )
    raw = graph["timeframe"]
    if not isinstance(raw, str) or raw not in _LEGAL_TIMEFRAMES:
        raise InvalidGraph(
            "timeframe",
            raw,
            'timeframe must be exactly one of "1h", "4h", "1d"',
        )


def require_v1_clock(graph: Any) -> None:
    """Refuse a graph whose ``schema_version`` or ``timeframe`` is not
    the exact legal v1 value.

    Returns ``None`` only when ``graph`` is a mapping whose
    ``schema_version`` is the integer ``1`` AND whose ``timeframe``
    is exactly ``"1h"``, ``"4h"``, or ``"1d"``. The two checks are
    independent: ``schema_version`` is checked first because a wrong
    schema version is the more fundamental refusal — no legal
    timeframe can rescue a graph whose schema_version is ``2`` or
    ``"1"`` or ``True``.

    The check uses ``type(value) is int`` for ``schema_version`` so a
    boolean (``True``, ``False``) does not pass: ``bool`` is a
    subclass of ``int`` in Python, so ``isinstance(True, int)`` is
    ``True``. The check uses set membership on a frozen string set
    for ``timeframe`` so an integer ``1``, a cased ``"1H"``, or an
    unsupported ``"1m"`` does not pass. Neither field is coerced or
    defaulted.

    ``graph`` must be a mapping. The function raises
    ``InvalidGraph`` (carrying ``field`` and ``value``) for any
    illegal value or for a missing field; the exception carries no
    ``equity``, ``return_pct``, or ``pnl`` attribute because a refused
    clock check is not a return. The function is a pure predicate
    over the graph shape; it does not import ``krellbot.venues``,
    ``krellbot.pack.evaluate``, or ``krellbot.run``, and it does not
    read the clock, touch the keyring, or open a network transport.
    """
    if not isinstance(graph, dict):
        raise InvalidGraph(
            "graph",
            type(graph).__name__,
            "graph must be a mapping",
        )
    _check_schema_version(graph)
    _check_timeframe(graph)


__all__ = ["InvalidGraph", "require_v1_clock"]

"""Trading-mode pack contract (DCA / grid / rebalance).

Modes are schema_version 1 DSL packs plus optional ``mode`` metadata.
Reserved ids must declare a matching ``mode.kind``. See
``docs/trading-modes.md``.
"""

from __future__ import annotations

from typing import Any

MODE_KINDS = frozenset({"dca", "grid", "rebalance"})

MODE_IDS: dict[str, str] = {
    "dca": "mode-dca",
    "grid": "mode-grid",
    "rebalance": "mode-rebalance",
}

MODE_LABELS: dict[str, str] = {
    "dca": "DCA",
    "grid": "Grid",
    "rebalance": "Rebalance",
}

RESERVED_MODE_IDS = frozenset(MODE_IDS.values())

_WEIGHT_SUM_TOLERANCE = 0.01


def kind_for_id(pack_id: str) -> str | None:
    """Return mode kind for a reserved pack id, else None."""
    for kind, reserved in MODE_IDS.items():
        if reserved == pack_id:
            return kind
    return None


def check_mode_contract(pack: dict) -> list[dict]:
    """Return contract errors for trading-mode packs.

    Ordinary packs without ``mode`` and without a reserved mode id return [].
    Call after JSON Schema + DSL semantic checks succeed (or when schema already
    refused structure — callers may still invoke this for reserved-id checks).
    """
    if not isinstance(pack, dict):
        return [{"field": "<root>", "message": "pack must be a JSON object"}]

    pack_id = pack.get("id")
    mode = pack.get("mode")
    errors: list[dict] = []

    if mode is None:
        if isinstance(pack_id, str) and pack_id in RESERVED_MODE_IDS:
            errors.append(
                {
                    "field": "mode",
                    "message": (f"reserved mode id `{pack_id}` requires a `mode` object with matching kind"),
                }
            )
        return errors

    if not isinstance(mode, dict):
        return [{"field": "mode", "message": "mode must be a JSON object"}]

    kind = mode.get("kind")
    if kind not in MODE_KINDS:
        # Schema should already catch this; keep a closed refusal.
        errors.append(
            {
                "field": "mode.kind",
                "message": "mode.kind must be one of: dca, grid, rebalance",
            }
        )
        return errors

    expected_id = MODE_IDS[kind]
    if pack_id != expected_id:
        errors.append(
            {
                "field": "id",
                "message": f"mode kind `{kind}` requires pack id `{expected_id}`",
            }
        )

    origin = pack.get("origin")
    if not isinstance(origin, str) or not origin.strip():
        errors.append(
            {
                "field": "origin",
                "message": "mode packs require a non-empty origin string",
            }
        )

    if kind == "grid":
        errors.extend(_check_grid_mode(mode))
    elif kind == "rebalance":
        errors.extend(_check_rebalance_mode(mode))

    return errors


def _check_grid_mode(mode: dict) -> list[dict]:
    levels = mode.get("levels")
    if not isinstance(levels, int) or isinstance(levels, bool) or not (2 <= levels <= 50):
        return [
            {
                "field": "mode.levels",
                "message": "grid mode requires integer levels between 2 and 50",
            }
        ]
    return []


def _check_rebalance_mode(mode: dict) -> list[dict]:
    errors: list[dict] = []
    threshold = mode.get("threshold_pct")
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
        errors.append(
            {
                "field": "mode.threshold_pct",
                "message": "rebalance mode requires numeric threshold_pct",
            }
        )
    elif not (0 < float(threshold) <= 100):
        errors.append(
            {
                "field": "mode.threshold_pct",
                "message": "threshold_pct must be > 0 and <= 100",
            }
        )

    targets = mode.get("targets")
    if not isinstance(targets, list) or not targets:
        errors.append(
            {
                "field": "mode.targets",
                "message": "rebalance mode requires a non-empty targets array",
            }
        )
        return errors

    weight_sum = 0.0
    for index, row in enumerate(targets):
        if not isinstance(row, dict):
            errors.append(
                {
                    "field": f"mode.targets[{index}]",
                    "message": "each target must be an object",
                }
            )
            continue
        symbol = row.get("symbol")
        weight = row.get("weight_pct")
        if not isinstance(symbol, str) or not symbol.strip():
            errors.append(
                {
                    "field": f"mode.targets[{index}].symbol",
                    "message": "target symbol is required",
                }
            )
        if not isinstance(weight, (int, float)) or isinstance(weight, bool):
            errors.append(
                {
                    "field": f"mode.targets[{index}].weight_pct",
                    "message": "weight_pct must be a number",
                }
            )
            continue
        if not (0 < float(weight) <= 100):
            errors.append(
                {
                    "field": f"mode.targets[{index}].weight_pct",
                    "message": "weight_pct must be > 0 and <= 100",
                }
            )
            continue
        weight_sum += float(weight)

    if abs(weight_sum - 100.0) > _WEIGHT_SUM_TOLERANCE:
        errors.append(
            {
                "field": "mode.targets",
                "message": (f"target weight_pct values must sum to 100 (±{_WEIGHT_SUM_TOLERANCE}); got {weight_sum}"),
            }
        )
    return errors


def is_mode_pack(pack: Any) -> bool:
    """True when pack declares mode metadata or uses a reserved mode id."""
    if not isinstance(pack, dict):
        return False
    if isinstance(pack.get("mode"), dict):
        return True
    pack_id = pack.get("id")
    return isinstance(pack_id, str) and pack_id in RESERVED_MODE_IDS

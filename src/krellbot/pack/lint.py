"""Semantic + structural validation for the Pack DSL.

Schema (JSON Schema 2020-12) handles the structure: required keys, types,
patterns, enums, len bounds. `check()` walks the pack for the things JSON Schema
cannot express:

    * indicator operand resolution (every name is a defined indicator or a price field)
    * unused indicators (every defined indicator is referenced somewhere)
    * nesting depth (conditions can only nest 3 deep)
    * lookback budget (max lookback across indicators + 1 must be <= 600)
    * power_mean p != 0 (the schema allows any number)

A pack with `id` + `public_label` and no `schema_version` is legacy: `check`
returns no errors and `is_legacy` returns True. Legacy packs list but do not run.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

import jsonschema

from . import indicators as ind

_LEGACY_KEYS = ("id", "public_label")
_MAX_DEPTH = 3
_MAX_LOOKBACK = 600

_SCHEMA_DOC: dict | None = None


def _schema() -> dict:
    global _SCHEMA_DOC
    if _SCHEMA_DOC is None:
        raw = resources.files("krellbot.pack").joinpath("schema.json").read_text(encoding="utf-8")
        _SCHEMA_DOC = json.loads(raw)
    return _SCHEMA_DOC


def is_legacy(pack: dict) -> bool:
    """True iff the dict has id+public_label and no schema_version."""
    if not isinstance(pack, dict):
        return False
    has_id = isinstance(pack.get("id"), str) and bool(pack["id"])
    has_label = isinstance(pack.get("public_label"), str) and bool(pack["public_label"])
    has_schema = "schema_version" in pack
    return has_id and has_label and not has_schema


def check(pack: Any) -> list[dict]:
    """Validate a pack dict. Returns [] on a valid pack or a legacy pack.

    On a legacy pack, callers should follow up with `is_legacy(pack)` to decide
    whether to print the "legacy: not runnable" marker.
    """
    errors: list[dict] = []
    if not isinstance(pack, dict):
        return [{"field": "<root>", "message": "pack must be a JSON object"}]
    if is_legacy(pack):
        return []
    schema = _schema()
    validator = jsonschema.Draft202012Validator(schema)
    seen: set[tuple] = set()
    for err in validator.iter_errors(pack):
        for sub in _expand_errors(err):
            key = (tuple(sub.absolute_path), sub.validator, sub.message)
            if key in seen:
                continue
            seen.add(key)
            field = _field_for(sub)
            errors.append({"field": field, "message": sub.message})
    if errors:
        return errors
    errors.extend(_semantic_checks(pack))
    return errors


def _expand_errors(err):
    """Yield a primary error plus any sub-errors in its context.

    jsonschema aggregates oneOf/anyOf failures at the parent path; the actual
    violation may live deeper in `err.context`. We want the deepest field name.
    """
    yield err
    context = getattr(err, "context", None)
    if not context:
        return
    for sub in context:
        yield from _expand_errors(sub)


def _field_for(err) -> str:
    """Return the most specific field name for an error.

    additionalProperties errors come back with an empty path but name the
    offending key in the message; pull it into the field for callers.
    """
    path = _format_path(err.absolute_path)
    if err.validator == "additionalProperties" and not path:
        msg = err.message
        # Format: "Additional properties are not allowed ('leverage' was unexpected)"
        if "'" in msg:
            name = msg.split("'")[1]
            return name
        return "additionalProperties"
    return path or err.validator or "<root>"


def _format_path(path) -> str:
    parts = [str(p) for p in path]
    return ".".join(parts)


def _semantic_checks(pack: dict) -> list[dict]:
    errors: list[dict] = []
    errors.extend(_check_indicators(pack))
    errors.extend(_check_operands(pack))
    errors.extend(_check_depth(pack))
    errors.extend(_check_lookback(pack))
    errors.extend(_check_power_mean_p(pack))
    return errors


def _check_indicators(pack: dict) -> list[dict]:
    errors: list[dict] = []
    indicators_map = pack.get("indicators", {})
    used = _used_indicator_names(pack)
    for name in list(indicators_map):
        if name not in used:
            errors.append(
                {
                    "field": f"indicators.{name}",
                    "message": f"unused indicator `{name}` is not allowed",
                }
            )
    return errors


def _check_operands(pack: dict) -> list[dict]:
    errors: list[dict] = []
    indicators_map = pack.get("indicators", {})
    for kind in ("entry", "exit"):
        cond = pack.get(kind)
        for path_token, name in _walk_operands(cond):
            if name in ind.PRICE_FIELDS:
                continue
            if isinstance(name, str) and name in indicators_map:
                continue
            errors.append(
                {
                    "field": f"{kind}.{path_token}",
                    "message": f"operand `{name}` is not a price field or a defined indicator",
                }
            )
    return errors


def _walk_operands(condition: Any, prefix: str = "") -> list[tuple[str, str]]:
    """Yield (path_token, operand_name) for every string operand in the tree."""
    out: list[tuple[str, str]] = []
    if isinstance(condition, dict):
        for key in ("all", "any"):
            for i, sub in enumerate(condition.get(key, [])):
                out.extend(_walk_operands(sub, f"{prefix}{key}[{i}]."))
    elif isinstance(condition, list) and len(condition) == 3:
        for idx, operand in enumerate((condition[0], condition[2])):
            if isinstance(operand, str):
                out.append((f"{prefix}[{idx}]", operand))
    return out


def _used_indicator_names(pack: dict) -> set[str]:
    used: set[str] = set()
    for kind in ("entry", "exit"):
        for _, name in _walk_operands(pack.get(kind)):
            if name not in ind.PRICE_FIELDS:
                used.add(name)
    return used


def _check_depth(pack: dict) -> list[dict]:
    errors: list[dict] = []
    for kind in ("entry", "exit"):
        depth = _depth(pack.get(kind))
        if depth > _MAX_DEPTH:
            errors.append(
                {
                    "field": kind,
                    "message": f"condition nesting depth {depth} exceeds max {_MAX_DEPTH}",
                }
            )
    return errors


def _depth(condition: Any) -> int:
    if isinstance(condition, dict):
        depths = [_depth(sub) for sub in condition.get("all", []) + condition.get("any", [])]
        if not depths:
            return 1
        return 1 + max(depths)
    if isinstance(condition, list) and len(condition) == 3:
        return 1
    return 0


def _check_lookback(pack: dict) -> list[dict]:
    indicators_map = pack.get("indicators", {})
    if not indicators_map:
        return []
    max_look = max(ind.lookback(p) for p in indicators_map.values())
    if max_look + 1 > _MAX_LOOKBACK:
        return [
            {
                "field": "indicators",
                "message": (
                    f"lookback {max_look + 1} exceeds max {_MAX_LOOKBACK}; lower an indicator `len` (or `smooth`)"
                ),
            }
        ]
    return []


def _check_power_mean_p(pack: dict) -> list[dict]:
    errors: list[dict] = []
    for name, params in pack.get("indicators", {}).items():
        if params.get("fn") == "power_mean" and float(params.get("p", 0)) == 0.0:
            errors.append(
                {
                    "field": f"indicators.{name}.p",
                    "message": "power_mean p must be non-zero",
                }
            )
    return errors


def lint_pack(path) -> list[dict]:
    """Load a pack from `path` and validate it. Returns [] if valid or legacy."""
    data = json.loads(path.read_text(encoding="utf-8"))
    return check(data)

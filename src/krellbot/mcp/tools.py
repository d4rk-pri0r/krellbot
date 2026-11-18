"""MCP tool registry — read / draft / validate / backtest / paper-arm.

Binds only to ``krellbot.application`` facades. Does not import ``run``,
``venues``, ``execution``, ``keys``, ``secrets.get``, ``live_gate``, or
``live_preflight``. Live arm and key read are refused with typed codes.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from krellbot.application import packs as packs_app
from krellbot.application import user_policy
from krellbot.application.paper import PaperService
from krellbot.application.research import ResearchRequest, ResearchService
from krellbot.application.strategy import (
    DraftNotRunnable,
    RevisionNotFound,
    StrategyDraftService,
    StrategyIdMismatch,
)
from krellbot.config import load_config
from krellbot.mcp.errors import (
    SCHEMA_VERSION,
    invalid_request,
    key_read_refused,
    live_arm_refused,
    policy_denied,
    unknown_tool,
)

# Canonical tool names (underscore form matches Python kwargs; aliases accepted).
ALLOWED_TOOLS: tuple[str, ...] = (
    "read",
    "draft",
    "validate",
    "backtest",
    "paper_arm",
)

_TOOL_ALIASES: dict[str, str] = {
    "paper-arm": "paper_arm",
    "paperarm": "paper_arm",
    "arm_paper": "paper_arm",
}

# Any of these prefixes / exact names are treated as key or live surfaces
# and refuse with the matching typed code (never dispatched).
_KEY_TOOL_MARKERS: tuple[str, ...] = (
    "key",
    "keys",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "keyring",
    "export_key",
    "export_keys",
    "read_key",
    "read_keys",
)
_LIVE_TOOL_MARKERS: tuple[str, ...] = (
    "live",
    "live_arm",
    "live.arm",
    "arm_live",
)


def _normalize_tool(name: str) -> str:
    raw = str(name or "").strip()
    lowered = raw.lower().replace(" ", "_")
    if lowered in _TOOL_ALIASES:
        return _TOOL_ALIASES[lowered]
    return lowered.replace("-", "_")


def _is_key_tool(normalized: str) -> bool:
    if normalized in ALLOWED_TOOLS:
        return False
    compact = normalized.replace(".", "_").replace("-", "_")
    parts = [p for p in compact.split("_") if p]
    if any(p in _KEY_TOOL_MARKERS for p in parts):
        return True
    return any(marker in compact for marker in ("secrets", "keyring", "credential"))


def _is_live_tool(normalized: str) -> bool:
    if normalized in ALLOWED_TOOLS:
        return False
    compact = normalized.replace(".", "_").replace("-", "_")
    if compact in _LIVE_TOOL_MARKERS:
        return True
    parts = [p for p in compact.split("_") if p]
    return "live" in parts


class McpTools:
    """In-process MCP tool surface for local agents (no network host required)."""

    def __init__(
        self,
        home: Path,
        *,
        clock: Callable[[], float] | None = None,
        fetch: Callable[..., Any] | None = None,
    ) -> None:
        self._home = Path(home)
        self._clock = clock
        self._fetch = fetch

    def list_tools(self) -> list[str]:
        """Return the closed allowlist (no live / keys tools)."""
        return list(ALLOWED_TOOLS)

    def policy_check(self, action: str) -> dict:
        """Evaluate one closed operator-policy action (does not mutate).

        Used by agents and tests to honor ``paper_arm`` / ``live`` /
        ``key_export`` without expanding the tool allowlist. Probes use
        :func:`user_policy.check` so they do not journal a refuse receipt;
        enforce seams (e.g. ``paper_arm``) call ``ensure_allowed`` instead.
        Hard MCP refuse codes for live/key tool names stay unchanged (M22.1).
        """
        decision = user_policy.check(self._home, str(action))
        body = decision.to_dict()
        body["tool"] = "policy_check"
        if not decision.ok:
            body["effect"] = "refused"
        return body

    def call(self, tool: str, **params: Any) -> dict:
        """Dispatch one tool; refusals return ``ok=False`` typed dicts (never raise)."""
        normalized = _normalize_tool(tool)
        # Hard MCP boundaries keep their typed codes (M22.1). Operator
        # policy further restricts allowlisted verbs such as paper_arm.
        if _is_key_tool(normalized):
            return key_read_refused(normalized).to_dict()
        if _is_live_tool(normalized):
            return live_arm_refused(normalized).to_dict()
        if normalized not in ALLOWED_TOOLS:
            return unknown_tool(normalized).to_dict()

        handlers: dict[str, Callable[..., dict]] = {
            "read": self._read,
            "draft": self._draft,
            "validate": self._validate,
            "backtest": self._backtest,
            "paper_arm": self._paper_arm,
        }
        return handlers[normalized](**params)

    # ---- verbs -----------------------------------------------------------

    def _read(self, **_params: Any) -> dict:
        drafts = StrategyDraftService(self._home, clock=self._clock).list_owned_summaries()
        packs = packs_app.list_packs(self._home)
        config = load_config(self._home)
        armed: list[dict] = []
        for row in config.armed:
            armed.append(
                {
                    "venue": row.venue,
                    "pair": row.pair,
                    "mode": row.mode,
                    "pack_id": row.pack_id,
                    "pack_version": row.pack_version,
                    "entries_paused": bool(getattr(row, "entries_paused", False)),
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "effect": "unchanged",
            "tool": "read",
            "drafts": drafts,
            "packs": packs,
            "armed": armed,
            "policy": user_policy.load_policy(self._home).to_dict(),
        }

    def _draft(
        self,
        *,
        pack: dict | None = None,
        parent_revision_id: str | None = None,
        **_extra: Any,
    ) -> dict:
        if not isinstance(pack, dict):
            return invalid_request("draft", "draft requires a pack object").to_dict()
        service = StrategyDraftService(self._home, clock=self._clock)
        try:
            if parent_revision_id:
                summary = service.edit(str(parent_revision_id), pack)
            else:
                summary = service.create(pack)
        except RevisionNotFound as exc:
            return invalid_request("draft", f"revision not found: {exc}").to_dict()
        except StrategyIdMismatch as exc:
            return invalid_request("draft", str(exc)).to_dict()
        except ValueError as exc:
            return invalid_request("draft", str(exc)).to_dict()
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "effect": "changed" if summary.get("outcome") == "created" else "unchanged",
            "tool": "draft",
            "result": summary,
        }

    def _validate(self, *, revision_id: str | None = None, **_extra: Any) -> dict:
        if not revision_id:
            return invalid_request("validate", "validate requires revision_id").to_dict()
        service = StrategyDraftService(self._home, clock=self._clock)
        try:
            summary = service.validate(str(revision_id))
        except RevisionNotFound as exc:
            return invalid_request("validate", f"revision not found: {exc}").to_dict()
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "effect": "changed",
            "tool": "validate",
            "result": summary,
        }

    def _backtest(
        self,
        *,
        pack_path: str | Path | None = None,
        dataset_csv: str | Path | None = None,
        venue: str = "kraken",
        pair: str | None = None,
        timeframe: str | None = None,
        allow_gaps: bool = False,
        **_extra: Any,
    ) -> dict:
        if pack_path is None:
            return invalid_request("backtest", "backtest requires pack_path").to_dict()
        request = ResearchRequest(
            pack_path=Path(pack_path),
            dataset_csv=Path(dataset_csv) if dataset_csv is not None else None,
            venue=str(venue),
            pair=pair,
            timeframe=timeframe,
            allow_gaps=bool(allow_gaps),
        )
        # Offline by default: no fetch means refuse without network/keyring.
        result = ResearchService(home=self._home, fetch=self._fetch).run(request)
        if not result.ok:
            refusal = result.refusal or {}
            return {
                "schema_version": SCHEMA_VERSION,
                "ok": False,
                "effect": "refused",
                "tool": "backtest",
                "code": str(refusal.get("code") or "research_refused"),
                "message": str(refusal.get("message") or "backtest refused"),
            }
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "effect": "unchanged",
            "tool": "backtest",
            "legacy_receipt": result.legacy_receipt,
            "detail": result.detail,
        }

    def _paper_arm(
        self,
        *,
        pack_path: str | Path | None = None,
        revision_id: str | None = None,
        venue: str | None = None,
        mode: str = "paper",
        paper_balance: Decimal | str | float | None = None,
        correlation_id: str = "",
        **_extra: Any,
    ) -> dict:
        # MCP boundary refuse before any paper/live service call.
        if str(mode) != "paper":
            return live_arm_refused("paper_arm").to_dict()

        decision = user_policy.ensure_allowed(self._home, user_policy.ACTION_PAPER_ARM)
        if not decision.ok:
            body = policy_denied("paper_arm", decision.message).to_dict()
            body["action"] = user_policy.ACTION_PAPER_ARM
            return body

        if not venue:
            return invalid_request("paper_arm", "paper_arm requires venue").to_dict()

        resolved_path: Path | None = None
        if revision_id:
            drafts = StrategyDraftService(self._home, clock=self._clock)
            try:
                resolved_path, _pack = drafts.pack_for_arm(str(revision_id))
            except RevisionNotFound as exc:
                return invalid_request("paper_arm", f"revision not found: {exc}").to_dict()
            except DraftNotRunnable as exc:
                return invalid_request("paper_arm", str(exc)).to_dict()
        elif pack_path is not None:
            resolved_path = Path(pack_path)
        else:
            return invalid_request(
                "paper_arm",
                "paper_arm requires pack_path or revision_id",
            ).to_dict()

        balance: Decimal | None
        if paper_balance is None:
            balance = None
        else:
            try:
                balance = Decimal(str(paper_balance))
            except (InvalidOperation, ValueError):
                return invalid_request("paper_arm", "paper_balance must be a decimal").to_dict()

        paper = PaperService(home=self._home, clock=self._clock)
        result = paper.arm(
            resolved_path,
            venue=str(venue),
            mode="paper",
            paper_balance=balance,
            correlation_id=correlation_id or "",
        )
        if revision_id and result.ok:
            try:
                StrategyDraftService(self._home, clock=self._clock).mark_deployed(str(revision_id))
            except (RevisionNotFound, DraftNotRunnable):
                pass
        out = result.to_dict()
        out["tool"] = "paper_arm"
        return out


__all__ = [
    "ALLOWED_TOOLS",
    "McpTools",
]

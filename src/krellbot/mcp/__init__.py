"""Local MCP adapter — agent tools against application facades only.

Exposes the five safe verbs (read, draft, validate, backtest, paper-arm).
Never live-arms and never reads or transmits exchange keys. Callers bind
an explicit ``home``; CI uses fakes / offline datasets only.
"""

from __future__ import annotations

from krellbot.mcp.errors import (
    CODE_KEY_READ_REFUSED,
    CODE_LIVE_ARM_REFUSED,
    CODE_POLICY_DENIED,
    CODE_UNKNOWN_TOOL,
    McpToolRefusal,
)
from krellbot.mcp.tools import ALLOWED_TOOLS, McpTools

__all__ = [
    "ALLOWED_TOOLS",
    "CODE_KEY_READ_REFUSED",
    "CODE_LIVE_ARM_REFUSED",
    "CODE_POLICY_DENIED",
    "CODE_UNKNOWN_TOOL",
    "McpToolRefusal",
    "McpTools",
]

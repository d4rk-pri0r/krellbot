"""Typed MCP refusals — closed codes for agent-visible errors.

Refusals never carry key material or live grant payloads. Messages are
from a closed set so an agent transcript cannot leak secrets.
"""

from __future__ import annotations

from dataclasses import dataclass

SCHEMA_VERSION = "1"

CODE_LIVE_ARM_REFUSED = "mcp_live_arm_refused"
CODE_KEY_READ_REFUSED = "mcp_key_read_refused"
CODE_UNKNOWN_TOOL = "mcp_unknown_tool"
CODE_INVALID_REQUEST = "mcp_invalid_request"

MESSAGE_LIVE_ARM_REFUSED = "MCP refuses live arm; paper-arm only"
MESSAGE_KEY_READ_REFUSED = "MCP refuses key read or key export"
MESSAGE_UNKNOWN_TOOL = "MCP tool is not in the allowlist"


@dataclass(frozen=True)
class McpToolRefusal:
    """Closed refusal returned by the MCP adapter (never raised as opaque text)."""

    code: str
    message: str
    tool: str

    def to_dict(self) -> dict:
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": False,
            "effect": "refused",
            "code": self.code,
            "message": self.message,
            "tool": self.tool,
        }


def live_arm_refused(tool: str) -> McpToolRefusal:
    return McpToolRefusal(CODE_LIVE_ARM_REFUSED, MESSAGE_LIVE_ARM_REFUSED, tool)


def key_read_refused(tool: str) -> McpToolRefusal:
    return McpToolRefusal(CODE_KEY_READ_REFUSED, MESSAGE_KEY_READ_REFUSED, tool)


def unknown_tool(tool: str) -> McpToolRefusal:
    return McpToolRefusal(CODE_UNKNOWN_TOOL, MESSAGE_UNKNOWN_TOOL, tool)


def invalid_request(tool: str, message: str) -> McpToolRefusal:
    return McpToolRefusal(CODE_INVALID_REQUEST, message, tool)

---
name: krellbot-mcp
description: >-
  Drive Krellbot’s local MCP adapter from Cursor — read, draft, validate,
  backtest, and paper-arm only against $KRELLBOT_HOME. Use when the user
  asks an agent to validate packs, run offline backtests, paper-arm, or
  work with the Krellbot MCP surface. Never live-arm and never read or
  transmit exchange keys.
---

# Krellbot MCP (Cursor)

Local, policy-bound agent tools for Krellbot. Full operator guide:
`docs/agent-cursor.md`. Surface contract: `docs/mcp.md`.

## When to use

- Validate → backtest → paper-arm a pack or draft on this machine
- Inventory drafts / packs / armed paper rows via `read`
- Any Cursor task that mentions Krellbot MCP, paper-arm, or agent tools

## Install / bind

1. Work in a Krellbot checkout (this skill lives at
   `.cursor/skills/krellbot-mcp/SKILL.md`) or symlink it into personal
   Cursor skills.
2. Ensure `$KRELLBOT_HOME` points at the operator data home (default
   `~/.krellbot`).
3. Call the in-process adapter only — no cloud MCP host, no remote keys:

```python
from pathlib import Path
import os
from krellbot.mcp import McpTools

home = Path(os.environ.get("KRELLBOT_HOME", Path.home() / ".krellbot"))
tools = McpTools(home)
```

## Auth to loopback

- Workstation API stays on `127.0.0.1` with Host / Origin / session /
  CSRF checks. Do not exfiltrate bootstrap tokens or session cookies.
- MCP binds `$KRELLBOT_HOME` in-process; it does not authenticate as a
  browser session and must not target non-loopback hosts.
- Never send exchange keys to krellbot.dev or into chat.

## Allowed verbs

| Tool | Params |
| --- | --- |
| `read` | — |
| `draft` | `pack`, optional `parent_revision_id` |
| `validate` | `revision_id` |
| `backtest` | `pack_path`, prefer offline `dataset_csv` |
| `paper_arm` | `venue`, `mode="paper"`, `pack_path` or `revision_id`, optional `paper_balance` |

Happy path: `validate` → `backtest` → `paper_arm`. Prefer offline CSV for
backtest. Honor typed refusals (`mcp_live_arm_refused`,
`mcp_key_read_refused`) as hard stops.

## Policy

Operator policy under `$KRELLBOT_HOME` (allow paper-arm / deny live /
deny key export) lands in M22.2+. Until then, MCP still hard-refuses
live and keys. Never bypass a policy deny.

## Explicit non-goals

- **Never live-arm** (`mode` must stay `paper`; no live-named tools).
- **Never read or transmit exchange keys** (no keyring / secret / credential tools).
- No key write, hosted keys, CLI agent product surface, or Learn view.
- Do not present backtest or fixture results as market performance.
- Leave `PAPER_ONLY_RELEASE` True.

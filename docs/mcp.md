# MCP agent surface (local)

Krellbot exposes a **local** MCP tool adapter for external agents. Tools
bind to application facades under `$KRELLBOT_HOME` (loopback domain /
offline datasets). They never talk to exchange key stores and never
live-arm.

## Allowed verbs

| Tool | Purpose |
| --- | --- |
| `read` | Closed inventory: owned drafts, pack library rows, armed paper records |
| `draft` | Create or edit a strategy draft (`pack`, optional `parent_revision_id`) |
| `validate` | Lint a draft revision (`revision_id`) |
| `backtest` | Offline research via `dataset_csv` (or an injected fetch in tests) |
| `paper_arm` | Paper-arm a pack path or validated `revision_id` (`mode` must be `paper`) |

Python entry point: `krellbot.mcp.McpTools(home).call(tool, **params)`.

## Explicit non-goals

- **Never live-arm.** `mode=live` or any live-named tool returns
  `mcp_live_arm_refused`.
- **Never read or transmit exchange keys.** Key/secret/credential tool
  names return `mcp_key_read_refused` without touching the OS keyring.
- No MCP key write, no hosted keys, no CLI agent UX as the product
  surface (the web workstation remains the user surface).

Operator policy lives at `$KRELLBOT_HOME/user-policy.json`. Missing
file defaults: allow paper-arm, allow live at the policy layer (still
blocked by `PAPER_ONLY_RELEASE` / MCP), deny key export. A written
policy can deny paper-arm, live, or key export. MCP `paper_arm` and
`policy_check` honor it; `read` includes the policy snapshot. Hard MCP
refuses for live and key tool names still apply regardless — policy
can only further restrict.

## Cursor client

Install, loopback auth, allowed verbs, and non-goals for the Cursor
agent client: [agent-cursor.md](agent-cursor.md). Project skill path:
`.cursor/skills/krellbot-mcp/SKILL.md`.

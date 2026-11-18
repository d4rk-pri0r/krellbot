# Cursor agent guide (local MCP)

Use **Cursor** as the first shipped agent client for Krellbot’s local MCP
surface. The web workstation remains the operator product surface; this
guide is how a Cursor agent may **validate → backtest → paper-arm**
against `$KRELLBOT_HOME` without live arm or key access.

Companion skill (project path named for install):
[`.cursor/skills/krellbot-mcp/SKILL.md`](../.cursor/skills/krellbot-mcp/SKILL.md).
Surface contract: [mcp.md](mcp.md).

## Install

1. Install / run Krellbot on the same machine as Cursor
   ([getting-started.md](getting-started.md)). Data home defaults to
   `~/.krellbot` (`$KRELLBOT_HOME`).
2. Prefer working in a checkout of this repository so the project skill
   loads. Cursor picks up
   `.cursor/skills/krellbot-mcp/SKILL.md` from the workspace.
3. Optional: copy or symlink that skill into a personal Cursor skills
   directory if you are not opening the repo as a project.
4. Bind tools with an explicit home, never a remote key store:

```python
from pathlib import Path
from krellbot.mcp import McpTools

tools = McpTools(Path.home() / ".krellbot")  # or Path(os.environ["KRELLBOT_HOME"])
tools.list_tools()  # read, draft, validate, backtest, paper_arm
```

From a checkout with the project env:

```sh
KRELLBOT_HOME="${KRELLBOT_HOME:-$HOME/.krellbot}" uv run --no-sync python -c \
  'from pathlib import Path; from krellbot.mcp import McpTools; print(McpTools(Path("'"$KRELLBOT_HOME"'")).list_tools())'
```

There is no cloud MCP host and no exchange-credential channel. Agents
call the in-process adapter (or a future local wrapper of the same
allowlist) on the operator machine only.

## Auth to loopback

Krellbot’s trust perimeter is **loopback on this machine**:

- The workstation API binds `127.0.0.1` and expects Host / Origin /
  session / CSRF checks (see [threat-model.md](threat-model.md)).
- MCP tools do **not** replace that browser session. They bind
  `$KRELLBOT_HOME` in-process and never open a non-loopback control
  plane or ship keys to krellbot.dev.
- Do not paste bootstrap tokens, session cookies, or reconnect codes
  into chats, tickets, or remote agents.
- Tailscale Serve (if used) is an operator-owned loopback proxy; it is
  not an MCP auth shortcut and does not authorize live arm or key read.

If you need the UI, open `http://127.0.0.1:<port>/` locally after
`krellbot` / `krellbot ui --open`. Agents stay on the MCP allowlist
below rather than scraping authenticated browser cookies.

## Allowed verbs

| Tool | Purpose | Typical params |
| --- | --- | --- |
| `read` | Inventory: owned drafts, pack library rows, armed paper records | _(none)_ |
| `draft` | Create or edit a strategy draft | `pack`, optional `parent_revision_id` |
| `validate` | Lint a draft revision | `revision_id` |
| `backtest` | Offline research | `pack_path`, prefer `dataset_csv` (no live fetch / keys) |
| `paper_arm` | Paper-arm a pack or validated revision | `venue`, `mode="paper"`, `pack_path` **or** `revision_id`, optional `paper_balance` |

Happy path for an agent: **`validate` → `backtest` → `paper_arm`**.
Call `read` first when you need ids/paths. Prefer offline `dataset_csv`
for backtest so CI and agents stay fake-transport / offline.

Example paper-arm shape (never `mode=live`):

```python
tools.call(
    "paper_arm",
    pack_path="/path/to/pack.json",
    venue="kraken",
    mode="paper",
    paper_balance="1000",
)
```

Typed refusals return `ok=False` dicts (`mcp_live_arm_refused`,
`mcp_key_read_refused`, …) — treat them as hard stops, not retries with
broader permissions.

## Policy

Operator **policy** files under `$KRELLBOT_HOME` (allow paper-arm, deny
live, deny key export) are M22.2+. Until that loader ships, the MCP
boundary still hard-refuses live arm and any key/secret/credential tool
name. When policy is present, honor denials; do not work around them via
CLI, env, or keyring.

## Explicit non-goals

- **Never live-arm.** No `mode=live`, no live-named tools, no typed
  `LIVE` grant through MCP. Live stays workstation-owned.
- **Never read, export, or transmit exchange keys.** No keyring probes,
  no `KRELLBOT_*_KEY` / secret exfiltration, no credentials in prompts
  or tool args.
- No MCP key write, hosted keys, or CLI-as-product agent UX.
- No inventing a Learn view; no presenting backtest/fixture numbers as
  live market performance.
- `PAPER_ONLY_RELEASE` stays `True` for agents — only the owner flips
  release policy.

## Related

- [mcp.md](mcp.md) — verb table and refusal codes
- [paper.md](paper.md) — paper arm semantics
- [threat-model.md](threat-model.md) — loopback / keychain boundaries
- [market-position.md](market-position.md) — why local policy-bound MCP

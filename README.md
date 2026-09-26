# Krellbot

Open Crypto Automation, Simplified.

Lightweight. Easy to install in one line. Designed for the agentic AI era, with security baked in from the ground up. Open platform. Open source code.

We provide the intelligence. You keep 100% of your trades.

This repository is the engine. It is free. It runs on your computer. It does not hold your money, and it does not send your exchange key to krellbot.dev.

Strategy packs are a separate download. The pack format is open, so you can write your own.

Site: https://krellbot.dev
Docs: https://krellbot.dev/docs/
Security: [SECURITY.md](SECURITY.md)

## Install

```sh
# macOS / Linux
curl -fsSL https://krellbot.dev/api/install?os=mac | sh

# Windows (PowerShell)
irm https://krellbot.dev/api/install?os=win | iex
```

The site installer downloads a per-user, one-directory frozen release
(artifact + SHA-256 manifest pinned by the site), verifies the digest
**before** staging anything, drops the binary under
`~/.local/share/krellbot/versions/<version>/` (POSIX) or
`%LOCALAPPDATA%\Krellbot\versions\<version>\` (Windows), and creates a
`krellbot` launcher at `~/.local/bin/krellbot` (POSIX) or
`%LOCALAPPDATA%\Krellbot\bin\krellbot.cmd` (Windows). It then opens the
local dashboard in your default browser.

**Signing status (this release):** the downloaded artifact is verified
against an HTTPS-pinned SHA-256 manifest, but the artifact itself is
**not** code-signed and **not** notarized. macOS Gatekeeper and Windows
SmartScreen may show a first-run warning; the SHA-256 check before
extraction is the integrity guarantee today. Authenticode, notarization,
and signed publisher releases are a future hardening step.

## Update policy

Re-run the same install command. Each release is staged under
`~/.local/share/krellbot/versions/<version>/` (or the Windows
equivalent) and the launcher swaps only after a smoke check. The prior
launcher is kept at `~/.local/bin/krellbot.prior` until the new one
passes; rollback is manual (rename). The data home
(`$KRELLBOT_HOME`, default `~/.krellbot`) is **never** touched by
install or update.

## Uninstall

```
# POSIX
~/.local/bin/krellbot uninstall

# Windows
krellbot uninstall
```

Removes only the managed launcher and the staged version directory for
the version you ran with. `$KRELLBOT_HOME` (keys, paper state, journal,
receipts) is **retained** by default. To delete the data home too,
pass `--purge-data` to the uninstall flow inside the installer.

## PATH check

```sh
# POSIX
command -v krellbot
which krellbot
ls -l ~/.local/bin/krellbot

# Windows
Get-Command krellbot
Test-Path "$env:LOCALAPPDATA\Krellbot\bin\krellbot.cmd"
```

If `command -v krellbot` (or `Get-Command krellbot` on Windows) returns
nothing, add `~/.local/bin` to `PATH` (POSIX) or
`%LOCALAPPDATA%\Krellbot\bin` to your user PATH (Windows). The site
installer's README has the exact `PATH` line per shell.

## Where things live

| What | POSIX | Windows |
| --- | --- | --- |
| Data home (`$KRELLBOT_HOME`, default) | `~/.krellbot/` | `%USERPROFILE%\.krellbot\` |
| Frozen binary | `~/.local/share/krellbot/versions/<ver>/krellbot` | `%LOCALAPPDATA%\Krellbot\versions\<ver>\krellbot.exe` |
| Launcher | `~/.local/bin/krellbot` | `%LOCALAPPDATA%\Krellbot\bin\krellbot.cmd` |
| Prior launcher (after update) | `~/.local/bin/krellbot.prior` | `%LOCALAPPDATA%\Krellbot\bin\krellbot.prior.cmd` |

`$KRELLBOT_HOME` is independent of the install path and is the only
place keys, paper state, the journal, and receipts live.

## Commands

```
krellbot keys add <venue> --file <key-file>   # store a key in the OS keychain
krellbot backtest <pack.json> --venue kraken  # run a DSL pack over candle data, no orders
krellbot arm <pack.json> --venue kraken --mode paper
krellbot service install                      # schedule the hourly tick for this user
krellbot ui                                   # serve a loopback dashboard at 127.0.0.1
krellbot ui --open                            # same, plus open the URL in your default browser
krellbot ui --port 8765                       # serve on a fixed loopback port
krellbot doctor                               # check install readiness and warnings
krellbot doctor --json                        # machine-readable report
krellbot community install <id>               # pull a pack from the community index
krellbot telemetry enable                     # opt in to anonymous usage telemetry
```

The dashboard, telemetry shape, and community library are documented in
[docs/dashboard.md](docs/dashboard.md), [docs/telemetry.md](docs/telemetry.md),
and [docs/community.md](docs/community.md). The readiness summary that
`krellbot doctor` reports is documented in [docs/service.md](docs/service.md).

## Readiness

`krellbot doctor` reports two booleans that are the right thing for a
first-run checklist:

- `install_ready` is `True` when the runtime can serve the local UI:
  home permissions are `0o700`, the keychain backend is a real
  persistent one (not null/fail/fake), and a loopback bind probe
  succeeds. It does **not** require keys, a tick, or the scheduler
  unit.
- `trading_ready` is `True` only when `install_ready` is `True`,
  the journal has a tick in the last two hours, and at least one
  stored key had its permissions probed with `trade=True` AND
  `withdraw=False`. Without a permission probe, the key's permissions
  are unknown and `trading_ready` stays `False`.

The detailed fields and the existing warnings (which still drive the
exit code) are documented in [docs/service.md](docs/service.md).

## Live and the UI gate

- The dashboard is `127.0.0.1` only; it refuses non-loopback `Host`
  headers and rejects live-arm POSTs. Live arm remains a CLI-only path
  that requires typing `LIVE` exactly.
- The UI does not call any exchange, the catalog, or `krellbot.dev`
  at any time. The server reads only from disk under `$KRELLBOT_HOME`.
- See [docs/live.md](docs/live.md) for the live arm flow and
  [docs/dashboard.md](docs/dashboard.md) for the dashboard.

## Working on the engine

```
git clone https://github.com/d4rk-pri0r/krellbot
cd krellbot
uv run pytest -q
uv run krellbot list
```

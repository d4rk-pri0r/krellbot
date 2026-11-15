# Krellbot

Open Crypto Automation, Simplified.

Local-first crypto automation with security boundaries and open source code.

We provide the intelligence. You keep 100% of your trades.

This repository is the engine. It is free. It runs on your computer. It does not hold your money, and it does not send your exchange key to krellbot.dev.

Strategy packs are a separate download. The pack format is open, so you can write your own.

Site: https://krellbot.dev
Docs: https://krellbot.dev/docs/
Security: [SECURITY.md](SECURITY.md)

## Install

The site installer is the way to run Krellbot. No exchange account, API keys,
or paid pack is needed for paper. Minimal Linux images need CA certificates,
curl and unzip first.

```sh
# Linux
curl -fsSL https://krellbot.dev/api/install?os=linux | sh

# macOS
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
`%LOCALAPPDATA%\Krellbot\bin\krellbot.cmd` (Windows). Running `krellbot`
with no arguments (or `krellbot ui --open` / `krellbot workstation --open`)
starts the workstation on loopback and opens it in your default browser.
Then [arm your first paper strategy](#arm-your-first-paper-strategy).

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

Uninstall, PATH checks, Tailscale Serve setup and other operational
snippets live in [docs/cli.md](docs/cli.md). Uninstall removes only the
managed launcher and staged version directory; `$KRELLBOT_HOME` is
retained by default.

## Where things live

| What | POSIX | Windows |
| --- | --- | --- |
| Data home (`$KRELLBOT_HOME`, default) | `~/.krellbot/` | `%USERPROFILE%\.krellbot\` |
| Frozen binary | `~/.local/share/krellbot/versions/<ver>/krellbot` | `%LOCALAPPDATA%\Krellbot\versions\<ver>\krellbot.exe` |
| Launcher | `~/.local/bin/krellbot` | `%LOCALAPPDATA%\Krellbot\bin\krellbot.cmd` |
| Prior launcher (after update) | `~/.local/bin/krellbot.prior` | `%LOCALAPPDATA%\Krellbot\bin\krellbot.prior.cmd` |

`$KRELLBOT_HOME` is independent of the install path and is the only
place keys, paper state, the journal, and receipts live.

## Arm your first paper strategy

Start the workstation (the installer leaves a `krellbot` launcher that
opens it with no arguments; `krellbot ui --open` is the same command), then:

1. Open **Strategies**, choose a free starter example, then **Save** and
   **Validate**. The starter examples ship with the release.
2. In the paper-arm form, use venue `kraken` and starting paper balance `1000`,
   then click **Arm**. This is simulated cash, not an exchange deposit.
3. Open **Operations**: the deployment must say `paper` and `active`, and live
   trading must remain disabled. **Workstation** also shows the armed paper row.

A research run is optional before arming. If you want an offline demonstration,
[paper trading](docs/paper.md) documents the public repository pack/candle
fixtures; demonstration fixture results are not market performance.

## Private access from your Tailscale devices

For an always-on workstation, keep the backend on loopback and let
[Tailscale Serve](https://tailscale.com/kb/1312/serve) provide tailnet-only
HTTPS. The exact launcher flags and Serve command are in
[docs/cli.md](docs/cli.md#private-access-from-your-tailscale-devices).

## Advanced and diagnostic commands

You do not need the command line to install Krellbot or arm a paper strategy.
The `krellbot` command is plumbing: the launcher, the scheduler entry point and
diagnostics such as readiness checks. Those commands are documented in
[docs/cli.md](docs/cli.md).

## Live and the UI gate

- The workstation is `127.0.0.1` only; it refuses non-loopback `Host`
  headers and rejects live orders. Live arm remains a CLI-only path
  that requires typing `LIVE` exactly.
- Exchange keys are stored in the native OS keychain (see
  [docs/cli.md](docs/cli.md)). No exchange credentials go to `krellbot.dev`.
- See [docs/live.md](docs/live.md) for the live arm flow.

## Working on the engine

Building from source is for engine and UI development, separate from the
installed release. See [Build from source](docs/cli.md#build-from-source).

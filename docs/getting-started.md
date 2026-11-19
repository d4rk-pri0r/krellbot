# Getting started

The client is free. It runs on your computer. It does not hold your money.

## Start with paper (no exchange credentials)

[Install the free client](#install-the-free-client), start the local app
with `krellbot`, then
[start a free paper strategy](../README.md#arm-your-first-paper-strategy).
Building from source is only for working on the engine; see
[Working on the engine](../README.md#working-on-the-engine).

On a fresh install the workstation’s first-run path aims at a
**full-screen Krell wizard**: pick a free starter, start a paper run, and
see honest status — with almost no text and no cockpit chrome until setup
is done (M26; supersedes the M25 coach overlay; not a reading list).

Paper mode needs neither an exchange account nor a key or paid license. Skip
the exchange-key instructions below for paper.
Headless/keychain warnings in `doctor` are not a request to load credentials;
verify your paper deployment in Operations and `krellbot status`. Live trading
stays unavailable in this release.

## What an API key is

An API key is a password your exchange gives to a program. Krellbot uses it to ask Kraken what to do. The key stays in a file on your machine. krellbot.dev never receives it.

## Turn trade on. Turn withdraw off.

You need an exchange account before a pack can place a **live** order. You do
not need one to read these docs, install the client, or run **paper**.

Qualified live venues for this distribution cut are **Kraken** and
**Coinbase** (wave pair `BTC-USD`). Both stay behind the workstation live
grant and the paper-only release rail until the owner flips
`PAPER_ONLY_RELEASE`. Binance is paper-only — do not create a Binance key
expecting qualified live.

When you create a Kraken or Coinbase key:

- Trade permission on.
- Withdraw / transfer permission off.

## Install the free client

The site installer downloads a per-user, one-directory frozen release,
verifies its SHA-256 digest before staging anything, and writes the
launcher next to your shell's `PATH`.

Choose the endpoint for your OS; `os=mac` is not a Linux installer:

```sh
# Linux
curl -fsSL https://krellbot.dev/api/install?os=linux | sh
# macOS
curl -fsSL https://krellbot.dev/api/install?os=mac | sh
```

On Windows (PowerShell):

```powershell
irm https://krellbot.dev/api/install?os=win | iex
```

Running `krellbot` with no arguments starts the workstation on loopback
and opens it in your default browser. `krellbot ui --open` and
`krellbot workstation --open` do the same.

Credential-source precedence when the engine later loads a key is a complete
`KRELLBOT_<VEN>_KEY` and `KRELLBOT_<VEN>_SECRET` environment pair, then
the keyring, then an explicitly configured `KRELLBOT_<VEN>_KEYFILE` if no
keyring pair exists. A partial environment pair is an error.

### What gets written

| What | POSIX | Windows |
| --- | --- | --- |
| Launcher | `~/.local/bin/krellbot` | `%LOCALAPPDATA%\Krellbot\bin\krellbot.cmd` |
| Frozen binary | `~/.local/share/krellbot/versions/<ver>/krellbot` | `%LOCALAPPDATA%\Krellbot\versions\<ver>\krellbot.exe` |
| Data home (default `$KRELLBOT_HOME`) | `~/.krellbot/` | `%USERPROFILE%\.krellbot\` |

The installer does not touch the data home. Your keys, paper state,
journal, and receipts survive install, update, and uninstall.

### Code-signing / notarization status

The downloaded artifact is verified against an HTTPS-pinned SHA-256
manifest **before** extraction. This cut remains an **unsigned
prerelease** until a secrets-gated signed release is published:

- macOS Gatekeeper may show a first-run warning.
- Windows SmartScreen may show a first-run warning.
- Linux stays checksum-pinned (no platform code-signature product).

Operator signing secrets, Gatekeeper / SmartScreen expectations, and
Linux policy: [docs/signing.md](signing.md).

### PATH check

If the launcher is not on your `PATH`:

- POSIX: add `~/.local/bin` to your shell's `PATH`. The installer's
  README prints the exact line for `bash`, `zsh`, and `fish`.
- Windows: add `%LOCALAPPDATA%\Krellbot\bin` to your user PATH
  (`Settings → System → About → Advanced system settings →
  Environment Variables`).

### Uninstall

There is no top-level engine CLI product command named
`krellbot uninstall`. Two separate removals exist (same honesty as
[docs/cli.md](cli.md#uninstall)):

**Release install** (site installer / managed launcher and staged
version directory): use the **installer's** uninstall flow. That flow
removes only the managed launcher and the staged version directory for
the version you ran with. `$KRELLBOT_HOME` (keys, paper state, journal,
receipts) is **retained** by default. To delete the data home too,
pass `--purge-data` to the uninstall flow inside the installer.

**Scheduler unit** (hourly tick only — not the release install):

```sh
krellbot service uninstall
```

Running `krellbot uninstall` on the engine CLI prints this pointer and
exits nonzero; it does not remove files. Details:
[docs/cli.md](cli.md#uninstall) and [docs/service.md](service.md).

## Is the install ready?

```sh
krellbot doctor --json
```

`install_ready` is `True` when the runtime can serve the local UI:
home permissions are `0o700`, the keychain backend is a real persistent
one, and a loopback bind probe succeeds. It does not require keys, a
tick, or the scheduler unit.

`trading_ready` is the stricter gate: it also needs a fresh tick in
the journal and at least one stored key whose permissions were probed
with `trade=True` AND `withdraw=False`. Unknown permissions are
fail-closed; a present key with no probe never satisfies
`trading_ready`.

A fresh install is `install_ready=True` and `trading_ready=False`
until you add a key and the scheduler runs a tick. See
[docs/service.md](service.md) for the full field list.

## What a pack is

A pack is a JSON file. The format is open. You can write your own and put it in `~/.krellbot/packs/`. The client reads the file. It does not run code inside it.

The packs we maintain are a separate download. Those names stay off the public page. $39 a month downloads them.

```
krellbot setup <license-key>
```

A pack you write does not need that key.

To share an unpaid community pack (separate from paid catalogue SKUs), see
the authoring checklist in
[community.md](community.md#authoring-checklist).

## What a window is

A window is the dates the chart covers. A return without those dates is not a result you can read.

## What a drawdown is

A drawdown is how far the result fell from a high point before it recovered. A high return with a large drawdown is still a large drawdown.

## What it will not do yet

The client will not place an order until that path exists. With no packs, it tells you none are installed. With a pack, it can show that pack's past history. That history is not a Krellbot fill.

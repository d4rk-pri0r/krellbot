# Getting started

The client is free. It runs on your computer. It does not hold your money.

## What an API key is

An API key is a password your exchange gives to a program. Krellbot uses it to ask Kraken what to do. The key stays in a file on your machine. krellbot.dev never receives it.

## Turn trade on. Turn withdraw off.

You need a Kraken account before a pack can place an order. You do not need one to read these docs or to install the client.

When you create the Kraken key:

- Trade permission on.
- Withdraw permission off.

Coinbase is not ready. Do not make a Coinbase key for this client yet.

## Install the free client

The site installer downloads a per-user, one-directory frozen release,
verifies its SHA-256 digest before staging anything, and writes the
launcher next to your shell's `PATH`.

On macOS or Linux:

```sh
curl -fsSL https://krellbot.dev/api/install?os=mac | sh
# or
curl -fsSL https://krellbot.dev/api/install?os=linux | sh
```

On Windows (PowerShell):

```powershell
irm https://krellbot.dev/api/install?os=win | iex
```

The first install also opens the local dashboard in your default
browser. Subsequent runs:

```sh
krellbot ui            # print the gated URL; do not open a browser
krellbot ui --open     # print the URL and hand it to the default browser
krellbot ui --port N   # bind a fixed loopback port instead of a random one
```

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
manifest **before** extraction. The artifact itself is **not**
code-signed and **not** notarized in this release:

- macOS Gatekeeper may show a first-run warning.
- Windows SmartScreen may show a first-run warning.
- Linux has no `gpg`/`minisign` publisher signature today.

Code signing, notarization, and signed publisher releases are a future
hardening step; the SHA-256 check is the integrity guarantee today.

### PATH check

If the launcher is not on your `PATH`:

- POSIX: add `~/.local/bin` to your shell's `PATH`. The installer's
  README prints the exact line for `bash`, `zsh`, and `fish`.
- Windows: add `%LOCALAPPDATA%\Krellbot\bin` to your user PATH
  (`Settings → System → About → Advanced system settings →
  Environment Variables`).

### Uninstall

```sh
# POSIX
~/.local/bin/krellbot uninstall

# Windows
krellbot uninstall
```

Removes only the managed launcher and the staged version directory
for the version you ran with. The data home is retained; pass
`--purge-data` to remove it too.

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

## What a window is

A window is the dates the chart covers. A return without those dates is not a result you can read.

## What a drawdown is

A drawdown is how far the result fell from a high point before it recovered. A high return with a large drawdown is still a large drawdown.

## What it will not do yet

The client will not place an order until that path exists. With no packs, it tells you none are installed. With a pack, it can show that pack's past history. That history is not a Krellbot fill.

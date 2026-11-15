# Krellbot CLI

The web workstation is the way to use Krellbot. Install it with the site
installer in the [README](../README.md#install), then arm strategies, run
research and watch paper deployments in the browser.

The `krellbot` command is plumbing: the launcher, the scheduler entry point
and diagnostics. Running `krellbot` with no arguments starts the workstation.
New user features land in the web app, not here.

## Advanced and diagnostic commands

These commands are for diagnostics, automation and advanced setups. You do not
need any of them to install Krellbot or to arm a paper strategy.

```
krellbot keys add <venue> --file <key-file>   # store a key in the OS keychain
krellbot backtest <pack.json> --venue kraken  # run a DSL pack over candle data, no orders
krellbot arm <pack.json> --venue kraken --mode paper
krellbot status                               # show armed deployments
krellbot service install                      # schedule the hourly tick for this user
krellbot doctor                               # check install readiness and warnings
krellbot doctor --json                        # machine-readable report
krellbot community install <id>               # pull a pack from the community index
krellbot telemetry enable                     # opt in to anonymous usage telemetry
```

Running `krellbot` with an unrecognized command prints the full usage line.

The telemetry shape and community library are documented in
[telemetry.md](telemetry.md) and [community.md](community.md). The readiness
summary that `krellbot doctor` reports is documented in [service.md](service.md).
The live arm flow is in [live.md](live.md).

### Check a paper deployment from a terminal

After arming a paper strategy in the workstation, `krellbot status` shows the
same armed deployment from a terminal. The workstation's **Operations** and
**Workstation** views are the primary check.

### Readiness

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
exit code) are documented in [service.md](service.md).

On a headless machine without a persistent OS keychain, `krellbot doctor` can
exit nonzero with keychain, missing-key, scheduler or stale-tick warnings and
`install_ready=false` / `trading_ready=false`. These diagnostics do not require
you to add keys for paper use. Verify paper readiness with the armed row in the
workstation; do not load credentials for this path.

### Uninstall

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

### PATH check

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

### Private access from your Tailscale devices

For an always-on workstation, keep the backend on loopback and let
[Tailscale Serve](https://tailscale.com/kb/1312/serve) provide tailnet-only HTTPS:

```sh
KRELLBOT_ENABLE_LIVE=0 krellbot workstation --port 8765 \
  --tailscale-origin https://your-machine.your-tailnet.ts.net \
  --tailscale-user you@example.com
tailscale serve --bg http://127.0.0.1:8765
```

Use your actual machine's HTTPS origin and the exact login name from Tailscale.
Open that URL on a device signed into that account, then click **Log in with
Tailscale**. Each browser gets its own session; no separate Krellbot password is
stored or shared. Reopen the URL to log in again after a service restart.

Both options are required together. Only the configured user, origin and
loopback proxy are accepted. Tailscale Serve removes spoofed identity headers;
never expose the backend directly or use Funnel. Tagged devices have no user
identity and cannot use this owner-login flow. Existing session, CSRF and
live-order refusal checks still apply. Without these options, the workstation
retains its original loopback-only bootstrap behavior.

## Build from source

### Build and run the workstation from source

The source checkout includes the React workstation (Studio, Library, Research,
Operations and paper deployment). This route is for engine and UI development,
separate from the installed release. It requires Git, [uv](https://docs.astral.sh/uv/getting-started/installation/),
Python 3.13 (uv can download it), and Node.js 24 with npm. Use the CI-tested
Python version explicitly: an unqualified `uv sync` on a machine without
Python can select a newer interpreter whose locked dependencies lack wheels.

On Ubuntu 24.04, install ordinary OS utilities first (as an administrator):

```sh
sudo apt-get update
sudo apt-get install -y ca-certificates curl git xz-utils
```

Then, as your normal user, install missing development prerequisites. If you
already have uv and Node.js 24 on PATH, skip this block. These are upstream
installers, not Krellbot binaries; [nvm](https://github.com/nvm-sh/nvm) installs
Node and npm per user:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
. "$NVM_DIR/nvm.sh"
nvm install 24
uv --version
node --version
npm --version
```

Build the frontend before starting the service. Run these commands in the
same shell (or reload your uv/nvm PATH in a new shell):

```sh
git clone https://github.com/d4rk-pri0r/krellbot
cd krellbot
uv sync --frozen --group dev --python 3.13
npm --prefix frontend ci --include=dev
npm --prefix frontend run build
KRELLBOT_ENABLE_LIVE=0 uv run --no-sync krellbot workstation --port 8765
```

Open `http://127.0.0.1:8765/`. Start in Strategies, pick a free starter example,
Save, then Validate. Research accepts a local candle CSV; paper mode needs no
exchange keys. New research jobs retain their status and completed results under
`$KRELLBOT_HOME/research-jobs/`. After a restart, unfinished jobs appear as
`interrupted`; they never resume automatically. Submit a new run to retry.

Run the tests:

```sh
KRELLBOT_HOME=$(mktemp -d) uv run --no-sync pytest -q
```

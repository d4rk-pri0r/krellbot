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
summary that `krellbot doctor` reports is documented in
[service.md](service.md). The live arm flow is in [live.md](live.md).

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

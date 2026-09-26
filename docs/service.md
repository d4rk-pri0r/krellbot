# Scheduling the tick

`krellbot tick` is a one-shot that runs every hour on the minute. The
schedule itself is owned by the operating system: macOS launchd, Linux
systemd user timers, or the Windows task scheduler. `krellbot service` and
`krellbot doctor` install and inspect the schedule without ever talking to
a live venue.

The renderers in `krellbot.service.render` are pure functions that take the
absolute path of the `krellbot` executable and the home directory. They do
not read `Path.home()` and they do not write files. Callers decide where to
write; the test suite writes only under an injected root.

## Renderers

Three platforms, one body shape:

- **macOS** — a launchd plist at
  `<home>/Library/LaunchAgents/dev.krellbot.tick.plist`. The label is
  `dev.krellbot.tick`. `StartCalendarInterval` has only `Minute = 1`; there
  is no `Hour` key so the host fires every hour on the minute. The
  `ProgramArguments` array is exactly `[executable, "tick"]`. `RunAtLoad`
  is false; the logs land at `<home>/logs/tick.out.log` and
  `<home>/logs/tick.err.log`.
- **Linux** — a pair of user units, `krellbot-tick.timer` and
  `krellbot-tick.service`, under `<home>/.config/systemd/user/`. The timer
  fires on `OnCalendar=*-*-* *:01:00` with `Persistent=true` so a missed
  tick on a sleeping laptop still runs when it wakes. The service has no
  `User=` line because user units run as the caller.
- **Windows** — a task XML with
  `<StartWhenAvailable>true</StartWhenAvailable>` and a `CalendarTrigger`
  that repeats every hour (`PT1H`) from minute 1. The `Exec` block carries
  the executable as `<Command>` and `tick` as the single `<Arguments>`
  entry. The macOS and Linux units also set `KRELLBOT_HOME` so the tick
  writes to the same home the logs use.

## Installing

```
krellbot service install --dry-run
```

Prints the unit body for the current platform and writes nothing. Use this
to inspect what will land on disk before committing.

```
krellbot service install
```

Writes the unit under your real home: `~/Library/LaunchAgents` on macOS,
`~/.config/systemd/user` on Linux, `~/Tasks` on Windows. `--root PATH`
writes there instead, which is how tests avoid touching the real home.
`--dry-run` still writes nothing.

```
krellbot service uninstall
```

Deletes only the unit files `install` wrote: the plist, both Linux units,
or the Windows task XML. Files outside the named set are never touched.

## Scheduler install vs. release install

There are two installs in this release and they do different things:

- **Release install** (the site installer / frozen one-dir binary) places
  the launcher at `~/.local/bin/krellbot` (POSIX) or
  `%LOCALAPPDATA%\Krellbot\bin\krellbot.cmd` (Windows), and stages the
  binary under `~/.local/share/krellbot/versions/<ver>/` or
  `%LOCALAPPDATA%\Krellbot\versions\<ver>\`. The data home stays at
  `$KRELLBOT_HOME` (default `~/.krellbot`).
- **`krellbot service install`** writes only the OS scheduler unit. It
  does not move the launcher, change `$KRELLBOT_HOME`, or download
  anything. Run it after the release install and only when you want the
  hourly tick.

`krellbot doctor --json` reports `service_installed` (the scheduler unit)
and `install_ready` (whether the local UI can run). A fresh release
install is `install_ready=True` even before
`krellbot service install` has been run — the scheduler is part of
the live arm step, not the install.

## Inspecting health: `krellbot doctor`

`krellbot doctor` runs every health check with no network unless a clock
source is injected. By default the CLI injects the public Kraken Time
endpoint (`https://api.kraken.com/0/public/Time`, reading `result.unixtime`)
so skew is checked against a real wall clock; tests pass a fake source and
prove zero socket calls.

```sh
krellbot doctor           # text, exit 0 when ok
krellbot doctor --json    # machine-readable, same keys, same exit code
```

The checks, each a row in text and a field in JSON:

| Field | Meaning |
| --- | --- |
| `home_mode_ok` | True if `KRELLBOT_HOME` is `0o700` on POSIX. `null` on Windows (skipped, not failed). |
| `keychain_backend` | The OS keychain backend name. A `null`, `fail`, or `fake` backend is a warning. |
| `keys` | Per venue: present or absent. With an injected permission probe, also `trade` and `withdraw`. Without a probe those keys are omitted — the key's permissions are unknown. |
| `service_installed` | True if the unit file exists for this platform under the write root. |
| `last_tick_age_s` | Seconds since the last `kind=tick` journal record. `null` if no record. |
| `last_tick_stale` | True when `last_tick_age_s` is missing or `>= 2 * 3600`. |
| `clock_skew_s` | `now - unixtime` from the injected source. `null` if no source. |
| `clock_warn` | A warning string when `abs(skew) > 5`. `"clock not checked"` when no source. |
| `license_status` | Status from `catalog/license-cache.json`, or `missing`. |
| `armed` | Per armed pack: `venue`, `pair`, `cap`, `ok`, `warning`. Unknown pair warns `minimums not loaded`. |
| `warnings` | Aggregated human-readable warnings. `ok` is `true` iff this list is empty. |
| `install_ready` | **New.** `True` iff `home_mode_ok is not False` AND the keychain backend is a real persistent one AND a `127.0.0.1:0` bind probe succeeds. Does not require keys, a tick, or the scheduler unit. |
| `trading_ready` | **New.** `True` only when `install_ready` is `True`, the journal has a tick in the last 2 hours, and at least one stored key had its permissions probed with `trade=True` AND `withdraw=False`. Unknown permissions are fail-closed: a present key with no probe does **not** satisfy this gate. |

JSON keys are stable. `ok` is true only when `warnings` is empty. Exit
code is 0 when `ok`, 1 otherwise. The `install_ready` / `trading_ready`
booleans live beside `ok`; they do not change `ok` and they do not
suppress the existing warnings.

### When does `install_ready` go true?

Right after the release install, on a host that:

- has its data home mode at `0o700` (POSIX) or skips the check
  (Windows),
- has a real persistent keychain backend (macOS Keychain, Windows
  Credential Manager, Linux Secret Service — not null/fail/fake), and
- can bind a TCP socket to `127.0.0.1` on a free port.

It does **not** require a stored exchange key, a journal tick, or the
OS scheduler unit. A brand-new install with no packs and no keys is
still `install_ready=True`.

### When does `trading_ready` go true?

Only after all three:

- `install_ready` is `True`.
- `last_tick_stale` is `False` — a tick ran in the last two hours. This
  is the journal record left by `krellbot tick` when the scheduler
  fires it.
- At least one stored key has a permission probe that returned
  `can_trade=True` and `can_withdraw=False`. If no probe ran, the
  fields `trade` and `withdraw` are not present in the JSON, and
  `trading_ready` stays `False`.

`trading_ready` is the right thing to gate an automated live arm on.
The dashboard does not bypass it: live-arm POSTs return `403` before
any state change.

## What the doctor never does

- Opens a URL without an injected time source. The CLI is the only caller
  that injects one, and it points at the public Kraken endpoint.
- Invents exchange minimums. When a pack's pair is not in
  `paper.default_rules`, the warning is `minimums not loaded` — never a
  fabricated `0.0001`.
- Prints a secret. The output never references the API key, the API
  secret, or the license key.
- Touches any address other than `127.0.0.1`. The bind probe is
  strictly loopback; no venue, no catalog, no `krellbot.dev` is ever
  contacted during `krellbot doctor`.

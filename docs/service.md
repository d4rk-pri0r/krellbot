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

## Inspecting health: `krellbot doctor`

`krellbot doctor` runs every health check with no network unless a clock
source is injected. By default the CLI injects the public Kraken Time
endpoint (`https://api.kraken.com/0/public/Time`, reading `result.unixtime`)
so skew is checked against a real wall clock; tests pass a fake source and
prove zero socket calls.

```
krellbot doctor           # text, exit 0 when ok
krellbot doctor --json    # machine-readable, same keys, same exit code
```

The checks, each a row in text and a field in JSON:

| Field | Meaning |
| --- | --- |
| `home_mode_ok` | True if `KRELLBOT_HOME` is `0o700` on POSIX. `null` on Windows (skipped, not failed). |
| `keychain_backend` | The OS keychain backend name. A `null`, `fail`, or `fake` backend is a warning. |
| `keys` | Per venue: present or absent. With an injected permission probe, also `trade` and `withdraw`. |
| `service_installed` | True if the unit file exists for this platform under the write root. |
| `last_tick_age_s` | Seconds since the last `kind=tick` journal record. `null` if no record. |
| `last_tick_stale` | True when `last_tick_age_s` is missing or `>= 2 * 3600`. |
| `clock_skew_s` | `now - unixtime` from the injected source. `null` if no source. |
| `clock_warn` | A warning string when `abs(skew) > 5`. `"clock not checked"` when no source. |
| `license_status` | Status from `catalog/license-cache.json`, or `missing`. |
| `armed` | Per armed pack: `venue`, `pair`, `cap`, `ok`, `warning`. Unknown pair warns `minimums not loaded`. |
| `warnings` | Aggregated human-readable warnings. `ok` is `true` iff this list is empty. |

JSON keys are stable. `ok` is true only when `warnings` is empty. Exit
code is 0 when `ok`, 1 otherwise.

## What the doctor never does

- Opens a URL without an injected time source. The CLI is the only caller
  that injects one, and it points at the public Kraken endpoint.
- Invents exchange minimums. When a pack's pair is not in
  `paper.default_rules`, the warning is `minimums not loaded` — never a
  fabricated `0.0001`.
- Prints a secret. The output never references the API key, the API
  secret, or the license key.

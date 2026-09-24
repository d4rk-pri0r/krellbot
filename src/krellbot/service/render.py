"""Render scheduler units for `krellbot tick`.

The render functions are pure: each takes the absolute executable path and
the home directory, and returns bytes. They never call `Path.home()` and
never write files. Callers (the `service install` command, or a test) decide
when and where to write.

The bodies match the contract in `.omo/briefs/phase6-implement.md`:

- macOS launchd plist with label `dev.krellbot.tick`. `StartCalendarInterval`
  fires at minute 1 of every hour (no `Hour` key). `ProgramArguments` is
  exactly `[executable, "tick"]`. `RunAtLoad` is false. Logs go to
  `<home>/logs/tick.{out,err}.log`.
- Linux systemd user units `krellbot-tick.service` and `krellbot-tick.timer`.
  The timer has `OnCalendar=*-*-* *:01:00` and `Persistent=true`. The
  service `ExecStart` is the executable plus `tick`. No `User=` line — this
  is a user unit.
- Windows task XML with `<StartWhenAvailable>true</StartWhenAvailable>` and a
  calendar trigger at minute 1 of every hour. The command is the executable
  and the argument is `tick`.
"""

from __future__ import annotations

from pathlib import Path


def render_launchd(executable: str, home: Path) -> bytes:
    """Render the macOS launchd plist body for label `dev.krellbot.tick`."""
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        "<dict>\n"
        "    <key>Label</key>\n"
        "    <string>dev.krellbot.tick</string>\n"
        "    <key>ProgramArguments</key>\n"
        "    <array>\n"
        f"        <string>{executable}</string>\n"
        "        <string>tick</string>\n"
        "    </array>\n"
        "    <key>StartCalendarInterval</key>\n"
        "    <dict>\n"
        "        <key>Minute</key>\n"
        "        <integer>1</integer>\n"
        "    </dict>\n"
        f"    <key>StandardOutPath</key>\n"
        f"    <string>{home}/logs/tick.out.log</string>\n"
        f"    <key>StandardErrorPath</key>\n"
        f"    <string>{home}/logs/tick.err.log</string>\n"
        "    <key>RunAtLoad</key>\n"
        "    <false/>\n"
        "    <key>EnvironmentVariables</key>\n"
        "    <dict>\n"
        "        <key>KRELLBOT_HOME</key>\n"
        f"        <string>{home}</string>\n"
        "    </dict>\n"
        "</dict>\n"
        "</plist>\n"
    )
    return body.encode("utf-8")


def render_systemd(executable: str, home: Path) -> dict[str, bytes]:
    """Render the Linux systemd user units. Returns {filename: bytes}.

    The pair is `krellbot-tick.timer` and `krellbot-tick.service`. The timer
    is persistent, firing at minute 1 of every hour. The service has no
    `User=` line because user units run as the caller.
    """
    timer = (
        "[Unit]\n"
        "Description=krellbot tick timer\n"
        "\n"
        "[Timer]\n"
        "OnCalendar=*-*-* *:01:00\n"
        "Persistent=true\n"
        "Unit=krellbot-tick.service\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    service = (
        "[Unit]\n"
        "Description=krellbot tick\n\n"
        "[Service]\n"
        f"ExecStart={executable} tick\n"
        f"Environment=KRELLBOT_HOME={home}\n"
    )
    return {
        "krellbot-tick.timer": timer.encode("utf-8"),
        "krellbot-tick.service": service.encode("utf-8"),
    }


def render_windows(executable: str, home: Path) -> bytes:
    """Render the Windows task XML for the tick schedule.

    `<StartWhenAvailable>true</StartWhenAvailable>` lets the task catch up
    after the laptop wakes from sleep. The trigger fires at minute 1 of every
    hour.
    """
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Task version="1.2" '
        'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        "  <RegistrationInfo>\n"
        "    <Author>krellbot</Author>\n"
        "    <URI>\\krellbot\\tick</URI>\n"
        "  </RegistrationInfo>\n"
        "  <Triggers>\n"
        "    <CalendarTrigger>\n"
        "      <StartBoundary>2026-01-01T00:01:00</StartBoundary>\n"
        "      <Repetition>\n"
        "        <Interval>PT1H</Interval>\n"
        "      </Repetition>\n"
        "    </CalendarTrigger>\n"
        "  </Triggers>\n"
        "  <Settings>\n"
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
        "    <AllowHardTerminate>true</AllowHardTerminate>\n"
        "    <StartWhenAvailable>true</StartWhenAvailable>\n"
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
        "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
        "    <Enabled>true</Enabled>\n"
        "    <Hidden>false</Hidden>\n"
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
        "    <WakeToRun>false</WakeToRun>\n"
        "    <ExecutionTimeLimit>PT10M</ExecutionTimeLimit>\n"
        "    <Priority>7</Priority>\n"
        "  </Settings>\n"
        '  <Actions Context="Author">\n'
        "    <Exec>\n"
        f"      <Command>{executable}</Command>\n"
        "      <Arguments>tick</Arguments>\n"
        "    </Exec>\n"
        "  </Actions>\n"
        "</Task>\n"
    )
    return body.encode("utf-8")

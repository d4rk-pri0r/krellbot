"""Service render tests.

The scheduler unit files are pure templates: render functions take the
absolute executable path and the home directory and return bytes. They
do not call Path.home() and do not write files.

`service install --dry-run` prints the unit for sys.platform and writes
nothing. `service install` without --dry-run writes under an injected
write_root only; tests never call that path against the real home.
"""

from __future__ import annotations

import sys


def test_launchd_fires_at_minute_1_and_passes_tick(home):
    """macOS plist: StartCalendarInterval Minute=1, ProgramArguments=[exec, "tick"],
    log paths, RunAtLoad false, label dev.krellbot.tick. No Hour key.
    """
    from krellbot.service.render import render_launchd

    body = render_launchd("/usr/local/bin/krellbot", home).decode("utf-8")

    assert "<key>Label</key>" in body
    assert "<string>dev.krellbot.tick</string>" in body

    assert "<key>ProgramArguments</key>" in body
    assert "<string>/usr/local/bin/krellbot</string>" in body
    assert "<string>tick</string>" in body
    pa_block = body.split("<key>ProgramArguments</key>", 1)[1].split("</array>", 1)[0]
    assert pa_block.count("<string>") == 2

    assert "<key>StartCalendarInterval</key>" in body
    assert "<key>Minute</key>" in body
    assert "<integer>1</integer>" in body
    assert "<key>Hour</key>" not in body

    assert "<key>StandardOutPath</key>" in body
    assert f"<string>{home}/logs/tick.out.log</string>" in body
    assert "<key>StandardErrorPath</key>" in body
    assert f"<string>{home}/logs/tick.err.log</string>" in body

    assert "<key>RunAtLoad</key>" in body
    assert "<false/>" in body
    assert "<key>KRELLBOT_HOME</key>" in body
    assert f"<string>{home}</string>" in body


def test_systemd_timer_is_persistent(home):
    """Linux user units: timer OnCalendar=*-*-* *:01:00, Persistent=true;
    service ExecStart = executable plus tick; no User= line.
    """
    from krellbot.service.render import render_systemd

    units = render_systemd("/usr/local/bin/krellbot", home)
    assert "krellbot-tick.timer" in units
    assert "krellbot-tick.service" in units

    timer = units["krellbot-tick.timer"].decode("utf-8")
    assert "OnCalendar=*-*-* *:01:00" in timer
    assert "Persistent=true" in timer

    service = units["krellbot-tick.service"].decode("utf-8")
    assert "ExecStart=/usr/local/bin/krellbot tick" in service
    # No User= line on a user unit.
    assert "User=" not in service
    assert f"Environment=KRELLBOT_HOME={home}" in service


def test_windows_xml_starts_when_available(home):
    """Windows task XML: <StartWhenAvailable>true</StartWhenAvailable>, calendar
    trigger at minute 1 of every hour, executable is the command, tick is the
    single argument.
    """
    from krellbot.service.render import render_windows

    body = render_windows(r"C:\Users\me\bin\krellbot.exe", home).decode("utf-8")

    assert "<StartWhenAvailable>true</StartWhenAvailable>" in body
    # Calendar trigger at minute 1.
    assert "<CalendarTrigger>" in body
    # The command and the argument.
    assert "<Command>C:\\Users\\me\\bin\\krellbot.exe</Command>" in body
    assert "<Arguments>tick</Arguments>" in body
    assert "<Interval>PT1H</Interval>" in body
    assert "ScheduleByDay" not in body


def test_dry_run_prints_unit_and_writes_nothing(home, capsys, monkeypatch):
    """`service install --dry-run` prints the unit for sys.platform and writes
    nothing under the injected write_root.
    """
    from krellbot.service import install

    write_root = home / "write-root"
    rc = install(
        executable="/usr/local/bin/krellbot",
        home=home,
        write_root=write_root,
        dry_run=True,
    )
    captured = capsys.readouterr()
    assert rc == 0
    # Nothing was written under the write root.
    assert not write_root.exists() or not any(write_root.rglob("*"))
    # The unit body was printed (depending on sys.platform).
    if sys.platform == "darwin":
        assert "Label" in captured.out
        assert "dev.krellbot.tick" in captured.out
    elif sys.platform.startswith("linux"):
        assert "OnCalendar" in captured.out
        assert "ExecStart" in captured.out
    elif sys.platform == "win32":
        assert "<StartWhenAvailable>true</StartWhenAvailable>" in captured.out

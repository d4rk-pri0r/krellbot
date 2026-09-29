"""M1R-FD: Windows scheduled tick must carry KRELLBOT_HOME.

The Task Scheduler XML schema (1.2) has no per-task environment-variable
element, so a plain ``<Command>{executable}</Command><Arguments>tick</Arguments>``
inherits the user's environment. The tick then falls back to ``~/.krellbot``
while the operator installed against a different ``KRELLBOT_HOME``, and
the tick silently reads and writes the wrong home. The launchd plist and
the systemd service already set ``KRELLBOT_HOME``; the Windows task XML
must do the same.

The renderer wraps the executable in ``cmd.exe /d /c`` so the environment
variable is set for exactly the child process:

::

    <Command>%SystemRoot%\\System32\\cmd.exe</Command>
    <Arguments>/d /c set "KRELLBOT_HOME=<home>" &amp;&amp; "<executable>" tick</Arguments>

with a ``<WorkingDirectory>`` set to ``<home>`` so relative paths resolve
there too. ``home`` and ``executable`` are XML-escaped so ``&``, ``<`` and
``>`` in a path cannot break the XML, and any cmd-quoting / cmd-metacharacter
in either (``"``, ``%``, ``^``, ``\\n``, ``\\r``) is refused with ``ValueError``
because it cannot be quoted safely for cmd.

The renderer is pure: it takes strings and a ``Path`` and returns bytes.
The install path is exercised through the macOS-runnable twin below so
the NS15 Windows test, which only runs on Windows CI, has a local guard.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
NS = {"t": TASK_NS}


def _find_exec(body: bytes):
    """Parse the task XML and return the <Exec> element.

    <Exec> is nested inside <Actions>, which is a direct child of <Task>,
    so we walk the tree explicitly instead of using a deep ``.//`` search.
    The Task XML declares the namespace as the default (``xmlns=...``) on
    the root, so every element we need to address lives in that namespace.
    """
    root = ET.fromstring(body)
    actions = root.find("t:Actions", NS)
    assert actions is not None, "<Actions> missing from rendered task XML"
    exec_el = actions.find("t:Exec", NS)
    assert exec_el is not None, "<Exec> missing from rendered task XML"
    return exec_el


EXE_GOOD = r"C:\Program Files\krellbot\krellbot.exe"
HOME_GOOD = Path(r"C:\Users\me\kb home")


# ---------------------------------------------------------------------------
# Pure renderer — wraps the tick in cmd.exe so KRELLBOT_HOME is set for the
# child only. Task XML has no environment block; this is the only way to
# carry the home into the scheduled process.
# ---------------------------------------------------------------------------


def test_windows_task_sets_krellbot_home_for_the_child():
    """render_windows wraps the tick in cmd.exe and sets KRELLBOT_HOME for
    the scheduled child only.
    """
    from krellbot.service.render import render_windows

    body = render_windows(EXE_GOOD, HOME_GOOD)
    exec_el = _find_exec(body)

    command = exec_el.findtext("t:Command", namespaces=NS)
    arguments = exec_el.findtext("t:Arguments", namespaces=NS)
    working_directory = exec_el.findtext("t:WorkingDirectory", namespaces=NS)

    assert command == r"%SystemRoot%\System32\cmd.exe"
    assert arguments == (
        r'/d /c set "KRELLBOT_HOME=C:\Users\me\kb home" && '
        r'"C:\Program Files\krellbot\krellbot.exe" tick'
    )
    assert working_directory == r"C:\Users\me\kb home"


def test_windows_task_escapes_xml_metacharacters():
    """``&``, ``<`` and ``>`` in a path are XML-escaped, so the rendered
    document parses as valid XML and the parsed element text round-trips
    back to the original path.
    """
    from krellbot.service.render import render_windows

    home = Path(r"C:\a&b<c>")
    body = render_windows(EXE_GOOD, home)

    # Parses as valid XML.
    exec_el = _find_exec(body)
    arguments = exec_el.findtext("t:Arguments", namespaces=NS)
    working_directory = exec_el.findtext("t:WorkingDirectory", namespaces=NS)

    assert "KRELLBOT_HOME=C:\\a&b<c>" in arguments
    assert working_directory == r"C:\a&b<c>"


@pytest.mark.parametrize(
    ("where", "bad_char"),
    [
        ("home", '"'),
        ("home", "%"),
        ("home", "^"),
        ("home", "\n"),
        ("home", "\r"),
        ("executable", '"'),
        ("executable", "%"),
        ("executable", "^"),
        ("executable", "\n"),
        ("executable", "\r"),
    ],
)
def test_windows_task_refuses_cmd_metacharacters(where, bad_char):
    """cmd/XML metacharacters in ``home`` or ``executable`` raise ``ValueError``.

    ``"`` cannot be quoted safely inside the cmd arguments string. ``%``
    triggers cmd variable expansion at parse time. ``^`` is the cmd escape
    character. ``\\n`` and ``\\r`` would split the command across lines
    or insert a literal carriage return that cmd cannot quote.
    """
    from krellbot.service.render import render_windows

    executable = EXE_GOOD
    home = HOME_GOOD
    if where == "home":
        home = Path(r"C:\Users\me\krellbot" + bad_char + r"home")
    else:
        executable = r"C:\bin\krellbot" + bad_char + ".exe"

    with pytest.raises(ValueError):
        render_windows(executable, home)


def test_windows_task_keeps_hourly_trigger(home):
    """The hourly trigger (PT1H + StartWhenAvailable, no ScheduleByDay) is
    preserved across the cmd.exe wrap.
    """
    from krellbot.service.render import render_windows

    body = render_windows(EXE_GOOD, home).decode("utf-8")

    assert "<Interval>PT1H</Interval>" in body
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in body
    # Once-daily triggers use ScheduleByDay, not a CalendarTrigger with an
    # hourly interval.
    assert "ScheduleByDay" not in body


# ---------------------------------------------------------------------------
# install path — macOS-runnable twin of the NS15 Windows test
# ---------------------------------------------------------------------------


def test_install_writes_windows_task_with_home(home, monkeypatch):
    """``install`` (Windows branch) writes a task XML that names
    ``KRELLBOT_HOME`` — the macOS-runnable twin of the NS15 Windows
    assertion that fails on the CI runner.

    ``install`` reads ``sys.platform`` at call time, so monkeypatching the
    ``sys`` module attribute on the test side is enough to route the
    Windows branch on macOS/Linux without touching the real install path.
    """
    from krellbot.service import install

    write_root = home / "write-root"
    monkeypatch.setattr(sys, "platform", "win32")

    rc = install(home, executable=EXE_GOOD, write_root=write_root)

    target = write_root / "Tasks" / "krellbot-tick.xml"
    assert rc == 0, "install() did not return 0 on Windows branch"
    assert target.is_file(), f"Windows unit file not written: {target}"

    body = target.read_text(encoding="utf-8")
    assert "KRELLBOT_HOME" in body
    assert str(home) in body

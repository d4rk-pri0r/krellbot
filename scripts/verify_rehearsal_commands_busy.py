#!/usr/bin/env python3
"""Offline source qualification: uv run --frozen python scripts/verify_rehearsal_commands_busy.py.

Uses only Python's standard library and local Git objects; no server or network.
Behavioral coverage is in RehearsalPanel.commandsBusy.test.tsx, not this parser.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "bcf8df1d99b3575b8580fd3068953e0c8a28e656"
PANEL = "frontend/src/features/paper/RehearsalPanel.tsx"
CLIENT = "frontend/src/features/paper/rehearsalClient.ts"
COMMANDS = ("start", "pause", "resume", "exit", "stop", "refresh")
REQUIRED = (
    "six_shortcuts", "six_busy_attributes", "six_command_testids", "start_busy_condition",
    "polite_sibling_region", "settled_message", "commands_panel_unchanged",
    "run_command_byte_equal", "refresh_helper_byte_equal", "reducer_byte_equal",
    "original_client_calls_preserved", "synchronous_guards", "disabled_gates_preserved",
    "pending_and_inflight_labels", "existing_testids_preserved", "classes_preserved",
    "other_render_blocks_byte_equal", "client_byte_equal",
)


def between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def verify(source: str, client: str, baseline: str, baseline_client: str) -> dict[str, bool]:
    section = between(source, '              aria-label="Rehearsal commands"', "            </section>")
    old_section = between(baseline, '              aria-label="Rehearsal commands"', "            </section>")
    buttons = re.findall(r"<button\b[\s\S]*?</button>", section)
    live = re.search(r'<p\b([^>]*)data-testid="rehearsal-commands-busy-status"([^>]*)>([\s\S]*?)</p>', section)
    attrs = (live[1] + live[2]) if live else ""
    checks = {
        "six_shortcuts": len(buttons) == 6 and all('aria-keyshortcuts="Enter Space"' in b for b in buttons),
        "six_busy_attributes": len(buttons) == 6 and all('aria-busy={' in b and '? "true" : undefined}' in b for b in buttons),
        "six_command_testids": all(f'data-testid="rehearsal-command-{c}"' in section for c in COMMANDS),
        "start_busy_condition": 'state.pending === "start" || commandInFlightRef.current.has("start")' in section,
        "polite_sibling_region": live is not None and 'aria-live="polite"' in attrs and 'role=' not in attrs
        and bool(re.search(r'</div>\s*<p\b[^>]*data-testid="rehearsal-commands-busy-status"', section)),
        "settled_message": 'state.pending ?? activeCommand' in source and 'REHEARSAL_COMMAND_ANNOUNCEMENTS[announcedCommand] : "Settled"' in section,
        "commands_panel_unchanged": 'data-testid="rehearsal-commands-panel"' in section
        and section.split('<div className="kbot-rehearsal__actions">')[0] == old_section.split('<div className="kbot-rehearsal__actions">')[0],
        "run_command_byte_equal": between(source, '  const runCommand =', '  if (client === null) {') == between(baseline, '  const runCommand =', '  if (client === null) {'),
        "refresh_helper_byte_equal": between(source, '  const refreshStatus =', '  const runCommand =') == between(baseline, '  const refreshStatus =', '  const runCommand ='),
        "reducer_byte_equal": between(source, 'function reducer(', '\nconst REHEARSAL_COMMAND_BUSY_LABELS') == between(baseline, 'function reducer(', '\nconst POLL_INTERVAL_MS'),
        # Guarded wrappers necessarily differ; their original call expressions do not.
        "original_client_calls_preserved": all(f'runCommand("{c}", () => client.{c}())' in section for c in COMMANDS[:-1]) and 'void refreshStatus().finally(' in section,
        "synchronous_guards": 'useRef<Set<string>>(new Set())' in source and all(
            f'if (commandInFlightRef.current.has("{c}") || inFlightRef.current) return;' in section
            and f'commandInFlightRef.current.add("{c}");' in section
            and f'commandInFlightRef.current.delete("{c}");' in section for c in COMMANDS),
        "disabled_gates_preserved": re.findall(r'disabled=\{[^}]+\}', section) == re.findall(r'disabled=\{[^}]+\}', old_section)
        and 'const busy = state.pending !== null || activeCommand !== null;' in source,
        "pending_and_inflight_labels": all(
            f'state.pending === "{c}" ? "{label}" : commandInFlightRef.current.has("{c}") ? REHEARSAL_COMMAND_BUSY_LABELS.{c}' in section
            for c, label in zip(COMMANDS[:-1], ("Starting…", "Pausing…", "Resuming…", "Exiting…", "Stopping…"))
        ) and 'refresh: "Refreshing status…"' in source,
        "existing_testids_preserved": [id_ for id_ in re.findall(r'data-testid="([^"]+)"', source)
            if id_ != 'rehearsal-commands-busy-status' and not id_.startswith('rehearsal-command-')]
            == re.findall(r'data-testid="([^"]+)"', baseline),
        "classes_preserved": re.findall(r'className=[^\n]+', source) == re.findall(r'className=[^\n]+', baseline),
        "other_render_blocks_byte_equal": between(source, '  const label =', '              aria-label="Rehearsal commands"')
            == between(baseline, '  const label =', '              aria-label="Rehearsal commands"')
            and source.split('            {state.unknownOutcome', 1)[1] == baseline.split('            {state.unknownOutcome', 1)[1],
        "client_byte_equal": client == baseline_client,
    }
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tests_tmp" / "rehearsal-commands-busy")
    args = parser.parse_args()
    checks = dict.fromkeys(REQUIRED, False)
    failure = None
    try:
        def original(path: str) -> str:
            return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT, text=True, timeout=10)

        checks.update(verify((ROOT / PANEL).read_text(), (ROOT / CLIENT).read_text(), original(PANEL), original(CLIENT)))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError) as error:
        failure = str(error)
    qualified = all(checks.get(name) is True for name in REQUIRED)
    result = {
        "qualified": qualified, "required_assertions": checks, "baseline": BASE,
        "scope": "offline source assertions; no audible screen-reader or browser acceptance claim",
        "handler_note": "The five original runCommand/client call expressions and refreshStatus call are retained, not byte-equal onClick wrappers (which must gain guards).",
    }
    if failure is not None:
        result["failure"] = failure
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if qualified else 1


if __name__ == "__main__":
    raise SystemExit(main())

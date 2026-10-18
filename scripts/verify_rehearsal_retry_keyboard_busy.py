#!/usr/bin/env python3
"""Qualify the bounded retry overlay against its base and run frontend checks.

Stdlib only. Logs and command argv/cwd/exit codes go to ignored tests_tmp/.
This is source + jsdom evidence, not an audible screen-reader acceptance test.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "c4148a53469876128d68615837791afa6ef6a1df"
PANEL = "frontend/src/features/paper/RehearsalPanel.tsx"
TEST = "frontend/src/features/paper/RehearsalPanel.retryBusy.test.tsx"
SCRIPT = "scripts/verify_rehearsal_retry_keyboard_busy.py"
OUTPUT = ROOT / "tests_tmp/rehearsal-retry-keyboard-busy"
ALLOWLIST = {PANEL, TEST, SCRIPT}
DEPENDENCIES = (
    "frontend/src/features/paper/rehearsalClient.ts",
    "frontend/src/features/paper/RehearsalPanel.signal.css",
    "frontend/src/features/paper/RehearsalPanel.commandsBusy.test.tsx",
    "frontend/src/features/paper/RehearsalPanel.signal.test.tsx",
    "frontend/src/features/paper/client.ts",
    "frontend/src/features/paper/StatusPanel.tsx",
    "frontend/src/shell/WorkstationShell.tsx",
    "frontend/package.json",
    "docs/design-system.md",
)
LABELS = '''const REHEARSAL_RETRY_BUSY_LABEL = "Reading rehearsal status…";
const REHEARSAL_RETRY_COMPLETE_LABEL = "Rehearsal status refreshed";

'''
STATE = '''  const [retryInFlight, setRetryInFlight] = useState(false);
  const retryHasFiredRef = useRef(false);
'''
HANDLER = '''  const retryStatus = (): void => {
    if (retryInFlight || inFlightRef.current) return;
    retryHasFiredRef.current = true;
    setRetryInFlight(true);
    void refreshStatus().finally(() => setRetryInFlight(false));
  };

'''
ATTRIBUTES = '''              aria-keyshortcuts="Enter Space"
              aria-busy={retryInFlight ? "true" : undefined}
              disabled={retryInFlight || undefined}
              onClick={retryStatus}'''
OLD_HANDLER = '''              onClick={() => {
                void refreshStatus();
              }}'''
LIVE_REGION = '''        ) : null}
        {retryHasFiredRef.current ? (
          <p
            data-testid="rehearsal-retry-busy-status"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {retryInFlight ? REHEARSAL_RETRY_BUSY_LABEL : REHEARSAL_RETRY_COMPLETE_LABEL}
          </p>
        ) : null}
        {state.loadFailed !== null && state.status === null ? null : ('''


def original(path: str) -> bytes:
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT, timeout=10)


def between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def verify(source: str, baseline: str) -> dict[str, bool]:
    buttons = re.findall(r"<button\b[\s\S]*?</button>", source)
    old_buttons = re.findall(r"<button\b[\s\S]*?</button>", baseline)
    retry = next(button for button in buttons if "Retry status" in button)
    normalized = source
    for addition in (LABELS, STATE, HANDLER):
        normalized = normalized.replace(addition, "", 1)
    normalized = normalized.replace(ATTRIBUTES, OLD_HANDLER, 1)
    normalized = normalized.replace(LIVE_REGION, "        ) : (", 1)
    ids = re.findall(r'data-testid="([^"]+)"', source)
    old_ids = re.findall(r'data-testid="([^"]+)"', baseline)
    return {
        "source_read": bool(source and baseline),
        "retry_button_carrys_aria_keyshortcuts": 'aria-keyshortcuts="Enter Space"' in retry,
        "retry_button_busy_attribute": 'aria-busy={retryInFlight ? "true" : undefined}' in retry,
        "retry_button_disabled_gate": 'disabled={retryInFlight || undefined}' in retry,
        "retry_busy_status_sibling_rendered": (
            "              Retry status\n            </button>\n          </>\n" + LIVE_REGION in source
        ),
        "retry_inflight_re_click_guard": HANDLER in source and "onClick={retryStatus}" in retry,
        "retry_labels_and_initial_state": LABELS in source and STATE in source,
        "six_command_buttons_byte_equal": len(buttons) == len(old_buttons) == 7
        and buttons[1:] == old_buttons[1:]
        and between(source, '              aria-label="Rehearsal commands"', '            {state.unknownOutcome')
        == between(baseline, '              aria-label="Rehearsal commands"', '            {state.unknownOutcome'),
        "existing_data_testids_only_addition": ids.count("rehearsal-retry-busy-status") == 1
        and [item for item in ids if item != "rehearsal-retry-busy-status"] == old_ids,
        "existing_css_classes_byte_equal": re.findall(r'className=[^\n]+', source)
        == re.findall(r'className=[^\n]+', baseline),
        "existing_aria_labels_byte_equal": re.findall(r'aria-label=[^\n]+', source)
        == re.findall(r'aria-label=[^\n]+', baseline),
        "refresh_status_byte_equal": between(source, "  const refreshStatus =", "  const retryStatus =")
        == between(baseline, "  const refreshStatus =", "  const runCommand ="),
        "props_reducer_initial_state_byte_equal": source.split("const REHEARSAL_COMMAND_BUSY_LABELS", 1)[0]
        == baseline.split("const REHEARSAL_COMMAND_BUSY_LABELS", 1)[0],
        # Exact inverse of the five permitted edits also pins every original
        # literal, client call, render surface and command/reducer implementation.
        "only_bounded_overlay_changes": normalized == baseline,
    }


def run(name: str, argv: list[str], cwd: Path) -> dict[str, object]:
    completed = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, timeout=180, check=False)
    log = OUTPUT / f"{name}.log"
    log.write_text(completed.stdout)
    return {"name": name, "argv": argv, "cwd": str(cwd.relative_to(ROOT)) or ".",
            "exit_code": completed.returncode, "log": str(log.relative_to(ROOT))}


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    checks: dict[str, bool] = {}
    commands: list[dict[str, object]] = []
    failure = None
    try:
        source = (ROOT / PANEL).read_text()
        checks.update(verify(source, original(PANEL).decode()))
        checks["dependency_paths_unchanged"] = all(
            (ROOT / path).read_bytes() == original(path) for path in DEPENDENCIES
        )
        changed = subprocess.check_output(
            ["git", "diff", "--name-only", BASE, "--"], cwd=ROOT, text=True, timeout=10
        ).splitlines()
        untracked = subprocess.check_output(
            ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True, timeout=10
        ).splitlines()
        checks["allowlist_only"] = set(changed + untracked) <= ALLOWLIST
        for name, argv, cwd in (
            ("typecheck", ["npm", "run", "typecheck"], ROOT / "frontend"),
            ("build", ["npm", "run", "build"], ROOT / "frontend"),
            ("runtime_tests", ["npm", "run", "test:unit", "--", "run",
                               "src/features/paper/RehearsalPanel.retryBusy.test.tsx",
                               "src/features/paper/RehearsalPanel.commandsBusy.test.tsx",
                               "src/features/paper/RehearsalPanel.signal.test.tsx"], ROOT / "frontend"),
            ("diff_check", ["git", "diff", "--check"], ROOT),
        ):
            commands.append(run(name, argv, cwd))
        results = {str(command["name"]): command["exit_code"] for command in commands}
        typecheck_log = (OUTPUT / "typecheck.log").read_text()
        diagnostics = re.findall(r"^(src/[^\n]+?)\(\d+,\d+\): error TS\d+:", typecheck_log, re.MULTILINE)
        checks["typecheck_no_slice_errors"] = results["typecheck"] == 0 or (
            results["typecheck"] in (1, 2) and bool(diagnostics)
            and all(f"frontend/{path}" not in ALLOWLIST
                    and (ROOT / "frontend" / path).read_bytes() == original(f"frontend/{path}")
                    for path in diagnostics)
        )
        checks["runtime_tests"] = results["runtime_tests"] == 0
        checks["build"] = results["build"] == 0
        checks["diff_check"] = results["diff_check"] == 0
        checks["verification_commands_recorded"] = len(commands) == 4 and all(
            (ROOT / str(command["log"])).is_file() for command in commands
        )
    except (OSError, ValueError, IndexError, StopIteration, subprocess.SubprocessError) as error:
        failure = str(error)
    qualified = failure is None and bool(checks) and all(checks.values())
    result = {
        "qualified": qualified, "baseline": BASE,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "tested_file_sha256": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                               for path in sorted(ALLOWLIST)},
        "required_assertions": checks, "commands": commands,
        "full_typecheck_passed": any(command["name"] == "typecheck" and command["exit_code"] == 0
                                     for command in commands),
        "scope": "Source preservation + real mounted jsdom tests; no audible AT/browser acceptance claim.",
        "settlement_note": "Success removes Retry with the existing failure branch; rejection clears its attributes. The live sibling persists across either outcome.",
        "typecheck_note": "Nonzero typecheck is accepted only for diagnostics in byte-equal files outside the allowlist; see typecheck.log.",
    }
    if failure is not None:
        result["failure"] = failure
    (OUTPUT / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if qualified else 1


if __name__ == "__main__":
    raise SystemExit(main())

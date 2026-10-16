#!/usr/bin/env python3
"""Offline source-preservation and React runtime checks for trace CSV ARIA hooks.

Defaults to this checkout; --container reads and tests the integrator checkout
via docker exec. The frozen commit supplies comparison bytes, not updated ARIA.
This verifies DOM hooks, not audible screen-reader output or a global shortcut.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "713dbf276ef5570f02fdf8ab3b0600574bf21d4b"
SOURCE = "frontend/src/features/research/TraceCsvExport.tsx"
REQUIRED = (
    "button_aria", "contextual_labels", "empty_status", "visible_copy",
    "download_flow_unchanged", "filename_unchanged", "disabled_passthrough",
    "helpers_unchanged", "props_unchanged", "surface_and_testids_unchanged",
    "consumer_unchanged", "no_global_shortcut", "runtime_tests",
)


def between(text: str, start: str, end: str) -> str:
    offset = text.index(start)
    return text[offset:text.index(end, offset) + len(end)]


def element(text: str, tag: str, testid: str) -> tuple[str, str]:
    matches = [
        (match[1], match[2].strip())
        for match in re.finditer(rf"<{tag}\b(.*?)>(.*?)</{tag}>", text, re.S)
        if f'data-testid="{testid}"' in match[1]
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one {tag} with data-testid={testid}")
    return matches[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--container", nargs="?", const="krellbot-integrator-sandbox")
    parser.add_argument("--container-root", default=str(ROOT))
    args = parser.parse_args()
    out = args.output_dir or Path(tempfile.mkdtemp(prefix="trace-csv-export-"))
    out.mkdir(parents=True, exist_ok=True)
    assertions = dict.fromkeys(REQUIRED, False)
    results = {
        "qualified": False,
        "required_assertions": assertions,
        "baseline": BASE,
        "source_mode": f"docker exec {args.container}" if args.container else "local checkout",
        "source_path": SOURCE,
    }

    def run(argv: list[str], directory: str = ".", timeout: int = 20) -> subprocess.CompletedProcess[str]:
        if args.container:
            command = ["docker", "exec", "-w", str(Path(args.container_root) / directory), args.container, *argv]
            cwd = ROOT
        else:
            command = argv
            cwd = ROOT / directory
        return subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)

    def read(argv: list[str]) -> str:
        process = run(argv)
        if process.returncode != 0:
            raise RuntimeError(process.stderr or process.stdout)
        return process.stdout

    try:
        source = read(["cat", SOURCE])
        baseline = read(["git", "show", f"{BASE}:{SOURCE}"])
        results["head"] = read(["git", "rev-parse", "HEAD"]).strip()
        results["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
        button, button_text = element(source, "button", "research-trace-csv-export")
        empty, empty_text = element(source, "p", "research-trace-csv-empty")
        assertions["button_aria"] = all(value in button for value in (
            'aria-keyshortcuts="Control+E Meta+E"', "aria-label={", "aria-busy={busy}",
        ))
        assertions["contextual_labels"] = bool(re.search(
            r'aria-label=\{\s*!hasRows\s*\? "Export trace CSV \(no trace rows to export\)"'
            r'\s*: jobId !== null\s*\? `Export trace CSV for run \$\{jobId\}`'
            r'\s*: "Export trace CSV"\s*\}', button,
        ))
        assertions["empty_status"] = all(value in empty for value in (
            'role="status"', 'aria-live="polite"', 'aria-atomic="true"',
        ))
        assertions["visible_copy"] = button_text == "Export CSV" and empty_text == "No trace rows to export."
        flow_start = "    const blob = new Blob("
        flow_end = "    URL.revokeObjectURL(url);"
        assertions["download_flow_unchanged"] = between(source, flow_start, flow_end) == between(baseline, flow_start, flow_end)
        filename = 'anchor.download = `krellbot-trace-${jobId ? jobId : "unk"}-${timestampStamp(new Date())}.csv`;'
        assertions["filename_unchanged"] = filename in source and filename in baseline
        assertions["disabled_passthrough"] = "disabled={!hasRows}" in button
        assertions["helpers_unchanged"] = between(
            source, "function formatCell(", "export function TraceCsvExport(",
        ) == between(baseline, "function formatCell(", "export function TraceCsvExport(")
        assertions["props_unchanged"] = between(
            source, "export type TraceCsvExportProps = {", "};",
        ) == between(baseline, "export type TraceCsvExportProps = {", "};")
        assertions["surface_and_testids_unchanged"] = (
            'className="kbot-research__action"' in button
            and 'type="button"' in button
            and "onClick={handleClick}" in button
            and 'className="kbot-research__trace-empty"' in empty
            and re.findall(r'data-testid="[^"]+"', source) == re.findall(r'data-testid="[^"]+"', baseline)
        )
        consumer = "frontend/src/features/research/ResearchView.tsx"
        assertions["consumer_unchanged"] = read(["cat", consumer]) == read(["git", "show", f"{BASE}:{consumer}"])
        assertions["no_global_shortcut"] = not re.search(r"addEventListener|onKeyDown|onkeydown", source)
        runtime = run([
            "npm", "run", "test:unit", "--", "run",
            "src/features/research/TraceCsvExport.keyboard.test.tsx",
            "src/features/research/TraceCsvExport.test.tsx",
        ], "frontend", timeout=120)
        (out / "runtime.log").write_text(runtime.stdout + runtime.stderr)
        results["runtime_exit"] = runtime.returncode
        assertions["runtime_tests"] = runtime.returncode == 0
        results["qualified"] = all(assertions.values())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        results["error"] = str(error)
    report = out / "results.json"
    report.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({**results, "results_file": str(report.resolve())}, indent=2))
    return 0 if results["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

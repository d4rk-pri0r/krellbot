#!/usr/bin/env python3
"""Check export ARIA DOM behavior and byte-preserved download code, not AT audio.

Run: uv run --frozen python scripts/verify_indicator_spec_export_aria.py
Reports/logs are kept outside the checkout unless --output-dir is supplied.
A failing whole-frontend typecheck qualifies only if its diagnostics match the
frozen base exactly and none concern this slice. Its exit code remains recorded.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "514f3deed0a938dca13fc59bb4e12e8d01b6569e"
SOURCE = "frontend/src/features/studio/IndicatorSpecJsonExport.tsx"
TEST = "frontend/src/features/studio/IndicatorSpecJsonExport.aria.test.tsx"
SCRIPT = "scripts/verify_indicator_spec_export_aria.py"
ALLOWED = {SOURCE, TEST, SCRIPT}
RUNTIME = [
    "npm", "run", "test:unit", "--", "run",
    "src/features/studio/IndicatorSpecJsonExport.aria.test.tsx",
    "src/features/studio/IndicatorSpecJsonExport.test.tsx",
]
REQUIRED = (
    "source_read", "button_aria_label_contains_spec_name", "button_aria_keyshortcuts",
    "button_aria_busy", "polite_aria_live_wiring", "null_return_branch_unchanged",
    "helper_imports_unchanged", "anchor_click_chain_unchanged", "prop_contract_unchanged",
    "runtime_tests", "typecheck_no_slice_errors", "build", "verification_commands_recorded",
    "default_timestamp_unchanged", "visible_button_unchanged", "allowlist_enforced",
    "dependencies_unchanged", "diff_check",
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
        raise ValueError(f"Expected exactly one {tag} for {testid}")
    return matches[0]


def diagnostics(output: str) -> list[str]:
    return sorted(re.findall(r"^src/.*?error TS\d+:.*$", output, re.M))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = args.output_dir or Path(tempfile.mkdtemp(prefix="indicator-spec-export-aria-"))
    output.mkdir(parents=True, exist_ok=True)
    assertions = dict.fromkeys(REQUIRED, False)
    commands: list[dict] = []
    results = {
        "baseline": BASE, "qualified": False, "required_assertions": assertions,
        "commands": commands,
        "invocation": ["uv", "run", "--frozen", "python", SCRIPT],
        "limitations": "jsdom DOM/runtime evidence; real keyboard and audible AT verification remains manual",
    }

    def run(name: str, argv: list[str], cwd: Path = ROOT, timeout: int = 120) -> subprocess.CompletedProcess[str]:
        process = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
        log = output / f"{name}.log"
        log.write_text(process.stdout + process.stderr)
        commands.append({"name": name, "argv": argv, "cwd": str(cwd),
                         "exit_code": process.returncode, "log": str(log.resolve())})
        return process

    def git(*argv: str) -> str:
        return subprocess.check_output(["git", *argv], cwd=ROOT, text=True, timeout=20)

    try:
        source = (ROOT / SOURCE).read_text()
        baseline = git("show", f"{BASE}:{SOURCE}")
        results["tested_sha"] = git("rev-parse", "HEAD").strip()
        results["source_dirty"] = bool(git("status", "--porcelain"))
        results["source_hashes"] = {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in sorted(ALLOWED)
        }
        assertions["source_read"] = bool(source and baseline)
        button, visible_text = element(source, "button", "studio-indicator-spec-export")
        status, status_text = element(source, "p", "studio-indicator-spec-export-status")
        assertions["button_aria_label_contains_spec_name"] = (
            'aria-label={"Export spec JSON for indicator " + (spec.name ?? "unknown")}' in button
        )
        assertions["button_aria_keyshortcuts"] = 'aria-keyshortcuts="Enter Space"' in button
        assertions["button_aria_busy"] = (
            "aria-busy={exporting || undefined}" in button
            and "useState<boolean>(false)" in source
            and source.index("setExporting(true)") < source.index("const blob =")
            and source.index("URL.revokeObjectURL(url);") < source.index("queueMicrotask(() => {")
            < source.index("setExporting(false)")
        )
        assertions["polite_aria_live_wiring"] = all(part in status for part in (
            "id={descId}", 'role="status"', 'aria-live="polite"', 'aria-atomic="true"',
            'className="kbot-palette__label"',
        )) and all(part in source for part in (
            "const descId = useId();", "aria-describedby={exporting ? descId : undefined}",
            "setStatus(`Exporting spec ${spec.name}…`)",
            "setStatus(`Export complete for spec ${spec.name}`)",
            'setTimeout(() => setStatus(""), 0)', "clearTimeout(timer)", "<>", "</>",
        )) and status_text == "{status}"
        for assertion, start, end in (
            ("null_return_branch_unchanged", "  if (spec === null) {", "    return null;\n  }"),
            ("helper_imports_unchanged", "import {\n  indicatorSpecFilename,", '} from "./indicatorSpecJson";'),
            ("anchor_click_chain_unchanged", "    const blob = new Blob(", "    URL.revokeObjectURL(url);"),
            ("prop_contract_unchanged", "export type IndicatorSpecJsonExportProps = {", "};"),
            ("default_timestamp_unchanged", "  const stamp = timestamp ??", "  const handleClick"),
        ):
            assertions[assertion] = between(source, start, end) == between(baseline, start, end)
        assertions["anchor_click_chain_unchanged"] &= (
            source.count("anchor.click();") == source.count("URL.revokeObjectURL(url);") == 1
            and "indicatorSpecFilename(spec.name, stamp)" in source
            and "indicatorSpecToJson(spec)" in source
        )
        original_button, original_text = element(baseline, "button", "studio-indicator-spec-export")
        assertions["visible_button_unchanged"] = visible_text == original_text == "Export spec JSON" and all(
            part in button and part in original_button for part in (
                'type="button"', 'className="kbot-studio-node-inspector__export"', "onClick={handleClick}",
            )
        ) and not re.search(r"onKeyDown|addEventListener|disabled=", source)
        changed = set(git("diff", "--name-only", BASE).splitlines())
        changed.update(git("ls-files", "--others", "--exclude-standard").splitlines())
        results["changed_files"] = sorted(changed)
        assertions["allowlist_enforced"] = changed <= ALLOWED
        dependencies = [
            "frontend/src/features/studio/IndicatorSpecJsonExport.test.tsx",
            "frontend/src/features/studio/StudioNodeInspector.tsx",
            "frontend/src/features/studio/indicatorSpecJson.ts", "docs/design-system.md", "frontend/package.json",
        ]
        assertions["dependencies_unchanged"] = all(
            (ROOT / path).read_text() == git("show", f"{BASE}:{path}") for path in dependencies
        )
        assertions["runtime_tests"] = run("runtime", RUNTIME, ROOT / "frontend").returncode == 0
        typecheck = run("typecheck", ["npm", "run", "typecheck"], ROOT / "frontend")
        current_diagnostics = diagnostics(typecheck.stdout + typecheck.stderr)
        results["typecheck_diagnostics"] = current_diagnostics
        assertions["typecheck_no_slice_errors"] = typecheck.returncode == 0
        if typecheck.returncode != 0:
            # Compare real tsc diagnostics against a clean frontend from the frozen base.
            archive = subprocess.check_output(["git", "archive", BASE, "frontend"], cwd=ROOT, timeout=20)
            with tempfile.TemporaryDirectory(prefix="indicator-export-base-") as directory:
                with tarfile.open(fileobj=io.BytesIO(archive)) as tree:
                    tree.extractall(directory, filter="data")
                frontend = Path(directory) / "frontend"
                (frontend / "node_modules").symlink_to((ROOT / "frontend/node_modules").resolve(), target_is_directory=True)
                base_check = run("base-typecheck", ["npm", "run", "typecheck"], frontend)
                base_diagnostics = diagnostics(base_check.stdout + base_check.stderr)
                results["baseline_typecheck_diagnostics"] = base_diagnostics
                assertions["typecheck_no_slice_errors"] = (
                    typecheck.returncode == base_check.returncode
                    and bool(current_diagnostics) and current_diagnostics == base_diagnostics
                    and not any("IndicatorSpecJsonExport" in item for item in current_diagnostics)
                )
        assertions["build"] = run("build", ["npm", "run", "build"], ROOT / "frontend").returncode == 0
        assertions["diff_check"] = run("diff-check", ["git", "diff", "--check"]).returncode == 0
        assertions["verification_commands_recorded"] = all(
            any(item["argv"] == argv and Path(item["log"]).is_file() for item in commands)
            for argv in (RUNTIME, ["npm", "run", "typecheck"], ["npm", "run", "build"], ["git", "diff", "--check"])
        )
        results["qualified"] = all(assertions.values())
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        results["error"] = str(error)
    report = output / "results.json"
    report.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({**results, "results_file": str(report.resolve())}, indent=2))
    return 0 if results["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Offline armed-record action checks against the canonical Docker checkout.

The frozen head supplies preservation bytes; updated source and React runtime
checks use the container's working tree. Unavailable Docker is a failed check,
not permission to qualify a different checkout.
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
BASE = "691e0b12ed"
SOURCE = "frontend/src/features/paper/ArmedRecordsList.tsx"
CLIENT = "frontend/src/features/paper/client.ts"
REQUIRED = (
    "pause_button", "resume_button", "disarm_button", "row_action_alert",
    "detail_wrapper_unchanged", "detail_metadata_unchanged", "existing_testids_unchanged",
    "client_signatures_unchanged", "props_unchanged", "helpers_unchanged",
    "refresh_and_keyboard_unchanged", "styles_unchanged", "consumers_unchanged",
    "runtime_tests",
)
NEW_IDS = {
    "paper-armed-row-pause", "paper-armed-row-resume", "paper-armed-row-disarm",
    "paper-armed-row-action-error",
}


def between(text: str, start: str, end: str) -> str:
    offset = text.index(start)
    return text[offset:text.index(end, offset) + len(end)]


def detail(text: str) -> tuple[str, str]:
    matches = list(re.finditer(
        r'<section\b[^>]*data-testid="paper-armed-detail"[^>]*>(.*?)</section>',
        text, re.S,
    ))
    if len(matches) != 1:
        raise ValueError("Expected exactly one armed detail section")
    match = matches[0]
    return match[0][:match[0].index(">") + 1], match[1]


def testids(text: str) -> list[str]:
    return re.findall(r'data-testid=(?:"[^"]*"|\{`[^`]*`\})', text)


def source_assertions(source: str, baseline: str, client: str, baseline_client: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    wrapper, body = detail(source)
    old_wrapper, old_body = detail(baseline)
    after_dl = body[body.index("</dl>") + len("</dl>"):]
    for kind, label in (("pause", "Pause entries on"), ("resume", "Resume entries on"), ("disarm", "Disarm")):
        testid = f"paper-armed-row-{kind}"
        # These JSX opening tags include an arrow callback; match through </button>.
        buttons = re.findall(r'<button\b.*?</button>', after_dl, re.S)
        matches = [tag for tag in buttons if f'data-testid="{testid}"' in tag]
        checks[f"{kind}_button"] = (
            len(matches) == 1
            and source.count(f'data-testid="{testid}"') == 1
            and 'type="button"' in matches[0]
            and f'aria-label={{`{label} ${{selected.venue}} ${{selected.pair}}`}}' in matches[0]
            and 'className="kbot-paper-armed__row-action"' in matches[0]
        )
    alerts = re.findall(r'<p\b[^>]*data-testid="paper-armed-row-action-error"[^>]*>.*?</p>', after_dl, re.S)
    checks["row_action_alert"] = (
        len(alerts) == 1
        and 'role="alert"' in alerts[0]
        and 'className="kbot-paper-armed__row-action-error"' in alerts[0]
        and "{rowActionError}" in alerts[0]
    )
    checks["detail_wrapper_unchanged"] = (
        wrapper == old_wrapper
        and 'role="region"' in wrapper
        and 'aria-label="Armed record detail"' in wrapper
    )
    checks["detail_metadata_unchanged"] = body[:body.index("</dl>") + len("</dl>")] == old_body[:old_body.index("</dl>") + len("</dl>")]
    checks["existing_testids_unchanged"] = [
        value for value in testids(source)
        if value not in {f'data-testid="{testid}"' for testid in NEW_IDS}
    ] == testids(baseline)
    signatures = [
        f"{method}(venue: string, pair: string): Promise<PaperCommandResult>;"
        for method in ("pauseEntries", "resumeEntries", "disarm")
    ]
    checks["client_signatures_unchanged"] = client == baseline_client and all(value in client for value in signatures)
    checks["props_unchanged"] = between(source, "export type ArmedRecordsListProps", "};") == between(baseline, "export type ArmedRecordsListProps", "};")
    checks["helpers_unchanged"] = between(source, "type EntriesSentence", "export function ArmedRecordsList") == between(baseline, "type EntriesSentence", "export function ArmedRecordsList")
    checks["refresh_and_keyboard_unchanged"] = all(
        between(source, start, end) == between(baseline, start, end)
        for start, end in (
            ("  useEffect(() => {", "  const refresh ="),
            ("  const refresh =", "  };"),
            ("  const toggleRow =", "  return ("),
            ('      <header', '      <div className="kbot-paper-armed__body">'),
        )
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", default="krellbot-integrator-sandbox")
    parser.add_argument("--container-root", default=str(ROOT))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    out = args.output_dir or Path(tempfile.mkdtemp(prefix="armed-records-actions-"))
    out.mkdir(parents=True, exist_ok=True)
    assertions = dict.fromkeys(REQUIRED, False)
    results = {
        "qualified": False, "required_assertions": assertions, "baseline": BASE,
        "source_mode": f"docker exec {args.container}", "source_path": SOURCE,
        "container_root": args.container_root,
    }

    def run(argv: list[str], directory: str = ".", timeout: int = 30) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["docker", "exec", "-w", str(Path(args.container_root) / directory), args.container, *argv],
            text=True, capture_output=True, timeout=timeout, check=False,
        )

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
        assertions.update(source_assertions(
            source, baseline, read(["cat", CLIENT]), read(["git", "show", f"{BASE}:{CLIENT}"]),
        ))
        css = "frontend/src/features/paper/ArmedRecordsList.signal.css"
        assertions["styles_unchanged"] = (
            read(["cat", css]) == read(["git", "show", f"{BASE}:{css}"])
            and 'import "./ArmedRecordsList.signal.css";' in source
        )
        assertions["consumers_unchanged"] = all(
            read(["cat", path]) == read(["git", "show", f"{BASE}:{path}"])
            for path in ("frontend/src/features/paper/StatusPanel.tsx", "frontend/src/shell/WorkstationShell.tsx")
        )
        runtime = run([
            "npm", "run", "test:unit", "--", "run",
            *[f"src/features/paper/ArmedRecordsList{suffix}.test.tsx"
              for suffix in (".rowActions", "", ".signal", ".keyboard")],
        ], "frontend", timeout=180)
        (out / "runtime.log").write_text(runtime.stdout + runtime.stderr, encoding="utf-8")
        results["runtime_exit"] = runtime.returncode
        assertions["runtime_tests"] = runtime.returncode == 0
        results["qualified"] = all(assertions.values())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        results["error"] = str(error)
    report = out / "results.json"
    report.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**results, "results_file": str(report.resolve())}, indent=2))
    return 0 if results["qualified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

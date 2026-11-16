"""Build honest GitHub Release notes from signing-status markers.

Reads ``signing-status-*.json`` artifacts produced by
``release-frozen.yml`` and prints a single notes string to stdout.
Never claims notarized / Authenticode unless both macOS and Windows
markers report ``signed: true``. Always suitable for ``--prerelease``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_notes(*, root: Path, sha: str) -> str:
    macos_signed = False
    windows_signed = False
    linux_policy = "checksum_pinned_policy"
    for path in sorted(root.rglob("signing-status-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        platform = data.get("platform")
        signed = bool(data.get("signed"))
        detail = str(data.get("detail") or "")
        if platform == "macos" and signed:
            macos_signed = True
        elif platform == "windows" and signed:
            windows_signed = True
        elif platform == "linux":
            linux_policy = detail or linux_policy

    base = f"Checksum-pinned build from {sha}."
    if macos_signed and windows_signed:
        return (
            f"{base} macOS: Developer ID-signed and notarized. "
            f"Windows: Authenticode-signed. Linux: checksum-pinned ({linux_policy}); "
            "no platform code signature. Still a prerelease — not GA."
        )
    return (
        f"{base} Unsigned checksum-pinned build. Not notarized. "
        "Not Authenticode-signed. SHA-256 is the integrity check."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("release-assets"),
        help="directory containing signing-status-*.json markers",
    )
    parser.add_argument("--sha", required=True, help="git commit SHA for the notes")
    args = parser.parse_args(argv)
    sys.stdout.write(build_notes(root=args.root, sha=args.sha))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

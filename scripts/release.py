"""Release script: write SHA256SUMS, optionally sign with minisign.

Computes the SHA-256 of a built wheel and writes a sums file in the
conventional `<64 lowercase hex>  <basename>` format used by `sha256sum`.
When `--secret` is given, the script invokes `minisign -S` to sign the
sums file in place. A release public key whose first line is `# DEV`
is refused unless `--dev` is also passed: a development key is never
trusted for a real release build.

This phase does NOT upload anything. There is no `--upload` flag.

Exit codes:
  0  success (sums written; signature written iff --secret was passed)
  2  refused: dev key without --dev, missing minisign, missing inputs, etc.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

_DEV_MARKER = "# DEV"
_CHUNK = 1 << 20  # 1 MiB read chunks for the wheel digest


def _sha256_of(path: Path) -> str:
    """Lowercase hex SHA-256 of the file at `path`."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _first_nonempty_line(path: Path) -> str | None:
    """First stripped non-empty line of `path`, or None if the file is empty/unreadable."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write SHA256SUMS for a built wheel and optionally sign it.",
    )
    parser.add_argument("--wheel", required=True, type=Path, help="path to the .whl file")
    parser.add_argument("--sums", required=True, type=Path, help="path to write the SHA256SUMS file")
    parser.add_argument(
        "--minisig",
        required=True,
        type=Path,
        help="path where minisign writes the .minisig signature",
    )
    parser.add_argument("--pub", required=True, type=Path, help="path to the release public key file")
    parser.add_argument(
        "--secret",
        type=Path,
        default=None,
        help="path to the minisign secret key; omit to skip signing",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="allow a # DEV-marked release public key (dev build only)",
    )
    args = parser.parse_args(argv)

    # 1. Validate the public key. A # DEV key is refused unless --dev is set.
    first = _first_nonempty_line(args.pub)
    if first is None:
        print(f"refused: release public key {args.pub} is empty or unreadable", file=sys.stderr)
        return 2
    if first == _DEV_MARKER and not args.dev:
        print(
            f"refused: release public key {args.pub.name} is marked {_DEV_MARKER!r}; pass --dev to override",
            file=sys.stderr,
        )
        return 2

    # 2. Verify the wheel exists, then compute its SHA-256.
    if not args.wheel.is_file():
        print(f"refused: wheel file not found: {args.wheel}", file=sys.stderr)
        return 2

    digest = _sha256_of(args.wheel)
    wheel_basename = args.wheel.name

    # 3. Write the SHA256SUMS file in `<hex>  <basename>` format (two spaces).
    args.sums.parent.mkdir(parents=True, exist_ok=True)
    args.sums.write_text(f"{digest}  {wheel_basename}\n", encoding="utf-8")

    # 4. Signing is optional. With no --secret we stop here.
    if args.secret is None:
        return 0

    # From here on, --secret was passed. We need minisign on PATH.
    if shutil.which("minisign") is None:
        print("refused: minisign is not installed; cannot sign without it", file=sys.stderr)
        return 2

    if not args.secret.is_file():
        print(f"refused: secret key file not found: {args.secret}", file=sys.stderr)
        return 2

    sums_path = args.sums.resolve()
    sig_path = args.minisig.resolve()
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "minisign",
        "-S",
        "-s",
        str(args.secret.resolve()),
        "-m",
        str(sums_path),
        "-x",
        str(sig_path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        print(f"refused: could not invoke minisign: {exc}", file=sys.stderr)
        return 2

    if proc.returncode != 0:
        # Surface minisign's own stderr (no key bytes, since minisign never prints them).
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

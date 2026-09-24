"""Tests for scripts/release.py.

The script writes a SHA256SUMS file in `<64 lowercase hex>  <basename>`
format for a built wheel and optionally signs it with minisign. These
tests cover the format, the dev-key refusal, and the no-signature path.
They never invoke a network call; `minisign` is only required when
`--secret` is passed and that path is exercised separately.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "release.py"

# 64 lowercase hex chars. Anchored, not partial.
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Invoke scripts/release.py with the given CLI args; capture stdout/stderr."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _write_dev_pub(tmp_path: Path, *, key_marker: str = "untrusted dev public key") -> Path:
    """Write a release public key file whose first line is `# DEV`."""
    pub = tmp_path / "release.pub"
    pub.write_text(f"# DEV\n{key_marker}\n", encoding="utf-8")
    return pub


def _write_release_pub(tmp_path: Path, *, key: str) -> Path:
    """Write a release public key file whose first line is NOT `# DEV`."""
    pub = tmp_path / "release.pub"
    pub.write_text(f"release\n{key}\n", encoding="utf-8")
    return pub


def test_sums_file_uses_real_sha256(tmp_path):
    """The sums file holds the SHA-256 we compute ourselves with hashlib."""
    wheel = tmp_path / "krellbot-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"deterministic wheel payload for hashing\n")

    expected = hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert _SHA256_RE.match(expected), "precondition: hashlib produced a valid hex digest"

    sums = tmp_path / "SHA256SUMS"
    minisig = tmp_path / "SHA256SUMS.minisig"
    pub = _write_dev_pub(tmp_path)

    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(minisig),
            "--pub",
            str(pub),
            "--dev",
        ]
    )

    assert result.returncode == 0, f"stderr was: {result.stderr!r}"
    assert sums.is_file(), "sums file must be created"

    content = sums.read_text(encoding="utf-8")
    # Exactly one line: "<64 hex>  <basename>\n". Two spaces between hash and name.
    assert content == f"{expected}  {wheel.name}\n", f"unexpected sums content: {content!r}"
    # No signature file: --secret was not passed.
    assert not minisig.exists(), "no signature file should be created without --secret"


def test_sums_format_is_two_spaces_and_lowercase(tmp_path):
    """The sums line must be `<64 lowercase hex>  <name>\\n` — exactly two spaces."""
    wheel = tmp_path / "pkg-1.0-py3-none-any.whl"
    # Use bytes that produce uppercase-looking but lowercase-hex output to prove the
    # format is lowercase hex (hexdigest is always lowercase; this also confirms it).
    wheel.write_bytes(bytes(range(256)) * 4)

    sums = tmp_path / "SHA256SUMS"
    pub = _write_dev_pub(tmp_path)

    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(tmp_path / "SHA256SUMS.minisig"),
            "--pub",
            str(pub),
            "--dev",
        ]
    )
    assert result.returncode == 0, result.stderr

    body = sums.read_text(encoding="utf-8")
    assert body.endswith("\n")
    line = body.rstrip("\n")
    match = re.fullmatch(r"([0-9a-f]{64})  (\S+)", line)
    assert match is not None, f"line must be `<64 hex>  <name>`: {line!r}"
    digest, name = match.group(1), match.group(2)
    assert _SHA256_RE.match(digest), f"digest must be 64 lowercase hex chars: {digest!r}"
    assert name == wheel.name, f"name must be the wheel basename, got: {name!r}"


def test_dev_pub_refused_without_dev_flag(tmp_path):
    """A # DEV public key without --dev exits 2 with no sums file and no key leak."""
    wheel = tmp_path / "krellbot.whl"
    wheel.write_bytes(b"x")

    sums = tmp_path / "SHA256SUMS"
    minisig = tmp_path / "SHA256SUMS.minisig"
    secret_marker = "SECRET-MARKER-DO-NOT-LEAK-XYZ"
    pub = _write_dev_pub(tmp_path, key_marker=secret_marker)

    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(minisig),
            "--pub",
            str(pub),
        ]
    )

    assert result.returncode == 2, f"expected exit 2, got {result.returncode}; stderr={result.stderr!r}"
    # Refusal must go to stderr.
    assert "DEV" in result.stderr or "dev" in result.stderr, (
        f"refusal reason must mention dev/Dev marker; stderr={result.stderr!r}"
    )
    # No key bytes leaked into stderr.
    assert secret_marker not in result.stderr, "refusal must not echo the public key bytes"
    assert secret_marker not in result.stdout, "refusal must not echo the public key bytes"
    # No sums file was written.
    assert not sums.exists(), "sums file must NOT be written when the dev key is refused"
    # No signature file was written.
    assert not minisig.exists()


def test_dev_pub_accepted_with_dev_flag(tmp_path):
    """With --dev, the script proceeds and writes SHA256SUMS for a known payload."""
    wheel = tmp_path / "krellbot.whl"
    wheel.write_bytes(b"hello world\n")
    expected = hashlib.sha256(wheel.read_bytes()).hexdigest()

    sums = tmp_path / "SHA256SUMS"
    minisig = tmp_path / "SHA256SUMS.minisig"
    pub = _write_dev_pub(tmp_path)

    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(minisig),
            "--pub",
            str(pub),
            "--dev",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert sums.read_text(encoding="utf-8") == f"{expected}  {wheel.name}\n"


def test_release_pub_without_dev_marker_is_accepted(tmp_path):
    """A non-DEV public key is accepted even without --dev."""
    wheel = tmp_path / "krellbot.whl"
    wheel.write_bytes(b"some bytes")

    sums = tmp_path / "SHA256SUMS"
    minisig = tmp_path / "SHA256SUMS.minisig"
    pub = _write_release_pub(tmp_path, key="RWQ7dWJhZ2Ugbm90IGEgcmVhbCBrZXk=")

    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(minisig),
            "--pub",
            str(pub),
        ]
    )
    assert result.returncode == 0, result.stderr
    assert sums.is_file()


def test_missing_wheel_is_refused(tmp_path):
    """A non-existent wheel file exits 2 and writes no sums file."""
    sums = tmp_path / "SHA256SUMS"
    pub = _write_release_pub(tmp_path, key="anykey")

    result = _run(
        [
            "--wheel",
            str(tmp_path / "does-not-exist.whl"),
            "--sums",
            str(sums),
            "--minisig",
            str(tmp_path / "x.minisig"),
            "--pub",
            str(pub),
        ]
    )
    assert result.returncode == 2
    assert not sums.exists()


def test_no_secret_no_signature_file(tmp_path):
    """With --dev and no --secret, the script writes sums but no signature file."""
    wheel = tmp_path / "krellbot.whl"
    wheel.write_bytes(b"abc")
    sums = tmp_path / "SHA256SUMS"
    minisig = tmp_path / "SHA256SUMS.minisig"
    pub = _write_dev_pub(tmp_path)

    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(minisig),
            "--pub",
            str(pub),
            "--dev",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert sums.is_file()
    assert not minisig.exists(), "no signature file should exist when --secret is omitted"


def test_secret_passed_but_minisign_missing_exits_2(tmp_path):
    """If --secret is passed and minisign is missing, the script exits 2.

    This test does not require minisign to be installed; it just verifies
    the refusal path. If minisign happens to be installed on the host, the
    script will instead try to use the (bogus) secret file and fail there,
    which also exits 2. Either way the contract is exit 2 + no fabricated
    signature.
    """
    import shutil

    wheel = tmp_path / "krellbot.whl"
    wheel.write_bytes(b"x")
    sums = tmp_path / "SHA256SUMS"
    minisig = tmp_path / "SHA256SUMS.minisig"
    pub = _write_dev_pub(tmp_path)
    fake_secret = tmp_path / "fake.key"
    fake_secret.write_text("not a real minisign secret\n", encoding="utf-8")

    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(minisig),
            "--pub",
            str(pub),
            "--dev",
            "--secret",
            str(fake_secret),
        ]
    )

    if shutil.which("minisign") is None:
        # The script detects the missing binary and refuses before invoking it.
        assert result.returncode == 2
        assert "minisign" in result.stderr.lower()
        # Critically, no signature file is invented.
        assert not minisig.exists()
    else:
        # minisign is installed but the secret is bogus. The script still exits 2
        # and does not produce a fabricated signature.
        assert result.returncode == 2
        assert not minisig.exists()


def test_signature_is_written_to_the_requested_path(tmp_path):
    """minisign must be given absolute -m and -x, even when those dirs differ."""
    import os

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "minisign"
    fake.write_text(
        "#!/bin/sh\n"
        'out=""\n'
        'prev=""\n'
        'for arg in "$@"; do\n'
        '  if [ "$prev" = "-x" ]; then out="$arg"; fi\n'
        '  prev="$arg"\n'
        "done\n"
        'printf \'%s\\n\' "$@" > "$MINISIGN_ARGV"\n'
        "printf 'signed\\n' > \"$out\"\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    wheel = tmp_path / "wheel" / "krellbot.whl"
    wheel.parent.mkdir()
    wheel.write_bytes(b"payload")
    sums = tmp_path / "sums" / "SHA256SUMS"
    sums.parent.mkdir()
    sig = tmp_path / "sigs" / "SHA256SUMS.minisig"
    pub = _write_dev_pub(tmp_path)
    secret = tmp_path / "release.key"
    secret.write_text("not used by the fake\n", encoding="utf-8")
    argv_path = tmp_path / "argv.txt"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["MINISIGN_ARGV"] = str(argv_path)
    result = _run(
        [
            "--wheel",
            str(wheel),
            "--sums",
            str(sums),
            "--minisig",
            str(sig),
            "--pub",
            str(pub),
            "--dev",
            "--secret",
            str(secret),
        ],
        env=env,
    )
    assert result.returncode == 0, result.stderr
    recorded = argv_path.read_text(encoding="utf-8").splitlines()
    assert str(sums.resolve()) in recorded
    assert str(sig.resolve()) in recorded
    assert sig.read_text(encoding="utf-8") == "signed\n"
    assert not (sums.parent / sig.name).exists() or sig.parent == sums.parent

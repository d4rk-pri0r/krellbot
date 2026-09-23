"""Credential storage with env > keyring > file fallback.

Precedence: env vars KRELLBOT_<VEN>_KEY and _SECRET beat the keyring beat the
plaintext file referenced by KRELLBOT_<VEN>_KEYFILE. On POSIX the file is
only accepted if its mode bits exclude any group/world read; on Windows the
ack line ensure_layout()/run/plaintext-ack must mention the venue. The
keyring write is loud-fail: a set_password that doesn't round-trip raises
RuntimeError, so a non-persisting backend (e.g. keyring.backends.null.Keyring)
can never silently swallow credentials.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from krellbot import paths, sanitize

VENUES = {"kraken", "coinbase"}


def _is_windows() -> bool:
    return sys.platform == "win32"


def _service(venue: str) -> str:
    return f"krellbot:{venue}"


def _read_keyfile_lines(path: Path) -> list[str]:
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped)
    return out


def _check_file_mode(path: Path, venue: str) -> None:
    if _is_windows():
        ack = paths.ensure_layout() / "run" / "plaintext-ack"
        if not ack.exists():
            raise PermissionError(f"Refusing to read {path}: missing plaintext-ack at {ack}")
        mentions = [line.strip() for line in ack.read_text(encoding="utf-8").splitlines()]
        if venue not in mentions:
            raise PermissionError(f"Refusing to read {path}: plaintext-ack does not mention {venue!r}")
        return
    mode = path.stat().st_mode
    if mode & 0o077:
        raise PermissionError(f"Refusing to read {path}: file is world/group readable (mode={oct(mode & 0o777)})")


def get(venue: str) -> tuple[str, str]:
    """Return (key, secret) for venue. Raises on partial env / corrupt keyring."""
    if venue not in VENUES:
        raise ValueError("venue must be one of: kraken, coinbase")

    ven = venue.upper()
    env_key = os.environ.get(f"KRELLBOT_{ven}_KEY")
    env_secret = os.environ.get(f"KRELLBOT_{ven}_SECRET")
    if env_key is not None and env_secret is not None:
        return env_key, env_secret
    if (env_key is None) != (env_secret is None):
        raise ValueError(f"KRELLBOT_{ven}_KEY and KRELLBOT_{ven}_SECRET must both be set")

    import keyring as _keyring

    svc = _service(venue)
    k = _keyring.get_password(svc, "key")
    s = _keyring.get_password(svc, "secret")
    if k is not None and s is not None:
        return k, s
    if (k is None) != (s is None):
        raise ValueError(f"keyring for {venue} is in a corrupt state: only one of key/secret is present")

    keyfile_env = os.environ.get(f"KRELLBOT_{ven}_KEYFILE")
    if not keyfile_env:
        raise FileNotFoundError(f"no KRELLBOT_{ven}_KEYFILE set and no keyring entry for {venue}")
    keyfile = Path(keyfile_env)
    _check_file_mode(keyfile, venue)
    lines = _read_keyfile_lines(keyfile)
    if len(lines) < 2:
        raise ValueError(f"{keyfile}: need two non-empty lines (key, then secret); got {len(lines)}")
    return lines[0], lines[1]


def store(venue: str, key: str, secret: str) -> str:
    """Persist (key, secret) for venue to the keyring. Returns backend name."""
    if venue not in VENUES:
        raise ValueError("venue must be one of: kraken, coinbase")

    sanitize.register_secret(key, secret)

    import keyring as _keyring

    svc = _service(venue)
    _keyring.set_password(svc, "key", key)
    _keyring.set_password(svc, "secret", secret)

    rb_k = _keyring.get_password(svc, "key")
    rb_s = _keyring.get_password(svc, "secret")
    if rb_k != key or rb_s != secret:
        raise RuntimeError("keyring backend did not persist credentials")

    backend = _keyring.get_keyring()
    name = getattr(backend, "name", None)
    if isinstance(name, str) and name:
        return name
    return type(backend).__name__


def migrate_legacy() -> bool:
    """If state.json has kraken_key/secret, move them to the keyring. Returns True if migrated.

    Only paths.home()/state.json. When KRELLBOT_HOME is set, that is the only
    file read. Do not fall through to Path.home()/.krellbot.
    """
    state_path = paths.home() / "state.json"
    if not state_path.exists():
        return False
    data = json.loads(state_path.read_text(encoding="utf-8"))
    has_k = "kraken_key" in data
    has_s = "kraken_secret" in data
    if not has_k and not has_s:
        return False
    if has_k != has_s:
        missing = "kraken_secret" if has_k else "kraken_key"
        raise ValueError(f"state.json has only one of kraken_key/kraken_secret; missing {missing}")

    k = data["kraken_key"]
    s = data["kraken_secret"]
    sanitize.register_secret(k, s)
    store("kraken", k, s)

    del data["kraken_key"]
    del data["kraken_secret"]
    paths.atomic_write(state_path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
    return True

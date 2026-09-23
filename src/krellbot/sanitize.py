"""Strip ANSI / C0 / C1 control bytes from text and redact secret values.

`text` uses a single-pass scan rather than regex so a hostile input cannot
trigger catastrophic backtracking. `register_secret` keeps values long
enough to be unambiguous (>=4 chars) so a stray "a" never poisons the set.
`redact` walks dicts and lists in place-shape, replacing registered strings
with "***" and unconditionally masking privileged dict keys.
"""

from __future__ import annotations

# Module-level set of secrets that redact() will replace in any string value.
_REGISTERED: set[str] = set()

# Dict keys whose values are always treated as secrets regardless of registration.
_PRIVILEGED_KEYS = frozenset(
    {"key", "secret", "kraken_key", "kraken_secret", "license_key", "password", "api_key", "api_secret"}
)


def _is_bad(ch_ord: int) -> bool:
    """True for C0 controls (except tab/lf/cr), DEL, and C1 controls."""
    if ch_ord <= 0x1F:
        return ch_ord not in (0x09, 0x0A, 0x0D)
    if ch_ord == 0x7F:
        return True
    return 0x80 <= ch_ord <= 0x9F


def text(s: str, max_len: int = 120) -> str:
    """Strip ANSI escapes, C0/C1 control bytes, and truncate to max_len."""
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        o = ord(ch)
        if ch == "\x1b" and i + 1 < n and s[i + 1] == "[":
            # CSI sequence: ESC [ ... <final byte 0x40-0x7E>
            i += 2
            while i < n:
                fo = ord(s[i])
                i += 1
                if 0x40 <= fo <= 0x7E:
                    break
            continue
        if ch == "\x1b":
            # Bare ESC.
            i += 1
            continue
        if ch == "\x9b":
            # C1 CSI: skip until final byte.
            i += 1
            while i < n:
                fo = ord(s[i])
                i += 1
                if 0x40 <= fo <= 0x7E:
                    break
            continue
        if _is_bad(o):
            i += 1
            continue
        out.append(ch)
        i += 1
    cleaned = "".join(out)
    return cleaned[:max_len]


def register_secret(*values: str) -> None:
    """Record string values for future redact() calls. Drops values < 4 chars."""
    for value in values:
        if len(value) >= 4:
            _REGISTERED.add(value)


def _redact_string(s: str) -> str:
    # Sort longest first so the longest possible match is replaced first;
    # this avoids partial replacement of a supersecret by a substring.
    needles = sorted(_REGISTERED, key=len, reverse=True)
    for needle in needles:
        if needle in s:
            s = s.replace(needle, "***")
    return s


def redact(value):
    """Walk value, replacing registered strings and privileged-key values with '***'."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k in _PRIVILEGED_KEYS:
                out[k] = "***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v) for v in value)
    if isinstance(value, str):
        return _redact_string(value)
    return value
